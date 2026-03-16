import json
import os
from pathlib import Path
from typing import Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_CONFIG_PATH = BASE_DIR / ".gemini_local_config.json"


def _clean_text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def local_gemini_config_path() -> Path:
    env_path = _clean_text(os.environ.get("LOCAL_GEMINI_CONFIG_PATH"))
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_LOCAL_CONFIG_PATH


def load_local_gemini_defaults() -> Tuple[Optional[str], Optional[str]]:
    config_path = local_gemini_config_path()
    if not config_path.exists() or not config_path.is_file():
        return None, None

    try:
        raw = config_path.read_text(encoding="utf-8")
    except Exception:
        return None, None

    if not raw.strip():
        return None, None

    try:
        payload = json.loads(raw)
    except Exception:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    project_id = _clean_text(
        payload.get("google_project")
        or payload.get("project_id")
        or payload.get("gcp_project_id")
    )
    location = _clean_text(
        payload.get("region")
        or payload.get("location")
        or payload.get("google_region")
        or payload.get("gcp_location")
    )
    return project_id, location
