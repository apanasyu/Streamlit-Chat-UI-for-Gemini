from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_root(env_key: str, subdir: str) -> Path:
    explicit = (os.environ.get(env_key) or "").strip()
    shared = (os.environ.get("STREAMLIT_ARTIFACT_ROOT") or "").strip()

    if explicit:
        root = Path(explicit).expanduser()
    elif shared:
        root = Path(shared).expanduser() / subdir
    else:
        root = BASE_DIR / ".artifacts" / subdir

    if not root.is_absolute():
        root = (BASE_DIR / root).resolve()
    return root


def brainstorm_artifact_root() -> Path:
    return _resolve_root("BRAINSTORM_ARTIFACT_ROOT", "brainstorm")


def etl_artifact_root() -> Path:
    return _resolve_root("ETL_ARTIFACT_ROOT", "etl")


def echo_audit_artifact_root() -> Path:
    return _resolve_root("ECHO_AUDIT_ARTIFACT_ROOT", "echo_audit")
