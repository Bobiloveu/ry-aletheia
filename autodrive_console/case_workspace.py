from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .case_store import CaseStore
from .models import TestCase


class CasePackageError(ValueError):
    """A portable test-case package failed a safety or compatibility check."""


class CaseWorkspace:
    """Persistent management metadata for cases stored on one robot.

    Task JSON remains the execution source of truth.  This registry only stores
    management information and fingerprints, so importing/exporting a case can
    never overwrite vehicle-specific scenario bindings or robot configuration.
    """

    SCHEMA = 1
    PACKAGE_TYPE = "ry-aletheia.test-case"
    MAX_PACKAGE_BYTES = 8 * 1024 * 1024
    MAX_UNPACKED_BYTES = 10 * 1024 * 1024
    MAX_COMPRESSION_RATIO = 80
    VALID_LIFECYCLES = {"draft", "local_verified", "published", "deprecated"}
    PACKAGE_MEMBERS = {"manifest.json", "task.json", "checksums.sha256"}
    VERSION = re.compile(r"^\d+(?:\.\d+){0,3}(?:[-+][A-Za-z0-9.-]+)?$")

    def __init__(self, config_dir: Path, case_dir: Path) -> None:
        self.path = config_dir / "case_workspace.json"
        self.case_dir = case_dir

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _default_document() -> dict:
        return {"schema": CaseWorkspace.SCHEMA, "cases": {}}

    def load(self) -> dict:
        if not self.path.is_file():
            return self._default_document()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("schema") != self.SCHEMA or not isinstance(document.get("cases"), dict):
                raise ValueError
            return document
        except (OSError, json.JSONDecodeError, ValueError):
            # A broken optional registry must never prevent existing task JSON
            # files from being discovered/executed.  The UI reports untracked
            # cases and the next metadata write repairs the registry.
            return self._default_document()

    def _save(self, document: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".case_workspace_", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _sha256(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _fingerprint(self, case: TestCase, previous: dict | None = None) -> dict:
        path = Path(case.source)
        stat = path.stat()
        signature = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        cached = (previous or {}).get("fingerprint")
        if isinstance(cached, dict) and all(cached.get(key) == value for key, value in signature.items()) and isinstance(cached.get("sha256"), str):
            return cached
        digest = self._sha256(path.read_bytes())
        return {**signature, "sha256": digest}

    @staticmethod
    def _clean_text(value: object, label: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise CasePackageError(f"{label}必须是文本")
        cleaned = " ".join(value.split())
        if len(cleaned) > maximum:
            raise CasePackageError(f"{label}不能超过 {maximum} 个字符")
        return cleaned

    def _metadata(self, case: TestCase, existing: dict | None = None) -> dict:
        previous = existing if isinstance(existing, dict) else {}
        fingerprint = self._fingerprint(case, previous)
        lifecycle = previous.get("lifecycle", "draft")
        if lifecycle not in self.VALID_LIFECYCLES:
            lifecycle = "draft"
        tags = previous.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return {
            "case_uid": previous.get("case_uid") if isinstance(previous.get("case_uid"), str) else str(uuid.uuid4()),
            "version": previous.get("version") if isinstance(previous.get("version"), str) else "0.1.0",
            "lifecycle": lifecycle,
            "tags": [str(item) for item in tags if isinstance(item, str)][:12],
            "summary": previous.get("summary") if isinstance(previous.get("summary"), str) else "",
            "recommended_execution": previous.get("recommended_execution") if isinstance(previous.get("recommended_execution"), dict) else {},
            "fingerprint": fingerprint,
            "origin": previous.get("origin") if isinstance(previous.get("origin"), dict) else {"kind": "local"},
            "created_at": previous.get("created_at") if isinstance(previous.get("created_at"), str) else self._now(),
            "updated_at": previous.get("updated_at") if isinstance(previous.get("updated_at"), str) else self._now(),
        }

    def describe(self, case: TestCase) -> dict:
        document = self.load()
        existing = document["cases"].get(case.id)
        metadata = self._metadata(case, existing)
        if isinstance(existing, dict) and existing.get("fingerprint") != metadata.get("fingerprint"):
            metadata["updated_at"] = self._now()
        if existing != metadata:
            document["cases"][case.id] = metadata
            self._save(document)
        return metadata

    def update(self, case: TestCase, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise CasePackageError("用例管理信息格式错误")
        document = self.load()
        current = self._metadata(case, document["cases"].get(case.id))
        if "version" in payload:
            version = self._clean_text(payload["version"], "用例版本", 32)
            if not version or not self.VERSION.fullmatch(version):
                raise CasePackageError("用例版本应为 0.1、1.2 或语义化版本")
            current["version"] = version
        if "lifecycle" in payload:
            lifecycle = payload["lifecycle"]
            if lifecycle not in self.VALID_LIFECYCLES:
                raise CasePackageError("用例状态无效")
            current["lifecycle"] = lifecycle
        if "summary" in payload:
            current["summary"] = self._clean_text(payload["summary"], "用例说明", 300)
        if "tags" in payload:
            raw_tags = payload["tags"]
            if not isinstance(raw_tags, list) or len(raw_tags) > 12:
                raise CasePackageError("标签最多 12 个")
            tags: list[str] = []
            for tag in raw_tags:
                clean = self._clean_text(tag, "标签", 24)
                if clean and clean not in tags:
                    tags.append(clean)
            current["tags"] = tags
        if "recommended_execution" in payload:
            recommended = payload["recommended_execution"]
            if not isinstance(recommended, dict):
                raise CasePackageError("推荐执行参数格式错误")
            try:
                rounds = int(recommended.get("rounds", 1))
                interval = float(recommended.get("interval_seconds", 3))
            except (TypeError, ValueError) as exc:
                raise CasePackageError("推荐执行参数必须是数字") from exc
            if not 1 <= rounds <= 1000 or not 0 <= interval <= 3600:
                raise CasePackageError("推荐执行参数超出允许范围")
            current["recommended_execution"] = {"rounds": rounds, "interval_seconds": interval}
        current["updated_at"] = self._now()
        document["cases"][case.id] = current
        self._save(document)
        return current

    def export_package(self, case: TestCase, alias: str = "") -> tuple[str, bytes]:
        metadata = self.describe(case)
        task = Path(case.source).read_bytes()
        manifest = {
            "schema": self.SCHEMA,
            "type": self.PACKAGE_TYPE,
            "case_uid": metadata["case_uid"],
            "version": metadata["version"],
            "display_name": alias or case.filename,
            "task_filename": case.filename,
            "task_sha256": self._sha256(task),
            "lifecycle": metadata["lifecycle"],
            "tags": metadata["tags"],
            "summary": metadata["summary"],
            "recommended_execution": metadata["recommended_execution"],
            "exported_at": self._now(),
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        checksums = f"{self._sha256(manifest_bytes)}  manifest.json\n{self._sha256(task)}  task.json\n".encode("ascii")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.writestr("manifest.json", manifest_bytes)
            bundle.writestr("task.json", task)
            bundle.writestr("checksums.sha256", checksums)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(case.filename).stem).strip("._") or "test_case"
        return f"{safe_name}_{metadata['version']}.rycase.zip", output.getvalue()

    def _read_package(self, source: bytes) -> tuple[dict, bytes]:
        if not 1 <= len(source) <= self.MAX_PACKAGE_BYTES:
            raise CasePackageError("用例包大小无效或超过 8 MiB 限制")
        try:
            archive = zipfile.ZipFile(io.BytesIO(source))
        except zipfile.BadZipFile as exc:
            raise CasePackageError("用例包不是有效 ZIP 文件") from exc
        with archive:
            names = {item.filename for item in archive.infolist()}
            if names != self.PACKAGE_MEMBERS or len(archive.infolist()) != len(self.PACKAGE_MEMBERS):
                raise CasePackageError("用例包只能包含 manifest.json、task.json 和 checksums.sha256")
            total = 0
            for item in archive.infolist():
                if item.is_dir() or item.file_size < 0 or item.file_size > self.MAX_UNPACKED_BYTES:
                    raise CasePackageError("用例包包含无效文件")
                total += item.file_size
                if item.compress_size and item.file_size / item.compress_size > self.MAX_COMPRESSION_RATIO:
                    raise CasePackageError("用例包压缩比异常，已拒绝解压")
            if total > self.MAX_UNPACKED_BYTES:
                raise CasePackageError("用例包解压后超过大小限制")
            manifest_bytes = archive.read("manifest.json")
            task = archive.read("task.json")
            checksums = archive.read("checksums.sha256").decode("ascii", errors="strict")
        expected: dict[str, str] = {}
        for line in checksums.splitlines():
            if not line.strip():
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or parts[1] in expected:
                raise CasePackageError("用例包校验和格式无效")
            expected[parts[1]] = parts[0]
        if set(expected) != {"manifest.json", "task.json"}:
            raise CasePackageError("用例包校验和文件不完整")
        if expected.get("manifest.json") != self._sha256(manifest_bytes) or expected.get("task.json") != self._sha256(task):
            raise CasePackageError("用例包校验和不匹配")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CasePackageError("用例包清单不是有效 UTF-8 JSON") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != self.SCHEMA or manifest.get("type") != self.PACKAGE_TYPE:
            raise CasePackageError("不支持的用例包格式")
        if manifest.get("task_sha256") != self._sha256(task):
            raise CasePackageError("任务文件指纹不匹配")
        return manifest, task

    def import_package(self, source: bytes) -> dict:
        manifest, task = self._read_package(source)
        filename = str(manifest.get("task_filename", ""))
        if not filename or Path(filename).name != filename:
            raise CasePackageError("用例包任务文件名不安全")
        try:
            contents = task.decode("utf-8")
            case = CaseStore.parse_case(filename, contents, str(self.case_dir / filename))
        except UnicodeDecodeError as exc:
            raise CasePackageError("用例包中的任务文件必须使用 UTF-8 编码") from exc
        version = self._clean_text(manifest.get("version", "0.1.0"), "用例版本", 32)
        if not self.VERSION.fullmatch(version):
            raise CasePackageError("用例包版本格式无效")
        lifecycle = manifest.get("lifecycle", "draft")
        if lifecycle not in self.VALID_LIFECYCLES:
            raise CasePackageError("用例包状态无效")
        package_tags = manifest.get("tags", [])
        if not isinstance(package_tags, list) or len(package_tags) > 12:
            raise CasePackageError("用例包标签格式无效")
        tags: list[str] = []
        for tag in package_tags:
            clean = self._clean_text(tag, "标签", 24)
            if clean and clean not in tags:
                tags.append(clean)
        summary = self._clean_text(manifest.get("summary", ""), "用例说明", 300)
        recommended = manifest.get("recommended_execution", {})
        if not isinstance(recommended, dict):
            raise CasePackageError("用例包推荐执行参数格式无效")
        if recommended:
            try:
                rounds = int(recommended.get("rounds", 1))
                interval = float(recommended.get("interval_seconds", 3))
            except (TypeError, ValueError) as exc:
                raise CasePackageError("用例包推荐执行参数无效") from exc
            if not 1 <= rounds <= 1000 or not 0 <= interval <= 3600:
                raise CasePackageError("用例包推荐执行参数超出允许范围")
            recommended = {"rounds": rounds, "interval_seconds": interval}
        target = self.case_dir / filename
        if target.exists():
            existing_hash = self._sha256(target.read_bytes())
            if existing_hash == self._sha256(task):
                return {"status": "already_present", "case": case, "message": "本机已存在内容一致的用例，未重复写入"}
            raise CasePackageError("tasks/ 中存在同名但内容不同的用例；已拒绝覆盖。请在来源端调整任务文件名后重新导出，工具不会擅自改写任务身份")
        self.case_dir.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(task)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            if target.exists():
                target.unlink()
            raise
        document = self.load()
        document["cases"][case.id] = {
            "case_uid": manifest.get("case_uid") if isinstance(manifest.get("case_uid"), str) else str(uuid.uuid4()),
            "version": version,
            "lifecycle": lifecycle,
            "tags": tags,
            "summary": summary,
            "recommended_execution": recommended,
            "fingerprint": {"size": len(task), "mtime_ns": target.stat().st_mtime_ns, "sha256": self._sha256(task)},
            "origin": {"kind": "package", "case_uid": manifest.get("case_uid", ""), "imported_at": self._now()},
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self._save(document)
        return {"status": "imported", "case": case, "message": "用例包已校验并导入；本机启动方案保持未绑定"}
