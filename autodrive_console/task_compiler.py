"""Pure, experimental compiler for indoor elevator and public-route previews.

This module intentionally has no DeploymentStore, HTTP, ROS or runtime-file
ownership.  It transforms a normalized SiteProject document into in-memory
artifacts so a later store layer can review and persist them beneath the
project-owned export root.
"""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
from math import cos, isfinite, sin
from pathlib import Path
import io
import json
import re
import zipfile
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

from .location_manifest import (
    LocationManifestError,
    RuntimeLayout,
    compile_location_manifest,
    elevator_inward_yaw,
    localization_template_text,
    physical_floor_index,
)
from .execution_chain import (
    ExecutionChainError,
    ExecutionNode,
    MapExecutionPlan,
    build_map_execution_plan,
)
from .task_route_families import TaskRouteFamilyError, derive_task_route_families
from . import task_status_codes as task_status_codes_module


PROFILE = "indoor_elevator_v1"
PROFILE_VERSION = 1
DEFAULT_MAP_ROOT = Path("/opt/ry/data/maps")
TEMPLATE_ROOT = Path(__file__).with_name("task_templates") / PROFILE
SPEED_MODES = frozenset({"task_point", "single_point", "elevator_in", "backward", "narrow_point", "slow_point"})
TARGET_ARRIVAL_ACTIONS = frozenset({"place_water", "auto_cargo"})
TARGET_ARRIVAL_ACTION_DEFAULT = "place_water"
_ROUTE_STAGE_LABELS = {
    "ferry": "摆渡层",
    "outdoor": "户外图",
    "lobby": "电梯大厅",
    "target_floor": "用户楼层",
}
_SAFE_SITE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SAFE_DOOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}\Z")
_SAFE_COMMUNITY = re.compile(r"[^/\\\x00-\x1f]{1,80}\Z")
_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")


class CompilationError(ValueError):
    """The project lacks a fact required by this deliberately narrow profile."""


@dataclass(frozen=True)
class Artifact:
    relative_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class CompilationInput:
    community: str
    site_id: str
    building: str
    unit: str
    target_floor: int
    door: str
    arrival_action: str
    lobby_map_url: str
    target_map_url: str


