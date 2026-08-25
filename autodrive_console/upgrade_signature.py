"""Authenticated offline-upgrade manifest helpers.

The ZIP intentionally remains a two-file archive for compatibility with
already-installed consoles: ``manifest.json`` carries the detached Ed25519
signature and ``ry-aletheia`` carries the executable.  The private release key
never enters the repository or the installed robot payload.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SIGNATURE_ALGORITHM = "ed25519"
RELEASE_KEY_ID = "ry-aletheia-release-2026"
# Raw Ed25519 public key, base64 encoded.  It is intentionally embedded in the
# client binary; only the matching offline release private key can sign a ZIP.
RELEASE_PUBLIC_KEY_B64 = "dUpFzM2nQsHirr0CqNMP6DlphkVufPJoCv96jvS07ZA="


class UpgradeSignatureError(ValueError):
    """An upgrade manifest cannot be authenticated by the release key."""


# Ed25519 verification is deliberately dependency-free so the frozen offline
# console does not need a system ``cryptography`` package.  This follows the
# RFC 8032 group equation and only verifies a signature against our fixed,
# shipped public key; private-key operations stay on the release workstation.
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_BASE = (
    15112221349535400772501151409588531511454012693041857206046113283949847762202,
    46316835694926478169428394003475163141307993866256225615783033603165251855960,
)


def canonical_manifest_payload(manifest: dict[str, Any]) -> bytes:
    """Return the only manifest fields covered by a release signature."""

    binary = manifest.get("binary") if isinstance(manifest, dict) else None
    if not isinstance(binary, dict):
        raise UpgradeSignatureError("升级清单缺少二进制签名字段")
    payload = {
        "schema": manifest.get("schema"),
        "version": manifest.get("version"),
        "created_at": manifest.get("created_at"),
        "binary": {
            "path": binary.get("path"),
            "size": binary.get("size"),
            "sha256": binary.get("sha256"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict[str, Any], private_key_path: Path) -> dict[str, str]:
    """Sign the canonical manifest payload with an external release key."""

    if not private_key_path.is_file():
        raise UpgradeSignatureError(f"无法读取 Ed25519 发布签名密钥：{private_key_path}")
    with tempfile.TemporaryDirectory(prefix="ry-aletheia-sign-") as directory:
        root = Path(directory)
        payload_path = root / "manifest.payload"
        signature_path = root / "manifest.signature"
        payload_path.write_bytes(canonical_manifest_payload(manifest))
        result = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(private_key_path), "-rawin", "-in", str(payload_path), "-out", str(signature_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not signature_path.is_file():
            detail = (result.stderr or result.stdout).strip()
            raise UpgradeSignatureError(f"无法使用 Ed25519 发布密钥签名：{detail or 'openssl pkeyutl 失败'}")
        signature = signature_path.read_bytes()
    if len(signature) != 64:
        raise UpgradeSignatureError("发布签名密钥不是有效的 Ed25519 私钥")
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": RELEASE_KEY_ID,
        "value": base64.b64encode(signature).decode("ascii"),
    }


def verify_manifest_signature(manifest: dict[str, Any]) -> None:
    """Raise a precise error unless the built-in release key verifies it."""

    signature = manifest.get("signature") if isinstance(manifest, dict) else None
    if not isinstance(signature, dict):
        raise UpgradeSignatureError("升级包缺少 Ed25519 发布签名")
    if signature.get("algorithm") != SIGNATURE_ALGORITHM or signature.get("key_id") != RELEASE_KEY_ID:
        raise UpgradeSignatureError("升级包签名算法或发布密钥标识不受信任")
    value = signature.get("value")
    if not isinstance(value, str):
        raise UpgradeSignatureError("升级包签名格式无效")
    try:
        raw_signature = base64.b64decode(value.encode("ascii"), validate=True)
        public_key = base64.b64decode(RELEASE_PUBLIC_KEY_B64.encode("ascii"), validate=True)
    except (ValueError, TypeError) as exc:
        raise UpgradeSignatureError("升级包签名编码无效") from exc
    if len(raw_signature) != 64 or len(public_key) != 32:
        raise UpgradeSignatureError("升级包 Ed25519 签名长度无效")
    if not _ed25519_verify(raw_signature, canonical_manifest_payload(manifest), public_key):
        raise UpgradeSignatureError("升级包发布签名校验失败")


def _recover_x(y: int) -> int | None:
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q:
        x = x * _I % _Q
    return x if (x * x - xx) % _Q == 0 else None


def _decode_point(encoded: bytes) -> tuple[int, int] | None:
    if len(encoded) != 32:
        return None
    value = int.from_bytes(encoded, "little")
    sign, y = value >> 255, value & ((1 << 255) - 1)
    if y >= _Q:
        return None
    x = _recover_x(y)
    if x is None or (x & 1) != sign:
        x = _Q - x
    if x == 0 and sign:
        return None
    return x, y


def _add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = left
    x2, y2 = right
    denominator = _D * x1 * x2 * y1 * y2 % _Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + denominator, _Q - 2, _Q) % _Q
    y3 = (y1 * y2 + x1 * x2) * pow(1 - denominator, _Q - 2, _Q) % _Q
    return x3, y3


def _multiply(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _ed25519_verify(signature: bytes, message: bytes, public_key: bytes) -> bool:
    encoded_r, encoded_s = signature[:32], signature[32:]
    point_r = _decode_point(encoded_r)
    point_a = _decode_point(public_key)
    scalar_s = int.from_bytes(encoded_s, "little")
    if point_r is None or point_a is None or scalar_s >= _L:
        return False
    challenge = int.from_bytes(hashlib.sha512(encoded_r + public_key + message).digest(), "little") % _L
    left = _multiply(_multiply(_BASE, scalar_s), 8)
    right = _multiply(_add(point_r, _multiply(point_a, challenge)), 8)
    return left == right
