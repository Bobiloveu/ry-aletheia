"""受控的场景前置启动参数切换。

本模块刻意不是通用文件编辑器：只识别 handle_modules.sh 中两个已登记的
ROS 启动参数，并以事务备份、校验和原子替换保护机器人常规配置。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


DEFAULT_DOCUMENT = {
    "startup_script": "/opt/ry/scripts/handle_modules.sh",
    "search_directories": [],
    "bindings": {},
    "profiles": [],
    "case_bindings": {},
}

_FCRP = re.compile(r"(?P<prefix>\bros2\s+launch\s+fcrp_bringup\s+)(?P<value>[^\s#]+)")
_LIGHTNING = re.compile(r"(?P<prefix>\bros2\s+run\s+lightning\s+run_loc_online\s+--config\s+)(?P<value>[^\s#]+)")
_ROS_LAUNCH = re.compile(r"(?P<prefix>\bros2\s+launch\s+(?P<package>[^\s#]+)\s+)(?P<value>[^\s#]+)")
_ROS_RUN_CONFIG = re.compile(r"(?P<prefix>\bros2\s+run\s+(?P<package>[^\s#]+)\s+(?P<executable>[^\s#]+)(?P<before_config>.*?)\s+--config\s+)(?P<value>[^\s#]+)")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class ScenarioSetupError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class ScenarioSetupStore:
    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / "scenario_setup.json"
        self.backup_dir = config_dir / "scenario_backups"
        self._lock = threading.RLock()
        # 覆盖“脚本替换 → Supervisor 重启 → 状态确认”的较长事务；不能仅靠
        # 文件锁，因为 HTTP 的重复点击和测试 finally 可能在两次文件操作之间
        # 交错重启同一批节点。
        self.runtime_lock = threading.Lock()

    def load(self) -> dict:
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                raw = {}
            document = {**DEFAULT_DOCUMENT, **(raw if isinstance(raw, dict) else {})}
            document["profiles"] = document["profiles"] if isinstance(document["profiles"], list) else []
            document["case_bindings"] = document["case_bindings"] if isinstance(document["case_bindings"], dict) else {}
            document["bindings"] = document["bindings"] if isinstance(document["bindings"], dict) else {}
            document["search_directories"] = document["search_directories"] if isinstance(document["search_directories"], list) else []
            return document

    def save(self, document: dict) -> dict:
        prepared = self._validate_document(document)
        with self._lock:
            self._raise_if_transaction_unresolved()
            temporary: Path | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", mode="w", encoding="utf-8", delete=False) as output:
                    output.write(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                    temporary = Path(output.name)
                os.replace(temporary, self.path)
                self._fsync_directory(self.path.parent)
            except OSError as exc:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise ScenarioSetupError(f"无法安全保存场景前置配置：{exc}") from exc
        return prepared

    def status(self) -> dict:
        # 状态查询也必须与 apply/restore 使用同一把锁。否则网页刷新刚好撞上
        # active.json 替换时，可能把瞬时空档误显示为“常规配置”。
        with self._lock:
            document = self.load()
            active, transaction = self._transaction_status()
            script = Path(document["startup_script"])
            inspection = {"path": str(script), "exists": script.is_file(), "writable": os.access(script, os.W_OK) if script.exists() else False}
            if script.is_file():
                try:
                    inspection.update(self._inspect_text(script.read_text(encoding="utf-8")))
                except UnicodeDecodeError:
                    inspection["error"] = "启动脚本不是 UTF-8 文本"
            # 文件选择改为按需逐级浏览，不在状态查询时递归扫描整棵机器人目录。
            return {
                "document": document,
                # 事务备份中含有常规脚本全文；状态接口只返回操作者需要的元数据。
                "active_backup": self._public_active(active),
                "transaction": transaction,
                "inspection": inspection,
                "files": {"scripts": [], "launch": [], "yaml": []},
            }

    def has_unresolved_transaction(self) -> bool:
        """活动或损坏的恢复事务都不能被当作常规配置。"""
        with self._lock:
            _active, transaction = self._transaction_status()
            return transaction["state"] != "normal"

    def is_case_bound(self, case_id: str) -> bool:
        """供执行器在写脚本前确认是否必须具备可重启的依赖编排。"""
        with self._lock:
            document = self.load()
            profile_id = str(document.get("case_bindings", {}).get(case_id, "")).strip()
            if not profile_id:
                return False
            if not any(item["id"] == profile_id for item in document["profiles"]):
                raise ScenarioSetupError("该用例绑定的场景前置方案不存在；请在用例资产库重新绑定")
            return True

    def browse(self, raw_path: str, kind: str) -> dict:
        """列出受控目录的一层内容，供 FCRP/lightning 文件浏览器按需使用。"""
        document = self.load()
        root = self._allowed_root(Path(document["startup_script"]))
        try:
            target = Path(raw_path or root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ScenarioSetupError("浏览目录不存在或无法解析") from exc
        if not target.is_dir() or (target != root and root not in target.parents):
            raise ScenarioSetupError("只能浏览启动脚本所在受控目录内的路径")
        if kind not in {"fcrp", "lightning"}:
            raise ScenarioSetupError("文件浏览类型无效")
        directories, files = [], []
        try:
            children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
            for child in children:
                if child.name.startswith("."):
                    continue
                try:
                    resolved = child.resolve(strict=True)
                except OSError:
                    continue
                if resolved != root and root not in resolved.parents:
                    continue
                if child.is_dir() and len(directories) < 300:
                    directories.append({"name": child.name, "path": str(resolved)})
                elif child.is_file() and len(files) < 300:
                    allowed = child.name.endswith(".launch.py") if kind == "fcrp" else child.suffix in {".yaml", ".yml"}
                    if allowed:
                        files.append({"name": child.name, "path": str(resolved), "size": child.stat().st_size})
        except OSError as exc:
            raise ScenarioSetupError(f"无法读取目录：{exc}") from exc
        parent = str(target.parent) if target != root else None
        return {"root": str(root), "path": str(target), "parent": parent, "directories": directories, "files": files, "kind": kind}

    def read_file(self, raw_path: str) -> dict:
        """读取供前端核验的受控文本文件，不提供写入能力。"""
        document = self.load()
        script = Path(document["startup_script"])
        root = self._allowed_root(script)
        try:
            target = Path(str(raw_path)).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ScenarioSetupError("所选文件不存在或无法解析") from exc
        if target != root and root not in target.parents:
            raise ScenarioSetupError("只能预览启动脚本所在受控目录内的文件")
        if not target.is_file() or target.suffix not in {".sh", ".py", ".yaml", ".yml"}:
            raise ScenarioSetupError("仅支持预览 .sh、.py、.yaml 和 .yml 文件")
        try:
            if target.stat().st_size > 512 * 1024:
                raise ScenarioSetupError("文件超过 512 KiB，拒绝在浏览器中预览")
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ScenarioSetupError("文件不是 UTF-8 文本，无法安全预览") from exc
        except OSError as exc:
            raise ScenarioSetupError(f"无法读取所选文件：{exc}") from exc
        return {"path": str(target), "content": content, "size": len(content.encode("utf-8")), "sha256": _sha256(content.encode("utf-8"))}

    def apply(self, profile_id: str) -> dict:
        with self._lock:
            document = self.load()
            profile = next((item for item in document["profiles"] if item["id"] == profile_id), None)
            if not profile:
                raise ScenarioSetupError("未找到指定场景前置方案")
            self._raise_if_transaction_unresolved()
            script = Path(document["startup_script"])
            original = self._read_script(script)
            values = self._validate_targets(profile)
            try:
                original_text = original.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ScenarioSetupError("启动脚本不是 UTF-8 文本，无法安全应用场景方案") from exc
            bindings = self._resolve_bindings(original_text, document.get("bindings", {}))
            targets = self._transaction_targets(original_text, bindings, values)
            changed = self._replace_targets(original_text, values, bindings)
            if changed.encode("utf-8") == original:
                raise ScenarioSetupError("启动参数已是该场景方案，无需重复应用")
            applied = changed.encode("utf-8")
            active = {
                "schema": 3,
                # 先落盘恢复日志，再改受控脚本。断电或磁盘异常时宁可留下待清理
                # 事务，也绝不能留下“脚本已改、备份不存在”的不可恢复状态。
                "state": "prepared",
                "profile_id": profile["id"], "profile_name": profile["name"], "script": str(script),
                "created_at": _now(), "original_sha256": _sha256(original), "applied_sha256": _sha256(applied),
                "original_b64": base64.b64encode(original).decode("ascii"),
                "targets": targets,
            }
            self._write_active(active)
            try:
                self._write_script(script, applied)
            except ScenarioSetupError:
                # prepared 日志保留，恢复操作会依据原始校验和安全清理它。
                raise
            active["state"] = "applied"
            self._write_active(active)
            return {"message": f"已应用场景前置方案：{profile['name']}", "active_backup": self._public_active(active)}

    def preview_application(self, document: dict, profile_id: str) -> dict:
        """在内存中生成方案应用后的启动脚本，绝不写入机器人文件。"""
        prepared = self._validate_document(document)
        profile = next((item for item in prepared["profiles"] if item["id"] == profile_id), None)
        if not profile:
            raise ScenarioSetupError("未找到要预览的场景前置方案")
        script = Path(prepared["startup_script"])
        original = self._read_script(script)
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScenarioSetupError("启动脚本不是 UTF-8 文本，无法生成预览") from exc
        values = self._validate_targets(profile)
        changed = self._replace_targets(text, values, prepared.get("bindings", {}))
        encoded = changed.encode("utf-8")
        return {
            "path": str(script),
            "content": changed,
            "size": len(encoded),
            "sha256": _sha256(encoded),
            "original_sha256": _sha256(original),
            "changed": encoded != original,
            "profile_name": profile["name"],
        }

    def bind_case(self, case_id: str, profile_id: str) -> dict:
        """将一个已存在的用例标识关联到一个方案；空方案表示解除关联。"""
        if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 255 or "\x00" in case_id or "/" in case_id or "\\" in case_id:
            raise ScenarioSetupError("用例标识无效")
        with self._lock:
            document = self.load()
            bindings = dict(document.get("case_bindings", {}))
            profile_id = str(profile_id).strip()
            if profile_id:
                profile = next((item for item in document["profiles"] if item["id"] == profile_id), None)
                if not profile:
                    raise ScenarioSetupError("未找到要绑定的场景前置方案")
                bindings[case_id] = profile_id
                message = f"已为该用例绑定场景方案：{profile['name']}"
            else:
                bindings.pop(case_id, None)
                message = "已解除该用例的场景方案绑定"
            document["case_bindings"] = bindings
            self.save(document)
            return {"message": message, "case_id": case_id, "profile_id": profile_id}

    def apply_for_case(self, case_id: str) -> dict:
        """应用指定用例已绑定的方案；未绑定用例明确保持常规启动配置。"""
        with self._lock:
            document = self.load()
            profile_id = str(document.get("case_bindings", {}).get(case_id, "")).strip()
            if not profile_id:
                _active, transaction = self._transaction_status()
                if transaction["state"] != "normal":
                    raise ScenarioSetupError("该用例未绑定场景方案，但当前仍有待恢复事务；请先在场景前置配置页恢复常规启动配置")
                return {"bound": False, "profile_id": "", "profile_name": "", "message": "该用例未绑定场景方案，使用常规启动配置"}
            profile = next((item for item in document["profiles"] if item["id"] == profile_id), None)
            if not profile:
                raise ScenarioSetupError("该用例绑定的场景方案不存在；请在用例资产库重新绑定")
            profile_name = profile["name"]
        result = self.apply(profile_id)
        # 运行状态只需展示方案标识；不能把含原文件内容的事务备份暴露给前端。
        return {"bound": True, "profile_id": profile_id, "profile_name": profile_name, "message": result["message"]}

    def restore(self) -> dict:
        """回写受控启动参数并清理事务；绝不操作 Supervisor 或 ROS 节点。"""
        with self._lock:
            active, transaction = self._transaction_status()
            if transaction["state"] == "corrupt":
                raise ScenarioSetupError(transaction["message"])
            if not active:
                return {"message": "当前没有待恢复的场景前置配置", "restored": False}
            script = Path(str(active["script"]))
            current = self._read_script(script)
            original = self._decode_original(active)
            if _sha256(current) == active["original_sha256"]:
                self._clear_active()
                return {"message": f"常规启动配置已存在，已清理恢复事务（原方案：{active['profile_name']}）", "restored": True}
            if active.get("targets"):
                restored = self._merge_targeted_restore(current, original, active)
            else:
                # 兼容旧版事务：旧记录没有可用于三方合并的目标字段，只能在
                # 当前脚本仍严格等于工具写入版本时整文件回滚，绝不猜测覆盖。
                if _sha256(current) != active["applied_sha256"]:
                    raise ScenarioSetupError("旧版恢复事务对应的启动脚本已发生外部修改；请先人工核对，升级后新事务将支持保留无关修改的定向恢复")
                restored = original
            if restored != current:
                self._write_script(script, restored)
            self._clear_active()
            return {"message": f"已恢复常规启动配置（原方案：{active['profile_name']}）", "restored": True}

    def note_runtime_activation_failure(self, detail: str) -> None:
        """保留已应用事务并说明运行依赖没有成功读取新参数。"""
        with self._lock:
            active, transaction = self._transaction_status()
            if transaction["state"] == "corrupt":
                raise ScenarioSetupError(transaction["message"])
            if not active:
                raise ScenarioSetupError("场景应用事务不存在，无法记录运行时启动失败")
            if active.get("state") == "script_restored":
                raise ScenarioSetupError("常规脚本已恢复，不能记录场景启动失败")
            active["state"] = "applied"
            active["runtime_message"] = str(detail)[:1000]
            self._write_active(active)

    def _validate_document(self, document: dict) -> dict:
        if not isinstance(document, dict):
            raise ScenarioSetupError("场景前置配置格式错误")
        script = str(document.get("startup_script", "")).strip()
        script_path = Path(script)
        # 开发与测试环境可运行在 Windows；绝对路径的判定必须交给 pathlib，不能
        # 把 Linux 的“以 / 开头”误当成通用规则。小车侧的配置文件和 ROS 路径仍由
        # _validate_profile_values 严格限制在 /opt/ry。
        # Windows 开发机不会把小车的 POSIX 路径识别为绝对路径；它仍是受控的
        # 目标路径表示，必须与本机绝对路径同样接受。两种语法都检查父目录跳转。
        is_robot_path = script.startswith("/opt/ry/")
        path_parts = (*script_path.parts, *PurePosixPath(script).parts)
        if not (script_path.is_absolute() or is_robot_path) or ".." in path_parts or "\x00" in script:
            raise ScenarioSetupError("启动脚本必须是安全的绝对路径")
        profiles = document.get("profiles", [])
        if not isinstance(profiles, list) or len(profiles) > 80:
            raise ScenarioSetupError("场景前置方案数量无效")
        prepared, ids = [], set()
        for raw in profiles:
            if not isinstance(raw, dict):
                raise ScenarioSetupError("场景前置方案格式错误")
            profile_id, name = str(raw.get("id", "")).strip(), str(raw.get("name", "")).strip()
            if not _PROFILE_ID.fullmatch(profile_id) or profile_id in ids:
                raise ScenarioSetupError("方案标识无效或重复")
            if not name or len(name) > 80:
                raise ScenarioSetupError("方案名称不能为空且不能超过 80 个字符")
            fcrp, lightning = str(raw.get("fcrp_launch", "")).strip(), str(raw.get("lightning_config", "")).strip()
            self._validate_profile_values(fcrp, lightning, check_exists=False)
            prepared.append({"id": profile_id, "name": name, "fcrp_launch": fcrp, "lightning_config": lightning})
            ids.add(profile_id)
        case_bindings = document.get("case_bindings", {})
        if not isinstance(case_bindings, dict) or any(not isinstance(case, str) or value not in ids for case, value in case_bindings.items()):
            raise ScenarioSetupError("用例与前置方案绑定无效")
        directories = self._validate_search_directories(document.get("search_directories", []), script_path)
        command_bindings = self._validate_bindings(document.get("bindings", {}))
        return {"startup_script": script, "search_directories": directories, "bindings": command_bindings, "profiles": prepared, "case_bindings": case_bindings}

    def _validate_search_directories(self, raw: object, script: Path) -> list[str]:
        if not isinstance(raw, list) or len(raw) > 12:
            raise ScenarioSetupError("文件检索目录数量无效")
        root, prepared = self._allowed_root(script), []
        for item in raw:
            value = str(item).strip()
            if not value:
                continue
            target = Path(value)
            if not target.is_absolute() or ".." in target.parts or "\x00" in value:
                raise ScenarioSetupError("文件检索目录必须是安全的绝对路径")
            try:
                resolved = target.resolve()
            except OSError as exc:
                raise ScenarioSetupError("文件检索目录无法解析") from exc
            if resolved != root and root not in resolved.parents:
                raise ScenarioSetupError("文件检索目录必须位于启动脚本的受控目录内")
            if str(resolved) not in prepared:
                prepared.append(str(resolved))
        return prepared

    @staticmethod
    def _validate_profile_values(fcrp: str, lightning: str, *, check_exists: bool) -> None:
        launch = Path(fcrp)
        if not fcrp.endswith(".launch.py") or ".." in launch.parts or (launch.is_absolute() and not fcrp.startswith("/opt/ry/")) or (not launch.is_absolute() and not re.fullmatch(r"[A-Za-z0-9_.-]+\.launch\.py", fcrp)):
            raise ScenarioSetupError("FCRP 启动文件必须是受控目录中的 .launch.py 文件")
        target = Path(lightning)
        if not lightning.startswith("/opt/ry/") or ".." in target.parts or target.suffix not in {".yaml", ".yml"}:
            raise ScenarioSetupError("定位配置必须是 /opt/ry/ 下的 YAML 文件")
        if check_exists and not target.is_file():
            raise ScenarioSetupError(f"定位配置文件不存在：{target}")

    def _validate_targets(self, profile: dict) -> dict:
        self._validate_profile_values(profile["fcrp_launch"], profile["lightning_config"], check_exists=True)
        launch = Path(profile["fcrp_launch"])
        if launch.is_absolute() and not launch.is_file():
            raise ScenarioSetupError(f"FCRP 启动文件不存在：{launch}")
        return {"fcrp": launch.name, "lightning": profile["lightning_config"]}

    @staticmethod
    def _inspect_text(text: str) -> dict:
        fcrp, lightning = list(_FCRP.finditer(text)), list(_LIGHTNING.finditer(text))
        return {
            "fcrp_matches": len(fcrp), "lightning_matches": len(lightning),
            "fcrp_launch": fcrp[0].group("value") if len(fcrp) == 1 else None,
            "lightning_config": lightning[0].group("value") if len(lightning) == 1 else None,
            "ready": len(fcrp) == 1 and len(lightning) == 1,
            "candidates": ScenarioSetupStore._command_candidates(text),
        }

    @staticmethod
    def _command_candidates(text: str) -> list[dict]:
        candidates = []
        for kind, expression in (("launch", _ROS_LAUNCH), ("config", _ROS_RUN_CONFIG)):
            occurrences: dict[str, int] = {}
            for match in expression.finditer(text):
                prefix = match.group("prefix")
                occurrence = occurrences.get(prefix, 0)
                occurrences[prefix] = occurrence + 1
                selector = f"{kind}\0{prefix}\0{occurrence}"
                candidates.append({
                    "id": _sha256(selector.encode("utf-8"))[:16],
                    "kind": kind,
                    "prefix": prefix,
                    "occurrence": occurrence,
                    "current": match.group("value"),
                    "package": match.group("package"),
                    "executable": match.groupdict().get("executable", ""),
                })
        return candidates

    @staticmethod
    def _validate_bindings(raw: object) -> dict:
        if not isinstance(raw, dict):
            raise ScenarioSetupError("启动命令绑定格式错误")
        prepared = {}
        for slot in ("fcrp", "lightning"):
            item = raw.get(slot)
            if item is None:
                continue
            if not isinstance(item, dict) or item.get("kind") not in {"launch", "config"} or not isinstance(item.get("prefix"), str) or not item["prefix"].startswith("ros2 "):
                raise ScenarioSetupError("启动命令绑定无效")
            if slot == "fcrp" and item["kind"] != "launch":
                raise ScenarioSetupError("FCRP 必须绑定 ros2 launch 命令")
            if slot == "lightning" and item["kind"] != "config":
                raise ScenarioSetupError("定位必须绑定带 --config 的 ros2 run 命令")
            occurrence = item.get("occurrence")
            if occurrence is not None and (not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0):
                raise ScenarioSetupError("启动命令绑定位置无效")
            prepared[slot] = {"kind": item["kind"], "prefix": item["prefix"]}
            if occurrence is not None:
                prepared[slot]["occurrence"] = occurrence
        return prepared

    @staticmethod
    def _binding_expression(binding: dict) -> re.Pattern[str]:
        return re.compile(re.escape(binding["prefix"]) + r"(?P<value>[^\s#]+)")

    def _match_binding(self, text: str, binding: dict, slot: str) -> re.Match[str]:
        matches = list(self._binding_expression(binding).finditer(text))
        occurrence = binding.get("occurrence")
        if occurrence is None:
            if len(matches) != 1:
                raise ScenarioSetupError(f"已选择的{slot}参数位置未能唯一匹配；请重新读取启动脚本后选择")
            return matches[0]
        if occurrence >= len(matches):
            raise ScenarioSetupError(f"已选择的{slot}参数位置不存在；启动脚本可能已被外部修改")
        return matches[occurrence]

    def _binding_for_match(self, text: str, kind: str, match: re.Match[str], prefix: str | None = None) -> dict:
        binding = {"kind": kind, "prefix": prefix if prefix is not None else match.group("prefix")}
        matches = list(self._binding_expression(binding).finditer(text))
        occurrence = next((index for index, item in enumerate(matches) if item.start() == match.start()), None)
        if occurrence is None:
            raise ScenarioSetupError("无法确定启动参数位置")
        return {**binding, "occurrence": occurrence}

    def _resolve_bindings(self, text: str, bindings: dict) -> dict:
        """将自动识别或人工选择转为可审计的两处精确位置。"""
        if bindings:
            if not bindings.get("fcrp") or not bindings.get("lightning"):
                raise ScenarioSetupError("已启用手动参数位置选择，请同时选择 FCRP 与 lightning 命令")
            resolved = {}
            for slot in ("fcrp", "lightning"):
                binding = dict(bindings[slot])
                match = self._match_binding(text, binding, slot)
                resolved[slot] = self._binding_for_match(text, binding["kind"], match, binding["prefix"])
            return resolved
        strict = {"fcrp": list(_FCRP.finditer(text)), "lightning": list(_LIGHTNING.finditer(text))}
        if len(strict["fcrp"]) == 1 and len(strict["lightning"]) == 1:
            return {
                "fcrp": self._binding_for_match(text, "launch", strict["fcrp"][0]),
                "lightning": self._binding_for_match(text, "config", strict["lightning"][0]),
            }
        candidates = self._command_candidates(text)
        launches = [item for item in candidates if item["kind"] == "launch"]
        configs = [item for item in candidates if item["kind"] == "config"]
        if len(launches) != 1 or len(configs) != 1:
            raise ScenarioSetupError("启动脚本未能自动唯一识别启动文件和定位配置命令；请保留各一个目标命令后重试")
        return {
            "fcrp": {"kind": "launch", "prefix": launches[0]["prefix"], "occurrence": launches[0]["occurrence"]},
            "lightning": {"kind": "config", "prefix": configs[0]["prefix"], "occurrence": configs[0]["occurrence"]},
        }

    def _replace_targets(self, text: str, values: dict, bindings: dict) -> str:
        """仅替换已解析的两处目标值，不会误改同脚本中的其他 ROS 命令。"""
        resolved = self._resolve_bindings(text, bindings)
        for slot, value in (("fcrp", values["fcrp"]), ("lightning", values["lightning"])):
            match = self._match_binding(text, resolved[slot], slot)
            text = text[:match.start("value")] + value + text[match.end("value"):]
        return text

    def _transaction_targets(self, text: str, bindings: dict, values: dict) -> list[dict]:
        """记录两个受控参数的基线和应用值，供恢复时做安全三方合并。"""
        targets = []
        for slot, value in (("fcrp", values["fcrp"]), ("lightning", values["lightning"])):
            binding = bindings[slot]
            match = self._match_binding(text, binding, slot)
            line_start = text.rfind("\n", 0, match.start("value")) + 1
            line_end = text.find("\n", match.end("value"))
            if line_end < 0:
                line_end = len(text)
            targets.append({
                "slot": slot,
                "prefix": binding["prefix"],
                "occurrence": binding["occurrence"],
                "original_value": match.group("value"),
                "applied_value": value,
                # occurrence 能区分同一命令前缀的多个实例；整行上下文再防止
                # 外部在前面插入同前缀命令时误回退到另一条命令。
                "line_before": text[line_start:match.start("value")],
                "line_after": text[match.end("value"):line_end],
            })
        return targets

    def _merge_targeted_restore(self, current: bytes, _original: bytes, active: dict) -> bytes:
        """只回退本工具写入的两个参数，保留脚本中无关的外部修改。"""
        try:
            text = current.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScenarioSetupError("启动脚本已不是 UTF-8 文本，无法安全恢复") from exc
        targets = active.get("targets")
        if not isinstance(targets, list) or {item.get("slot") for item in targets if isinstance(item, dict)} != {"fcrp", "lightning"}:
            raise ScenarioSetupError("恢复事务缺少受控参数记录，已拒绝覆盖")
        for target in targets:
            if not isinstance(target, dict):
                raise ScenarioSetupError("恢复事务参数记录损坏，已拒绝覆盖")
            binding = {"prefix": target.get("prefix"), "occurrence": target.get("occurrence")}
            if not isinstance(binding["prefix"], str) or not isinstance(binding["occurrence"], int):
                raise ScenarioSetupError("恢复事务参数位置损坏，已拒绝覆盖")
            matches = list(self._binding_expression(binding).finditer(text))
            occurrence = binding["occurrence"]
            if occurrence >= len(matches):
                raise ScenarioSetupError(f"{target.get('slot', '受控')} 参数位置已不存在；脚本结构可能已被外部修改")
            match = matches[occurrence]
            line_start = text.rfind("\n", 0, match.start("value")) + 1
            line_end = text.find("\n", match.end("value"))
            if line_end < 0:
                line_end = len(text)
            line_before = target.get("line_before")
            line_after = target.get("line_after")
            if line_before is not None or line_after is not None:
                if not isinstance(line_before, str) or not isinstance(line_after, str):
                    raise ScenarioSetupError("恢复事务命令上下文损坏，已拒绝覆盖")
                if text[line_start:match.start("value")] != line_before or text[match.end("value"):line_end] != line_after:
                    raise ScenarioSetupError(f"{target.get('slot', '受控')} 命令行在方案应用后被外部修改；为避免覆盖该变更，已拒绝恢复")
            current_value = match.group("value")
            original_value, applied_value = target.get("original_value"), target.get("applied_value")
            if not isinstance(original_value, str) or not isinstance(applied_value, str):
                raise ScenarioSetupError("恢复事务参数值损坏，已拒绝覆盖")
            if current_value == original_value:
                continue
            if current_value != applied_value:
                raise ScenarioSetupError(f"{target['slot']} 参数在方案应用后被外部改为“{current_value}”；为避免覆盖该变更，已拒绝恢复")
            text = text[:match.start("value")] + original_value + text[match.end("value"):]
        return text.encode("utf-8")

    @staticmethod
    def _allowed_root(script: Path) -> Path:
        return Path("/opt/ry").resolve() if str(script).startswith("/opt/ry/") else script.parent.resolve()

    @classmethod
    def _discover_files(cls, script: Path, directories: list[str]) -> dict:
        root = cls._allowed_root(script)
        roots = [Path(item) for item in directories] or [script.parent]
        groups = {"scripts": [], "launch": [], "yaml": []}
        try:
            for scan_root in roots:
                if not scan_root.is_dir() or (scan_root != root and root not in scan_root.resolve().parents):
                    continue
                for target in scan_root.rglob("*"):
                    if len(groups["scripts"]) >= 200 and len(groups["launch"]) >= 300 and len(groups["yaml"]) >= 600:
                        break
                    if not target.is_file() or target.stat().st_size > 1024 * 1024:
                        continue
                    if target.suffix == ".sh" and len(groups["scripts"]) < 200:
                        groups["scripts"].append(str(target))
                    elif target.name.endswith(".launch.py") and len(groups["launch"]) < 300:
                        groups["launch"].append(str(target))
                    elif target.suffix in {".yaml", ".yml"} and len(groups["yaml"]) < 600:
                        groups["yaml"].append(str(target))
        except OSError:
            pass
        return {key: sorted(value) for key, value in groups.items()}

    @staticmethod
    def _read_script(script: Path) -> bytes:
        if not script.is_file():
            raise ScenarioSetupError(f"启动脚本不存在：{script}")
        try:
            return script.read_bytes()
        except OSError as exc:
            raise ScenarioSetupError(f"无法读取启动脚本：{exc}") from exc

    @staticmethod
    def _write_script(script: Path, data: bytes) -> None:
        try:
            mode = script.stat().st_mode
            with tempfile.NamedTemporaryFile(dir=script.parent, prefix=f".{script.name}.", delete=False) as output:
                output.write(data); output.flush(); os.fsync(output.fileno()); temporary = Path(output.name)
            os.chmod(temporary, mode)
            os.replace(temporary, script)
            ScenarioSetupStore._fsync_directory(script.parent)
        except OSError as exc:
            try: temporary.unlink(missing_ok=True)  # type: ignore[has-type]
            except (UnboundLocalError, OSError): pass
            raise ScenarioSetupError(f"无法安全写入启动脚本（请确认已授予受控写权限）：{exc}") from exc

    def _active_path(self) -> Path:
        return self.backup_dir / "active.json"

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _decode_original(active: dict) -> bytes:
        try:
            original = base64.b64decode(active["original_b64"].encode("ascii"), validate=True)
        except (KeyError, AttributeError, UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise ScenarioSetupError("恢复事务备份已损坏，已拒绝恢复") from exc
        if _sha256(original) != active.get("original_sha256"):
            raise ScenarioSetupError("恢复事务备份校验失败，已拒绝恢复")
        return original

    def _transaction_status(self) -> tuple[dict | None, dict]:
        """读取并校验活动事务；损坏记录必须显式暴露，不能伪装成常规状态。"""
        path = self._active_path()
        if not path.exists():
            return None, {"state": "normal", "message": "未检测到待恢复事务", "restore_available": False}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            active = self._validate_active(raw)
        except (OSError, json.JSONDecodeError, ScenarioSetupError) as exc:
            return None, {
                "state": "corrupt",
                "message": f"恢复事务不可用：{exc}。请勿继续应用方案、升级或退出控制台；需先人工核对启动脚本与备份。",
                "restore_available": False,
            }
        state = active.get("state", "applied")
        if state == "script_restored":
            detail = str(active.get("runtime_message", "")).strip()
            message = "常规启动脚本已恢复。这是旧版本留下的恢复记录；点击“恢复常规配置”可核对并清理记录，不会重启任何服务。"
            if detail:
                message = f"{message} 最近失败原因：{detail}"
            return active, {"state": "pending", "phase": state, "message": message, "restore_available": True}
        detail = str(active.get("runtime_message", "")).strip()
        if state == "prepared":
            message = f"场景方案“{active['profile_name']}”写入状态未确认。请执行恢复以核对并回退受控参数。"
        else:
            message = f"待恢复：{active['profile_name']} 已于 {active['created_at']} 应用。恢复仅回退受控参数，并保留无关脚本修改。"
            if detail:
                message = f"{message} 最近运行时启动失败：{detail}"
        return active, {
            "state": "pending",
            "phase": state,
            "message": message,
            "restore_available": True,
        }

    @staticmethod
    def _validate_active(raw: object) -> dict:
        if not isinstance(raw, dict):
            raise ScenarioSetupError("恢复事务格式错误")
        required = ("profile_id", "profile_name", "script", "created_at", "original_sha256", "applied_sha256", "original_b64")
        if any(not isinstance(raw.get(key), str) or not raw[key] for key in required):
            raise ScenarioSetupError("恢复事务字段不完整")
        if not Path(raw["script"]).is_absolute() or "\x00" in raw["script"]:
            raise ScenarioSetupError("恢复事务脚本路径无效")
        if any(not re.fullmatch(r"[0-9a-f]{64}", raw[key]) for key in ("original_sha256", "applied_sha256")):
            raise ScenarioSetupError("恢复事务校验和无效")
        state = raw.get("state", "applied")
        if state not in {"prepared", "applied", "script_restored"}:
            raise ScenarioSetupError("恢复事务状态无效")
        # 先验证备份内容，避免页面显示“可恢复”而点击后才发现没有基线。
        ScenarioSetupStore._decode_original(raw)
        targets = raw.get("targets")
        if targets is not None:
            if not isinstance(targets, list) or len(targets) != 2:
                raise ScenarioSetupError("恢复事务受控参数记录无效")
            slots = set()
            for target in targets:
                if not isinstance(target, dict):
                    raise ScenarioSetupError("恢复事务受控参数记录无效")
                slot = target.get("slot")
                if slot not in {"fcrp", "lightning"} or slot in slots:
                    raise ScenarioSetupError("恢复事务受控参数记录无效")
                slots.add(slot)
                if (not isinstance(target.get("prefix"), str) or not target["prefix"].startswith("ros2 ")
                        or not isinstance(target.get("occurrence"), int) or isinstance(target.get("occurrence"), bool) or target["occurrence"] < 0
                        or not isinstance(target.get("original_value"), str) or not isinstance(target.get("applied_value"), str)):
                    raise ScenarioSetupError("恢复事务受控参数记录无效")
                if (target.get("line_before") is not None and not isinstance(target.get("line_before"), str)) or (target.get("line_after") is not None and not isinstance(target.get("line_after"), str)):
                    raise ScenarioSetupError("恢复事务命令上下文无效")
        return raw

    @staticmethod
    def _public_active(active: dict | None) -> dict | None:
        if not active:
            return None
        return {key: active[key] for key in ("profile_id", "profile_name", "script", "created_at", "state") if key in active}

    def _raise_if_transaction_unresolved(self) -> None:
        _active, transaction = self._transaction_status()
        if transaction["state"] == "normal":
            return
        if transaction["state"] == "corrupt":
            raise ScenarioSetupError(transaction["message"])
        raise ScenarioSetupError("已有场景前置配置待恢复；请先恢复常规启动配置")

    def _clear_active(self) -> None:
        try:
            self._active_path().unlink(missing_ok=True)
            self._fsync_directory(self.backup_dir)
        except OSError as exc:
            raise ScenarioSetupError(f"常规脚本已回写，但无法清理恢复事务：{exc}；请勿重新应用方案") from exc

    def _write_active(self, active: dict) -> None:
        temporary: Path | None = None
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            path = self._active_path()
            with tempfile.NamedTemporaryFile(dir=self.backup_dir, prefix=".active.", suffix=".tmp", mode="w", encoding="utf-8", delete=False) as output:
                output.write(json.dumps(active, ensure_ascii=False, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
                temporary = Path(output.name)
            os.replace(temporary, path)
            self._fsync_directory(self.backup_dir)
        except OSError as exc:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ScenarioSetupError(f"无法持久化恢复事务：{exc}") from exc
