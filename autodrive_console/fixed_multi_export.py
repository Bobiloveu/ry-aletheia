"""Lossless export of representable fixed lines into existing R6B fragments."""
import re
import json
from copy import deepcopy

from . import task_compiler as tc
from .task_route_families import _target_branch, TaskRouteFamilyError


def _saved_stage(project, map_id, binding):
    """Resolve role from the saved flow assignment, never from a display name."""
    assignments = [a for a in project.get('map_stage_assignments',[]) if a.get('map_asset_id')==map_id]
    if len(assignments)!=1:
        raise tc.CompilationError('多任务点地图必须有唯一的部署阶段分配')
    stage_id = assignments[0].get('stage')
    flow = project.get('deployment_flow')
    if flow is None:
        # Older projects use the stage type itself as the assignment ID.
        stage_type = stage_id
    else:
        if not isinstance(flow,list) or any(not isinstance(s,dict) for s in flow):
            raise tc.CompilationError('保存的部署阶段流程格式无效')
        matches = [s for s in flow if s.get('id')==stage_id]
        if len(matches)!=1:
            raise tc.CompilationError('多任务点地图分配的阶段不在保存的部署流程中')
        stage_type = matches[0].get('type')
    expected = {'ferry':'ferry','outdoor':'outdoor','lobby':'indoor','target_floor':'floor'}.get(stage_type)
    if expected is None or binding.get('type')!=expected:
        raise tc.CompilationError('地图阶段与定位绑定角色不一致，请重新确认地图阶段')
    roles = {'ferry':{'ferry'},'outdoor':{'outdoor'},'lobby':{'lobby'},
             'target_floor':{'typical_floor','floor_override'}}[stage_type]
    instances = [i for i in project.get('map_instances',[]) if i.get('map_asset_id')==map_id]
    if len(instances)!=1 or instances[0].get('role') not in roles:
        raise tc.CompilationError('地图实例角色与保存的部署阶段不一致')
    return stage_id,stage_type


def multi_layout(project, line):
    components = {c['id']:c for c in project.get('components', [])}
    waypoints = {w['id']:w for w in project.get('waypoints', [])}
    source = components[line['start_component_id']]['map_asset_id']
    visits = [(step, (waypoints if step['kind']=='transition' else components)[step['id']]) for step in line['steps']]
    destinations = {location['map_asset_id'] for _,location in visits} - {source}
    if not destinations and len(project.get('deployment_flow', [])) == 1:
        return _single_map_layout(project, source, visits, components)
    if len(destinations) != 1:
        raise tc.CompilationError('多任务点结构需要一个公共地图和一个连续用户楼层段；不能把该线路导出为单任务结构')
    destination = destinations.pop()
    entered = False
    for step, location in visits:
        if location['map_asset_id'] == destination:
            entered = True
        elif entered:
            raise tc.CompilationError('多任务点分段不支持送货后重新进入公共地图取货；请拆分线路')
        elif step.get('action', {}).get('purpose') == 'delivery':
            raise tc.CompilationError('多任务点公共路线仅支持取货或访问，送货目标应位于用户楼层')
    targets = [(step,location) for step,location in visits if location['map_asset_id']==destination and location.get('kind')=='target']
    if len(targets)!=1 or targets[0][0].get('action',{}).get('purpose')!='delivery' or visits[-1][1]['id']!=targets[0][1]['id']:
        raise tc.CompilationError('多任务点分段要求楼层段以唯一送货目标结束；多个楼层目标或重复访问请分别配置线路')
    bindings = {b['map_asset_id']:b for b in project.get('localization_bindings', [])}
    source_binding, target_binding = bindings.get(source, {}), bindings.get(destination, {})
    if source_binding.get('type') not in {'indoor','ferry'} or target_binding.get('type')!='floor':
        raise tc.CompilationError('多任务点跨图固定线路需要室内大厅（可包含在摆渡层中）和用户楼层定位绑定')
    source_stage,source_type = _saved_stage(project,source,source_binding)
    target_stage,target_type = _saved_stage(project,destination,target_binding)
    flow = project.get('deployment_flow')
    order = [s.get('id') for s in flow] if flow is not None else [a.get('stage') for a in project['map_stage_assignments']]
    if order!=[source_stage,target_stage]:
        raise tc.CompilationError('固定线路的地图阶段顺序与保存的部署流程不一致；不能跳过或重排阶段')
    building, unit = target_binding.get('building',''), target_binding.get('unit','')
    if not all(isinstance(value,str) and re.fullmatch(r'[1-9][0-9]*',value) for value in (building,unit)):
        raise tc.CompilationError('多任务点目录需要有效的数字楼栋和单元')
    source_instance = next(i for i in project.get('map_instances',[]) if i.get('map_asset_id')==source)
    ownership = (source_instance.get('building',''),source_instance.get('unit',''))
    global_ferry = source_type=='ferry' and ownership==('','')
    # A global ferry receives a scoped binding copy for this compilation only.
    # Indoor and historical unit-owned ferry instances must retain real ownership.
    if ((source_binding.get('building'),source_binding.get('unit'))!=(building,unit)
        or (not global_ferry and ownership!=(building,unit))
        or (source_type=='ferry' and source_instance.get('scope')=='global' and not global_ferry)):
        raise tc.CompilationError('多任务点公共源地图实例、定位绑定与目标楼层的楼栋单元不一致')
    instances = [i for i in project.get('map_instances', []) if i.get('map_asset_id')==destination and i.get('role') in {'typical_floor','floor_override'}]
    if len(instances)!=1 or (instances[0].get('building'),instances[0].get('unit'))!=(building,unit):
        raise tc.CompilationError('多任务点用户楼层需要唯一且匹配楼栋单元的地图实例')
    try:
        branch = _target_branch(targets[0][1],instances[0],building,unit,list(components.values()),
                                {e['id']:e for e in project.get('physical_elevators', [])})
    except TaskRouteFamilyError as exc:
        raise tc.CompilationError(f'多任务点目标配置无效：{exc}') from exc
    assets = {a['id']:a for a in project.get('map_assets', [])}
    common_kind = 'ferry' if source_type=='ferry' else 'indoor'
    common_stem = 'sub_outdoor_eguard' if source_type=='ferry' else f'indoor/{building}_{unit}'
    family = {'building':building,'unit':unit,'required_outputs':[common_kind,'floor'],
              'stages':[{'type':source_type,'label':assets[source].get('label') or '公共路线'},
                        {'type':target_type,'label':assets[destination].get('label') or '用户楼层'}],
              'targets':[{'full_room_number':branch.full_room_number,'physical_floor':branch.physical_floor,
                          'button_floor':branch.button_floor,'door':branch.door,'floor_stem':branch.floor_stem}]}
    return {'source':source,'destination':destination,'building':building,'unit':unit,
            'floor_stem':branch.floor_stem,'common_stem':common_stem,'family':family}


