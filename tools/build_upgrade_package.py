#!/usr/bin/env python3
"""在开发机为已验证的 ry-aletheia 二进制生成离线升级包。"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "ry-aletheia-offline-upgrade/v1"


def md5_file(target: Path) -> str:
    digest = hashlib.md5()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 RY Aletheia 离线升级包")
    parser.add_argument("version", help="本次升级版本，例如 2026.08.12-01")
    parser.add_argument("--binary", type=Path, default=Path("dist/ry-aletheia"), help="已打包二进制路径")
    parser.add_argument("--output-dir", type=Path, default=Path("releases"), help="升级包输出目录")
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        raise SystemExit(f"未找到二进制：{binary}")
    version = args.version.strip()
    if not __import__("re").fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise SystemExit("版本号必须为数字点号格式，例如 0.1、0.2、1.1。")
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "binary": {"path": "ry-aletheia", "size": binary.stat().st_size, "md5": md5_file(binary)},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"ry-aletheia_{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        bundle.write(binary, "ry-aletheia")
    print(output)
    print(f"MD5: {manifest['binary']['md5']}")


if __name__ == "__main__":
    main()