@dataclass(frozen=True)
class CompilationPreview:
    input_sha256: str
    task_json: dict[str, Any]
    artifacts: tuple[Artifact, ...]
    manifest: dict[str, Any]
    derived_points: dict[str, dict[str, float]]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def compile_single_task_points(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    """Compile one complete legacy-shaped task per marked delivery target.

    The existing two-map compiler remains the one source of component and
    behavior-tree semantics.  This wrapper selects one target branch at a
    time, then merges only byte-identical shared artifacts.
    """
    previews = _target_branch_previews(project, map_root=map_root)
    flow = project.get("deployment_flow")
    flow_types = {
        str(item.get("type") or "")
        for item in flow
        if isinstance(item, dict)
    } if isinstance(flow, list) else set()
    has_public_stages = bool({"ferry", "outdoor"} & flow_types)
    if has_public_stages:
        try:
            families = derive_task_route_families(project)
        except TaskRouteFamilyError as exc:
            raise CompilationError(str(exc)) from exc
    else:
        # Historical single-task projects predate the explicit flow model.
        # They retain the established two-map compiler byte-for-byte.
        families = ()
    families_by_target = {
        target.component_id: family
        for family in families for target in family.targets
    }
    if has_public_stages:
        try:
            status_xml_values = task_status_codes_module.task_status_code_snapshot().xml_values()
        except task_status_codes_module.TaskStatusCodeError as exc:
            raise CompilationError(f"任务状态码配置无效：{exc}") from exc
        previews = [
            (
                target_id,
                _compose_single_public_preview(
                    project, target_id, preview, families_by_target.get(target_id),
                    map_root, status_xml_values,
                ),
            )
            for target_id, preview in previews
        ]
    if len(previews) == 1 and not has_public_stages:
        preview = previews[0][1]
        return CompilationPreview(
            preview.input_sha256,
            preview.task_json,
            preview.artifacts,
            {**preview.manifest, "task_mode": "single"},
            preview.derived_points,
            preview.warnings,
            preview.errors,
        )
    merged: dict[str, Artifact] = {}
    for _, preview in previews:
        for artifact in preview.artifacts:
            if artifact.relative_path in {"runtime/loc_yaml_path.json", "runtime/lift_id_list.json"}:
                continue
            _merge_artifact(merged, artifact)
    try:
        location_manifest = compile_location_manifest(
            _location_manifest_project(project), map_root=map_root,
        )
    except LocationManifestError as exc:
        raise CompilationError(str(exc)) from exc
    for location_artifact in location_manifest.artifacts:
        _merge_artifact(
            merged,
            _artifact(location_artifact.relative_path, location_artifact.content),
        )
    task_artifacts = [item for item in merged.values() if item.relative_path.startswith("tasks/")]
    digest = _sha(_json_bytes([item.sha256 for item in sorted(merged.values(), key=lambda item: item.relative_path)]))
    manifest = {
        "compiler_profile": PROFILE,
        "compiler_version": PROFILE_VERSION,
        "task_mode": "single",
        "validation_status": "experimental_preview",
        "input_sha256": digest,
        "artifacts": [{"path": item.relative_path, "sha256": item.sha256} for item in sorted(merged.values(), key=lambda item: item.relative_path)],
        "route_families": [{"targets": [
            {"task": item.relative_path.rsplit("/", 1)[-1], "full_room_number": item.relative_path.rsplit("_", 1)[-1].removesuffix(".json")}
            for item in sorted(task_artifacts, key=lambda item: item.relative_path)
        ]}],
        "robot_runtime_changed": False,
        "statement": "实验预览：未写入任何机器人运行时文件。",
    }
    return CompilationPreview(digest, {"mode": "single", "tasks": [json.loads(item.content) for item in sorted(task_artifacts, key=lambda item: item.relative_path)]}, tuple(sorted(merged.values(), key=lambda item: item.relative_path)), manifest, {})


def _compose_single_public_preview(
    project: dict[str, Any],
    target_id: str,
    preview: CompilationPreview,
    family: Any,
    map_root: Path,
    status_xml_values: dict[str, str],
) -> CompilationPreview:
    """Expand the automatic public segments around one legacy elevator task."""
    if family is None:
        raise CompilationError("目标点缺少配送路线族")
    route = _route_for_target_preview(project, target_id)
    outbound_public: list[dict[str, Any]] = []
    inbound_public: list[dict[str, Any]] = []
    public_artifacts: list[Artifact] = []
    for stage in ("ferry", "outdoor"):
        if stage not in family.required_outputs:
            continue
        outbound, inbound, members = _compile_public_segment(
            project, route, family.building, family.unit, stage, map_root, status_xml_values,
        )
        outbound_public.append(outbound)
        inbound_public.insert(0, inbound)
        public_artifacts.extend(members)
    task_json = deepcopy(preview.task_json)
    subtasks = task_json.get("subtasks")
    if not isinstance(subtasks, list) or len(subtasks) != 4:
        raise CompilationError("室内任务编译结果无效")
    task_json["subtasks"] = [
        *outbound_public,
        *subtasks[:2],
        *subtasks[2:],
        *inbound_public,
    ]
    artifacts: list[Artifact] = []
    replaced_task = False
    for artifact in preview.artifacts:
        if artifact.relative_path.startswith("tasks/"):
            artifacts.append(_artifact(artifact.relative_path, _task_json_bytes(task_json)))
            replaced_task = True
        else:
            artifacts.append(artifact)
    if not replaced_task:
        raise CompilationError("室内任务编译产物缺失")
    artifacts.extend(public_artifacts)
    merged: dict[str, Artifact] = {}
    for artifact in artifacts:
        _merge_artifact(merged, artifact)
    return CompilationPreview(
        preview.input_sha256,
        task_json,
        tuple(sorted(merged.values(), key=lambda item: item.relative_path)),
        preview.manifest,
        preview.derived_points,
        preview.warnings,
        preview.errors,
    )


def compile_multi_task_points(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    """Split verified target branches into reusable multi-task route files.

    Indoor branches continue through the established elevator compiler;
    ferry and outdoor segments are rendered from the same backend-derived
    execution chain.  This keeps map, device and behavior-tree validation
    identical in both project modes without asking a browser to order paths.
    """
    try:
        families = derive_task_route_families(project)
    except TaskRouteFamilyError as exc:
        raise CompilationError(str(exc)) from exc
    assets_by_id = _assets(project)
    previews = _target_branch_previews(project, map_root=map_root)
    previews_by_target = {target_id: preview for target_id, preview in previews}
    community = _community(project)
    artifacts: dict[str, Artifact] = {}
    route_manifest: list[dict[str, Any]] = []
    try:
        status_snapshot = task_status_codes_module.task_status_code_snapshot()
        status_xml_values = status_snapshot.xml_values()
    except task_status_codes_module.TaskStatusCodeError as exc:
        raise CompilationError(f"任务状态码配置无效：{exc}") from exc
    emitted_ferry = False

    for family in families:
        branch_previews: list[tuple[Any, CompilationPreview]] = []
        for target in family.targets:
            preview = previews_by_target.get(target.component_id)
            if preview is None:
                raise CompilationError("目标点缺少已验证的定位路线")
            branch_previews.append((target, preview))
            outbound, inbound = preview.task_json["subtasks"][1:3]
            _merge_artifact(artifacts, _artifact(
                f"multi_tasks/{community}/floor/{target.floor_stem}.json",
                _task_json_bytes(_single_subtask_document(outbound, target.floor_stem)),
            ))
            _merge_artifact(artifacts, _artifact(
                f"multi_tasks/{community}/floor/{target.floor_stem}_r.json",
                _task_json_bytes(_single_subtask_document(inbound, f"{target.floor_stem}_r")),
            ))

        # Public indoor entry/return routes are shared by every delivery target
        # of one building/unit.  A mismatch indicates an ambiguous map marking,
        # so fail instead of choosing an arbitrary branch.
        first_preview = branch_previews[0][1]
        for index, suffix in ((0, ""), (3, "_r")):
            documents = [preview.task_json["subtasks"][index] for _, preview in branch_previews]
            if any(document != documents[0] for document in documents[1:]):
                raise CompilationError("同一单元的公共室内路线不一致")
            _merge_artifact(artifacts, _artifact(
                f"multi_tasks/{community}/indoor/{family.building}_{family.unit}{suffix}.json",
                _task_json_bytes(_single_subtask_document(documents[0], f"{family.building}_{family.unit}{suffix}")),
            ))

        # External segments use the exact same derived execution chain as the
        # indoor compiler.  They are not expanded from browser ordering: their
        # map entry/exit anchors were selected by automatic_route.py.
        route = _route_for_target_preview(project, family.targets[0].component_id)
        if "ferry" in family.required_outputs and not emitted_ferry:
            outbound, inbound, members = _compile_public_segment(
                project, route, family.building, family.unit, "ferry", map_root, status_xml_values,
            )
            _merge_artifact(artifacts, _artifact(
                f"multi_tasks/{community}/sub_outdoor_eguard.json", _task_json_bytes(outbound),
            ))
            _merge_artifact(artifacts, _artifact(
                f"multi_tasks/{community}/sub_outdoor_eguard_r.json", _task_json_bytes(inbound),
            ))
            for member in members:
                _merge_artifact(artifacts, member)
            emitted_ferry = True
        if "outdoor" in family.required_outputs:
            outbound, inbound, members = _compile_public_segment(
                project, route, family.building, family.unit, "outdoor", map_root, status_xml_values,
            )
            for suffix, document in (("", outbound), ("_r", inbound)):
                _merge_artifact(artifacts, _artifact(
                    f"multi_tasks/{community}/outdoor/{family.building}_{family.unit}{suffix}.json",
                    _task_json_bytes(document),
                ))
            for member in members:
                _merge_artifact(artifacts, member)

        stages = []
        for stage in family.stages:
            label = _ROUTE_STAGE_LABELS[stage.stage]
            asset = assets_by_id.get(stage.map_asset_id)
            if asset is not None:
                label = str(asset.get("label") or label)
            stages.append({"type": stage.stage, "label": label})
        route_manifest.append({
            "building": family.building,
            "unit": family.unit,
            "stages": stages,
            "required_outputs": sorted(family.required_outputs),
            "targets": [
                {
                    # This is an operator-facing audit manifest.  Component
                    # identifiers are storage implementation details, not a
                    # delivery fact, so never expose them to Web previews.
                    "full_room_number": target.full_room_number,
                    "physical_floor": target.physical_floor,
                    "button_floor": target.button_floor,
                    "door": target.door,
                    "floor_stem": target.floor_stem,
                }
                for target in family.targets
            ],
        })

    # Behavior-tree support is supplied once.  Per-target legacy branches each
    # render a partial location manifest, which necessarily differs for a
    # second building/unit; emit one complete community manifest below instead
    # of treating those partial runtime files as a filename collision.
    for _, preview in previews:
        for artifact in preview.artifacts:
            if not artifact.relative_path.startswith("tasks/") and artifact.relative_path not in {
                "runtime/loc_yaml_path.json", "runtime/lift_id_list.json",
            }:
                _merge_artifact(artifacts, artifact)
    try:
        location_manifest = compile_location_manifest(
            _location_manifest_project(project), map_root=map_root,
        )
    except LocationManifestError as exc:
        raise CompilationError(str(exc)) from exc
    for location_artifact in location_manifest.artifacts:
        _merge_artifact(
            artifacts,
            _artifact(location_artifact.relative_path, location_artifact.content),
        )
    ordered = tuple(sorted(artifacts.values(), key=lambda item: item.relative_path))
    input_fingerprints = _multi_input_fingerprints(
        project, _sha(status_snapshot.raw_bytes),
    )
    digest = _sha(_json_bytes({
        "profile": PROFILE,
        "version": PROFILE_VERSION,
        "task_mode": "multi",
        "input_fingerprints": input_fingerprints,
        "artifacts": [item.sha256 for item in ordered],
    }))
    manifest = {
        "compiler_profile": PROFILE,
        "compiler_version": PROFILE_VERSION,
        "task_mode": "multi",
        "validation_status": "experimental_preview",
        "input_sha256": digest,
        "task_status_codes_sha256": input_fingerprints["task_status_codes"],
        "input_fingerprints": input_fingerprints,
        "artifacts": [{"path": item.relative_path, "sha256": item.sha256} for item in ordered],
        "route_families": route_manifest,
        "robot_runtime_changed": False,
        "statement": "实验预览：未写入任何机器人运行时文件。",
    }
    return CompilationPreview(
        digest,
        {"mode": "multi", "route_families": route_manifest},
        ordered,
        manifest,
        {},
    )


def _multi_input_fingerprints(
    project: dict[str, Any], task_status_codes_sha256: str,
) -> dict[str, str]:
    """Fingerprint every saved fact that can change a multi-task preview.

    These are audit fields, not browser routing controls.  They let a review
    package prove why a content-addressed preview changed while keeping the
    original source records private to the project document.
    """
    fields = (
        "deployment_flow", "map_assets", "map_instances", "components",
        "virtual_walls", "map_edits", "localization_bindings",
        "localization_routes", "physical_elevators", "localization_template",
        "component_templates", "behavior_templates",
    )
    return {
        **{
            field: _sha(_json_bytes(project.get(field)))
            for field in fields
        },
        "task_status_codes": task_status_codes_sha256,
    }


def _route_for_target_preview(project: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Find a target's automatic route without using its display order."""
    target = next(
        (item for item in project.get("components", [])
         if isinstance(item, dict) and item.get("id") == target_id),
        None,
    )
    if target is None:
        raise CompilationError("目标点缺少自动定位路线")
    generated = set(target.get("generated_waypoint_ids") or [])
    if not generated:
        generated = {
            str(point.get("id")) for point in project.get("waypoints", [])
            if isinstance(point, dict)
            and (
                point.get("generated_by") == target_id
                or (
                    point.get("map_asset_id") == target.get("map_asset_id")
                    and all(
                        abs(float(point.get(axis, 0.0)) - float(target.get(axis, 0.0))) <= 1e-6
                        for axis in ("x", "y", "yaw")
                    )
                )
            )
        }
    matches = [
        route for route in project.get("localization_routes", [])
        if isinstance(route, dict) and route.get("task_target_waypoint_id") in generated
    ]
    if len(matches) != 1:
        raise CompilationError("每个目标点必须有唯一自动定位路线")
    return matches[0]


def _compile_public_segment(
    project: dict[str, Any],
    route: dict[str, Any],
    building: str,
    unit: str,
    stage: str,
    map_root: Path,
    status_xml_values: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], list[Artifact]]:
    """Render one ferry/outdoor segment from a backend-derived route.

    This deliberately has no filename, point order, or endpoint inputs from
    Web.  The stage binding and hand-off anchors must already be present in
    the audited automatic route.
    """
    bindings = {
        str(item.get("id")): item for item in project.get("localization_bindings", [])
        if isinstance(item, dict) and item.get("id")
    }
    binding_ids = route.get("binding_ids")
    if not isinstance(binding_ids, list):
        raise CompilationError("自动定位路线无效")
    selected = [bindings.get(str(identifier)) for identifier in binding_ids]
    match_indexes = [
        index for index, binding in enumerate(selected)
        if isinstance(binding, dict) and binding.get("type") == stage
    ]
    if len(match_indexes) != 1:
        raise CompilationError(f"自动定位路线缺少唯一{('摆渡层' if stage == 'ferry' else '户外')}地图")
    index = match_indexes[0]
    if index >= len(selected) - 1:
        raise CompilationError("公共地图段不能作为配送路线终点")
    binding = selected[index]
    if not isinstance(binding, dict):
        raise CompilationError("自动定位路线绑定无效")
    start = _route_entry_point(project, route, binding, index)
    end = _route_exit_point(project, route, binding, selected[index + 1], index)
    try:
        plan = build_map_execution_plan(
            project, str(binding["id"]), start_anchor=start, end_anchor=end,
            end_speed_mode="single_point",
        )
    except ExecutionChainError as exc:
        raise CompilationError(str(exc)) from exc
    assets = _assets(project)
    asset = assets.get(str(binding.get("map_asset_id")))
    if asset is None:
        raise CompilationError("公共地图段引用的地图不存在")
    layout = RuntimeLayout(str(project.get("id") or ""), _community(project))
    map_url = layout.map_yaml(building, unit, stage).installed
    label = "outdoor" if stage == "ferry" else f"outdoor_{building}_{unit}"
    outbound = {
        "change_loc": False, "map_url": map_url, "pcd_url": "", "subtask_name": label,
        "waypoints": [
            _waypoint(f"{stage}_start", start, "task_point", is_task_point=False),
            *_execution_waypoints(stage, plan.outbound_nodes, building, unit),
            _waypoint(f"{stage}_handoff", end, "single_point"),
        ],
    }
    inbound = {
        "change_loc": False, "map_url": map_url, "pcd_url": "", "subtask_name": f"{label}_r",
        "waypoints": [
            _waypoint(f"{stage}_return_handoff", end, "task_point", is_task_point=False),
            *_execution_waypoints(f"{stage}_r", plan.return_nodes, building, unit),
            _waypoint(f"{stage}_return_start", start, "single_point"),
        ],
    }
    try:
        members = [
            artifact for _, artifact in _component_action_artifacts(
                project, _site_id(asset, map_root), building, unit, status_xml_values,
                status_xml_values, plan,
            )
        ]
    except CompilationError:
        raise
    return outbound, inbound, members


def _route_entry_point(
    project: dict[str, Any], route: dict[str, Any], binding: dict[str, Any], index: int,
) -> dict[str, float]:
    if index == 0:
        return _route_waypoint_point(project, route.get("task_start_waypoint_id"), binding, "任务起点")
    anchors = route.get("entry_anchors")
    if not isinstance(anchors, list):
        raise CompilationError("公共地图段缺少自动入口锚点")
    match = next(
        (item for item in anchors
         if isinstance(item, dict) and item.get("binding_id") == binding.get("id")),
        None,
    )
    if not isinstance(match, dict):
        raise CompilationError("公共地图段缺少自动入口锚点")
    return _route_anchor_point(project, match.get("anchor"), binding, "入口锚点")


def _route_exit_point(
    project: dict[str, Any], route: dict[str, Any], binding: dict[str, Any], next_binding: Any, index: int,
) -> dict[str, float]:
    links = route.get("links")
    if not isinstance(links, list) or index >= len(links) or not isinstance(next_binding, dict):
        raise CompilationError("公共地图段缺少自动转场锚点")
    link = links[index]
    if not isinstance(link, dict) or link.get("from_binding_id") != binding.get("id") or link.get("to_binding_id") != next_binding.get("id"):
        raise CompilationError("公共地图段转场顺序无效")
    return _route_anchor_point(project, link.get("anchor"), binding, "转场锚点")


def _route_waypoint_point(project: dict[str, Any], identifier: Any, binding: dict[str, Any], label: str) -> dict[str, float]:
    waypoint = next(
        (item for item in project.get("waypoints", [])
         if isinstance(item, dict) and item.get("id") == identifier),
        None,
    )
    if waypoint is None or waypoint.get("map_asset_id") != binding.get("map_asset_id"):
        raise CompilationError(f"{label}必须位于对应地图")
    return _point_dict(waypoint)


def _route_anchor_point(project: dict[str, Any], anchor: Any, binding: dict[str, Any], label: str) -> dict[str, float]:
    if not isinstance(anchor, dict):
        raise CompilationError(f"{label}无效")
    if anchor.get("kind") == "waypoint" and set(anchor) == {"kind", "waypoint_id"}:
        return _route_waypoint_point(project, anchor.get("waypoint_id"), binding, label)
    if anchor.get("kind") == "component_center" and set(anchor) == {"kind", "component_id"}:
        component = next(
            (item for item in project.get("components", [])
             if isinstance(item, dict) and item.get("id") == anchor.get("component_id")),
            None,
        )
        if component is None or component.get("map_asset_id") != binding.get("map_asset_id"):
            raise CompilationError(f"{label}组件必须位于对应地图")
        return _point_dict(component)
    raise CompilationError(f"{label}无效")


def _location_manifest_project(project: dict[str, Any]) -> dict[str, Any]:
    """Select the shared localization path once per building/unit.

    Delivery branches may have different final targets but share the same map
    localization chain.  The runtime location manifest is keyed by
    building/unit, not by apartment, so feeding every branch to it would
    wrongly be reported as duplicate topology.  Preserve the first stable
    branch of each unit; the surrounding compiler still byte-compares all
    branch-local localization artifacts and rejects a diverging path.
    """
    routes = project.get("localization_routes")
    if not isinstance(routes, list):
        return project
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for route in routes:
        if not isinstance(route, dict):
            continue
        identity = (str(route.get("building") or ""), str(route.get("unit") or ""))
        if not all(identity):
            continue
        current = selected.get(identity)
        if current is None or str(route.get("id") or "") < str(current.get("id") or ""):
            selected[identity] = route
    branch = deepcopy(project)
    branch["localization_routes"] = [selected[key] for key in sorted(selected)]
    return branch


def _target_branch_previews(
    project: dict[str, Any], *, map_root: Path,
) -> list[tuple[str, CompilationPreview]]:
    targets = [
        item for item in project.get("components", [])
        if isinstance(item, dict) and item.get("kind") == "target"
    ]
    if not targets:
        raise CompilationError("至少需要一个目标点")
    previews: list[tuple[str, CompilationPreview]] = []
    for target in sorted(targets, key=lambda item: str(item.get("id") or "")):
        target_id = str(target.get("id") or "")
        if not target_id:
            raise CompilationError("目标点标识无效")
        generated_ids = set(target.get("generated_waypoint_ids") or [])
        if not generated_ids:
            generated_ids = {
                str(point.get("id"))
                for point in project.get("waypoints", [])
                if isinstance(point, dict)
                and point.get("map_asset_id") == target.get("map_asset_id")
                and all(abs(float(point.get(axis, 0)) - float(target.get(axis, 0))) <= 1e-6 for axis in ("x", "y", "yaw"))
            }
        routes = [
            route for route in project.get("localization_routes", [])
            if route.get("task_target_waypoint_id") in generated_ids
        ]
        if len(routes) != 1:
            raise CompilationError("每个目标点必须有唯一自动定位路线")
        branch = _target_compilation_branch(project, target, routes[0])
        previews.append((target_id, compile_indoor_elevator(branch, map_root=map_root)))
    return previews


def _target_compilation_branch(
    project: dict[str, Any], target: dict[str, Any], route: dict[str, Any],
) -> dict[str, Any]:
    """Project one target's two approved elevator maps out of a community.

    The legacy compiler is intentionally strict about exactly one lobby and
    one floor map.  A community project can legitimately contain many such
    pairs, so each target must be compiled from its own automatically-derived
    route rather than whichever pair happened to occupy the old import-guide
    assignment first.
    """
    binding_ids = route.get("binding_ids")
    if not isinstance(binding_ids, list):
        raise CompilationError("目标点的自动定位路线无效")
    bindings_by_id = {
        str(item.get("id")): item
        for item in project.get("localization_bindings", [])
        if isinstance(item, dict) and item.get("id")
    }
    selected_bindings = [bindings_by_id.get(str(identifier)) for identifier in binding_ids]
    lobby = next(
        (item for item in selected_bindings
         if isinstance(item, dict) and item.get("type") == "indoor"),
        None,
    )
    floor = next(
        (item for item in selected_bindings
         if isinstance(item, dict) and item.get("type") == "floor"
         and item.get("map_asset_id") == target.get("map_asset_id")),
        None,
    )
    if not isinstance(lobby, dict) or not isinstance(floor, dict):
        raise CompilationError("目标点的自动定位路线缺少大厅或用户楼层")
    lobby_map_id, target_map_id = str(lobby["map_asset_id"]), str(floor["map_asset_id"])
    selected_map_ids = {lobby_map_id, target_map_id}
    branch = deepcopy(project)
    branch["scene_model"] = "custom"
    branch["deployment_flow"] = [
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    branch["map_stage_assignments"] = [
        {"stage": "lobby", "map_asset_id": lobby_map_id},
        {"stage": "target_floor", "map_asset_id": target_map_id},
    ]
    branch["map_assets"] = [
        item for item in branch.get("map_assets", [])
        if isinstance(item, dict) and item.get("id") in selected_map_ids
    ]
    branch["map_instances"] = [
        item for item in branch.get("map_instances", [])
        if isinstance(item, dict) and item.get("map_asset_id") in selected_map_ids
    ]
    branch["localization_bindings"] = [
        item for item in branch.get("localization_bindings", [])
        if isinstance(item, dict) and item.get("id") in {lobby["id"], floor["id"]}
    ]
    # The legacy compiler owns only the approved lobby→floor elevator pair.
    # A community route may have already crossed ferry/outdoor maps; project
    # that audited route down to the pair rather than asking the user to make
    # a second, manually ordered route.
    lobby_index = next(index for index, item in enumerate(selected_bindings) if item is lobby)
    floor_index = next(index for index, item in enumerate(selected_bindings) if item is floor)
    link_rows = route.get("links") if isinstance(route.get("links"), list) else []
    pair_link = next(
        (item for item in link_rows
         if isinstance(item, dict) and item.get("from_binding_id") == lobby.get("id")
         and item.get("to_binding_id") == floor.get("id")),
        None,
    )
    if pair_link is None or floor_index != lobby_index + 1:
        raise CompilationError("目标点的自动定位路线缺少大厅到用户楼层的电梯衔接")
    branch_route = deepcopy(route)
    branch_route["binding_ids"] = [lobby["id"], floor["id"]]
    branch_route["links"] = [pair_link]
    if isinstance(route.get("execution_nodes"), list):
        branch_route["execution_nodes"] = [
            item for item in route["execution_nodes"]
            if isinstance(item, dict) and item.get("binding_id") in {lobby["id"], floor["id"]}
        ]
    if isinstance(route.get("entry_anchors"), list):
        branch_route["entry_anchors"] = [
            item for item in route["entry_anchors"]
            if isinstance(item, dict) and item.get("binding_id") in {lobby["id"], floor["id"]}
        ]
        lobby_entry = next(
            (item for item in branch_route["entry_anchors"]
             if item.get("binding_id") == lobby["id"]),
            None,
        )
        anchor = lobby_entry.get("anchor") if isinstance(lobby_entry, dict) else None
        if isinstance(anchor, dict) and anchor.get("kind") == "component_center":
            entry_waypoints = [
                item for item in project.get("waypoints", [])
                if isinstance(item, dict) and item.get("generated_by") == anchor.get("component_id")
                and item.get("map_asset_id") == lobby_map_id
            ]
            if len(entry_waypoints) != 1:
                raise CompilationError("楼栋入口缺少自动定位标记；请回到地图重新标记入口")
            branch_route["task_start_waypoint_id"] = entry_waypoints[0]["id"]
    branch["localization_routes"] = [branch_route]
    branch["components"] = [
        item for item in branch.get("components", [])
        if isinstance(item, dict)
        and item.get("map_asset_id") in selected_map_ids
        and (item.get("kind") != "target" or item.get("id") == target.get("id"))
    ]
    branch["waypoints"] = [
        item for item in branch.get("waypoints", [])
        if isinstance(item, dict) and item.get("map_asset_id") in selected_map_ids
    ]
    branch["map_edits"] = [
        item for item in branch.get("map_edits", [])
        if isinstance(item, dict) and item.get("map_asset_id") in selected_map_ids
    ]
    branch["virtual_walls"] = [
        item for item in branch.get("virtual_walls", [])
        if isinstance(item, dict) and item.get("map_asset_id") in selected_map_ids
    ]
    physical_ids = {
        str(item.get("attributes", {}).get("physical_elevator_id") or "")
        for item in branch["components"]
        if item.get("kind") == "elevator" and isinstance(item.get("attributes"), dict)
    }
    if isinstance(branch.get("physical_elevators"), list):
        branch["physical_elevators"] = [
            item for item in branch["physical_elevators"]
            if isinstance(item, dict) and item.get("id") in physical_ids
        ]
    return branch


def _single_subtask_document(subtask: dict[str, Any], task_group_name: str) -> dict[str, Any]:
    """Match the R6B multi-task file contract: exactly one subtask object.

    Multi-task runtime files are not full task-group JSON documents.  Each
    member is one selected subtask, so adding a ``subtasks`` wrapper would be
    accepted by a loose JSON reader yet ignored by the runtime executor.
    ``task_group_name`` remains a caller-side audit label only; it must not be
    serialized into the runtime member.
    """
    del task_group_name
    return deepcopy(subtask)


def _merge_artifact(artifacts: dict[str, Artifact], candidate: Artifact) -> None:
    existing = artifacts.get(candidate.relative_path)
    if existing is not None and existing.content != candidate.content:
        raise CompilationError("输出文件名冲突")
    artifacts[candidate.relative_path] = candidate


def compile_indoor_elevator(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    """Compile the only approved profile without writing any output to disk."""
    if not isinstance(project, dict):
        raise CompilationError("部署项目格式无效")
    try:
        status_snapshot = task_status_codes_module.task_status_code_snapshot()
    except task_status_codes_module.TaskStatusCodeError as exc:
        raise CompilationError(f"任务状态码配置无效：{exc}") from exc
    status_xml_values = status_snapshot.xml_values()
    status_config_bytes = status_snapshot.raw_bytes
    status_config_sha = _sha(status_config_bytes)
    scene_model = project.get("scene_model")
    if scene_model not in {"indoor", "custom"}:
        raise CompilationError("当前室内任务模板需要电梯大厅和用户楼层流程")
    if scene_model == "custom":
        flow = project.get("deployment_flow")
        flow_types = [item.get("type") for item in flow] if isinstance(flow, list) else []
        if flow_types != ["lobby", "target_floor"]:
            raise CompilationError(
                "当前室内电梯实验模板不支持户外或摆渡地图；自定义流程仅支持大厅到用户楼层"
            )

    root = Path(map_root).resolve()
    if not root.is_dir():
        raise CompilationError("受控地图根目录不存在")
    assets = _assets(project)
    stage_assets = _stage_assets(project, assets)
    lobby_asset, target_asset = stage_assets["lobby"], stage_assets["target_floor"]
    site_id = _site_id(lobby_asset, root)
    target_asset["source_path"] = _source_path(target_asset, root)
    lobby_instance = _instance_for(project, lobby_asset["id"], "lobby")
    target_instance = _instance_for(project, target_asset["id"], "target_floor")
    building, unit = _same_building_unit(lobby_instance, target_instance)
    community = _community(project)
    components = _components(project, assets)
    start = _lobby_start_component(components, lobby_asset["id"], project)
    target = _one_component(components, target_asset["id"], "target", "目标点")
    door = _door(target)
    arrival_action = _target_arrival_action(target)
    if "physical_elevators" in project:
        lobby_elevator, target_elevator, physical_elevator = _shared_elevator_pair(
            project, components, lobby_asset["id"], target_asset["id"]
        )
        lobby_physical_floor = _shared_physical_floor(physical_elevator, lobby_elevator)
        target_physical_floor = _shared_physical_floor(physical_elevator, target_elevator)
        # A task filename is an operator-facing panel-floor address (15_1509),
        # whereas task JSON uses the runtime physical-floor index.  The map
        # instance deliberately has no floor because it is created before the
        # elevator landing is marked.
        target_task_floor = _shared_button_floor(physical_elevator, target_elevator)
    else:
        lobby_elevator, target_elevator = _elevator_pair(components, lobby_asset["id"], target_asset["id"])
        lobby_physical_floor = _physical_floor(lobby_elevator, lobby_instance)
        target_physical_floor = _physical_floor(target_elevator, target_instance)
        target_task_floor = int(target_instance["floor"])

    _validate_point(lobby_asset, start, "起点")
    _validate_point(target_asset, target, "目标点")
    for elevator, asset, label in ((lobby_elevator, lobby_asset, "大厅电梯"), (target_elevator, target_asset, "目标层电梯")):
        _validate_point(asset, elevator, label)

    lobby_wait, lobby_inward = _wait_point(lobby_elevator)
    target_wait, target_inward = _wait_point(target_elevator)
    # The return task starts at the target-floor elevator call point.  It is
    # derived from the same door/wait geometry as the arrival task, so the
    # operator only needs to mark the delivery target.
    return_target = target_wait
    _validate_point(lobby_asset, lobby_wait, "大厅候梯点")
    _validate_point(target_asset, target_wait, "目标层候梯点")
    lobby_binding_id, target_binding_id, execution_route = _indoor_execution_bindings(
        project, building, unit, lobby_asset["id"], target_asset["id"],
    )
    _assert_approved_indoor_execution_route(execution_route, lobby_binding_id, target_binding_id)
    _assert_route_target_matches_delivery_target(project, execution_route, target)
    try:
        lobby_plan = build_map_execution_plan(
            project, lobby_binding_id, start_anchor=start, end_anchor=lobby_wait,
            end_speed_mode="single_point",
        )
        target_plan = build_map_execution_plan(
            project, target_binding_id, start_anchor=target_wait, end_anchor=target,
            end_speed_mode="single_point",
        )
    except ExecutionChainError as exc:
        raise CompilationError(str(exc)) from exc

    try:
        location_manifest = compile_location_manifest(project, map_root=root)
        layout = RuntimeLayout(str(project.get("id") or ""), community)
        target_template = _floor_template_for_asset(
            project, target_asset["id"], building, unit
        )
    except LocationManifestError as exc:
        raise CompilationError(str(exc)) from exc
    source_localization = layout.localization_yaml(building, unit, "indoor").installed
    target_localization = layout.localization_yaml(
        building, unit, f"floor-{target_template}"
    ).installed
    source_map_yaml = layout.map_yaml(building, unit, "indoor").installed
    target_map_yaml = layout.map_yaml(building, unit, f"floor-{target_template}").installed
    _assert_selected_localization_artifacts(
        project,
        location_manifest,
        layout,
        building,
        unit,
        target_template,
        lobby_asset["id"],
        target_asset["id"],
        lobby_elevator["id"],
    )

    input_value = CompilationInput(
        community=community,
        site_id=site_id,
        building=building,
        unit=unit,
        target_floor=target_physical_floor,
        door=door,
        arrival_action=arrival_action,
        lobby_map_url=source_map_yaml,
        target_map_url=target_map_yaml,
    )
    derived = {
        "start": _point_dict(start),
        "target": _point_dict(target),
        "return_target": _point_dict(return_target),
        "lobby_wait": _point_dict(lobby_wait, lobby_inward),
        "lobby_elevator_center": _point_dict(lobby_elevator, lobby_inward),
        "target_wait": _point_dict(target_wait, target_inward),
        "target_elevator_center": _point_dict(target_elevator, target_inward),
    }
    execution_chain = {
        "lobby": _execution_plan_manifest(lobby_binding_id, lobby_plan, building, unit),
        "target": _execution_plan_manifest(target_binding_id, target_plan, building, unit),
    }
    input_sha = _input_hash(
        project, input_value, derived, execution_chain, status_config_sha,
    )
    task_json = _task_json(
        input_value, derived, lobby_plan, target_plan
    )
    template_hashes: dict[str, str] = {}
    artifacts: list[Artifact] = []

    task_name = f"{community}_{building}_{unit}_{target_task_floor}_{door}.json"
    artifacts.append(_artifact(f"tasks/{task_name}", _task_json_bytes(task_json)))
    xml_values = {
        **_xml_values(
            input_value, target_map_yaml, source_localization, target_localization,
            lobby_physical_floor, lobby_elevator, lobby_inward,
        ),
        **status_xml_values,
    }
    xml_names = {
        "start_task.xml": "start_task.xml",
        "task_complete.xml": "task_complete.xml",
        "elevator_in_n_x.xml": f"{building}_{unit}_elevator_in_n_x.xml",
        "elevator_in_x_n.xml": f"{building}_{unit}_elevator_in_x_n.xml",
        "elevator_out_n_x.xml": f"{building}_{unit}_elevator_out_n_x.xml",
        "elevator_out_x_n.xml": f"{building}_{unit}_elevator_out_x_n.xml",
        "close_elevdoor_n.xml": f"{building}_{unit}_close_elevdoor_n.xml",
        "close_elevdoor_x.xml": f"{building}_{unit}_close_elevdoor_x.xml",
        f"{arrival_action}.xml": f"{arrival_action}.xml",
    }
    for template_name, output_name in xml_names.items():
        template = _template(template_name)
        _validate_status_code_template(template, status_xml_values)
        template_hashes[template_name] = _sha(template.encode("utf-8"))
        content = _render_xml(template, xml_values).encode("utf-8")
        artifacts.append(_artifact(f"waypoint_tasks/{site_id}/{output_name}", content))
    component_artifacts = _component_action_artifacts(
        project, site_id, building, unit, xml_values, status_xml_values,
        lobby_plan, target_plan,
    )
    for template_name, artifact in component_artifacts:
        template_hashes[template_name] = _sha(_template(template_name).encode("utf-8"))
        artifacts.append(artifact)

    template_hashes.setdefault(
        "localization_base.yaml",
        _sha(localization_template_text(project, map_root=root).encode("utf-8")),
    )
    template_hashes["task-status-codes.json"] = status_config_sha
    artifacts.extend(
        _artifact(item.relative_path, item.content) for item in location_manifest.artifacts
    )
    location_artifact_paths = [
        item.relative_path
        for item in location_manifest.artifacts
        if item.relative_path in {"runtime/loc_yaml_path.json", "runtime/lift_id_list.json"}
    ]
    lift_artifact = next(
        (item for item in location_manifest.artifacts if item.relative_path == "runtime/lift_id_list.json"),
        None,
    )
    if lift_artifact is None:
        raise CompilationError("定位电梯清单缺失")
    try:
        lift_document = json.loads(lift_artifact.content)
        lift_count = len(lift_document["lifts"])
    except (TypeError, ValueError, KeyError) as exc:
        raise CompilationError("定位电梯清单无效") from exc

    manifest = {
        "compiler_profile": PROFILE,
        "compiler_version": PROFILE_VERSION,
        "validation_status": "experimental_preview",
        "input_sha256": input_sha,
        "task_status_codes_sha256": status_config_sha,
        "template_sha256": dict(sorted(template_hashes.items())),
        "artifacts": [{"path": item.relative_path, "sha256": item.sha256} for item in artifacts],
        "derived_points": derived,
        "execution_chain": execution_chain,
        "location_manifest": {
            "community": community,
            "binding_count": len(location_manifest.summary),
            "lift_count": lift_count,
            "artifacts": location_artifact_paths,
            "bindings": list(location_manifest.summary),
        },
        "robot_runtime_changed": False,
        "statement": "实验预览：未写入任何机器人运行时文件。",
    }
    return CompilationPreview(input_sha, task_json, tuple(artifacts), manifest, derived)


def bundle_zip(preview: CompilationPreview) -> bytes:
    """Package only compiler-owned relative artifacts plus the manifest."""
    members = list(preview.artifacts) + [_artifact("manifest.json", _json_bytes(preview.manifest))]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in members:
            _safe_archive_path(item.relative_path)
            archive.writestr(item.relative_path, item.content)
    return output.getvalue()


def _assets(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = project.get("map_assets")
    if not isinstance(values, list):
        raise CompilationError("地图资产无效")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or raw["id"] in result:
            raise CompilationError("地图资产无效")
        # Keep compilation pure: derived resolved paths must not be written
        # back into the caller's persisted project document.
        result[raw["id"]] = dict(raw)
    return result


def _stage_assets(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    assignments = project.get("map_stage_assignments")
    if not isinstance(assignments, list):
        raise CompilationError("室内场景必须绑定大厅和目标层地图")
    mapping: dict[str, str] = {}
    for item in assignments:
        if not isinstance(item, dict):
            continue
        stage, asset_id = item.get("stage"), item.get("map_asset_id")
        if stage in {"lobby", "target_floor"} and isinstance(asset_id, str):
            if stage in mapping:
                raise CompilationError("大厅和目标层地图必须各唯一一张")
            mapping[stage] = asset_id
    if set(mapping) != {"lobby", "target_floor"} or mapping["lobby"] == mapping["target_floor"]:
        raise CompilationError("室内场景必须绑定唯一的大厅和目标层地图")
    try:
        return {stage: assets[asset_id] for stage, asset_id in mapping.items()}
    except KeyError as exc:
        raise CompilationError("地图阶段引用不存在的地图资产") from exc


def _site_id(asset: dict[str, Any], root: Path) -> str:
    source = _source_path(asset, root)
    configured = asset.get("site_id")
    if isinstance(configured, str) and _SAFE_SITE_ID.fullmatch(configured):
        asset["source_path"] = source
        return configured
    relative = source.relative_to(root)
    if len(relative.parts) < 2 or not _SAFE_SITE_ID.fullmatch(relative.parts[0]):
        raise CompilationError("地图站点目录无效")
    asset["source_path"] = source
    return relative.parts[0]


def _source_path(asset: dict[str, Any], root: Path) -> Path:
    value = asset.get("source_yaml")
    if not isinstance(value, str) or not value:
        raise CompilationError("地图缺少源 YAML")
    source = Path(value).resolve()
    if source.suffix.lower() not in {".yaml", ".yml"} or not source.is_file() or not source.is_relative_to(root):
        raise CompilationError("地图源 YAML 必须位于受控地图目录")
    return source


def _instance_for(project: dict[str, Any], asset_id: str, stage: str) -> dict[str, Any]:
    values = project.get("map_instances")
    if not isinstance(values, list):
        raise CompilationError("地图实例无效")
    expected_roles = {"lobby"} if stage == "lobby" else {"typical_floor", "floor_override"}
    matches = [item for item in values if isinstance(item, dict) and item.get("map_asset_id") == asset_id and item.get("role") in expected_roles]
    if len(matches) != 1:
        raise CompilationError(f"{stage} 缺少唯一地图实例")
    return matches[0]


def _same_building_unit(lobby: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    values = []
    for item in (lobby, target):
        building, unit = item.get("building"), item.get("unit")
        if not isinstance(building, str) or not building.strip() or not isinstance(unit, str) or not unit.strip():
            raise CompilationError("地图实例缺少楼栋或单元")
        values.append((building.strip(), unit.strip()))
    if values[0] != values[1]:
        raise CompilationError("大厅与目标层必须属于同一楼栋和单元")
    return values[0]


def _floor_template_for_asset(
    project: dict[str, Any], map_asset_id: str, building: str, unit: str
) -> str:
    """Resolve the layout template attached to the current target map asset."""
    bindings = project.get("localization_bindings")
    if not isinstance(bindings, list):
        raise CompilationError("缺少定位绑定")
    matches = [
        item
        for item in bindings
        if isinstance(item, dict)
        and item.get("map_asset_id") == map_asset_id
        and item.get("building") == building
        and item.get("unit") == unit
        and item.get("type") == "floor"
    ]
    if len(matches) != 1:
        raise CompilationError("目标层地图缺少唯一用户楼层定位绑定")
    template = matches[0].get("floor_template")
    if not isinstance(template, str) or not template.strip():
        raise CompilationError("目标层定位绑定缺少布局模板")
    return template.strip()


def _community(project: dict[str, Any]) -> str:
    value = project.get("task_compiler", {})
    identity = value.get("identity", {}) if isinstance(value, dict) else {}
    community = " ".join(str(identity.get("community") or "").split()) if isinstance(identity, dict) else ""
    if not _SAFE_COMMUNITY.fullmatch(community) or community in {".", ".."}:
        raise CompilationError("任务编译器缺少有效小区名称")
    return community


def _components(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values = project.get("components")
    if not isinstance(values, list):
        raise CompilationError("组件数据无效")
    result = []
    for item in values:
        if not isinstance(item, dict) or item.get("map_asset_id") not in assets:
            raise CompilationError("组件地图引用无效")
        result.append(item)
    return result


def _one_component(components: list[dict[str, Any]], asset_id: str, kind: str, label: str) -> dict[str, Any]:
    matches = [item for item in components if item.get("map_asset_id") == asset_id and item.get("kind") == kind]
    if len(matches) != 1:
        raise CompilationError(f"{label}必须恰有一个")
    return matches[0]


def _lobby_start_component(
    components: list[dict[str, Any]], lobby_asset_id: str, project: dict[str, Any],
) -> dict[str, Any]:
    """Use the derived building entry when an external stage precedes lobby.

    For the original two-map route this falls back exactly to the existing
    start component.  In a public-route chain the entry is a core map fact,
    and treating it as the indoor segment's first pose avoids inventing a
    second operator-configured start point.
    """
    routes = project.get("localization_routes")
    if isinstance(routes, list) and len(routes) == 1 and isinstance(routes[0], dict):
        binding_ids = routes[0].get("binding_ids")
        anchors = routes[0].get("entry_anchors")
        if isinstance(binding_ids, list) and binding_ids and isinstance(anchors, list):
            lobby_binding = next(
                (item for item in project.get("localization_bindings", [])
                 if isinstance(item, dict) and item.get("map_asset_id") == lobby_asset_id
                 and item.get("type") == "indoor" and item.get("id") in binding_ids),
                None,
            )
            if lobby_binding is not None:
                entry = next(
                    (item for item in anchors if isinstance(item, dict)
                     and item.get("binding_id") == lobby_binding.get("id")),
                    None,
                )
                anchor = entry.get("anchor") if isinstance(entry, dict) else None
                if isinstance(anchor, dict) and anchor.get("kind") == "component_center":
                    component = next(
                        (item for item in components if item.get("id") == anchor.get("component_id")
                         and item.get("map_asset_id") == lobby_asset_id
                         and item.get("kind") == "building_entrance"),
                        None,
                    )
                    if component is not None:
                        return component
    return _one_component(components, lobby_asset_id, "start", "大厅起点")


def _door(target: dict[str, Any]) -> str:
    attributes = target.get("attributes")
    door = str(attributes.get("door") or "").strip() if isinstance(attributes, dict) else ""
    if not _SAFE_DOOR.fullmatch(door):
        raise CompilationError("目标点缺少有效门牌号")
    return door


def _target_arrival_action(target: dict[str, Any]) -> str:
    """Resolve the only two approved target behaviors from persisted metadata."""
    attributes = target.get("attributes")
    if not isinstance(attributes, dict) or "arrival_action" not in attributes:
        return TARGET_ARRIVAL_ACTION_DEFAULT
    raw = attributes["arrival_action"]
    if not isinstance(raw, str):
        raise CompilationError("目标点到达动作不受支持")
    action = raw.strip()
    if action not in TARGET_ARRIVAL_ACTIONS:
        raise CompilationError("目标点到达动作不受支持")
    return action


def _elevator_pair(components: list[dict[str, Any]], lobby_id: str, target_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    elevators = [item for item in components if item.get("kind") == "elevator"]
    lobby = [item for item in elevators if item.get("map_asset_id") == lobby_id]
    target = [item for item in elevators if item.get("map_asset_id") == target_id]
    if len(elevators) != 2 or len(lobby) != 1 or len(target) != 1:
        raise CompilationError("第一期必须恰有两个同一电梯组件，且大厅和目标层各一个")
    ids = []
    for item in (lobby[0], target[0]):
        attrs = item.get("attributes")
        identifier = str(attrs.get("elevator_id") or "").strip() if isinstance(attrs, dict) else ""
        if not identifier:
            raise CompilationError("同一电梯必须填写电梯编号")
        ids.append(identifier)
    if ids[0] != ids[1]:
        raise CompilationError("同一电梯的编号必须一致")
    return lobby[0], target[0]


def _shared_elevator_pair(
    project: dict[str, Any], components: list[dict[str, Any]], lobby_id: str, target_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Resolve two map-local landings to their one project-level lift."""
    raw = project.get("physical_elevators")
    if not isinstance(raw, list):
        raise CompilationError("物理电梯数据无效")
    elevators = [item for item in components if item.get("kind") == "elevator"]
    lobby = [item for item in elevators if item.get("map_asset_id") == lobby_id]
    target = [item for item in elevators if item.get("map_asset_id") == target_id]
    if len(elevators) != 2 or len(lobby) != 1 or len(target) != 1:
        raise CompilationError("第一期必须恰有两个同一物理电梯落点，且大厅和目标层各一个")
    landing_ids: list[str] = []
    for landing in (lobby[0], target[0]):
        attributes = landing.get("attributes")
        identifier = str(attributes.get("physical_elevator_id") or "").strip() if isinstance(attributes, dict) else ""
        if not identifier:
            raise CompilationError("电梯落点必须关联物理电梯")
        landing_ids.append(identifier)
    if landing_ids[0] != landing_ids[1]:
        raise CompilationError("大厅和目标层必须关联同一物理电梯")
    matches = [item for item in raw if isinstance(item, dict) and item.get("id") == landing_ids[0]]
    if len(matches) != 1:
        raise CompilationError("电梯落点关联的物理电梯不存在")
    physical = matches[0]
    if isinstance(physical.get("migration_conflict"), str) and physical["migration_conflict"].strip():
        raise CompilationError(f"物理电梯旧数据冲突：{physical['migration_conflict']}")
    elevator_id = " ".join(str(physical.get("elevator_id") or "").split())
    protocol = " ".join(str(physical.get("elevator_protocol") or "").split())
    if not elevator_id or not protocol:
        raise CompilationError("物理电梯缺少编号或梯控协议")
    return lobby[0], target[0], physical


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CompilationError(f"{label}无效") from exc
    if not isfinite(number) or abs(number) >= 1e7:
        raise CompilationError(f"{label}无效")
    return number


def _point_dict(component: dict[str, Any], yaw: float | None = None) -> dict[str, float]:
    return {"x": _number(component.get("x"), "组件坐标"), "y": _number(component.get("y"), "组件坐标"), "yaw": _number(component.get("yaw") if yaw is None else yaw, "组件朝向")}


def _validate_point(asset: dict[str, Any], point: dict[str, Any], label: str) -> None:
    value = _point_dict(point)
    try:
        origin = asset["origin"]
        min_x, min_y = float(origin[0]), float(origin[1])
        maximum_x = min_x + float(asset["width"]) * float(asset["resolution_m"])
        maximum_y = min_y + float(asset["height"]) * float(asset["resolution_m"])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CompilationError("地图尺寸元数据无效") from exc
    if not (min_x <= value["x"] <= maximum_x and min_y <= value["y"] <= maximum_y):
        raise CompilationError(f"{label}位于地图边界外")


def _wait_point(elevator: dict[str, Any]) -> tuple[dict[str, float], float]:
    center = _point_dict(elevator)
    attrs = elevator.get("attributes") if isinstance(elevator.get("attributes"), dict) else {}
    height = _number(attrs.get("height_m"), "电梯门向尺寸")
    wait_distance = _number(attrs.get("wait_distance_m", 1.5), "候梯距离")
    if not 0 < height <= 20 or not 0.5 <= wait_distance <= 5:
        raise CompilationError("电梯尺寸或候梯距离超出允许范围")
    door_out_x, door_out_y = -sin(center["yaw"]), cos(center["yaw"])
    inward_yaw = elevator_inward_yaw(center["yaw"])
    distance = height / 2 + wait_distance
    return {"x": center["x"] + door_out_x * distance, "y": center["y"] + door_out_y * distance, "yaw": inward_yaw}, inward_yaw


def _physical_floor(elevator: dict[str, Any], instance: dict[str, Any]) -> int:
    attrs = elevator.get("attributes") if isinstance(elevator.get("attributes"), dict) else {}
    value = attrs.get("physical_floor")
    try:
        map_floor = int(attrs.get("map_floor"))
        expected_physical = map_floor + 1
        floor = int(value) if value is not None else expected_physical
        logical_floor = int(instance.get("floor"))
    except (TypeError, ValueError) as exc:
        raise CompilationError("电梯或地图实例缺少有效楼层") from exc
    if not -19 <= floor <= 121 or logical_floor < -20 or logical_floor > 120:
        raise CompilationError("电梯楼层超出允许范围")
    if map_floor != logical_floor or floor != expected_physical:
        raise CompilationError("电梯楼层必须与所属地图实例一致")
    return floor


def _shared_physical_floor(physical_elevator: dict[str, Any], landing: dict[str, Any]) -> int:
    return _shared_floor_pair(physical_elevator, landing)[0]


def _shared_button_floor(physical_elevator: dict[str, Any], landing: dict[str, Any]) -> int:
    return _shared_floor_pair(physical_elevator, landing)[1]


def _shared_floor_pair(physical_elevator: dict[str, Any], landing: dict[str, Any]) -> tuple[int, int]:
    try:
        minimum = int(physical_elevator.get("min_floor"))
        maximum = int(physical_elevator.get("max_floor"))
        attributes = landing.get("attributes")
        button_floor = int(attributes.get("button_floor")) if isinstance(attributes, dict) else None
    except (TypeError, ValueError) as exc:
        raise CompilationError("物理电梯或电梯落点缺少有效按钮层") from exc
    if not -20 <= minimum <= maximum <= 120:
        raise CompilationError("电梯服务楼层范围无效")
    try:
        physical_floor = physical_floor_index(
            minimum,
            maximum,
            button_floor,
            physical_elevator.get("unavailable_button_floors", ()),
        )
    except LocationManifestError as exc:
        raise CompilationError(f"电梯落点按钮层无效：{exc}") from exc
    return physical_floor, button_floor


def _pose(point: dict[str, float]) -> dict[str, dict[str, float]]:
    yaw = point["yaw"]
    return {"position": {"x": point["x"], "y": point["y"], "z": 0.0}, "orientation": {"x": 0.0, "y": 0.0, "z": sin(yaw / 2), "w": cos(yaw / 2)}}


def _waypoint(identifier: str, point: dict[str, float], speed_mode: str, task_id: str = "", *, is_task_point: bool = True) -> dict[str, Any]:
    if speed_mode not in SPEED_MODES:
        raise CompilationError("速度模式不在批准列表中")
    return {"waypoint_task_id": task_id, "is_task_point": is_task_point, "speed_mode": speed_mode, "is_backward": False, "is_single_point": True, "pose": _pose(point), "waypoint_id": identifier}


def _task_json(
    value: CompilationInput,
    points: dict[str, dict[str, float]],
    lobby_plan: MapExecutionPlan,
    target_plan: MapExecutionPlan,
) -> dict[str, Any]:
    b, u = value.building, value.unit
    return {
        "subtasks": [
            {"change_loc": False, "map_url": value.lobby_map_url, "pcd_url": "", "subtask_name": "elevator_hall", "waypoints": [
                _waypoint("lobby_start", points["start"], "task_point", "start_task", is_task_point=False),
                *_execution_waypoints("lobby", lobby_plan.outbound_nodes, b, u),
                _waypoint("lobby_wait", points["lobby_wait"], "single_point", f"{b}_{u}_elevator_in_n_x"),
                _waypoint("lobby_elevator_center", points["lobby_elevator_center"], "elevator_in", f"{b}_{u}_elevator_out_n_x"),
            ]},
            {"change_loc": False, "map_url": value.target_map_url, "pcd_url": "", "subtask_name": value.door, "waypoints": [
                _waypoint("target_wait", points["target_wait"], "backward", f"{b}_{u}_close_elevdoor_x"),
                *_execution_waypoints(value.door, target_plan.outbound_nodes, b, u),
                _waypoint("target", points["target"], "single_point", value.arrival_action),
            ]},
            {"change_loc": False, "map_url": value.target_map_url, "pcd_url": "", "subtask_name": f"{value.door}_r", "waypoints": [
                *_execution_waypoints(f"{value.door}_r", target_plan.return_nodes, b, u),
                _waypoint("target_return_wait", points["return_target"], "task_point", f"{b}_{u}_elevator_in_x_n"),
                _waypoint("target_return_elevator_center", points["target_elevator_center"], "elevator_in", f"{b}_{u}_elevator_out_x_n"),
            ]},
            {"change_loc": False, "map_url": value.lobby_map_url, "pcd_url": "", "subtask_name": "elevator_hall_r", "waypoints": [
                _waypoint("lobby_return_wait", points["lobby_wait"], "backward", f"{b}_{u}_close_elevdoor_n"),
                *_execution_waypoints("lobby_r", lobby_plan.return_nodes, b, u),
                _waypoint("lobby_return_start", points["start"], "single_point", "task_complete"),
            ]},
        ],
        # The verified task-editor sample keeps the unit in the filename but
        # omits it from task_group_name.
        "task_group_name": f"{value.community}_{value.building}_{value.target_floor - 1}_{value.door}",
    }


def _execution_waypoints(
    prefix: str, nodes: tuple[ExecutionNode, ...], building: str, unit: str,
) -> list[dict[str, Any]]:
    return [
        _waypoint(
            f"{prefix}_{index}" if node.source_kind == "transition"
            else f"{prefix}_{node.source_id}_{node.action or node.role}",
            {"x": node.x, "y": node.y, "yaw": node.yaw},
            node.incoming_speed_mode,
            _component_action_task_id(node, building, unit) if node.action else "",
            is_task_point=bool(node.action),
        )
        for index, node in enumerate(nodes, start=1)
    ]


def _component_action_task_id(node: ExecutionNode, building: str, unit: str) -> str:
    if not node.action or node.source_kind != "component":
        raise CompilationError("组件动作节点无效")
    try:
        verb, direction = node.action.split("_", 1)
    except ValueError as exc:
        raise CompilationError("组件动作名称无效") from exc
    if verb not in {"open", "close"} or direction not in {"go", "back"}:
        raise CompilationError("组件动作名称无效")
    if node.component_kind == "gate":
        return f"e_guard_{verb}_{direction}"
    if node.component_kind == "auto_door":
        return f"{building}_{unit}_{verb}_door_{direction}"
    raise CompilationError("组件动作缺少受支持的设备类型")


def _xml_values(value: CompilationInput, target_map_yaml: str, source_localization: str, target_localization: str, lobby_floor: int, lobby: dict[str, Any], lobby_inward: float) -> dict[str, str]:
    return {
        "ORIGIN_FLOOR": str(lobby_floor),
        "TARGET_LOCALIZATION_YAML": target_localization,
        "TARGET_MAP_YAML": target_map_yaml,
        "SOURCE_LOCALIZATION_YAML": source_localization,
        "RELOCALIZE_X": _format_number(_number(lobby.get("x"), "大厅电梯坐标")),
        "RELOCALIZE_Y": _format_number(_number(lobby.get("y"), "大厅电梯坐标")),
        "RELOCALIZE_YAW": _format_number(lobby_inward),
    }


def _indoor_execution_bindings(
    project: dict[str, Any], building: str, unit: str, lobby_map_id: str, target_map_id: str,
) -> tuple[str, str, dict[str, Any]]:
    bindings = {
        item.get("id"): item
        for item in project.get("localization_bindings", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    route = next(
        (item for item in project.get("localization_routes", [])
         if isinstance(item, dict) and item.get("building") == building and item.get("unit") == unit),
        None,
    )
    if route is None:
        raise CompilationError("旧定位绑定尚未迁移为定位路线")
    selected = [bindings.get(item) for item in route.get("binding_ids", [])]
    lobby = next(
        (item for item in selected if isinstance(item, dict)
         and item.get("type") == "indoor" and item.get("map_asset_id") == lobby_map_id),
        None,
    )
    target = next(
        (item for item in selected if isinstance(item, dict)
         and item.get("type") == "floor" and item.get("map_asset_id") == target_map_id),
        None,
    )
    if lobby is None or target is None:
        raise CompilationError("定位路线未包含室内编译所选大厅或目标层地图")
    return str(lobby["id"]), str(target["id"]), route


def _assert_route_target_matches_delivery_target(
    project: dict[str, Any], route: dict[str, Any], target: dict[str, Any],
) -> None:
    target_id = route.get("task_target_waypoint_id")
    route_target = next(
        (item for item in project.get("waypoints", [])
         if isinstance(item, dict) and item.get("id") == target_id),
        None,
    )
    if route_target is None:
        raise CompilationError("定位路线缺少去程终点")
    try:
        route_pose = _point_dict(route_target)
        target_pose = _point_dict(target)
    except CompilationError as exc:
        raise CompilationError("定位路线的去程终点坐标无效") from exc
    if any(abs(route_pose[key] - target_pose[key]) > 1e-6 for key in ("x", "y", "yaw")):
        raise CompilationError("定位路线的去程终点必须与目标点一致")


def _assert_approved_indoor_execution_route(
    route: dict[str, Any], lobby_binding_id: str, target_binding_id: str,
) -> None:
    """This profile has semantics only for one lobby-to-floor lift journey."""
    if route.get("binding_ids") != [lobby_binding_id, target_binding_id]:
        raise CompilationError(
            "当前室内电梯实验模板不支持户外或摆渡地图；请改用对应的已批准任务 profile"
        )


def _component_action_artifacts(
    project: dict[str, Any],
    site_id: str,
    building: str,
    unit: str,
    xml_values: dict[str, str],
    status_xml_values: dict[str, str],
    *plans: MapExecutionPlan,
) -> list[tuple[str, Artifact]]:
    components = {
        item.get("id"): item for item in project.get("components", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    artifacts: list[tuple[str, Artifact]] = []
    emitted: set[tuple[str, str]] = set()
    for plan in plans:
        for node in (*plan.outbound_nodes, *plan.return_nodes):
            if not node.action:
                continue
            key = (node.source_id, node.action)
            if key in emitted:
                continue
            emitted.add(key)
            component = components.get(node.source_id)
            if component is None or component.get("kind") not in {"gate", "auto_door"}:
                raise CompilationError("组件动作缺少受控组件来源")
            if not node.controller_device_id or not re.fullmatch(r"[1-9][0-9]*", node.controller_device_id):
                raise CompilationError("组件动作缺少纯数字控制设备号")
            template_name = f"components/{component['kind']}_{node.action}.xml"
            task_id = _component_action_task_id(node, building, unit)
            template = _template(template_name)
            _validate_status_code_template(template, status_xml_values)
            rendered = _render_xml(
                template,
                {**xml_values, "CONTROLLER_DEVICE_ID": node.controller_device_id},
            ).encode("utf-8")
            artifacts.append((
                template_name,
                _artifact(f"waypoint_tasks/{site_id}/{task_id}.xml", rendered),
            ))
    return artifacts


def _template(name: str) -> str:
    allowed = {
        "localization_base.yaml", "start_task.xml", "task_complete.xml",
        "elevator_in_n_x.xml", "elevator_in_x_n.xml", "elevator_out_n_x.xml",
        "elevator_out_x_n.xml", "close_elevdoor_n.xml", "close_elevdoor_x.xml",
        "place_water.xml", "auto_cargo.xml",
        *(f"components/{kind}_{action}.xml" for kind in ("gate", "auto_door")
          for action in ("open_go", "close_go", "open_back", "close_back")),
    }
    if name not in allowed:
        raise CompilationError("未批准的行为树模板")
    path = TEMPLATE_ROOT / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompilationError(f"受控模板不可用：{name}") from exc


def _render_xml(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in values:
            raise CompilationError(f"行为树模板包含未批准的替换标记：{token}")
        return xml_escape(values[token], {'"': "&quot;"})
    rendered = _TOKEN.sub(replace, template)
    if "{{" in rendered or "}}" in rendered:
        raise CompilationError("行为树模板包含未解析替换标记")
    try:
        root = ElementTree.fromstring(rendered)
    except ElementTree.ParseError as exc:
        raise CompilationError(f"行为树模板不是有效 XML：{exc}") from exc
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


def _validate_status_code_template(template: str, status_xml_values: dict[str, str]) -> None:
    """Require every task-status publication to use one current registry token."""
    try:
        root = ElementTree.fromstring(template)
    except ElementTree.ParseError as exc:
        raise CompilationError(f"任务状态码模板不是有效 XML：{exc}") from exc
    for node in root.iter("PublishTaskStatus"):
        status_code = node.get("status_code")
        match = _TOKEN.fullmatch(status_code or "")
        if match is None or match.group(1) not in status_xml_values:
            raise CompilationError("任务状态码模板必须使用批准的 STATUS_* 令牌")


def _render_localization(template: str, map_directory: Path) -> str:
    matches = list(re.finditer(r"(?m)^\s*map_path:\s*.*$", template))
    if len(matches) != 1:
        raise CompilationError("定位基线缺少唯一 system.map_path")
    updated, count = re.subn(r"(?m)^(\s*map_path:\s*).*$", lambda match: f"{match.group(1)}{map_directory}", template, count=1)
    if count != 1:
        raise CompilationError("定位基线缺少唯一 system.map_path")
    return updated


def _input_hash(
    project: dict[str, Any],
    value: CompilationInput,
    derived: dict[str, dict[str, float]],
    execution_chain: dict[str, dict[str, Any]],
    task_status_codes_sha256: str,
) -> str:
    payload = {"profile": PROFILE, "input": value.__dict__, "scene_model": project.get("scene_model"), "deployment_flow": project.get("deployment_flow"), "components": project.get("components"), "physical_elevators": project.get("physical_elevators"), "map_assets": project.get("map_assets"), "map_edits": project.get("map_edits"), "virtual_walls": project.get("virtual_walls"), "map_instances": project.get("map_instances"), "localization_bindings": project.get("localization_bindings"), "localization_routes": project.get("localization_routes"), "route_waypoints": _route_waypoint_facts(project), "execution_chain": execution_chain, "map_stage_assignments": project.get("map_stage_assignments"), "derived": derived, "task_status_codes_sha256": task_status_codes_sha256}
    return _sha(_json_bytes(payload))


def _execution_plan_manifest(
    binding_id: str, plan: MapExecutionPlan, building: str, unit: str,
) -> dict[str, Any]:
    def node_summary(node: ExecutionNode) -> dict[str, Any]:
        return {
            "source_kind": node.source_kind,
            "source_id": node.source_id,
            "role": node.role,
            "x": node.x,
            "y": node.y,
            "yaw": node.yaw,
            "incoming_speed_mode": node.incoming_speed_mode,
            "generated_by": node.generated_by,
            "action": node.action,
            "controller_device_id": node.controller_device_id,
            "behavior_tree": (
                f"{_component_action_task_id(node, building, unit)}.xml"
                if node.action else None
            ),
        }
    return {
        "binding_id": binding_id,
        "outbound": [node_summary(node) for node in plan.outbound_nodes],
        "return": [node_summary(node) for node in plan.return_nodes],
    }


def _assert_selected_localization_artifacts(
    project: dict[str, Any],
    location_manifest: Any,
    layout: RuntimeLayout,
    building: str,
    unit: str,
    target_template: str,
    lobby_asset_id: str,
    target_asset_id: str,
    lobby_elevator_id: str,
) -> None:
    """Require the approved indoor maps to be covered by the resolved route export."""
    bindings = project.get("localization_bindings")
    routes = project.get("localization_routes")
    bindings_by_id = {
        item.get("id"): item
        for item in bindings
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(bindings, list) else {}
    selected_route = next((route for route in routes
        if isinstance(route, dict) and route.get("building") == building and route.get("unit") == unit
    ), None) if isinstance(routes, list) else None
    selected_bindings = [bindings_by_id.get(identifier) for identifier in selected_route.get("binding_ids", [])] if selected_route else []
    lobby_binding = next((binding for binding in selected_bindings if isinstance(binding, dict)
        and binding.get("type") == "indoor" and binding.get("map_asset_id") == lobby_asset_id
    ), None)
    floor_binding = next((binding for binding in selected_bindings if isinstance(binding, dict)
        and binding.get("type") == "floor" and binding.get("map_asset_id") == target_asset_id
        and binding.get("floor_template") == target_template
    ), None)
    if lobby_binding is None or floor_binding is None:
        raise CompilationError("定位路线未包含室内编译所选大厅或目标层地图")
    elevator_link = next((link for link in selected_route.get("links", [])
        if isinstance(link, dict) and link.get("from_binding_id") == lobby_binding["id"]
        and link.get("to_binding_id") == floor_binding["id"]
    ), None)
    if elevator_link is None or elevator_link.get("anchor") != {
        "kind": "component_center", "component_id": lobby_elevator_id,
    }:
        raise CompilationError("室内编译的大厅到用户楼层切图必须关联所选电梯组件中心")
    expected = {
        layout.localization_yaml(building, unit, "indoor").relative,
        layout.localization_yaml(building, unit, f"floor-{target_template}").relative,
        layout.map_yaml(building, unit, "indoor").relative,
        layout.map_yaml(building, unit, f"floor-{target_template}").relative,
    }
    exported = {item.relative_path for item in location_manifest.artifacts}
    if not expected <= exported:
        raise CompilationError("定位路线未包含室内编译所选大厅或目标层地图")


def _route_waypoint_facts(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only geometry read while resolving persisted localization routes."""
    routes = project.get("localization_routes")
    waypoints = project.get("waypoints")
    if not isinstance(routes, list) or not isinstance(waypoints, list):
        return []
    by_id = {
        item.get("id"): item
        for item in waypoints
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    identifiers: list[str] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        for value in (
            route.get("task_start_waypoint_id"),
            route.get("task_target_waypoint_id"),
        ):
            if isinstance(value, str) and value not in identifiers:
                identifiers.append(value)
        for link in route.get("links", []):
            anchor = link.get("anchor") if isinstance(link, dict) else None
            value = anchor.get("waypoint_id") if isinstance(anchor, dict) and anchor.get("kind") == "waypoint" else None
            if isinstance(value, str) and value not in identifiers:
                identifiers.append(value)
    facts = []
    for identifier in identifiers:
        waypoint = by_id.get(identifier)
        if waypoint is None:
            facts.append({"id": identifier, "missing": True})
        else:
            facts.append({
                "id": identifier,
                "map_asset_id": waypoint.get("map_asset_id"),
                "x": waypoint.get("x"),
                "y": waypoint.get("y"),
                "yaw": waypoint.get("yaw"),
            })
    return facts


def _artifact(relative_path: str, content: bytes) -> Artifact:
    _safe_archive_path(relative_path)
    return Artifact(relative_path, content, _sha(content))


def _safe_archive_path(relative_path: str) -> None:
    path = Path(relative_path)
    if not relative_path or path.is_absolute() or ".." in path.parts or path.parts[0] not in {"tasks", "multi_tasks", "waypoint_tasks", "localization", "runtime", "manifest.json"}:
        raise CompilationError("导出文件路径无效")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _task_json_bytes(value: dict[str, Any]) -> bytes:
    """Match the readable, field-ordered task JSON used by the task editor."""
    return (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _format_number(value: float) -> str:
    return format(value, ".12g")
