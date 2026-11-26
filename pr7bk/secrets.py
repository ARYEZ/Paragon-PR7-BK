"""Passwords (no Qt): each backup's restic password and its destination's key (S3 / B2 secret, REST password) live in
Windows Credential Manager through `keyring` (service "Paragon PR7-BK"), never in jobs.json. PR7BK_MEMORY_KEYRING keeps
them in memory instead (tests: never the real Credential Manager). PR7-F's scheme."""

from __future__ import annotations

import os

SERVICE = "Paragon PR7-BK"
_memory: dict[str, str] = {}


def _memory_only() -> bool:
    return bool(os.environ.get("PR7BK_MEMORY_KEYRING"))


def _keyring():
    if _memory_only():
        return None
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - no usable keyring: fall back to memory (the user is told)
        return None


def available() -> bool:
    return _memory_only() or _keyring() is not None


def get(job_id: str, what: str = "password") -> str:
    key = f"{job_id}:{what}"
    kr = _keyring()
    if kr is None:
        return _memory.get(key, "")
    try:
        return kr.get_password(SERVICE, key) or ""
    except Exception:  # noqa: BLE001
        return ""


def put(job_id: str, value: str, what: str = "password"):
    key = f"{job_id}:{what}"
    kr = _keyring()
    if kr is None:
        _memory[key] = value
        return
    if value:
        kr.set_password(SERVICE, key, value)
    else:
        forget(job_id, what)


def forget(job_id: str, what: str | None = None):
    for w in ([what] if what else ["password", "secret"]):
        key = f"{job_id}:{w}"
        _memory.pop(key, None)
        kr = _keyring()
        if kr is not None:
            try:
                kr.delete_password(SERVICE, key)
            except Exception:  # noqa: BLE001 - nothing to delete
                pass