def _single_map_layout(project, map_id, visits, components):
    bindings = [b for b in project.get('localization_bindings', []) if b.get('map_asset_id') == map_id]
    if len(bindings) != 1:
        raise tc.CompilationError('单图线路需要唯一有效的定位绑定')
    binding = bindings[0]
    stage_id, stage_type = _saved_stage(project, map_id, binding)
    if project['deployment_flow'][0].get('id') != stage_id:
        raise tc.CompilationError('单图线路与保存的部署阶段不一致')
    instance = next(i for i in project['map_instances'] if i.get('map_asset_id') == map_id)
    building, unit = binding.get('building', ''), binding.get('unit', '')
    ownership = instance.get('building', ''), instance.get('unit', '')
    global_ferry = stage_type == 'ferry' and (building, unit) == ('', '')
    if ownership != (building, unit) or (not global_ferry and not all(
        isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) for value in (building, unit)
    )):
        raise tc.CompilationError('单图地图实例与定位绑定的楼栋单元不一致')
    targets = []
    if stage_type == 'target_floor':
        deliveries = [(step, location) for step, location in visits if step.get('action', {}).get('purpose') == 'delivery']
        if len(deliveries) != 1 or visits[-1] != deliveries[0]:
            raise tc.CompilationError('多任务点单图楼层线路应以唯一送货目标结束；请为各目标保存独立线路')
        target = deliveries[0][1]
        landings = [c for c in components.values() if c.get('map_asset_id') == map_id and c.get('kind') == 'elevator']
        if landings:
            try:
                branch = _target_branch(target, instance, building, unit, list(components.values()),
                                        {e['id']: e for e in project.get('physical_elevators', [])})
            except TaskRouteFamilyError as exc:
                raise tc.CompilationError(f'多任务点目标配置无效：{exc}') from exc
            stem = branch.floor_stem
            targets.append({'full_room_number': branch.full_room_number, 'physical_floor': branch.physical_floor,
                            'button_floor': branch.button_floor, 'door': branch.door, 'floor_stem': stem})
        else:
            room = str(target.get('attributes', {}).get('door') or '').strip()
            if not re.fullmatch(r'[1-9][0-9]{2,15}', room):
                raise tc.CompilationError('多任务点单图楼层目标需填写有效门牌（楼层与两位户号）')
            button, door = int(room[:-2]), room[-2:]
            stem = f'{building}_{unit}_n_n{door}' if instance['role'] == 'typical_floor' else f'{building}_{unit}_{button}_{room}'
            targets.append({'full_room_number': room, 'physical_floor': None, 'button_floor': button,
                            'door': door, 'floor_stem': stem})
        stem = f'floor/{stem}'
    else:
        stem = 'sub_outdoor_eguard' if stage_type == 'ferry' else f'{binding["type"]}/{building}_{unit}'
    asset = next(a for a in project['map_assets'] if a['id'] == map_id)
    family = {'building': building, 'unit': unit, 'required_outputs': [binding['type']],
              'stages': [{'type': stage_type, 'label': asset.get('label') or stage_type}], 'targets': targets}
    return {'source': map_id, 'destination': map_id, 'single_map_stem': stem, 'family': family}


