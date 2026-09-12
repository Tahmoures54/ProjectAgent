# Path: pms_app/blueprints/auth/helpers/two_factor.py
from __future__ import annotations

import base64
import json
import secrets
from io import BytesIO

from pms_app.extensions import check_password_hash, generate_password_hash

BACKUP_CODE_COUNT = 8


def totp_available() -> bool:
    try:
        import pyotp  # noqa: F401
        return True
    except ImportError:
        return False


def generate_totp_secret() -> str | None:
    try:
        import pyotp
    except ImportError:
        return None
    return pyotp.random_base32()


def build_provisioning_uri(secret: str, account: str, issuer: str) -> str | None:
    if not secret:
        return None
    try:
        import pyotp
    except ImportError:
        return None
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code or len(code) != 6 or not code.isdigit():
        return False
    try:
        import pyotp
    except ImportError:
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(code, valid_window=1))
    except Exception:
        return False


def make_qr_data_uri(data: str) -> str | None:
    if not data:
        return None
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError:
        return None
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, format="PNG")
    b64 = base64.b64encode(bio.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def format_secret_display(secret: str) -> str:
    raw = (secret or "").replace(" ", "").upper()
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    codes: list[str] = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_codes(codes: list[str]) -> str:
    return json.dumps([generate_password_hash(_normalize_backup(c)) for c in codes])


def parse_backup_hashes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def consume_backup_code(stored_json: str | None, code: str) -> str | None:
    """Return updated JSON hashes if a code matched, else None."""
    needle = _normalize_backup(code)
    if len(needle) < 8:
        return None
    hashes = parse_backup_hashes(stored_json)
    for idx, hashed in enumerate(hashes):
        try:
            ok = check_password_hash(hashed, needle)
        except Exception:
            ok = False
        if ok:
            hashes.pop(idx)
            return json.dumps(hashes)
    return None


def _normalize_backup(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("-", "")
