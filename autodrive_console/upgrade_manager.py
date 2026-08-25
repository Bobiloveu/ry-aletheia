from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from .upgrade_signature import UpgradeSignatureError, verify_manifest_signature


class UpgradeError(ValueError):
    """离线升级包不完整、被篡改或不适用于当前运行实例。"""


class UpgradeManager:
    """校验并原子替换当前单文件程序，不接触任务、配置和报告。"""

    SCHEMA = "ry-aletheia-offline-upgrade/v1"
    MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
    PACKAGE_FILES = {"manifest.json", "ry-aletheia"}

    def __init__(self, workspace: Path, executable: Path, frozen: bool) -> None:
        self.workspace = workspace.resolve()
        self.executable = executable.resolve()
        self.frozen = frozen
        self.updates_dir = self.workspace / "updates"
        # 版本仅在控制台启动时读取一次；升级成功时由 apply() 使用包内清单更新。
        self._installed = self._installed_metadata()
        self._current_version = str(self._installed.get("version") or self._workspace_version() or "开发版")

    def status(self) -> dict:
        ready = self.frozen and self.executable.is_file() and self.executable.is_relative_to(self.workspace)
        result = {
            "supported": ready,
            "schema": self.SCHEMA,
            "message": "可上传离线升级包" if ready else "当前为开发源码运行，不支持覆盖升级；请运行 dist/ry-aletheia。",
            "current_binary": self.executable.name if ready else None,
            "current_version": self._current_version,
        }
        if self._installed:
            result["installed"] = self._installed
        return result

    def _installed_metadata(self) -> dict:
        installed = self.updates_dir / "installed.json"
        if not installed.is_file():
            return {}
        try:
            data = json.loads(installed.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _workspace_version(self) -> str:
        """首次部署尚未有升级记录时，从部署包的 VERSION 读取版本。"""
        try:
            return (self.workspace / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def apply(self, upload: BinaryIO, content_length: int, original_name: str) -> dict:
        if not self.frozen:
            raise UpgradeError("当前为开发源码运行，拒绝覆盖升级。请使用 dist/ry-aletheia 运行控制台。")
        if not self.executable.is_file() or not self.executable.is_relative_to(self.workspace):
            raise UpgradeError("无法确认当前二进制位于工程目录内，已拒绝升级。")
        if not 1 <= content_length <= self.MAX_PACKAGE_BYTES:
            raise UpgradeError("升级包大小无效或超过 1 GiB 限制。")
        if not original_name.lower().endswith(".zip"):
            raise UpgradeError("仅接受 .zip 离线升级包。")

        staging = self.updates_dir / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="upload-", dir=staging) as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "package.zip"
            remaining = content_length
            with archive.open("wb") as output:
                while remaining:
                    chunk = upload.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise UpgradeError("升级包上传不完整。")
                    output.write(chunk)
                    remaining -= len(chunk)
            manifest, binary = self._validate_package(archive, temp_root)
            backup_dir = self.updates_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / "ry-aletheia.bak"
            backup_staging = backup_dir / ".ry-aletheia.bak.tmp"
            try:
                # 先写入同目录临时文件再原子替换固定备份槽位，旧程序始终有可恢复副本。
                shutil.copy2(self.executable, backup_staging)
                os.replace(backup_staging, backup)
                # 兼容历史版本产生的时间戳备份；升级成功前清理，避免备份目录持续膨胀。
                for candidate in backup_dir.glob("*.bak"):
                    if candidate != backup and (candidate.is_file() or candidate.is_symlink()):
                        candidate.unlink()
                os.replace(binary, self.executable)
                self.executable.chmod(self.executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                installed = {
                    "version": manifest["version"],
                    "created_at": manifest["created_at"],
                    "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "md5": manifest["binary"]["md5"],
                    "backup": str(backup.relative_to(self.workspace)),
                }
                (self.updates_dir / "installed.json").write_text(json.dumps(installed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self._installed = installed
                self._current_version = manifest["version"]
            except OSError as exc:
                backup_staging.unlink(missing_ok=True)
                if backup.is_file() and not self.executable.is_file():
                    shutil.copy2(backup, self.executable)
                raise UpgradeError(f"替换程序失败：{exc}") from exc
        return {"message": f"升级包校验通过，已备份旧程序到 {backup.relative_to(self.workspace)}，正在重启到 {manifest['version']}。", "version": manifest["version"]}

    def _validate_package(self, archive: Path, temp_root: Path) -> tuple[dict, Path]:
        if not zipfile.is_zipfile(archive):
            raise UpgradeError("文件不是有效的 ZIP 升级包。")
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or set(names) != self.PACKAGE_FILES:
                raise UpgradeError("升级包只能包含 manifest.json 和 ry-aletheia，拒绝额外或缺失文件。")
            if any(entry.is_dir() or Path(entry.filename).name != entry.filename for entry in entries):
                raise UpgradeError("升级包路径不安全。")
            if any(entry.file_size > self.MAX_PACKAGE_BYTES or entry.compress_size == 0 and entry.file_size > 0 for entry in entries):
                raise UpgradeError("升级包内容大小异常。")
            manifest = self._read_manifest(bundle)
            binary_info = manifest["binary"]
            binary_entry = bundle.getinfo("ry-aletheia")
            if binary_entry.file_size != binary_info["size"]:
                raise UpgradeError("升级包二进制大小与清单不一致。")
            binary = temp_root / "ry-aletheia"
            # 兼容上一版本读取的 MD5 字段，同时使用 SHA-256 与 Ed25519 发布
            # 签名保证内容完整性和发布者真实性。所有校验均发生在 os.replace 前。
            md5_digest = hashlib.md5()
            sha256_digest = hashlib.sha256()
            with bundle.open(binary_entry) as source, binary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    md5_digest.update(chunk)
                    sha256_digest.update(chunk)
        if md5_digest.hexdigest() != manifest["binary"]["md5"]:
            raise UpgradeError("MD5 校验失败，升级包可能已损坏。")
        if sha256_digest.hexdigest() != manifest["binary"]["sha256"]:
            raise UpgradeError("SHA-256 校验失败，升级包可能已损坏。")
        return manifest, binary

    def _read_manifest(self, bundle: zipfile.ZipFile) -> dict:
        try:
            manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpgradeError("升级清单 manifest.json 无法读取。") from exc
        binary = manifest.get("binary") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != self.SCHEMA
            or not isinstance(manifest.get("version"), str)
            or not manifest["version"].strip()
            or not isinstance(manifest.get("created_at"), str)
            or not isinstance(binary, dict)
            or binary.get("path") != "ry-aletheia"
            or not isinstance(binary.get("size"), int)
            or binary["size"] < 1
            or not isinstance(binary.get("md5"), str)
            or not __import__("re").fullmatch(r"[0-9a-f]{32}", binary["md5"])
            or not isinstance(binary.get("sha256"), str)
            or not __import__("re").fullmatch(r"[0-9a-f]{64}", binary["sha256"])
        ):
            raise UpgradeError("升级清单字段不符合 RY Aletheia 离线升级协议。")
        try:
            verify_manifest_signature(manifest)
        except UpgradeSignatureError as exc:
            raise UpgradeError(str(exc)) from exc
        return manifest