def multi_fragments(layout, community, subtasks, map_ids):
    groups = []
    for subtask,map_id in zip(subtasks,map_ids):
        key = (map_id,subtask['subtask_name'].startswith('return_'))
        if not groups or groups[-1][0]!=key:
            groups.append((key,[]))
        groups[-1][1].append(subtask)
    standalone = layout.get('single_map_stem')
    expected = ([(layout['source'],False),(layout['source'],True)] if standalone else
                [(layout['source'],False),(layout['destination'],False),
                 (layout['destination'],True),(layout['source'],True)])
    if len(subtasks)!=len(map_ids) or [key for key,_ in groups]!=expected:
        raise tc.CompilationError('多任务点执行顺序不能无损拆分为公共与楼层正返段')
    if standalone:
        names = [standalone, f'{standalone}_r']
    else:
        common = layout['common_stem']
        names = [common,f"floor/{layout['floor_stem']}",f"floor/{layout['floor_stem']}_r",f'{common}_r']
    artifacts = []
    for name,(_,members) in zip(names,groups):
        first = members[0]
        if any((m['map_url'],m['pcd_url'],m['change_loc'])!=(first['map_url'],first['pcd_url'],first['change_loc']) for m in members):
            raise tc.CompilationError('多任务点分段不能合并不同地图或切图方式')
        document = {key:first[key] for key in ('change_loc','map_url','pcd_url')}
        document.update(subtask_name=name.split('/')[-1],waypoints=[w for m in members for w in m['waypoints']])
        artifacts.append(tc._artifact(f'multi_tasks/{community}/{name}.json',tc._task_json_bytes(document)))
    return artifacts


