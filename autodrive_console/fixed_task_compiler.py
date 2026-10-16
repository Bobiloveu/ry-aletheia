"""Compile a selected, project-owned itinerary without runtime side effects.

Visits carry business intent. Return travel retraces the outbound navigation
without repeating cargo actions. Facilities reuse the existing approved trees.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from math import isfinite
import re
import yaml
from xml.etree import ElementTree as ET
from typing import Any

from . import task_compiler as tc
from . import location_manifest as lm
from .automatic_route import AutomaticRouteError, _virtual_wall_segments
from .map_reachability import FreeCells, map_reachable
from .execution_chain import ExecutionChainError, MapExecutionPlan, _reverse_nodes, build_directed_map_execution_plan
from .fixed_route_geometry import crossing_components, discover_execution_nodes, validate_passage_axis
from .location_manifest import LocationManifestError, RuntimeLayout, compile_location_manifest
from .task_lines import TaskLineError, normalise_task_line
from .task_path import TASK_TRANSITION_SPEED_MODES, return_yaw
from .fixed_multi_export import multi_layout, multi_fragments, merge_multi_line_previews


def _filename_token(value: str, *, byte_limit: int = 72, fallback: str = 'task_line', ascii_only: bool = False) -> str:
    token = ''.join(c if (c.isalnum() and (not ascii_only or c.isascii())) or c in '_-' else '_' for c in value)
    token = re.sub('_+', '_', token).strip('_-')
    return token.encode('utf-8')[:byte_limit].decode('utf-8', errors='ignore').rstrip('_-') or fallback


def _export_line_name(project: dict, line: dict, *, ascii_only: bool = False) -> str:
    """Readable project-local namespace, including sanitized-name collisions."""
    entries = [(item['id'], _filename_token(item['name'], ascii_only=ascii_only,
                fallback=f'line_{index:02d}' if ascii_only else 'task_line'))
               for index, item in enumerate(project.get('task_lines', []), 1)]
    reserved = {name.casefold() for _, name in entries}
    used = set()
    for identifier, base in entries:
        name = base
        if name.casefold() in used:
            number = 2
            while f'{base}_{number}'.casefold() in used | reserved:
                number += 1
            name = f'{base}_{number}'
        used.add(name.casefold())
        if identifier == line['id']:
            return name
    raise tc.CompilationError('导出线路不属于当前项目')


def compile_fixed_task_line(project: dict[str, Any], *, map_root: Path) -> tc.CompilationPreview:
    raw = next((line for line in project.get('task_lines', [])
                if line.get('id') == project.get('active_task_line_id')), None)
    if raw is None:
        raise tc.CompilationError('请选择一条已保存的任务线路')
    try:
        line = normalise_task_line(project, {k:v for k,v in raw.items() if k != 'id'}, identifier=raw['id'])
        return _Compiler(_scope_shared_ferry(project, line), line, Path(map_root).resolve()).compile()
    except (TaskLineError, ExecutionChainError, LocationManifestError, AutomaticRouteError) as exc:
        raise tc.CompilationError(str(exc)) from exc


def compile_fixed_task_lines(project: dict[str, Any], *, map_root: Path) -> tc.CompilationPreview:
    """Multi mode exports every saved destination, single mode the selection."""
    if project.get('task_mode')!='multi' or len(project.get('task_lines',[]))<=1:
        return compile_fixed_task_line(project,map_root=map_root)
    if not any(line.get('id')==project.get('active_task_line_id') for line in project['task_lines']):
        raise tc.CompilationError('请选择一条已保存的任务线路')
    previews=[]
    for raw in project['task_lines']:
        try:
            branch=compile_fixed_task_line({**project,'active_task_line_id':raw['id']},map_root=map_root)
            previews.append((branch.manifest['active_task_line'],branch))
        except tc.CompilationError as exc:
            raise tc.CompilationError(f'线路“{raw.get("name") or "未命名"}”：{exc}') from exc
    return merge_multi_line_previews(project,previews)


def _scope_shared_ferry(project: dict, line: dict) -> dict:
    """Resolve a global ferry's runtime unit from actual shared lift landings.

    A ferry can already contain the lift lobby. Its stage/ownership stays
    global in the project; only this compilation receives a unit-scoped copy.
    Do not infer ownership from an unused floor or the current UI selection.
    """
    components = {c['id']: c for c in project.get('components', [])}
    waypoints = {w['id']: w for w in project.get('waypoints', [])}
    used = {components[line['start_component_id']]['map_asset_id']}
    used.update((waypoints if s['kind'] == 'transition' else components)[s['id']]['map_asset_id']
                for s in line['steps'])
    bindings = project.get('localization_bindings', [])
    known_lifts = {lift['id'] for lift in project.get('physical_elevators', [])}
    lifts_by_map: dict[str, set[str]] = {}
    for component in components.values():
        physical = component.get('attributes', {}).get('physical_elevator_id')
        if component.get('kind') == 'elevator' and physical in known_lifts:
            lifts_by_map.setdefault(component['map_asset_id'], set()).add(physical)
    scoped = []
    for binding in bindings:
        map_id = binding.get('map_asset_id')
        if map_id not in used or binding.get('type') != 'ferry' or binding.get('building') or binding.get('unit'):
            scoped.append(binding)
            continue
        if len(used) == 1:
            scoped.append(binding)
            continue
        identities = {(other['building'], other['unit']) for other in bindings
                      if other.get('map_asset_id') in used and other.get('type') in {'floor', 'indoor'}
                      and other.get('building') and other.get('unit')
                      and lifts_by_map.get(map_id, set()) & lifts_by_map.get(other['map_asset_id'], set())}
        if len(identities) != 1:
            raise tc.CompilationError('摆渡层电梯连接无法确定唯一楼栋单元；请关联线路所经楼层的物理电梯')
        building, unit = identities.pop()
        scoped.append({**binding, 'building':building, 'unit':unit})
    return {**project, 'localization_bindings':scoped}


def _validate_map_calibration(metadata: dict, asset: dict):
    """Reject source drift before raster edits or geometry use asset coordinates."""
    def finite_number(value):
        try:
            return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value)
        except OverflowError:
            return False

    for label, origin, resolution in (
        ('YAML',metadata.get('origin'),metadata.get('resolution')),
        ('资产',asset.get('origin'),asset.get('resolution_m')),
    ):
        if (not isinstance(origin,list) or len(origin)!=3 or not all(finite_number(v) for v in origin)
            or not finite_number(resolution) or resolution<=0):
            raise tc.CompilationError(f'地图{label}标定 origin/resolution 无效，请重新导入地图')
    if metadata['origin']!=asset['origin'] or metadata['resolution']!=asset['resolution_m']:
        raise tc.CompilationError('地图 YAML 标定 origin/resolution 与资产不一致，请重新导入地图')
    # Shared reachability, bounds and raster edits currently use axis-aligned
    # maps. Do not silently treat a rotated raster as an unrotated export.
    # Reject every nonzero value, including full turns; never rewrite evidence.
    if metadata['origin'][2]!=0:
        raise tc.CompilationError('当前固定线路编译不支持旋转栅格，请使用 origin yaw=0 且坐标一致的地图')


class _Compiler:
    def __init__(self, project: dict, line: dict, root: Path):
        self.p, self.line, self.root = project, line, root
        self.assets = tc._assets(project)
        self.components = {c['id']: c for c in project.get('components', [])}
        self.waypoints = {w['id']: w for w in project.get('waypoints', [])}
        self.community = tc._community(project)
        self.layout = RuntimeLayout(project['id'], self.community)
        self.start = self.components[line['start_component_id']]
        self.task_mode = project.get('task_mode', 'single')
        if not isinstance(self.task_mode,str) or self.task_mode not in {'single','multi'}:
            raise tc.CompilationError('项目模式只能是 single 或 multi')
        self.multi_layout = multi_layout(project,line) if self.task_mode=='multi' else None
        self.site = tc._site_id(self.assets[self.start['map_asset_id']], root)
        self.prefix = 'fl_' + sha256(line['id'].encode()).hexdigest()[:12]
        self.export_line_name = _export_line_name(project, line)
        self.runtime_line_name = _export_line_name(project, line, ascii_only=True)
        self.export_task_name = f"{_filename_token(self.community, byte_limit=120, fallback='community')}_{self.export_line_name}"
        self.action_labels: dict[str, str] = {}
        self.bindings: dict[str, dict] = {}
        self.events: list[dict] = []
        self.subtasks: list[dict] = []
        self.subtask_maps: list[str] = []
        self.artifacts: dict[str, tc.Artifact] = {}
        self.template_hashes: dict[str, str] = {}
        self.execution: dict[str, dict] = {}
        self.location_entries: dict[str, dict] = {}
        self.status = tc.task_status_codes_module.task_status_code_snapshot()
        self.values = self.status.xml_values()
        self.counter = 0
        self.grids: dict[str, tuple] = {}
        self.node_metadata: dict[str, dict] = {}
        self.waypoint_trace: list[dict] = []

    def binding(self, map_id: str) -> dict:
        if map_id not in self.bindings:
            matches = [b for b in self.p.get('localization_bindings', []) if b.get('map_asset_id') == map_id]
            if len(matches) != 1:
                raise tc.CompilationError('线路地图必须有唯一有效的自动定位绑定')
            b = matches[0]
            global_ferry = b.get('type') == 'ferry' and not b.get('building') and not b.get('unit')
            if (not b.get('building') or not b.get('unit')) and not global_ferry:
                raise tc.CompilationError('固定线路尚不支持未明确楼栋单元的地图连接')
            tc._source_path(self.assets[map_id], self.root)
            self.bindings[map_id] = b
        return self.bindings[map_id]

    def grid(self, map_id: str) -> tuple:
        """Decode once per map, from exactly the edited monochrome export."""
        if map_id not in self.grids:
            asset = self.assets[map_id]
            source = tc._source_path(asset, self.root)
            try:
                text = source.read_text(encoding='utf-8')
                try:
                    metadata = yaml.safe_load(text)
                except yaml.YAMLError as exc:
                    raise tc.CompilationError('无法解析受控地图 YAML') from exc
                if not isinstance(metadata,dict):
                    raise tc.CompilationError('地图 YAML 根节点无效')
                _validate_map_calibration(metadata,asset)
                match = lm._IMAGE.search(text)
                if match is None:
                    raise tc.CompilationError('地图 YAML 缺少 image')
                image_value = Path(match.group(1).strip().strip("\"'"))
                image = (source.parent / image_value).resolve()
                if image_value.is_absolute() or not image.is_relative_to(self.root) or not image.is_file():
                    raise tc.CompilationError('地图 image 必须是受控相对路径')
                encoded = image.read_bytes()
                edits = [edit for edit in self.p.get('map_edits', []) if edit.get('map_asset_id') == map_id]
                if edits:
                    encoded = lm._rasterize_map_edits(encoded, asset, edits)
                encoded = lm._navigation_map_bytes(encoded, text)
                width, height, pixels = lm._read_pgm_bytes(encoded)
            except (OSError, UnicodeError) as exc:
                raise tc.CompilationError('无法读取受控地图栅格') from exc
            if (width, height) != (asset.get('width'), asset.get('height')):
                raise tc.CompilationError('地图栅格与资产尺寸不一致，请重新导入')
            # Keep ROS YAML occupancy semantics, including inverted external
            # maps. White-background normalization applies only when negate=0.
            negate = metadata.get('negate', 0)
            try:
                threshold = float(metadata.get('free_thresh', .196))
            except (TypeError, ValueError) as exc:
                raise tc.CompilationError('地图自由空间阈值无效') from exc
            if negate not in (0, 1) or not isfinite(threshold) or not 0 < threshold < 1:
                raise tc.CompilationError('地图占据参数无效')
            free = FreeCells(width, height, pixels, negate=negate, free_thresh=threshold)
            if not free:
                raise tc.CompilationError('地图没有可达的自由空间')
            self.grids[map_id] = (width,height,free)
        return self.grids[map_id]

    def paths(self, map_id: str) -> tuple[str, str]:
        b = self.binding(map_id)
        key = f"floor-{b['floor_template']}" if b['type'] == 'floor' else b['type']
        return (self.layout.map_yaml(b['building'], b['unit'], key).installed,
                self.layout.localization_yaml(b['building'], b['unit'], key).installed)

    def xml(self, task_id: str, template_name: str, *, values: dict | None = None,
            fixed: dict | None = None, relocalize: dict | None = None, label: str | None = None) -> str:
        template = tc._template(template_name)
        tc._validate_status_code_template(template, self.values)
        self.template_hashes[template_name] = tc._sha(template.encode())
        tree = ET.fromstring(tc._render_xml(template, {**self.values, **(values or {})}))
        if fixed:
            # Existing templates obtain dynamic delivery identity. A fixed line
            # supplies the same approved blackboard ports explicitly per trip.
            for parent in tree.iter():
                for child in list(parent):
                    if child.tag == 'GetTaskTargetInfo':
                        index = list(parent).index(child)
                        parent.remove(child)
                        for offset, (key, value) in enumerate(fixed.items()):
                            parent.insert(index+offset, ET.Element('SetBlackboard', output_key=key, value=str(value)))
        if relocalize:
            for node in tree.iter('SetUseWheelOdom'):
                if node.get('use_wheel_odom') == 'false':
                    node.attrib.update({k:tc._format_number(v) for k,v in relocalize.items()})
                    node.set('z', '0.4')
        encoded = ET.tostring(tree, encoding='utf-8') + b'\n'
        member = tc._artifact(f'waypoint_tasks/{self.site}/{task_id}.xml', encoded)
        tc._merge_artifact(self.artifacts, member)
        self.action_labels[task_id] = label or Path(template_name).stem
        return task_id

    def cargo(self, step: dict, ordinal: int) -> str:
        action = step['action']
        if action['purpose'] == 'visit':
            return ''
        task_id = f'{self.prefix}_visit_{ordinal}'
        root = ET.Element('root', main_tree_to_execute='MainTree')
        sequence = ET.SubElement(ET.SubElement(root, 'BehaviorTree', ID='MainTree'), 'Sequence', name='FixedTargetVisit')
        message = f'{self.line["name"]} · {ordinal}'
        if self.task_mode=='multi' and action['purpose']=='delivery':
            ET.SubElement(sequence, 'GetTaskTargetInfo', delivery_code='{delivery_code}',success='{task_target_success}')
            message = '{delivery_code}'
        if action['purpose'] == 'delivery':
            ET.SubElement(sequence, 'PublishTaskStatus', status_code=self.values['STATUS_MULTI_TASK_START'], message=message)
        ET.SubElement(sequence, 'CargoSingleCommand', caogo_id=str(action['cargo_id']),
                      operation_code=str({'open':0,'close':1,'unload':2}[action['operation']]))
        if action['purpose'] == 'delivery':
            ET.SubElement(sequence, 'PublishTaskStatus', status_code=self.values['STATUS_MULTI_TASK_ARRIVED'], message=message)
        tc._merge_artifact(self.artifacts, tc._artifact(f'waypoint_tasks/{self.site}/{task_id}.xml', ET.tostring(root, encoding='utf-8') + b'\n'))
        self.action_labels[task_id] = f"{action['purpose']}_{'upper' if action['cargo_id'] == 1 else 'lower'}_{action['operation']}"
        return task_id

    def publish_action_names(self):
        """Rename exported trees and references together, in execution order."""
        nodes = [node for subtask in self.subtasks for node in subtask['waypoints']]
        identifiers = list(dict.fromkeys(node['waypoint_task_id'] for node in nodes if node['waypoint_task_id']))
        width = max(2, len(str(len(identifiers))))
        names = {}
        for ordinal, identifier in enumerate(identifiers, 1):
            label = self.action_labels.get(identifier)
            if not label:
                raise tc.CompilationError('行为树缺少导出名称')
            name = f'{ordinal:0{width}d}_{label}_{self.runtime_line_name}'
            old = self.artifacts.pop(f'waypoint_tasks/{self.site}/{identifier}.xml')
            tc._merge_artifact(self.artifacts, tc._artifact(f'waypoint_tasks/{self.site}/{name}.xml', old.content))
            names[identifier] = name
        for node in nodes:
            if node['waypoint_task_id']:
                node['waypoint_task_id'] = names[node['waypoint_task_id']]

    def append(self, map_id: str, name: str, nodes: list[dict], *, reverse: bool = False):
        if not nodes:
            return
        b = self.binding(map_id)
        entry = self.location_entries.setdefault(map_id, {'binding_id':b['id'],
                'init_go': self.pose(nodes[0]), 'init_return': self.pose(nodes[0]), 'elevator_anchors':[]})
        if reverse and not entry.get('_return_set'):
            entry['init_return'] = self.pose(nodes[0])
            entry['_return_set'] = True
        self.subtask_maps.append(map_id)
        self.subtasks.append({'change_loc':False,'map_url':self.paths(map_id)[0], 'pcd_url':'',
                              'subtask_name':name,'waypoints':nodes})

    @staticmethod
    def pose(node: dict) -> dict:
        from math import atan2
        position, orientation = node['pose']['position'], node['pose']['orientation']
        return {'x':position['x'],'y':position['y'],'z':0.,'yaw':2*atan2(orientation['z'], orientation['w'])}

    def tagged_waypoint(self, identifier, point, speed, action='', *, source=None,
                        purpose='waypoint', role='waypoint', reverse=False, is_task_point=False):
        source = source or {}
        label = source.get('label') or purpose
        self.node_metadata[identifier] = {'leg':'return' if reverse else 'outbound',
            'label':label, 'purpose':purpose, 'role':role, 'source_id':source.get('id','')}
        return tc._waypoint(identifier,point,speed,action,is_task_point=is_task_point)

    def publish_waypoint_names(self):
        count = sum(len(sub['waypoints']) for sub in self.subtasks)
        width = max(2,len(str(count)))
        for map_id,subtask in zip(self.subtask_maps,self.subtasks):
            for node in subtask['waypoints']:
                meta = self.node_metadata[node['waypoint_id']]
                ordinal = len(self.waypoint_trace)+1
                purpose = meta['purpose'].removeprefix(meta['leg']+'_')
                name = f"{ordinal:0{width}d}_{meta['leg']}_{purpose}"
                if meta['label'] != meta['purpose']:
                    label = _filename_token(meta['label'],byte_limit=72,fallback='',ascii_only=True)
                    if label:
                        name += '_' + label
                node['waypoint_id'] = name
                self.waypoint_trace.append({'waypoint_id':name,'map_asset_id':map_id,
                    **{k:meta[k] for k in ('leg','label','role','source_id')}})

    def navigation(self, map_id: str, start: dict, end: dict, refs: list[dict], ordinal: int,
                   action: str = '', end_speed: str = 'single_point', *, reverse=False,
                   endpoint=None, purpose='waypoint'):
        binding = self.binding(map_id)
        grid = self.grid(map_id)
        tc._validate_point(self.assets[map_id], start, '线路起点')
        tc._validate_point(self.assets[map_id], end, '线路终点')
        plan = build_directed_map_execution_plan(self.p, binding['id'], node_refs=refs,
                    start_anchor=start, end_anchor=end, end_speed_mode=end_speed)
        walls = _virtual_wall_segments(self.p,map_id)
        expanded = list(plan.outbound_nodes)
        # Adding long-axis or device clearance nodes changes the approach legs.
        # Reinspect those actual legs until no additional facility is crossed.
        # Bound refinement and fail closed if overlapping facilities never
        # converge; never silently leave a changed approach unchecked.
        for _ in range(len(self.components)+1):
            previous = tc._point_dict(start)
            previous_node = None
            refined = []
            for node in (*expanded,None):
                point = {'x':node.x,'y':node.y,'yaw':node.yaw} if node else tc._point_dict(end)
                excluded = {n.source_id for n in (previous_node,node)
                            if n and n.source_kind=='component'}
                added = discover_execution_nodes(self.p,binding,self.assets[map_id],previous,point,
                           excluded=excluded,grid=grid,virtual_walls=walls)
                refined.extend(added)
                if node:
                    refined.append(node)
                previous = point
                previous_node = node
            if len(refined)==len(expanded):
                break
            expanded = refined
        else:
            raise tc.CompilationError('通行设施路径无法稳定展开；请检查重叠组件与接近路径')
        if reverse:
            expanded = [replace(n,action=n.action.replace('_go','_back')) if n.action else n for n in expanded]
        plan = MapExecutionPlan(tuple(expanded),tuple(_reverse_nodes(expanded,end_speed)))
        passage_entries = {}
        for node in plan.outbound_nodes:
            if node.source_kind!='component' or self.components[node.source_id]['kind']!='narrow_passage':
                continue
            if node.role=='entry':
                passage_entries[node.source_id] = node
            elif node.role=='exit':
                entry = passage_entries.pop(node.source_id,None)
                if entry is None:
                    raise tc.CompilationError('窄通道缺少对应入口节点')
                validate_passage_axis(self.assets[map_id],self.components[node.source_id],
                    entry,node,grid=grid,virtual_walls=walls)
        previous = tc._point_dict(start)
        for node in (*plan.outbound_nodes,None):
            point = {'x':node.x,'y':node.y,'yaw':node.yaw} if node else tc._point_dict(end)
            map_reachable(self.assets[map_id],previous,point,virtual_walls=walls,grid_override=grid)
            previous = point
        start_source = start if start.get('id') else None
        if start_source is None and self.events and self.events[-1]['kind']=='transfer':
            transfer = self.events[-1]
            _,start_source,_ = self.lift_pair(transfer['source'],transfer['destination'])
        event = {'kind':'navigation','map':map_id,'start':tc._point_dict(start), 'end':tc._point_dict(end),
                 'plan':plan,'ordinal':ordinal,'action':action,'end_speed':end_speed,
                 'endpoint':endpoint, 'purpose':purpose,'start_source':start_source}
        self.events.append(event)
        self.record_navigation(event, reverse)

    def record_navigation(self, event: dict, reverse: bool):
        map_id, plan = event['map'], event['plan']
        binding = self.binding(map_id)
        self.execution[f'block_{len(self.events)}'] = {'binding_id':binding['id'],
            'map_asset_id':map_id, 'leg':'return' if reverse else 'outbound',
            'start_anchor':event['start'], 'end_anchor':event['end'],
            'end_speed_mode':event['end_speed'], 'outbound':[asdict(n) for n in plan.outbound_nodes],
            'return':[asdict(n) for n in plan.return_nodes]}
        self.emit_navigation(event, reverse)

    def emit_navigation(self, event: dict, reverse: bool):
        self.counter += 1
        direction = 'return' if reverse else 'outbound'
        prefix = f'{self.prefix}_{direction}_{self.counter}'
        result = []
        for index,node in enumerate(event['plan'].outbound_nodes):
            source = (self.waypoints if node.source_kind=='transition' else self.components)[node.source_id]
            purpose = ('transition' if node.source_kind=='transition' else source['kind'])+'_'+node.role
            action = ''
            if node.action:
                action = self.xml(f'{prefix}_device_{index}', f'components/{node.component_kind}_{node.action}.xml',
                                  values={'CONTROLLER_DEVICE_ID':node.controller_device_id},
                                  label=f'{direction}_{node.component_kind}_{node.action}')
            result.append(self.tagged_waypoint(f'{prefix}_{index}', {'x':node.x,'y':node.y,'yaw':node.yaw},
                node.incoming_speed_mode, action,source=source,purpose=purpose,role=node.role,
                reverse=reverse,is_task_point=bool(action)))
        result.append(self.tagged_waypoint(f'{prefix}_end',event['end'],event['end_speed'],event['action'],
            source=event['endpoint'],purpose=event['purpose'],role=event['purpose'],
            reverse=reverse,is_task_point=bool(event['action'])))
        self.append(event['map'], direction+'_'+str(self.counter),result,reverse=reverse)

    def return_to_start(self):
        """Reverse validated outbound legs, not the business actions they carry."""
        outbound = list(self.events)
        for index in range(len(outbound)-1, -1, -1):
            event = outbound[index]
            if event['kind']=='transfer':
                self.transfer(event['destination'],event['source'],event['ordinal'],reverse=True)
                continue
            nodes = []
            for node,original in zip(event['plan'].return_nodes,reversed(event['plan'].outbound_nodes)):
                role = {'entry':'exit','exit':'entry'}.get(node.role,node.role)
                kind = self.components[node.source_id]['kind'] if node.source_kind=='component' else None
                speed = node.incoming_speed_mode
                if kind in {'gate','auto_door'}:
                    speed = original.incoming_speed_mode
                elif role=='entry' and kind in {'narrow_passage','slow_zone','ramp'}:
                    speed = 'single_point'
                nodes.append(replace(node,role=role,incoming_speed_mode=speed))
            source = event['start_source']
            end = dict(event['start'])
            # Only the final parking arrival retains the departure heading.
            if index:
                end['yaw'] = return_yaw(end['yaw'])
            kind = (source or {}).get('kind')
            purpose = ('return_start' if index==0 else 'elevator_approach' if kind=='elevator'
                       else 'transition' if kind=='transition' else 'waypoint')
            speed = (source.get('speed_mode') or 'single_point') if kind=='transition' else 'single_point'
            returned = {**event,'start':event['end'],'end':end,'action':'','end_speed':speed,
                        'endpoint':source,'purpose':purpose,
                        'plan':MapExecutionPlan(tuple(nodes), tuple(event['plan'].outbound_nodes))}
            self.events.append(returned)
            self.record_navigation(returned, True)

    def lift_pair(self, source: str, destination: str) -> tuple[dict, dict, dict]:
        a, b = self.binding(source), self.binding(destination)
        if (a['building'],a['unit']) != (b['building'],b['unit']) or a['type'] not in {'indoor','floor','ferry'} or b['type'] not in {'indoor','floor','ferry'}:
            raise tc.CompilationError('此地图连接缺少已批准的同楼栋单元电梯通行方案')
        landings = [c for c in self.components.values() if c.get('kind') == 'elevator']
        physicals = {e['id']:e for e in self.p.get('physical_elevators', [])}
        candidates = [(x,y,physicals.get(x.get('attributes',{}).get('physical_elevator_id')))
            for x in landings for y in landings if x['map_asset_id'] == source and y['map_asset_id'] == destination
            and x.get('attributes',{}).get('physical_elevator_id') and x['attributes']['physical_elevator_id'] == y.get('attributes',{}).get('physical_elevator_id')]
        if len(candidates) != 1 or candidates[0][2] is None:
            raise tc.CompilationError('两张地图必须有唯一关联同一物理电梯的落点，不猜测连接')
        x,y,physical = candidates[0]
        if physical.get('migration_conflict') or not physical.get('elevator_id') or not physical.get('elevator_protocol'):
            raise tc.CompilationError('物理电梯配置不完整或存在迁移冲突')
        if tc._shared_physical_floor(physical,x) == tc._shared_physical_floor(physical,y):
            raise tc.CompilationError('不同地图的电梯落点不能使用同一按钮层')
        return x,y,physical

    def transfer(self, source: str, destination: str, ordinal: int, *, reverse: bool = False):
        x,y,physical = self.lift_pair(source, destination)
        source_wait, source_yaw = tc._wait_point(x)
        destination_wait, destination_yaw = tc._wait_point(y)
        for map_id, landing, wait in ((source,x,source_wait),(destination,y,destination_wait)):
            grid = self.grid(map_id)
            tc._validate_point(self.assets[map_id], landing, '电梯落点')
            tc._validate_point(self.assets[map_id], wait, '候梯点')
            candidates = [c for c in self.components.values() if c['map_asset_id']==map_id
                          and c.get('kind') in {'gate','auto_door','narrow_passage','ramp','slow_zone'}]
            overlaps = crossing_components(candidates,[(wait['x'],wait['y']),(landing['x'],landing['y'])])
            if overlaps:
                labels = '、'.join(c.get('label') or c['id'] for c in overlaps)
                raise tc.CompilationError(f'电梯进出段与通行设施“{labels}”重叠，现有电梯时序无法表达；请调整设施或电梯候梯点')
            map_reachable(self.assets[map_id],wait,landing,
                virtual_walls=_virtual_wall_segments(self.p,map_id),grid_override=grid)
        destination_seen = destination in self.location_entries
        self.counter += 1
        name = f'{self.prefix}_lift_{self.counter}'
        binding = self.binding(source)
        fixed = {'community':self.community,'building':binding['building'],'unit':binding['unit'],
                 'floor':tc._shared_physical_floor(physical,y)}
        values = {'ORIGIN_FLOOR':str(tc._shared_physical_floor(physical,x)),
                  'TARGET_LOCALIZATION_YAML':self.paths(destination)[1], 'TARGET_MAP_YAML':self.paths(destination)[0]}
        direction = 'return' if reverse else 'outbound'
        returning_multi = self.task_mode=='multi' and reverse
        if self.task_mode=='multi':
            fixed = None
            values['ORIGIN_FLOOR'] = str(tc._shared_physical_floor(physical,y if reverse else x))
        if returning_multi:
            values.update(TARGET_LOCALIZATION_YAML=self.paths(source)[1],SOURCE_LOCALIZATION_YAML=self.paths(destination)[1],
                          RELOCALIZE_X=tc._format_number(y['x']),RELOCALIZE_Y=tc._format_number(y['y']),RELOCALIZE_YAW=tc._format_number(destination_yaw))
        call = self.xml(f'{name}_call','elevator_in_x_n.xml' if returning_multi else 'elevator_in_n_x.xml',values=values,fixed=fixed,label=f'{direction}_elevator_call')
        ride = self.xml(f'{name}_ride','elevator_out_x_n.xml' if returning_multi else 'elevator_out_n_x.xml',values=values,fixed=fixed,
                        relocalize=tc._point_dict(y, destination_yaw),label=f'{direction}_elevator_ride')
        close = self.xml(f'{name}_close','close_elevdoor_n.xml' if returning_multi else 'close_elevdoor_x.xml',values=values,fixed=fixed,label=f'{direction}_elevator_close_door')
        subtask_name = f'{direction}_elevator_step_{ordinal:02d}'
        self.append(source, subtask_name, [
            self.tagged_waypoint(f'{name}_wait',source_wait,'single_point',call,source=x,purpose='elevator_wait',role='elevator_wait',reverse=reverse,is_task_point=True),
            self.tagged_waypoint(f'{name}_center',tc._point_dict(x,source_yaw),'elevator_in',ride,source=x,purpose='elevator_center',role='elevator_center',reverse=reverse,is_task_point=True)], reverse=reverse)
        self.append(destination, subtask_name+'_arrival', [
            self.tagged_waypoint(f'{name}_arrival',destination_wait,'backward',close,source=y,purpose='elevator_arrival',role='elevator_arrival',reverse=reverse,is_task_point=True)], reverse=reverse)
        for map_id, landing in ((source,x),(destination,y)):
            entry = self.location_entries[map_id]
            if landing['id'] not in entry['elevator_anchors']:
                entry['elevator_anchors'].append(landing['id'])
        if not reverse:
            # Wheel-odometry recovery switches at the actual destination lift
            # centre, before the outward/backward waypoint is executed.
            entry = self.location_entries[destination]
            if not destination_seen:
                entry['init_go'] = {**tc._point_dict(y,destination_yaw),'z':0.}
            self.events.append({'kind':'transfer','source':source,'destination':destination,'ordinal':ordinal})
        return destination_wait

    def compile(self) -> tc.CompilationPreview:
        start_action = self.xml(f'{self.prefix}_start','start_task.xml')
        current_map, current = self.start['map_asset_id'], self.start
        self.append(current_map,'start', [self.tagged_waypoint(f'{self.prefix}_start',tc._point_dict(current),'task_point',start_action,source=self.start,purpose='start',role='start',is_task_point=True)])
        pending = []
        for ordinal, step in enumerate(self.line['steps'], 1):
            source = (self.waypoints if step['kind'] == 'transition' else self.components)[step['id']]
            map_id = source['map_asset_id']
            try:
                if map_id != current_map:
                    landing, _, _ = self.lift_pair(current_map, map_id)
                    wait, _ = tc._wait_point(landing)
                    self.navigation(current_map,current,wait,pending,ordinal,endpoint=landing,purpose='elevator_approach')
                    pending = []
                    current = self.transfer(current_map,map_id,ordinal)
                    current_map = map_id
                if source.get('kind') == 'target':
                    action = self.cargo(step, ordinal)
                    self.navigation(current_map,current,source,pending,ordinal,action,endpoint=source,purpose=step['action']['purpose'])
                    pending = []
                    current = source
                else:
                    pending.append({'kind':step['kind'],'id':step['id']})
            except (tc.CompilationError, ExecutionChainError, AutomaticRouteError) as exc:
                raise tc.CompilationError(f'第 {ordinal} 步：{exc}') from exc
        if pending:
            # A final transition is an ordinary endpoint, without a cargo task.
            last = pending[-1]
            source = (self.waypoints if last['kind'] == 'transition' else self.components)[last['id']]
            if source.get('kind') != 'transition':
                raise tc.CompilationError('线路末步应为目标点或过渡点，请为最后一个通行区域添加出口过渡点')
            speed = source.get('speed_mode') or 'single_point'
            if speed not in TASK_TRANSITION_SPEED_MODES:
                raise tc.CompilationError('末步过渡点速度模式无效')
            self.navigation(current_map,current,source,pending[:-1],len(self.line['steps']),end_speed=speed,endpoint=source,purpose='transition')
            current = source
        self.return_to_start()
        complete = self.xml(f'{self.prefix}_complete','task_complete.xml')
        # Attach completion to the final physical return arrival, once.
        last = self.subtasks[-1]['waypoints'][-1]
        last.update(waypoint_task_id=complete,is_task_point=True,is_single_point=True)
        entries = [{k:v for k,v in entry.items() if not k.startswith('_')} for entry in self.location_entries.values()]
        locations = compile_location_manifest(self.p,map_root=self.root,execution_entries=entries)
        for a in locations.artifacts:
            tc._merge_artifact(self.artifacts,tc._artifact(a.relative_path,a.content))
        self.publish_action_names()
        self.publish_waypoint_names()
        task_json = {'subtasks':self.subtasks, 'task_group_name':self.export_task_name}
        multi_files = []
        if self.multi_layout:
            fragments = multi_fragments(self.multi_layout,self.community,self.subtasks,self.subtask_maps)
            for fragment in fragments:
                tc._merge_artifact(self.artifacts,fragment)
            multi_files = [fragment.relative_path for fragment in fragments]
            task_json.update(mode='multi',route_families=[self.multi_layout['family']])
        else:
            tc._merge_artifact(self.artifacts,tc._artifact(f'tasks/{self.export_task_name}.json',tc._task_json_bytes(task_json)))
        artifacts = tuple(sorted(self.artifacts.values(),key=lambda a:a.relative_path))
        digest = tc._sha(tc._json_bytes({'line':self.line,'task_mode':self.task_mode,'artifacts':[(a.relative_path,a.sha256) for a in artifacts],
            'virtual_walls':self.p.get('virtual_walls',[]),'status':self.status.sha256 if hasattr(self.status,'sha256') else tc._sha(self.status.raw_bytes)}))
        manifest = {'compiler_profile':'fixed_task_line_v1','compiler_version':4,'task_mode':self.task_mode,
            'validation_status':'experimental_preview','input_sha256':digest,'active_task_line':self.line,
            'waypoint_trace':self.waypoint_trace,'execution_chain':self.execution,'subtask_map_asset_ids':self.subtask_maps,'task_status_codes_sha256':tc._sha(self.status.raw_bytes),
            'template_sha256':self.template_hashes, 'artifacts':[{'path':a.relative_path,'sha256':a.sha256} for a in artifacts],
            'location_manifest':{'community':self.community,'binding_count':len(locations.summary),'bindings':list(locations.summary)},
            'robot_runtime_changed':False,'statement':'实验预览：未写入任何机器人运行时文件。'}
        if self.multi_layout:
            manifest.update(multi_task_files=multi_files,route_families=[self.multi_layout['family']])
        return tc.CompilationPreview(digest,task_json,artifacts,manifest,{})
