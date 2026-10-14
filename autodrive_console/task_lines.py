"""Project-owned fixed business itineraries, independent of robot execution."""
from __future__ import annotations

from copy import deepcopy
import uuid
from typing import Any


class TaskLineError(ValueError):
    pass


def _floor_line_name(project, target):
    asset=next((a for a in project.get('map_assets',[]) if a['id']==target['map_asset_id']),{})
    peers=[c for c in project.get('components',[]) if c.get('kind')=='target' and c.get('map_asset_id')==target['map_asset_id']]
    ordinal=next((i+1 for i,c in enumerate(peers) if c['id']==target['id']),1)
    door=str(target.get('attributes',{}).get('door') or '').strip()
    return f'{asset.get("label") or "用户楼层"} · {door or f"目标点 {ordinal}"}'[:80]


def ensure_floor_target_line(project, target, *, previous=None):
    """A marked floor destination owns a separate saved route, never another stop.

    Reuse the selected same-map delivery recipe. Until the first recipe has
    been saved, there is no authorized pickup/cargo intent to copy.
    """
    if project.get('task_mode')!='multi' or target.get('kind')!='target' or 'task_lines' not in project:return
    floor_maps={i.get('map_asset_id') for i in project.get('map_instances',[]) if i.get('role') in {'typical_floor','floor_override'}}
    if target.get('map_asset_id') not in floor_maps:return
    lines=project['task_lines']
    existing=[line for line in lines if any(s.get('kind')=='component' and s.get('id')==target['id'] for s in line.get('steps',[]))]
    if existing:
        if previous:
            old_name=_floor_line_name(project,previous)
            for line in existing:
                if line['name']==old_name:line['name']=_floor_line_name(project,target)
        return
    if previous is not None:return  # Property edits must respect explicit line deletion.
    components={c['id']:c for c in project.get('components',[])}
    candidates=[]
    for line in lines:
        last=(line.get('steps') or [{}])[-1]
        if (last.get('action',{}).get('purpose')=='delivery' and
            components.get(last.get('id'),{}).get('map_asset_id')==target['map_asset_id']):
            candidates.append(line)
    template=next((line for line in candidates if line['id']==project.get('active_task_line_id')),next(iter(candidates),None))
    if template is None:return
    steps=deepcopy(template['steps']);steps[-1]['id']=target['id']
    try:
        line=normalise_task_line(project,{'name':_floor_line_name(project,target),
            'start_component_id':template['start_component_id'],'steps':steps})
    except TaskLineError:
        # A stale recipe must not break placing a marker or invent actions.
        return
    lines.append(line)


def normalise_task_line(project: dict[str, Any], data: object, *, identifier: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {"name", "start_component_id", "steps"}:
        raise TaskLineError("任务线路仅接受名称、起点和去程步骤")
    if not isinstance(data["name"], str):
        raise TaskLineError("任务线路名称无效")
    name = " ".join(data["name"].split())
    if not 1 <= len(name) <= 80:
        raise TaskLineError("任务线路名称应为 1 至 80 个字符")
    components = {item.get("id"): item for item in project.get("components", []) if isinstance(item, dict)}
    waypoints = {item.get("id"): item for item in project.get("waypoints", []) if isinstance(item, dict)}
    start_id = data["start_component_id"]
    if not isinstance(start_id, str) or components.get(start_id, {}).get("kind") != "start":
        raise TaskLineError("请选择当前项目已有的起点组件")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 512:
        raise TaskLineError("去程应包含 1 至 512 个步骤")
    steps = []
    for index, raw in enumerate(raw_steps, start=1):
        try:
            steps.append(_step(raw, components, waypoints))
        except TaskLineError as exc:
            raise TaskLineError(f"第 {index} 步：{exc}") from exc
    if steps[-1]["kind"] == "component" and components[steps[-1]["id"]].get("kind") != "target":
        raise TaskLineError("线路末步应为目标点或过渡点，请为最后一个通行设施添加出口过渡点")
    return {"id": identifier or f"task-line-{uuid.uuid4().hex[:12]}", "name": name,
            "start_component_id": start_id, "steps": steps}


def _step(raw: object, components: dict, waypoints: dict) -> dict[str, Any]:
    if not isinstance(raw, dict) or not {"kind", "id"} <= set(raw) or set(raw) - {"kind", "id", "action"}:
        raise TaskLineError("步骤只允许引用位置和目标动作")
    kind, identifier = raw["kind"], raw["id"]
    if not isinstance(identifier, str) or not isinstance(kind, str) or kind not in {"transition", "component"}:
        raise TaskLineError("位置引用格式无效")
    source = (waypoints if kind == "transition" else components).get(identifier)
    if source is None:
        raise TaskLineError("引用的位置已删除或不属于当前项目，请重新选择")
    if kind == "transition":
        if source.get("kind") != "transition" or source.get("generated_by") or source.get("exclude_task_export"):
            raise TaskLineError("仅手动任务过渡点可以加入线路")
    elif source.get("kind") not in {"target", "gate", "auto_door", "narrow_passage", "ramp", "slow_zone"}:
        raise TaskLineError("此组件由系统处理，不能作为去程步骤")
    if source.get("kind") != "target":
        if "action" in raw:
            raise TaskLineError("通行节点不能配置取货或送货动作")
        return {"kind": kind, "id": identifier}
    action = raw.get("action")
    if not isinstance(action, dict):
        raise TaskLineError("请配置目标访问的用途和动作")
    purpose = action.get("purpose")
    if purpose == "visit":
        if set(action) != {"purpose"}:
            raise TaskLineError("仅到达目标不接受仓控参数")
    elif isinstance(purpose, str) and purpose in {"pickup", "delivery"}:
        if set(action) != {"purpose", "cargo_id", "operation"}:
            raise TaskLineError("取送货应明确仓位与操作方式")
        if type(action["cargo_id"]) is not int or action["cargo_id"] not in {1, 2}:
            raise TaskLineError("仓位只支持上仓 1 或下仓 2")
        if not isinstance(action["operation"], str) or action["operation"] not in {"open", "close", "unload"}:
            raise TaskLineError("仓控方式只支持开仓、关仓或自动卸货")
    else:
        raise TaskLineError("目标用途只支持取货、送货或仅到达")
    return {"kind": kind, "id": identifier, "action": deepcopy(action)}
