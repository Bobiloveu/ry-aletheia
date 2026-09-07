"""Safe, local SiteProject storage for the first deployment-mapping phase.

This module deliberately only persists SiteProject metadata and imported map
artefacts.  Online mapping is owned by ``mapping.py``; neither module changes
localisation nor writes into ``/opt/ry/data/maps``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .map_assets import MapAssetCache, MapAssetError
from .task_compiler import CompilationPreview, bundle_zip, compile_indoor_elevator


class DeploymentError(ValueError):
    pass


class DeploymentStore:
    SCHEMA = 1
    MAP_ROOT = Path("/opt/ry/data/maps").resolve()
    # This is deliberately not an export destination.  It documents the
    # runtime boundary which experimental compiler exports must never cross.
    RUNTIME_TASK_ROOT = Path("/opt/ry/data/tasks/origin_tasks").resolve()
    EXPORTS_DIRNAME = "exports"
    STAGE_ORDER = {
        "outdoor": ("outdoor",),
        "indoor": ("lobby", "target_floor"),
        "indoor_outdoor": ("outdoor", "lobby", "target_floor"),
    }
    STAGE_LABELS = {
        "outdoor": "室外 / 起点",
        "lobby": "大厅 / 首层",
        "target_floor": "目标楼层",
    }
    PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
    MAP_ID = re.compile(r"map-[a-z0-9][a-z0-9-]{0,63}\Z")
    TASK_COMPILER_COMMUNITY = re.compile(r"[^/\\\x00-\x1f]{1,80}\Z")
    TASK_COMPILER_DOOR = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
    MAX_MAP_BYTES = 2 * 1024 * 1024 * 1024
    MAP_MEMBERS = ("map.yaml", "map.pgm", "map_walls.yaml")
    COMPONENT_LABELS = {"start": "起点", "target": "目标点", "building_entrance": "楼栋入口", "elevator": "电梯", "gate": "闸机", "auto_door": "自动门", "narrow_passage": "窄通道", "ramp": "坡道", "slow_zone": "减速区"}
    COMPONENT_DIMENSIONS = {"elevator": (1.8, 2.0), "gate": (2.0, .7), "auto_door": (1.8, .6), "narrow_passage": (.9, 2.0), "ramp": (1.5, 2.0), "slow_zone": (2.0, 1.5)}
    PROTOCOL_CATEGORIES = ("access_protocols", "elevator_protocols")
    DEFAULT_COMPONENT_TEMPLATES = {
        "access_protocols": (
            {"id": "bluetooth", "label": "蓝牙"},
            {"id": "4g", "label": "4G"},
        ),
        "elevator_protocols": (
            {"id": "bluetooth", "label": "蓝牙"},
            {"id": "4g", "label": "4G"},
        ),
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def _default_component_templates(cls) -> dict[str, list[dict[str, str]]]:
        return {key: [dict(item) for item in value] for key, value in cls.DEFAULT_COMPONENT_TEMPLATES.items()}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _slug(value: str) -> str:
        text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return text[:48] or "site"

    def _project_dir(self, project_id: str) -> Path:
        if not self.PROJECT_ID.fullmatch(project_id):
            raise DeploymentError("部署项目标识无效")
        return self.root / project_id

    def _document_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "site-project.json"

    def _write_json(self, target: Path, value: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    @staticmethod
    def _write_bytes(target: Path, value: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    @classmethod
    def _normalise_task_compiler(cls, source: object) -> dict[str, Any]:
        raw = source if isinstance(source, dict) else {}
        identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
        community = " ".join(str(identity.get("community") or "").split())
        if community in {".", ".."} or not cls.TASK_COMPILER_COMMUNITY.fullmatch(community):
            community = ""
        previous = identity.get("last_preview_input_sha256")
        input_hash = previous if isinstance(previous, str) and re.fullmatch(r"[0-9a-f]{64}", previous) else None
        return {
            "profile": "indoor_elevator_v1",
            "identity": {"community": community, "last_preview_input_sha256": input_hash},
        }

    @classmethod
    def _normalise_physical_elevator(
        cls, source: object, templates: object, *, identifier: str | None = None
    ) -> dict[str, Any]:
        """Validate the project-owned facts of one real elevator.

        Coordinates, door facing and the waiting distance deliberately do not
        belong here: they describe one landing on one map, not the shared
        physical lift.
        """
        if not isinstance(source, dict):
            raise DeploymentError("物理电梯属性无效")
        elevator_id = " ".join(str(source.get("elevator_id") or "").split())
        if not elevator_id:
            raise DeploymentError("电梯编号不能为空")
        if len(elevator_id) > 64:
            raise DeploymentError("电梯编号不能超过 64 个字符")
        catalogue = cls._normalise_component_templates(templates)
        protocol = " ".join(str(source.get("elevator_protocol") or "").split())
        if not protocol:
            protocol = catalogue["elevator_protocols"][0]["id"]
        if protocol not in {item["id"] for item in catalogue["elevator_protocols"]}:
            raise DeploymentError("电梯通信协议不在当前项目模板中")
        try:
            minimum = int(source.get("min_floor"))
            maximum = int(source.get("max_floor"))
        except (TypeError, ValueError) as exc:
            raise DeploymentError("电梯服务楼层必须为整数") from exc
        if not -20 <= minimum <= maximum <= 120:
            raise DeploymentError("电梯最低层和最高层范围无效")
        result = {
            "id": identifier or f"physical-elevator-{uuid.uuid4().hex[:12]}",
            "elevator_id": elevator_id,
            "elevator_protocol": protocol,
            "min_floor": minimum,
            "max_floor": maximum,
        }
        conflict = source.get("migration_conflict")
        if isinstance(conflict, str) and conflict.strip():
            result["migration_conflict"] = " ".join(conflict.split())[:240]
        return result

    def _normalise_physical_elevators(self, document: dict[str, Any]) -> bool:
        """Migrate repeated legacy lift facts into project-level entities.

        Legacy component fields remain for backwards readability, but landing
        geometry remains local and all new consumers use the stable reference.
        """
        templates = document.get("component_templates")
        raw = document.get("physical_elevators")
        migrated = not isinstance(raw, list)
        entries = raw if isinstance(raw, list) else []
        physical: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        by_number: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                migrated = True
                continue
            raw_id = str(entry.get("id") or "").strip()
            if not raw_id or raw_id in by_id:
                migrated = True
                raw_id = f"physical-elevator-{uuid.uuid4().hex[:12]}"
            normalised = self._normalise_physical_elevator(entry, templates, identifier=raw_id)
            if normalised["elevator_id"] in by_number:
                raise DeploymentError("物理电梯编号重复")
            physical.append(normalised)
            by_id[raw_id] = normalised
            by_number[normalised["elevator_id"]] = normalised
            if normalised != entry:
                migrated = True

        for component in document.get("components", []):
            if not isinstance(component, dict) or component.get("kind") != "elevator":
                continue
            attributes = component.get("attributes")
            if not isinstance(attributes, dict):
                continue
            existing_id = str(attributes.get("physical_elevator_id") or "").strip()
            if existing_id and existing_id in by_id:
                continue
            elevator_id = " ".join(str(attributes.get("elevator_id") or "").split())
            if not elevator_id:
                continue
            legacy = self._normalise_physical_elevator(attributes, templates)
            shared = by_number.get(elevator_id)
            if shared is None:
                physical.append(legacy)
                by_id[legacy["id"]] = legacy
                by_number[elevator_id] = legacy
                shared = legacy
                migrated = True
            else:
                divergent = [
                    key
                    for key in ("elevator_protocol", "min_floor", "max_floor")
                    if shared[key] != legacy[key]
                ]
                if divergent:
                    shared["migration_conflict"] = (
                        f"旧电梯编号 {elevator_id} 的共享属性不一致：" + "、".join(divergent)
                    )
                    migrated = True
            if attributes.get("physical_elevator_id") != shared["id"]:
                attributes["physical_elevator_id"] = shared["id"]
                migrated = True

        unlinked = [
            component
            for component in document.get("components", [])
            if isinstance(component, dict)
            and component.get("kind") == "elevator"
            and isinstance(component.get("attributes"), dict)
            and not str(component["attributes"].get("physical_elevator_id") or "").strip()
            and not " ".join(str(component["attributes"].get("elevator_id") or "").split())
        ]
        if len(physical) == 1 and len(unlinked) == 1:
            attributes = dict(unlinked[0]["attributes"])
            attributes["physical_elevator_id"] = physical[0]["id"]
            unlinked[0]["attributes"] = self._normalise_elevator_landing_attributes(
                document, attributes
            )
            migrated = True
        if document.get("physical_elevators") != physical:
            document["physical_elevators"] = physical
            migrated = True
        return migrated

    def _invalidate_task_compiler_preview(self, document: dict[str, Any]) -> None:
        compiler = self._normalise_task_compiler(document.get("task_compiler"))
        compiler["identity"]["last_preview_input_sha256"] = None
        document["task_compiler"] = compiler

    def _compiler_export_root(self, project_id: str) -> Path:
        project_root = self._project_dir(project_id).resolve()
        root = (project_root / self.EXPORTS_DIRNAME).resolve()
        if not root.is_relative_to(project_root):
            raise DeploymentError("实验导出目录无效")
        return root

    def _compiler_export_directory(self, project_id: str, input_sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", input_sha256):
            raise DeploymentError("编译输入指纹无效")
        root = self._compiler_export_root(project_id)
        target = (root / input_sha256).resolve()
        if not target.is_relative_to(root):
            raise DeploymentError("实验导出目录无效")
        return target

    @staticmethod
    def _preview_payload(preview: CompilationPreview) -> dict[str, Any]:
        """Expose only rendered data and relative artifact metadata to HTTP callers."""
        return {
            "status": "ready",
            "experimental": True,
            "input_sha256": preview.input_sha256,
            "task_json": preview.task_json,
            "manifest": preview.manifest,
            "derived_points": preview.derived_points,
            "artifacts": [
                {"path": artifact.relative_path, "sha256": artifact.sha256, "size_bytes": len(artifact.content)}
                for artifact in preview.artifacts
            ],
            "warnings": list(preview.warnings),
            "errors": list(preview.errors),
            "statement": "实验产物，尚未安装到机器人。",
        }

    def _persist_task_compiler_preview(self, project_id: str, document: dict[str, Any], preview: CompilationPreview) -> None:
        export_dir = self._compiler_export_directory(project_id, preview.input_sha256)
        for artifact in preview.artifacts:
            target = (export_dir / artifact.relative_path).resolve()
            if not target.is_relative_to(export_dir):
                raise DeploymentError("实验导出文件路径无效")
            self._write_bytes(target, artifact.content)
        # A manifest is the completion marker.  It is written only after every
        # artifact was durably replaced below this project-owned export root.
        self._write_json(export_dir / "manifest.json", preview.manifest)
        compiler = self._normalise_task_compiler(document.get("task_compiler"))
        compiler["identity"]["last_preview_input_sha256"] = preview.input_sha256
        document["task_compiler"] = compiler
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)

    def list_projects(self) -> list[dict[str, Any]]:
        if not self.root.is_dir(): return []
        result = []
        for item in sorted(self.root.iterdir()):
            if not item.is_dir() or not self.PROJECT_ID.fullmatch(item.name): continue
            try:
                document = self.get(item.name)
                result.append({"id": document["id"], "name": document["name"], "updated_at": document["updated_at"], "map_count": len(document["map_assets"])})
            except DeploymentError:
                continue
        return result

    def create(self, name: object) -> dict[str, Any]:
        cleaned = " ".join(str(name or "").split())
        if not 1 <= len(cleaned) <= 80: raise DeploymentError("项目名称应为 1 至 80 个字符")
        base = self._slug(cleaned)
        project_id = base
        index = 2
        while self._project_dir(project_id).exists():
            project_id = f"{base[:58]}-{index}"; index += 1
        now = self._now()
        document = {"schema": self.SCHEMA, "type": "ry-aletheia.site-project", "id": project_id, "name": cleaned, "created_at": now, "updated_at": now, "scene_model": None, "map_assets": [], "map_stage_assignments": [], "buildings": [], "map_instances": [], "physical_elevators": [], "components": [], "waypoints": [], "routes": [], "map_transitions": [], "virtual_walls": [], "map_edits": [], "behavior_templates": [], "component_templates": self._default_component_templates(), "task_compiler": self._normalise_task_compiler(None), "deployment_config": {"state": "draft", "robot_target": None}, "mapping": {"mode": "import_or_robot", "recording": "not_started"}}
        self._write_json(self._document_path(project_id), document)
        return document

    def get(self, project_id: str) -> dict[str, Any]:
        target = self._document_path(project_id)
        try: document = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc: raise DeploymentError("部署项目不存在或文件损坏") from exc
        if not isinstance(document, dict) or document.get("schema") != self.SCHEMA or document.get("id") != project_id or not isinstance(document.get("map_assets"), list):
            raise DeploymentError("部署项目格式不受支持")
        for key in ("buildings", "map_instances", "components", "waypoints", "routes", "map_transitions", "virtual_walls", "map_edits", "behavior_templates"):
            if not isinstance(document.get(key), list): document[key] = []
        if not isinstance(document.get("map_stage_assignments"), list): document["map_stage_assignments"] = []
        if not isinstance(document.get("deployment_config"), dict): document["deployment_config"] = {"state": "draft", "robot_target": None}
        if document.get("scene_model") not in {None, "indoor", "indoor_outdoor", "outdoor"}: document["scene_model"] = None
        # Correct projects created before physical elevator levels were aligned
        # with the robot protocol (1F maps to command level 2).  This is a
        # derived value only; no user-entered field is changed.
        migrated = False
        templates = self._normalise_component_templates(document.get("component_templates"))
        if document.get("component_templates") != templates:
            document["component_templates"] = templates
            migrated = True
        compiler = self._normalise_task_compiler(document.get("task_compiler"))
        if document.get("task_compiler") != compiler:
            document["task_compiler"] = compiler
            migrated = True
        if self._normalise_project_map_sources(document):
            migrated = True
        if self._normalise_physical_elevators(document):
            migrated = True
        for component in document["components"]:
            if not isinstance(component, dict):
                continue
            attributes = component.get("attributes")
            if not isinstance(attributes, dict):
                continue
            if component.get("kind") == "target" and "door" not in attributes:
                attributes["door"] = ""
                migrated = True
            if component.get("kind") != "elevator":
                continue
            if "wait_distance_m" not in attributes:
                attributes["wait_distance_m"] = 1.5
                migrated = True
            try:
                physical_floor = int(attributes.get("map_floor", 1)) + 1
            except (TypeError, ValueError):
                continue
            if attributes.get("physical_floor") != physical_floor:
                attributes["physical_floor"] = physical_floor
                migrated = True
        if migrated: self._write_json(target, document)
        return document

    def _site_id_for_source(self, project_id: str, source: Path) -> str:
        """Derive a safe behavior-tree site ID without trusting upload staging."""
        try:
            relative = source.resolve().relative_to(self.MAP_ROOT.resolve())
        except ValueError:
            return project_id
        if len(relative.parts) >= 2 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", relative.parts[0]):
            return relative.parts[0]
        return project_id

    def _normalise_project_map_sources(self, document: dict[str, Any]) -> bool:
        """Make project snapshots, not transient imports, the compiler source of truth."""
        project_id = str(document["id"])
        project_root = self._project_dir(project_id).resolve()
        snapshot_root = (project_root / "maps").resolve()
        migrated = False
        for asset in document.get("map_assets", []):
            if not isinstance(asset, dict):
                continue
            files = asset.get("files")
            yaml_relative = files.get("yaml") if isinstance(files, dict) else None
            if not isinstance(yaml_relative, str) or not yaml_relative:
                continue
            snapshot = (project_root / yaml_relative).resolve()
            if (
                snapshot.suffix.lower() not in {".yaml", ".yml"}
                or not snapshot.is_relative_to(snapshot_root)
                or not snapshot.is_file()
            ):
                continue
            source_value = asset.get("source_yaml")
            source = Path(source_value).resolve() if isinstance(source_value, str) and source_value else snapshot
            if asset.get("source_yaml") != str(snapshot):
                asset["source_yaml"] = str(snapshot)
                migrated = True
            site_id = asset.get("site_id")
            if not isinstance(site_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", site_id):
                asset["site_id"] = self._site_id_for_source(project_id, source)
                migrated = True
        return migrated

    def add_physical_elevator(self, project_id: str, data: object) -> dict[str, Any]:
        document = self.get(project_id)
        elevator = self._normalise_physical_elevator(data, document.get("component_templates"))
        if any(item.get("elevator_id") == elevator["elevator_id"] for item in document["physical_elevators"]):
            raise DeploymentError("电梯编号已存在")
        document["physical_elevators"].append(elevator)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return elevator

    def update_physical_elevator(
        self, project_id: str, physical_elevator_id: str, data: object
    ) -> dict[str, Any]:
        document = self.get(project_id)
        if not isinstance(data, dict):
            raise DeploymentError("物理电梯属性无效")
        current = next(
            (item for item in document["physical_elevators"] if item.get("id") == physical_elevator_id),
            None,
        )
        if current is None:
            raise DeploymentError("物理电梯不存在")
        merged = {**current, **data}
        updated = self._normalise_physical_elevator(
            merged, document.get("component_templates"), identifier=physical_elevator_id
        )
        if any(
            item.get("id") != physical_elevator_id
            and item.get("elevator_id") == updated["elevator_id"]
            for item in document["physical_elevators"]
        ):
            raise DeploymentError("电梯编号已存在")
        current.clear()
        current.update(updated)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return current

    def delete_physical_elevator(self, project_id: str, physical_elevator_id: str) -> None:
        document = self.get(project_id)
        if any(
            isinstance(item, dict)
            and isinstance(item.get("attributes"), dict)
            and item["attributes"].get("physical_elevator_id") == physical_elevator_id
            for item in document["components"]
        ):
            raise DeploymentError("物理电梯仍有地图落点")
        previous = len(document["physical_elevators"])
        document["physical_elevators"] = [
            item for item in document["physical_elevators"] if item.get("id") != physical_elevator_id
        ]
        if len(document["physical_elevators"]) == previous:
            raise DeploymentError("物理电梯不存在")
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)

    def update_task_compiler_config(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        document = self.get(project_id)
        if not isinstance(data, dict):
            raise DeploymentError("任务编译器配置无效")
        community = " ".join(str(data.get("community") or "").split())
        if community in {".", ".."} or not self.TASK_COMPILER_COMMUNITY.fullmatch(community):
            raise DeploymentError("小区名称应为不含路径分隔符的 1 至 80 个字符")
        compiler = self._normalise_task_compiler(document.get("task_compiler"))
        compiler["identity"] = {"community": community, "last_preview_input_sha256": None}
        document["task_compiler"] = compiler
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return compiler

    def task_compiler_preview(self, project_id: str) -> dict[str, Any]:
        document = self.get(project_id)
        preview = compile_indoor_elevator(
            document, map_root=self._project_dir(project_id) / "maps"
        )
        self._persist_task_compiler_preview(project_id, document, preview)
        return self._preview_payload(preview)

    def task_compiler_bundle(self, project_id: str) -> tuple[str, bytes]:
        document = self.get(project_id)
        preview = compile_indoor_elevator(
            document, map_root=self._project_dir(project_id) / "maps"
        )
        self._persist_task_compiler_preview(project_id, document, preview)
        task_artifact = next((item for item in preview.artifacts if item.relative_path.startswith("tasks/")), None)
        if task_artifact is None:
            raise DeploymentError("实验任务文件缺失")
        filename = f"{Path(task_artifact.relative_path).stem}_experimental.zip"
        return filename, bundle_zip(preview)

    def set_scene_model(self, project_id: str, scene_model: object) -> dict[str, Any]:
        document = self.get(project_id)
        value = str(scene_model or "")
        if value not in self.STAGE_ORDER:
            raise DeploymentError("场景模型无效")
        assignments = self._stage_assignment_map(document)
        allowed_stages = set(self.STAGE_ORDER[value])
        if any(stage not in allowed_stages for stage in assignments):
            raise DeploymentError("场景模型与已有地图阶段不兼容；请先调整地图阶段")
        document["scene_model"] = value
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return document

    def import_map(self, project_id: str, raw_path: object, label: object, kind: object) -> dict[str, Any]:
        source = Path(str(raw_path or "")).resolve()
        if source.suffix != ".yaml" or not source.is_file() or not source.is_relative_to(self.MAP_ROOT):
            raise DeploymentError("只能导入 /opt/ry/data/maps 内的 map.yaml")
        return self._import_map_snapshot(project_id, source, label, kind, self.MAP_ROOT)

    def import_captured_map(self, project_id: str, captured_yaml: Path, label: object, kind: object, session_root: Path) -> dict[str, Any]:
        """Promote a finished mapping-session output into an editable snapshot."""
        source = captured_yaml.resolve()
        allowed = session_root.resolve()
        if source.suffix != ".yaml" or not source.is_file() or not source.is_relative_to(allowed):
            raise DeploymentError("建图产物不在受控会话目录内")
        return self._import_map_snapshot(project_id, source, label, kind, allowed)

    def import_uploaded_map(self, project_id: str, uploaded_yaml: Path, label: object, kind: object, upload_root: Path) -> dict[str, Any]:
        """Promote a map folder uploaded by the browser into a project snapshot."""
        source = uploaded_yaml.resolve()
        allowed = upload_root.resolve()
        if source.suffix.lower() not in {".yaml", ".yml"} or not source.is_file() or not source.is_relative_to(allowed):
            raise DeploymentError("上传的地图 YAML 不在本次受控导入目录内")
        return self._import_map_snapshot(project_id, source, label, kind, allowed)

    def _import_map_snapshot(self, project_id: str, source: Path, label: object, kind: object, allowed_root: Path) -> dict[str, Any]:
        document = self.get(project_id)
        try:
            yaml_text = source.read_text(encoding="utf-8")
            image_value, resolution, origin = MapAssetCache._parse_metadata(yaml_text)
            image = (source.parent / str(image_value)).resolve() if image_value and not Path(image_value).is_absolute() else Path(str(image_value or "")).resolve()
            if not image.is_file() or not image.is_relative_to(allowed_root.resolve()): raise DeploymentError("地图 YAML 的 image 指向无效")
            width, height = MapAssetCache._pgm_dimensions(image)
            if not resolution or not origin or not width or not height: raise DeploymentError("地图必须是带 resolution、origin 的有效 PGM YAML")
        except (OSError, UnicodeDecodeError, MapAssetError) as exc: raise DeploymentError(f"无法读取地图：{exc}") from exc
        members = [source, image]
        walls = source.with_name("map_walls.yaml")
        if walls.is_file(): members.append(walls)
        pcd = [item for item in source.parent.glob("*.pcd") if item.is_file()]
        members.extend(pcd)
        total = sum(item.stat().st_size for item in members)
        if total > self.MAX_MAP_BYTES: raise DeploymentError("地图资产超过 2 GiB 导入上限")
        digest = self._sha256(source)[:12]
        map_id = f"map-{digest}"
        if any(item.get("id") == map_id for item in document["map_assets"]): raise DeploymentError("该地图已在项目中；不会重复复制")
        target = self._project_dir(project_id) / "maps" / map_id
        target.mkdir(parents=True, exist_ok=False)
        try:
            for item in members: shutil.copy2(item, target / item.name)
            # map YAML can legally name its PGM differently; retain the existing
            # filename and never rewrite user map metadata during import.
        except OSError as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise DeploymentError(f"复制地图资产失败：{exc}") from exc
        cleaned_label = " ".join(str(label or source.parent.name).split())[:80] or source.parent.name
        map_kind = str(kind or "custom")
        if map_kind not in {"outdoor", "lobby", "typical_floor", "custom"}: raise DeploymentError("地图类型无效")
        snapshot_yaml = (target / source.name).resolve()
        asset = {"id": map_id, "label": cleaned_label, "kind": map_kind, "source_yaml": str(snapshot_yaml), "site_id": self._site_id_for_source(project_id, source), "files": {"yaml": f"maps/{map_id}/{source.name}", "image": f"maps/{map_id}/{image.name}", "walls": f"maps/{map_id}/{walls.name}" if walls in members else None, "pcd_count": len(pcd)}, "resolution_m": resolution, "origin": origin, "width": width, "height": height, "sha256": {item.name: self._sha256(item) for item in members}}
        document["map_assets"].append(asset)
        self._assign_next_stage(document, map_id)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)
        return asset

    def stage_plan(self, project_id: str) -> dict[str, Any]:
        """Return the ordered deployment map stages without changing the project."""
        document = self.get(project_id)
        if document.get("scene_model") not in self.STAGE_ORDER:
            return {"scene_model": None, "stages": [], "current_stage": None, "errors": ["请先选择场景模型"]}
        assignments = self._stage_assignment_map(document)
        assets = {item.get("id"): item for item in document["map_assets"] if isinstance(item, dict)}
        stages = []
        for stage in self.STAGE_ORDER[document["scene_model"]]:
            map_id = assignments.get(stage)
            asset = assets.get(map_id)
            stages.append({
                "stage": stage,
                "label": self.STAGE_LABELS[stage],
                "map_asset_id": map_id,
                "map_label": asset.get("label") if asset else None,
                "status": "editing" if asset else "missing",
            })
        current = next((item["stage"] for item in stages if item["status"] == "missing"), None)
        return {"scene_model": document["scene_model"], "stages": stages, "current_stage": current, "errors": []}

    def assign_map_stage(self, project_id: str, map_id: object, stage: object) -> dict[str, Any]:
        """Bind one project map asset to one required deployment stage."""
        document = self.get(project_id)
        scene_model = document.get("scene_model")
        if scene_model not in self.STAGE_ORDER:
            raise DeploymentError("请先选择场景模型")
        asset_id, stage_id = str(map_id or ""), str(stage or "")
        if stage_id not in self.STAGE_ORDER[scene_model]:
            raise DeploymentError("地图阶段不属于当前场景模型")
        if not any(item.get("id") == asset_id for item in document["map_assets"] if isinstance(item, dict)):
            raise DeploymentError("要绑定的地图资产不存在")
        assignments = self._stage_assignment_map(document)
        assigned_stage = next((key for key, value in assignments.items() if value == asset_id), None)
        if assigned_stage and assigned_stage != stage_id:
            raise DeploymentError("该地图已绑定到其他阶段")
        assignments[stage_id] = asset_id
        document["map_stage_assignments"] = [
            {"stage": key, "map_asset_id": assignments[key]}
            for key in self.STAGE_ORDER[scene_model]
            if key in assignments
        ]
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return self.stage_plan(project_id)

    def add_map_transition(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create one directed hand-off between immediately adjacent map stages."""
        document = self.get(project_id)
        scene_model = document.get("scene_model")
        if scene_model not in self.STAGE_ORDER:
            raise DeploymentError("请先选择场景模型")
        source = self._waypoint(document, str(data.get("from_waypoint_id") or ""))
        target = self._waypoint(document, str(data.get("to_waypoint_id") or ""))
        from_map = str(data.get("from_map_asset_id") or "")
        to_map = str(data.get("to_map_asset_id") or "")
        if source["map_asset_id"] != from_map or target["map_asset_id"] != to_map:
            raise DeploymentError("Transition Waypoint 与声明地图不一致")
        if from_map == to_map:
            raise DeploymentError("Transition 必须连接不同地图")
        assignments = self._stage_assignment_map(document)
        from_stage = next((stage for stage, map_id in assignments.items() if map_id == from_map), None)
        to_stage = next((stage for stage, map_id in assignments.items() if map_id == to_map), None)
        if not from_stage or not to_stage:
            raise DeploymentError("Transition 两端地图必须先绑定部署阶段")
        stages = self.STAGE_ORDER[scene_model]
        if stages.index(to_stage) != stages.index(from_stage) + 1:
            raise DeploymentError("Transition 只能连接相邻阶段")
        if any(item.get("from_map_asset_id") == from_map for item in document["map_transitions"]):
            raise DeploymentError("该地图阶段已有出向 Transition")
        if any(item.get("to_map_asset_id") == to_map for item in document["map_transitions"]):
            raise DeploymentError("该地图阶段已有入向 Transition")
        label = " ".join(str(data.get("label") or f"{self.STAGE_LABELS[from_stage]} 至 {self.STAGE_LABELS[to_stage]}").split())[:80]
        if not label:
            raise DeploymentError("Transition 名称不能为空")
        template_ref = data.get("behavior_template_ref")
        if template_ref is not None:
            template_ref = " ".join(str(template_ref).split())[:80] or None
        transition = {
            "id": f"transition-{uuid.uuid4().hex[:12]}",
            "from_map_asset_id": from_map,
            "from_waypoint_id": source["id"],
            "to_map_asset_id": to_map,
            "to_waypoint_id": target["id"],
            "label": label,
            "behavior_template_ref": template_ref,
        }
        document["map_transitions"].append(transition)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return transition

    def delete_map_transition(self, project_id: str, transition_id: str) -> None:
        document = self.get(project_id)
        previous = len(document["map_transitions"])
        document["map_transitions"] = [item for item in document["map_transitions"] if item.get("id") != transition_id]
        if len(document["map_transitions"]) == previous:
            raise DeploymentError("Transition 不存在")
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)

    def save_route(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Store one user-authored route whose geometry stays inside one map asset."""
        document = self.get(project_id)
        map_id = str(data.get("map_asset_id") or "")
        if not any(item.get("id") == map_id for item in document["map_assets"] if isinstance(item, dict)):
            raise DeploymentError("路线对应地图不存在")
        raw_waypoints = data.get("waypoint_ids")
        if not isinstance(raw_waypoints, list):
            raise DeploymentError("路线 Waypoint 列表无效")
        waypoint_ids = [str(value or "") for value in raw_waypoints]
        if len(waypoint_ids) < 2 or len(set(waypoint_ids)) != len(waypoint_ids) or any(not value for value in waypoint_ids):
            raise DeploymentError("路线至少需要两个不重复的 Waypoint")
        points = [self._waypoint(document, waypoint_id) for waypoint_id in waypoint_ids]
        if any(point.get("map_asset_id") != map_id for point in points):
            raise DeploymentError("路线 Waypoint 必须属于同一张地图")
        label = " ".join(str(data.get("label") or "地图路线").split())[:80]
        if not label:
            raise DeploymentError("路线名称不能为空")
        route = {
            "id": f"route-{uuid.uuid4().hex[:12]}",
            "map_asset_id": map_id,
            "label": label,
            "waypoint_ids": waypoint_ids,
        }
        document["routes"].append(route)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return route

    def delete_route(self, project_id: str, route_id: str) -> None:
        document = self.get(project_id)
        previous = len(document["routes"])
        document["routes"] = [item for item in document["routes"] if item.get("id") != route_id]
        if len(document["routes"]) == previous:
            raise DeploymentError("路线不存在")
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)

    def validate_topology(self, project_id: str) -> dict[str, Any]:
        """Validate the project-owned delivery topology without generating files."""
        document = self.get(project_id)
        scene_model = document.get("scene_model")
        if scene_model not in self.STAGE_ORDER:
            return {
                "valid": False,
                "errors": ["请先选择场景模型"],
                "stages": [],
                "transitions": [],
                "routes": [],
                "virtual_wall_count": len(document["virtual_walls"]),
            }
        stage_order = self.STAGE_ORDER[scene_model]
        assignments = self._stage_assignment_map(document)
        assets = {item.get("id"): item for item in document["map_assets"] if isinstance(item, dict)}
        points = {item.get("id"): item for item in document["waypoints"] if isinstance(item, dict)}
        errors: list[str] = []
        map_by_stage: dict[str, str] = {}
        for stage in stage_order:
            map_id = assignments.get(stage)
            if not map_id or map_id not in assets:
                errors.append(f"{self.STAGE_LABELS[stage]}缺少地图")
            else:
                map_by_stage[stage] = map_id

        valid_transitions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        transition_preview: list[dict[str, Any]] = []
        for transition in document["map_transitions"]:
            if not isinstance(transition, dict):
                errors.append("Transition 数据格式无效")
                continue
            from_map = transition.get("from_map_asset_id")
            to_map = transition.get("to_map_asset_id")
            source = points.get(transition.get("from_waypoint_id"))
            target = points.get(transition.get("to_waypoint_id"))
            if not isinstance(source, dict) or not isinstance(target, dict):
                errors.append("Transition 引用了不存在的 Waypoint")
                continue
            if source.get("map_asset_id") != from_map or target.get("map_asset_id") != to_map:
                errors.append("Transition Waypoint 与地图不一致")
                continue
            from_stage = next((stage for stage, map_id in map_by_stage.items() if map_id == from_map), None)
            to_stage = next((stage for stage, map_id in map_by_stage.items() if map_id == to_map), None)
            if not from_stage or not to_stage or stage_order.index(to_stage) != stage_order.index(from_stage) + 1:
                errors.append("Transition 未连接相邻地图阶段")
                continue
            valid_transitions.setdefault((from_stage, to_stage), []).append(transition)
            transition_preview.append(transition)

        stage_status: dict[str, str] = {
            stage: "missing" if stage not in map_by_stage else "editing"
            for stage in stage_order
        }
        first_stage, final_stage = stage_order[0], stage_order[-1]
        if first_stage in map_by_stage and not any(
            point.get("map_asset_id") == map_by_stage[first_stage] and point.get("kind") == "start"
            for point in points.values()
        ):
            errors.append("第一阶段缺少起点 Waypoint")
        if final_stage in map_by_stage and not any(
            point.get("map_asset_id") == map_by_stage[final_stage] and point.get("kind") == "target"
            for point in points.values()
        ):
            errors.append("最终阶段缺少目标 Waypoint")
        for index, stage in enumerate(stage_order[:-1]):
            next_stage = stage_order[index + 1]
            links = valid_transitions.get((stage, next_stage), [])
            if len(links) != 1:
                errors.append(f"{self.STAGE_LABELS[stage]}至{self.STAGE_LABELS[next_stage]}缺少唯一 Transition")
        if not errors:
            for stage in stage_order:
                stage_status[stage] = "complete"

        for route in document["routes"]:
            if not isinstance(route, dict):
                errors.append("路线数据格式无效")
                continue
            route_map = route.get("map_asset_id")
            ids = route.get("waypoint_ids")
            if route_map not in assets or not isinstance(ids, list) or len(ids) < 2 or len(set(ids)) != len(ids):
                errors.append("路线引用无效")
                continue
            if any(not isinstance(points.get(item), dict) or points[item].get("map_asset_id") != route_map for item in ids):
                errors.append("路线 Waypoint 与地图不一致")
        for wall in document["virtual_walls"]:
            if not isinstance(wall, dict) or wall.get("map_asset_id") not in assets:
                errors.append("虚拟墙引用的地图不存在")

        stages = [
            {
                "stage": stage,
                "label": self.STAGE_LABELS[stage],
                "map_asset_id": map_by_stage.get(stage),
                "map_label": assets[map_by_stage[stage]]["label"] if stage in map_by_stage else None,
                "status": stage_status[stage],
            }
            for stage in stage_order
        ]
        return {
            "valid": not errors,
            "errors": errors,
            "stages": stages,
            "transitions": transition_preview,
            "routes": [item for item in document["routes"] if isinstance(item, dict)],
            "virtual_wall_count": len(document["virtual_walls"]),
        }

    def _assign_next_stage(self, document: dict[str, Any], map_id: str) -> None:
        """Use the next empty stage for imports without ever moving an existing map."""
        scene_model = document.get("scene_model")
        if scene_model not in self.STAGE_ORDER:
            return
        assignments = self._stage_assignment_map(document)
        if map_id in assignments.values():
            return
        next_stage = next((stage for stage in self.STAGE_ORDER[scene_model] if stage not in assignments), None)
        if not next_stage:
            return
        assignments[next_stage] = map_id
        document["map_stage_assignments"] = [
            {"stage": stage, "map_asset_id": assignments[stage]}
            for stage in self.STAGE_ORDER[scene_model]
            if stage in assignments
        ]

    @staticmethod
    def _stage_assignment_map(document: dict[str, Any]) -> dict[str, str]:
        """Read valid persisted stage bindings while ignoring legacy malformed rows."""
        result: dict[str, str] = {}
        seen_maps: set[str] = set()
        for item in document.get("map_stage_assignments", []):
            if not isinstance(item, dict):
                continue
            stage, map_id = str(item.get("stage") or ""), str(item.get("map_asset_id") or "")
            if not stage or not map_id or stage in result or map_id in seen_maps:
                continue
            result[stage] = map_id
            seen_maps.add(map_id)
        return result

    @staticmethod
    def _waypoint(document: dict[str, Any], waypoint_id: str) -> dict[str, Any]:
        item = next((point for point in document["waypoints"] if point.get("id") == waypoint_id), None)
        if not isinstance(item, dict):
            raise DeploymentError("Transition Waypoint 不存在")
        return item

    def map_image(self, project_id: str, map_id: str) -> Path:
        if not self.MAP_ID.fullmatch(map_id): raise DeploymentError("地图标识无效")
        document = self.get(project_id)
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        if not asset: raise DeploymentError("地图不存在")
        target = (self._project_dir(project_id) / str(asset["files"]["image"])).resolve()
        if not target.is_relative_to(self._project_dir(project_id)) or not target.is_file(): raise DeploymentError("地图图像不存在")
        return target

    def add_map_instance(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        document = self.get(project_id)
        map_id = str(data.get("map_id", ""))
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        if not asset: raise DeploymentError("要复用的地图资产不存在")
        role = str(data.get("role", ""))
        if role not in {"outdoor", "lobby", "typical_floor", "floor_override"}: raise DeploymentError("地图实例类型无效")
        building = " ".join(str(data.get("building", "")).split())[:32]
        unit = " ".join(str(data.get("unit", "")).split())[:32]
        try: floor = int(data.get("floor")) if data.get("floor") not in (None, "") else None
        except (TypeError, ValueError) as exc: raise DeploymentError("楼层必须是整数") from exc
        if role == "outdoor": building, unit, floor = "", "", None
        elif not building or not unit or floor is None: raise DeploymentError("大厅、标准层和覆盖层必须填写楼栋、单元和楼层")
        instance = {"id": f"instance-{uuid.uuid4().hex[:12]}", "map_asset_id": map_id, "role": role, "building": building, "unit": unit, "floor": floor, "label": " ".join(str(data.get("label") or asset["label"]).split())[:80] or asset["label"]}
        if any(all(item.get(key) == instance[key] for key in ("role", "building", "unit", "floor")) for item in document["map_instances"]):
            raise DeploymentError("该物理位置已有地图实例；请使用 Floor Override 或先检查已有部署")
        document["map_instances"].append(instance)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return instance

    def add_waypoint(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        document = self.get(project_id)
        map_id = str(data.get("map_id", ""))
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        if not asset: raise DeploymentError("Waypoint 对应地图不存在")
        try: x, y = float(data.get("x")), float(data.get("y")); yaw = float(data.get("yaw", 0.0))
        except (TypeError, ValueError) as exc: raise DeploymentError("Waypoint 坐标或朝向无效") from exc
        if not all(abs(value) < 1e7 for value in (x, y, yaw)): raise DeploymentError("Waypoint 数值超出范围")
        minimum_x, minimum_y = float(asset["origin"][0]), float(asset["origin"][1])
        maximum_x = minimum_x + float(asset["width"]) * float(asset["resolution_m"])
        maximum_y = minimum_y + float(asset["height"]) * float(asset["resolution_m"])
        if not (minimum_x <= x <= maximum_x and minimum_y <= y <= maximum_y): raise DeploymentError("Waypoint 必须位于地图边界内")
        kind = str(data.get("kind", "waypoint"))
        if kind not in {"start", "target", "waypoint", "building_entrance", "map_transition"}: raise DeploymentError("Waypoint 类型无效")
        label = " ".join(str(data.get("label") or kind).split())[:80]
        if not label: raise DeploymentError("Waypoint 名称不能为空")
        item = {"id": f"waypoint-{uuid.uuid4().hex[:12]}", "map_asset_id": map_id, "kind": kind, "label": label, "x": x, "y": y, "yaw": yaw}
        document["waypoints"].append(item); document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)
        return item

    def delete_waypoint(self, project_id: str, waypoint_id: str) -> None:
        document = self.get(project_id)
        previous = len(document["waypoints"])
        document["waypoints"] = [item for item in document["waypoints"] if item.get("id") != waypoint_id]
        if len(document["waypoints"]) == previous: raise DeploymentError("Waypoint 不存在")
        document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)

    def add_component(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Store one semantic marker and derive its robot-facing task points.

        Generated points are deliberately tagged with their source component;
        the deployment engine can therefore be rerun after a template change.
        """
        document = self.get(project_id)
        map_id, kind = str(data.get("map_id", "")), str(data.get("kind", ""))
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        recipes = {"start": ["start"], "target": ["target"], "building_entrance": ["building_entrance"], "elevator": ["elevator_call", "elevator_enter", "elevator_exit"], "gate": ["gate_before", "gate_after"], "auto_door": ["door_before", "door_after"], "narrow_passage": ["narrow"], "ramp": ["ramp"], "slow_zone": ["slow"]}
        if not asset: raise DeploymentError("组件对应地图不存在")
        if kind not in recipes: raise DeploymentError("组件类型无效")
        try: x, y, yaw = float(data.get("x")), float(data.get("y")), float(data.get("yaw", 0))
        except (TypeError, ValueError) as exc: raise DeploymentError("组件坐标无效") from exc
        self._validate_point(asset, x, y, yaw)
        label = " ".join(str(data.get("label") or self.COMPONENT_LABELS[kind]).split())[:80] or self.COMPONENT_LABELS[kind]
        component_id = f"component-{uuid.uuid4().hex[:12]}"
        attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        attrs = self._normalise_component_attributes(kind, attrs, document.get("component_templates"))
        if kind == "elevator":
            attrs = self._normalise_elevator_landing_attributes(document, attrs)
        component = {"id": component_id, "map_asset_id": map_id, "kind": kind, "label": label, "x": x, "y": y, "yaw": yaw, "attributes": attrs, "generated_waypoint_ids": []}
        # Offsets may later be supplied by configurable component templates.
        for index, point_kind in enumerate(recipes[kind]):
            offset = (index - (len(recipes[kind]) - 1) / 2) * 0.45
            point = {"id": f"waypoint-{uuid.uuid4().hex[:12]}", "map_asset_id": map_id, "kind": point_kind, "label": f"{label} · {point_kind}", "x": x + offset, "y": y, "yaw": yaw, "generated_by": component_id}
            self._validate_point(asset, point["x"], point["y"], yaw)
            document["waypoints"].append(point); component["generated_waypoint_ids"].append(point["id"])
        document["components"].append(component)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return component

    def update_component(self, project_id: str, component_id: str, data: dict[str, Any]) -> dict[str, Any]:
        document = self.get(project_id); component = next((item for item in document["components"] if item.get("id") == component_id), None)
        if not component: raise DeploymentError("组件不存在")
        asset = next((item for item in document["map_assets"] if item.get("id") == component["map_asset_id"]), None)
        if not asset: raise DeploymentError("组件地图不存在")
        try: x, y, yaw = float(data.get("x", component["x"])), float(data.get("y", component["y"])), float(data.get("yaw", component["yaw"]))
        except (TypeError, ValueError) as exc: raise DeploymentError("组件位置或朝向无效") from exc
        self._validate_point(asset, x, y, yaw)
        attributes = data.get("attributes", component.get("attributes", {}))
        if not isinstance(attributes, dict): raise DeploymentError("组件属性无效")
        attributes = self._normalise_component_attributes(component["kind"], {**component.get("attributes", {}), **attributes}, document.get("component_templates"))
        if component["kind"] == "elevator":
            attributes = self._normalise_elevator_landing_attributes(document, attributes)
        label = " ".join(str(data.get("label", component["label"])).split())[:80]
        if not label: raise DeploymentError("组件名称不能为空")
        component.update({"x": x, "y": y, "yaw": yaw, "label": label, "attributes": attributes})
        # Existing generated points keep stable IDs, but follow their component.
        points = [item for item in document["waypoints"] if item.get("generated_by") == component_id]
        for index, point in enumerate(points):
            offset = (index - (len(points) - 1) / 2) * .45
            point.update({"x": x + offset, "y": y, "yaw": yaw}); self._validate_point(asset, point["x"], point["y"], yaw)
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)
        return component

    @classmethod
    def _normalise_component_templates(cls, source: object) -> dict[str, list[dict[str, str]]]:
        """Normalise the project-owned protocol catalogue.

        The catalogue is intentionally separate from a component instance so
        new robot integrations can be added without changing editor code or
        existing deployment records.
        """
        raw = source if isinstance(source, dict) else {}
        result: dict[str, list[dict[str, str]]] = {}
        for category in cls.PROTOCOL_CATEGORIES:
            candidates = raw.get(category)
            if not isinstance(candidates, list):
                candidates = cls.DEFAULT_COMPONENT_TEMPLATES[category]
            entries: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get("id") or "").strip()
                label = " ".join(str(item.get("label") or "").split())
                if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", identifier) or not 1 <= len(label) <= 40 or identifier in seen:
                    continue
                entries.append({"id": identifier, "label": label})
                seen.add(identifier)
            result[category] = entries or [dict(item) for item in cls.DEFAULT_COMPONENT_TEMPLATES[category]]
        return result

    def add_component_protocol(self, project_id: str, category: object, label: object) -> dict[str, Any]:
        document = self.get(project_id)
        key = str(category or "")
        if key not in self.PROTOCOL_CATEGORIES:
            raise DeploymentError("协议模板类型无效")
        title = " ".join(str(label or "").split())
        if not 1 <= len(title) <= 40:
            raise DeploymentError("协议名称应为 1 至 40 个字符")
        templates = self._normalise_component_templates(document.get("component_templates"))
        if any(item["label"].casefold() == title.casefold() for item in templates[key]):
            raise DeploymentError("该协议已在此模板中")
        identifier = f"custom-{uuid.uuid4().hex[:10]}"
        templates[key].append({"id": identifier, "label": title})
        document["component_templates"] = templates
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return document

    def remove_component_protocol(self, project_id: str, category: object, protocol_id: object) -> dict[str, Any]:
        document = self.get(project_id)
        key, identifier = str(category or ""), str(protocol_id or "")
        if key not in self.PROTOCOL_CATEGORIES:
            raise DeploymentError("协议模板类型无效")
        templates = self._normalise_component_templates(document.get("component_templates"))
        if len(templates[key]) <= 1:
            raise DeploymentError("每类组件至少保留一种通信协议")
        attribute_key = "access_protocol" if key == "access_protocols" else "elevator_protocol"
        component_uses_protocol = any(item.get("attributes", {}).get(attribute_key) == identifier for item in document["components"] if isinstance(item, dict) and isinstance(item.get("attributes"), dict))
        physical_elevator_uses_protocol = key == "elevator_protocols" and any(
            item.get("elevator_protocol") == identifier
            for item in document.get("physical_elevators", [])
            if isinstance(item, dict)
        )
        if physical_elevator_uses_protocol:
            raise DeploymentError("该协议正在被物理电梯使用；请先修改对应电梯")
        if component_uses_protocol:
            raise DeploymentError("该协议正在被组件使用；请先修改对应组件")
        previous = len(templates[key])
        templates[key] = [item for item in templates[key] if item["id"] != identifier]
        if len(templates[key]) == previous:
            raise DeploymentError("协议模板不存在")
        document["component_templates"] = templates
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return document

    def update_map_edits(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Append or revise non-destructive PGM cleanup operations.

        Original robot maps remain immutable.  These world-coordinate edits
        form a project-owned layer that can later be rasterised into a derived
        deployment map after validation.
        """
        document = self.get(project_id)
        action = str(data.get("action") or "add")
        map_id = str(data.get("map_id") or "")
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        if not asset:
            raise DeploymentError("地图编辑对应地图不存在")
        edits = document["map_edits"]
        if action == "undo":
            for index in range(len(edits) - 1, -1, -1):
                if edits[index].get("map_asset_id") == map_id:
                    edits.pop(index)
                    document["updated_at"] = self._now()
                    self._write_json(self._document_path(project_id), document)
                    return document
            raise DeploymentError("当前地图没有可撤销的擦除操作")
        if action == "clear":
            document["map_edits"] = [item for item in edits if item.get("map_asset_id") != map_id]
            document["updated_at"] = self._now()
            self._write_json(self._document_path(project_id), document)
            return document
        if action != "add":
            raise DeploymentError("地图编辑操作无效")
        kind = str(data.get("kind") or "")
        raw_points = data.get("points")
        if kind not in {"brush_erase", "polygon_erase"} or not isinstance(raw_points, list):
            raise DeploymentError("擦除类型或坐标无效")
        minimum_points = 1 if kind == "brush_erase" else 3
        if not minimum_points <= len(raw_points) <= 5000:
            raise DeploymentError("擦除路径点数量无效")
        points: list[dict[str, float]] = []
        for point in raw_points:
            if not isinstance(point, dict):
                raise DeploymentError("擦除路径坐标无效")
            try:
                x, y = float(point.get("x")), float(point.get("y"))
            except (TypeError, ValueError) as exc:
                raise DeploymentError("擦除路径坐标无效") from exc
            self._validate_point(asset, x, y, 0)
            points.append({"x": x, "y": y})
        radius_m = None
        shape = None
        if kind == "brush_erase":
            try:
                radius_m = float(data.get("radius_m"))
            except (TypeError, ValueError) as exc:
                raise DeploymentError("橡皮擦尺寸无效") from exc
            if not .05 <= radius_m <= 10:
                raise DeploymentError("橡皮擦半径应在 0.05 至 10 米之间")
            shape = str(data.get("shape") or "circle")
            if shape not in {"circle", "square"}:
                raise DeploymentError("橡皮擦形状无效")
        edit = {"id": f"map-edit-{uuid.uuid4().hex[:12]}", "map_asset_id": map_id, "kind": kind, "points": points}
        if radius_m is not None:
            edit["radius_m"] = radius_m
            edit["shape"] = shape
        document["map_edits"].append(edit)
        document["updated_at"] = self._now()
        self._write_json(self._document_path(project_id), document)
        return document

    def delete_component(self, project_id: str, component_id: str) -> None:
        document = self.get(project_id)
        if not any(item.get("id") == component_id for item in document["components"]): raise DeploymentError("组件不存在")
        document["components"] = [item for item in document["components"] if item.get("id") != component_id]
        document["waypoints"] = [item for item in document["waypoints"] if item.get("generated_by") != component_id]
        self._invalidate_task_compiler_preview(document)
        document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)

    @staticmethod
    def _validate_dimensions(attributes: dict[str, Any]) -> None:
        try: width, height = float(attributes.get("width_m")), float(attributes.get("height_m"))
        except (TypeError, ValueError) as exc: raise DeploymentError("组件尺寸无效") from exc
        if not .1 <= width <= 20 or not .1 <= height <= 20: raise DeploymentError("组件尺寸应在 0.1 至 20 米之间")
        attributes["width_m"], attributes["height_m"] = width, height

    @classmethod
    def _normalise_component_attributes(cls, kind: str, source: dict[str, Any], templates: object = None) -> dict[str, Any]:
        """Keep semantic component metadata typed and deployment-template ready.

        The editor owns presentation, while this canonical SiteProject layer
        validates only robot-relevant facts.  Deployment templates can consume
        these stable keys later without coupling to a particular UI control.
        """
        defaults: dict[str, Any] = {"width_m": cls.COMPONENT_DIMENSIONS.get(kind, (.8, .8))[0], "height_m": cls.COMPONENT_DIMENSIONS.get(kind, (.8, .8))[1]}
        profiles: dict[str, dict[str, Any]] = {
            "elevator": {"wait_distance_m": 1.5},
            "gate": {"gate_id": "", "access_protocol": "bluetooth", "speed_profile": "single_point"},
            "auto_door": {"door_id": "", "access_protocol": "bluetooth", "speed_profile": "single_point"},
            "narrow_passage": {"speed_profile": "narrow_point"},
            "ramp": {"speed_profile": "slow_point"},
            "slow_zone": {"speed_profile": "slow_point"},
            "target": {"arrival_action": "deliver", "door": ""},
            "start": {"start_action": "dispatch"},
        }
        attributes = {**defaults, **profiles.get(kind, {}), **source}
        catalogue = cls._normalise_component_templates(templates)
        protocol_category = "access_protocols" if kind in {"gate", "auto_door"} else None
        protocol_key = "access_protocol" if protocol_category == "access_protocols" else "elevator_protocol" if protocol_category else None
        # A project owns its protocol catalogue.  A newly placed component must
        # therefore start with a protocol that this project actually exposes,
        # rather than a historical global default such as ``bluetooth``.
        # Explicit caller input is still validated below and never rewritten.
        if protocol_category and protocol_key and protocol_key not in source:
            attributes[protocol_key] = catalogue[protocol_category][0]["id"]
        cls._validate_dimensions(attributes)
        if kind == "elevator":
            try:
                wait_distance_m = float(attributes["wait_distance_m"])
            except (TypeError, ValueError) as exc:
                raise DeploymentError("候梯距离无效") from exc
            if not .5 <= wait_distance_m <= 5.0:
                raise DeploymentError("候梯距离应在 0.5 至 5 米之间")
            attributes["wait_distance_m"] = wait_distance_m
        if kind == "target":
            door = str(attributes.get("door") or "").strip()
            if door and not cls.TASK_COMPILER_DOOR.fullmatch(door):
                raise DeploymentError("目标门牌号应为 1 至 32 个字母、数字、连字符或下划线")
            attributes["door"] = door
        for key in ("gate_id", "door_id", "access_protocol", "elevator_protocol", "control_protocol", "speed_profile", "arrival_action", "start_action"):
            if key in attributes:
                value = " ".join(str(attributes[key] or "").split())
                if len(value) > 64: raise DeploymentError("组件属性不能超过 64 个字符")
                attributes[key] = value
        if protocol_category and protocol_key and attributes[protocol_key] not in {item["id"] for item in catalogue[protocol_category]}:
            raise DeploymentError("组件通信协议不在当前项目模板中")
        return attributes

    @staticmethod
    def _normalise_elevator_landing_attributes(
        document: dict[str, Any], attributes: dict[str, Any]
    ) -> dict[str, Any]:
        """Keep a map landing linked to an existing physical elevator only."""
        physical_elevator_id = str(attributes.get("physical_elevator_id") or "").strip()
        if not physical_elevator_id:
            raise DeploymentError("电梯落点必须关联物理电梯")
        if not any(
            item.get("id") == physical_elevator_id
            for item in document.get("physical_elevators", [])
            if isinstance(item, dict)
        ):
            raise DeploymentError("物理电梯不存在")
        local = dict(attributes)
        for key in (
            "elevator_id",
            "elevator_protocol",
            "min_floor",
            "max_floor",
            "map_floor",
            "physical_floor",
        ):
            local.pop(key, None)
        local["physical_elevator_id"] = physical_elevator_id
        return local

    def add_virtual_wall(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        document = self.get(project_id); map_id = str(data.get("map_id", ""))
        asset = next((item for item in document["map_assets"] if item.get("id") == map_id), None)
        points = data.get("points")
        if not asset or not isinstance(points, list) or len(points) < 3: raise DeploymentError("虚拟墙需在一张已导入地图内至少绘制三个点")
        cleaned = []
        for point in points:
            if not isinstance(point, dict): raise DeploymentError("虚拟墙坐标无效")
            x, y = float(point.get("x")), float(point.get("y")); self._validate_point(asset, x, y, 0); cleaned.append({"x": x, "y": y})
        wall = {"id": f"wall-{uuid.uuid4().hex[:12]}", "map_asset_id": map_id, "kind": "forbidden_zone", "label": " ".join(str(data.get("label") or "禁行区").split())[:80], "points": cleaned}
        document["virtual_walls"].append(wall); document["updated_at"] = self._now(); self._write_json(self._document_path(project_id), document)
        return wall

    @staticmethod
    def _validate_point(asset: dict[str, Any], x: float, y: float, yaw: float) -> None:
        if not all(abs(value) < 1e7 for value in (x, y, yaw)): raise DeploymentError("坐标数值超出范围")
        minimum_x, minimum_y = float(asset["origin"][0]), float(asset["origin"][1])
        if not (minimum_x <= x <= minimum_x + float(asset["width"]) * float(asset["resolution_m"]) and minimum_y <= y <= minimum_y + float(asset["height"]) * float(asset["resolution_m"])): raise DeploymentError("标记必须位于地图边界内")