def merge_multi_line_previews(project, previews):
    """Publish all independent routes using the existing shared R6B file keys.

    Common files have one runtime owner. Compare navigation/action semantics,
    ignoring only display waypoint IDs; never pick an arbitrary business route.
    Preview subtasks are the actual exported fragments, attributed per line.
    """
    artifacts, action_content = {}, {}
    fragments, fragment_traces, fragment_maps = {}, {}, {}
    subtasks, maps, owners, trace, lines, families = [], [], [], [], [], {}
    location_units, location_owners, lift_entries = {}, {}, {}
    community = tc._community(project)
    template_hashes={}
    status_hash=previews[0][1].manifest['task_status_codes_sha256']
    for line, preview in previews:
        if preview.manifest['task_status_codes_sha256']!=status_hash:
            raise tc.CompilationError('多线路编译期间任务状态码发生变化，请重新生成')
        for name,digest in preview.manifest['template_sha256'].items():
            if template_hashes.setdefault(name,digest)!=digest:
                raise tc.CompilationError('多线路编译期间行为树模板发生变化，请重新生成')
        members = {a.relative_path:a for a in preview.artifacts}
        replacements = {}
        for path, member in members.items():
            if not path.startswith('waypoint_tasks/'):
                continue
            key = (path.rsplit('/',1)[0],member.content)
            canonical = action_content.setdefault(key, path)
            replacements[path.rsplit('/',1)[1][:-4]] = canonical.rsplit('/',1)[1][:-4]
            tc._merge_artifact(artifacts,tc._artifact(canonical,member.content))
        lookup = {item['waypoint_id']:item for item in preview.manifest['waypoint_trace']}
        ordered_maps = list(dict.fromkeys(preview.manifest['subtask_map_asset_ids']))
        direction_maps = ([ordered_maps[0]] * 2 if len(ordered_maps) == 1 else
                          [ordered_maps[0],ordered_maps[1],ordered_maps[1],ordered_maps[0]])
        start = len(subtasks)
        for index,path in enumerate(preview.manifest['multi_task_files']):
            document = json.loads(members[path].content)
            for waypoint in document['waypoints']:
                if waypoint['waypoint_task_id']:
                    waypoint['waypoint_task_id'] = replacements[waypoint['waypoint_task_id']]
            def semantic(value):
                result=deepcopy(value)
                for waypoint in result['waypoints']:waypoint.pop('waypoint_id',None)
                return result
            if path in fragments and semantic(fragments[path])!=semantic(document):
                kind='公共' if '/floor/' not in path else '同一门牌楼层'
                raise tc.CompilationError(f'线路“{line["name"]}”的{kind}路线不一致：{path}；请统一公共流程或为目标配置唯一门牌')
            if path not in fragments:
                fragments[path]=document
                fragment_maps[path]=direction_maps[index]
                fragment_traces[path]=[lookup[w['waypoint_id']] for w in document['waypoints']]
                tc._merge_artifact(artifacts,tc._artifact(path,tc._task_json_bytes(document)))
            subtasks.append(deepcopy(fragments[path]))
            maps.append(fragment_maps[path]);owners.append(line['id'])
            trace.extend({**item,'task_line_id':line['id']} for item in fragment_traces[path])
        lines.append({**deepcopy(line),'subtask_start':start,'subtask_count':len(subtasks)-start})
        for family in preview.manifest['route_families']:
            key=(family['building'],family['unit'])
            merged=families.setdefault(key,{**deepcopy(family),'targets':[]})
            for target in family['targets']:
                if target not in merged['targets']:merged['targets'].append(target)
        for path,member in members.items():
            if path.startswith(('multi_tasks/','waypoint_tasks/')):continue
            if path=='runtime/loc_yaml_path.json':
                for unit in json.loads(member.content)['loc_yaml']:
                    key=(unit['building'],unit['unit'])
                    merged=location_units.setdefault(key,{**unit,'yaml_index':[]})
                    for entry in unit['yaml_index']:
                        previous=next((e for e in merged['yaml_index'] if (e['type'],e.get('floor'))==(entry['type'],entry.get('floor'))),None)
                        owner=(key,entry['type'],entry.get('floor'))
                        if previous is not None and previous!=entry:
                            # The terminal floor is never re-entered on return.
                            # Existing multi-task manifests keep one stable
                            # representative here; apartment navigation lives
                            # in each independent floor_r fragment.
                            comparable=lambda e:{k:v for k,v in e.items() if k!='init_return'}
                            if entry['type']!='floor' or comparable(previous)!=comparable(entry):
                                raise tc.CompilationError(f'线路“{line["name"]}”的同地图定位锚点不一致，请统一该地图的切图位置')
                            if line['id']<location_owners[owner]:
                                previous.update(entry);location_owners[owner]=line['id']
                        if previous is None:
                            merged['yaml_index'].append(entry);location_owners[owner]=line['id']
                        else:
                            location_owners[owner]=min(location_owners[owner],line['id'])
            elif path=='runtime/lift_id_list.json':
                for entry in json.loads(member.content)['lifts']:
                    old=lift_entries.setdefault(entry['lift_id'],entry)
                    if old!=entry:raise tc.CompilationError('共享电梯编号的楼栋单元归属冲突')
            else:tc._merge_artifact(artifacts,member)
    tc._merge_artifact(artifacts,tc._artifact('runtime/loc_yaml_path.json',tc._task_json_bytes({'community':community,'loc_yaml':list(location_units.values())})))
    tc._merge_artifact(artifacts,tc._artifact('runtime/lift_id_list.json',tc._task_json_bytes({'community':community,'lifts':list(lift_entries.values())})))
    # A tree used only by a duplicate fragment is intentionally not published.
    used={w['waypoint_task_id'] for s in fragments.values() for w in s['waypoints'] if w['waypoint_task_id']}
    artifacts={path:a for path,a in artifacts.items() if not path.startswith('waypoint_tasks/') or path.rsplit('/',1)[1][:-4] in used}
    ordered=tuple(sorted(artifacts.values(),key=lambda a:a.relative_path))
    active=next(line for line,_ in previews if line['id']==project['active_task_line_id'])
    digest=tc._sha(tc._json_bytes({'lines':lines,'active':active['id'],'artifacts':[(a.relative_path,a.sha256) for a in ordered]}))
    base=deepcopy(previews[0][1].manifest)
    base.update(compiler_version=4,input_sha256=digest,active_task_line=active,compiled_task_lines=lines,
        template_sha256=template_hashes,
        subtask_map_asset_ids=maps,subtask_task_line_ids=owners,waypoint_trace=trace,execution_chain={},
        route_families=list(families.values()),multi_task_files=list(fragments),
        artifacts=[{'path':a.relative_path,'sha256':a.sha256} for a in ordered])
    summaries=[{'building':u['building'],'unit':u['unit'],'type':entry['type'],
        **({'floor_template':entry['floor']} if entry['type']=='floor' else {})}
        for u in location_units.values() for entry in u['yaml_index']]
    base['location_manifest']={'community':community,'binding_count':len(summaries),'bindings':summaries}
    task={'mode':'multi','task_group_name':community,'route_families':list(families.values()),'subtasks':subtasks}
    return tc.CompilationPreview(digest,task,ordered,base,{})
