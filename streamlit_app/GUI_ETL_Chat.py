import contextlib
import html
import mimetypes
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from local_runtime_config import load_local_gemini_defaults
from runtime_paths import etl_artifact_root
from ui_theme import apply_streamlit_theme


LOCAL_GCP_PROJECT, LOCAL_GCP_LOCATION = load_local_gemini_defaults()

AUTH_MODE_API_KEY = "API key"
AUTH_MODE_VERTEX = "Vertex AI project"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | TEXT_EXTENSIONS | PDF_EXTENSIONS
SUPPORTED_MODELS = [
    {"label": "Gemini 3.1 Pro Preview", "id": "gemini-3.1-pro-preview"},
    {"label": "Gemini 3.1 Flash Lite Preview", "id": "gemini-3.1-flash-lite-preview"},
    {"label": "Gemini 3.1 Flash Image Preview", "id": "gemini-3.1-flash-image-preview"},
    {"label": "Gemini 3 Flash Preview", "id": "gemini-3-flash-preview"},
    {"label": "Gemini 3 Pro Image Preview", "id": "gemini-3-pro-image-preview"},
    {"label": "Gemini 2.5 Pro", "id": "gemini-2.5-pro"},
    {"label": "Gemini 2.5 Flash", "id": "gemini-2.5-flash"},
    {"label": "Gemini 2.5 Flash Lite", "id": "gemini-2.5-flash-lite"},
    {"label": "Gemini 2.5 Flash Image", "id": "gemini-2.5-flash-image"},
]
SUPPORTED_MODEL_IDS = [item["id"] for item in SUPPORTED_MODELS]
MODEL_LABEL_BY_ID = {item["id"]: item["label"] for item in SUPPORTED_MODELS}
IMAGE_OUTPUT_MODEL_IDS = {
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
    "gemini-2.5-flash-image",
}
IMAGE_OUTPUT_MODEL_RECOMMENDATIONS = [
    model_id for model_id in SUPPORTED_MODEL_IDS if model_id in IMAGE_OUTPUT_MODEL_IDS
]
DEFAULT_MODEL = (
    os.environ.get("GEMINI_CHAT_DEFAULT_MODEL", "").strip()
    if os.environ.get("GEMINI_CHAT_DEFAULT_MODEL", "").strip() in SUPPORTED_MODEL_IDS
    else "gemini-3-flash-preview"
)
DEFAULT_LOCATION = "global"
DEFAULT_AUTH_MODE = AUTH_MODE_VERTEX if (LOCAL_GCP_PROJECT or "").strip() else AUTH_MODE_API_KEY
DEFAULT_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("GENAI_API_KEY")
    or ""
)
COMMON_VERTEX_LOCATIONS = [
    value
    for value in [
        DEFAULT_LOCATION,
        LOCAL_GCP_LOCATION,
        "us-central1",
        "us-east5",
        "us-west1",
        "europe-west4",
        "europe-west1",
        "asia-southeast1",
    ]
    if isinstance(value, str) and value.strip()
]
ETL_CHAT_TEMP_ROOT = etl_artifact_root() / "gui_etl_chat_temp"
IMAGE_EDIT_PROMPT_TEMPLATE = """You are editing the provided BASE image in-place.

Reminders:
- Preserve camera angle, geometry, and lighting of the base image unless the user explicitly asks otherwise.
- Keep the original subject clearly recognizable unless the user explicitly asks for a replacement.
- Apply only the visible modifications requested below.

USER REQUEST:
{user_request}
"""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _unique_in_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _human_size(size_bytes: int) -> str:
    size = float(max(0, int(size_bytes)))
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size_bytes)} B"


def _format_model_option(model_id: str) -> str:
    label = MODEL_LABEL_BY_ID.get(model_id, model_id)
    suffix = " [image output]" if model_id in IMAGE_OUTPUT_MODEL_IDS else ""
    if label == model_id:
        return f"{model_id}{suffix}"
    return f"{label} ({model_id}){suffix}"


def _mime_type_for_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".md" or suffix == ".markdown":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    mime_type, _ = mimetypes.guess_type(name)
    return mime_type or "application/octet-stream"


def _extension_for_mime_type(mime_type: str) -> str:
    normalized = _clean_text(mime_type).lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/png":
        return ".png"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/gif":
        return ".gif"
    guessed = mimetypes.guess_extension(normalized, strict=False) if normalized else None
    return guessed or ".bin"


def _attachment_supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_EXTENSIONS


def _safe_session_temp_dir(session_id: str) -> Path:
    safe_session_id = _clean_text(session_id) or uuid.uuid4().hex[:12]
    root = ETL_CHAT_TEMP_ROOT.resolve()
    target = (ETL_CHAT_TEMP_ROOT / safe_session_id).resolve()
    if root not in target.parents and target != root:
        raise ValueError("Resolved temp directory is outside the GUI ETL chat temp root.")
    return target


def ensure_chat_temp_dir() -> Path:
    target = _safe_session_temp_dir(str(st.session_state.get("etl_chat_session_id", "")))
    target.mkdir(parents=True, exist_ok=True)
    return target


def cleanup_chat_temp_dir(session_id: str) -> None:
    if not _clean_text(session_id):
        return
    with contextlib.suppress(Exception):
        shutil.rmtree(_safe_session_temp_dir(session_id), ignore_errors=True)


def _normalize_path(path_text: str) -> Path:
    candidate = Path(path_text).expanduser()
    try:
        return candidate.resolve()
    except Exception:
        return candidate.absolute()


def _supported_extensions_label() -> str:
    ordered = [".pdf", ".txt", ".md", ".markdown", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]
    return ", ".join(ordered)


def current_chat_config() -> Dict[str, str]:
    auth_mode = _clean_text(st.session_state.get("etl_chat_auth_mode", DEFAULT_AUTH_MODE))
    return {
        "auth_mode": auth_mode,
        "model": _clean_text(st.session_state.get("etl_chat_model", DEFAULT_MODEL)),
        "project_id": _clean_text(st.session_state.get("etl_chat_project_id", "")),
        "location": _clean_text(st.session_state.get("etl_chat_location", DEFAULT_LOCATION)),
    }


def chat_config_signature(config: Optional[Dict[str, str]] = None) -> str:
    payload = config or current_chat_config()
    return "||".join(
        [
            _clean_text(payload.get("auth_mode")),
            _clean_text(payload.get("model")),
            _clean_text(payload.get("project_id")),
            _clean_text(payload.get("location")),
        ]
    )


def active_chat_config() -> Dict[str, str]:
    payload = st.session_state.get("etl_chat_active_config")
    if isinstance(payload, dict):
        return {
            "auth_mode": _clean_text(payload.get("auth_mode")),
            "model": _clean_text(payload.get("model")),
            "project_id": _clean_text(payload.get("project_id")),
            "location": _clean_text(payload.get("location")),
        }
    return current_chat_config()


def set_active_chat_config(config: Optional[Dict[str, str]] = None) -> None:
    payload = dict(config or current_chat_config())
    st.session_state["etl_chat_active_config"] = payload
    st.session_state["etl_chat_active_config_signature"] = chat_config_signature(payload)


def pending_chat_config_change() -> bool:
    messages = list(st.session_state.get("etl_chat_messages") or [])
    if not messages:
        return False
    return chat_config_signature(current_chat_config()) != chat_config_signature(active_chat_config())


def describe_chat_config(config: Optional[Dict[str, str]] = None) -> str:
    payload = config or current_chat_config()
    auth_mode = _clean_text(payload.get("auth_mode")) or DEFAULT_AUTH_MODE
    model = _clean_text(payload.get("model")) or DEFAULT_MODEL
    if auth_mode == AUTH_MODE_VERTEX:
        project_id = _clean_text(payload.get("project_id")) or "(no project)"
        location = _clean_text(payload.get("location")) or DEFAULT_LOCATION
        return f"{model} via Vertex (`{project_id}` / `{location}`)"
    return f"{model} via API key"


def init_state() -> None:
    st.session_state.setdefault("etl_chat_messages", [])
    st.session_state.setdefault("etl_chat_auth_mode", DEFAULT_AUTH_MODE)
    st.session_state.setdefault("etl_chat_api_key", DEFAULT_API_KEY)
    st.session_state.setdefault("etl_chat_project_id", _clean_text(LOCAL_GCP_PROJECT))
    st.session_state.setdefault("etl_chat_location", DEFAULT_LOCATION)
    st.session_state.setdefault("etl_chat_model", DEFAULT_MODEL)
    if _clean_text(st.session_state.get("etl_chat_model", "")) not in SUPPORTED_MODEL_IDS:
        st.session_state["etl_chat_model"] = DEFAULT_MODEL
    st.session_state.setdefault("etl_chat_temperature", 0.2)
    st.session_state.setdefault("etl_chat_system_prompt", "")
    st.session_state.setdefault("etl_chat_max_output_tokens", 4096)
    st.session_state.setdefault("etl_chat_top_p", 0.95)
    st.session_state.setdefault("etl_chat_top_k", 40)
    st.session_state.setdefault("etl_chat_seed", "")
    st.session_state.setdefault("etl_chat_enable_thinking", False)
    st.session_state.setdefault("etl_chat_include_thoughts", False)
    st.session_state.setdefault("etl_chat_thinking_budget", 1024)
    st.session_state.setdefault("etl_chat_uploader_nonce", 0)
    st.session_state.setdefault("etl_chat_session_id", uuid.uuid4().hex[:12])
    st.session_state.setdefault("etl_chat_active_config", current_chat_config())
    st.session_state.setdefault(
        "etl_chat_active_config_signature",
        chat_config_signature(current_chat_config()),
    )
    if not list(st.session_state.get("etl_chat_messages") or []):
        set_active_chat_config(current_chat_config())


def reset_composer() -> None:
    current_upload_key = _uploaded_files_key()
    current_attachment_key = _attachment_paths_key()
    current_prompt_key = _prompt_fallback_key()
    st.session_state.pop(current_upload_key, None)
    st.session_state.pop(current_attachment_key, None)
    st.session_state.pop(current_prompt_key, None)
    st.session_state["etl_chat_uploader_nonce"] = int(
        st.session_state.get("etl_chat_uploader_nonce", 0)
    ) + 1


def clear_chat() -> None:
    cleanup_chat_temp_dir(str(st.session_state.get("etl_chat_session_id", "")))
    st.session_state["etl_chat_messages"] = []
    st.session_state["etl_chat_session_id"] = uuid.uuid4().hex[:12]
    set_active_chat_config(current_chat_config())
    reset_composer()


def trigger_rerun() -> None:
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if callable(rerun_fn):
        rerun_fn()


def apply_chat_theme() -> None:
    apply_streamlit_theme("GUI ETL Chat")
    st.markdown(
        """
        <style>
        .chat-shell {
            max-width: 980px;
            margin: 0 auto 1rem auto;
        }
        .chat-hero {
            display: flex;
            gap: 1rem;
            justify-content: space-between;
            align-items: flex-start;
            padding: 1.15rem 1.25rem;
            border: 1px solid var(--border);
            border-radius: 22px;
            background: linear-gradient(145deg, rgba(253,251,247,0.96), rgba(244,236,228,0.95));
            box-shadow: var(--shadow);
            margin-bottom: 1rem;
        }
        .chat-hero h1 {
            margin: 0;
            font-size: 2.1rem;
            line-height: 1.05;
        }
        .chat-hero p {
            margin: 0.45rem 0 0 0;
            color: #5f5953;
            max-width: 720px;
        }
        .chat-kicker {
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--accent);
            font-size: 0.8rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }
        .chat-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: flex-end;
        }
        .chat-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.7);
            border: 1px solid rgba(213,77,54,0.18);
            color: #5c554d;
            font-size: 0.86rem;
        }
        .chat-empty {
            border: 1px dashed #cbbba8;
            border-radius: 20px;
            padding: 1.25rem;
            background: rgba(255,255,255,0.62);
            color: #5f5953;
        }
        .attachment-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            margin-top: 0.35rem;
        }
        .attachment-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            border: 1px solid #d9cbbd;
            background: #fbf6ef;
            color: #5a534d;
            font-size: 0.82rem;
        }
        .attachment-source {
            color: #8b857f;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(251,246,239,0.95), rgba(243,236,228,0.95));
        }
        div[data-testid="stChatMessage"] {
            background: rgba(255,255,255,0.6);
            border: 1px solid rgba(226,219,209,0.7);
            border-radius: 18px;
            padding: 0.2rem 0.2rem 0.3rem 0.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_client(auth_mode: str, api_key: str, project_id: str, location: str) -> genai.Client:
    if auth_mode == AUTH_MODE_API_KEY:
        resolved_api_key = _clean_text(api_key)
        if not resolved_api_key:
            raise ValueError("Enter an API key before sending a request.")
        return genai.Client(api_key=resolved_api_key)

    resolved_project_id = _clean_text(project_id)
    if not resolved_project_id:
        raise ValueError("Enter a Google Cloud project ID before sending a request.")
    resolved_location = _clean_text(location) or DEFAULT_LOCATION
    return genai.Client(
        vertexai=True,
        project=resolved_project_id,
        location=resolved_location,
    )


def build_generation_config(
    *,
    response_modalities: Optional[List[str]] = None,
) -> types.GenerateContentConfig:
    try:
        temperature = float(st.session_state.get("etl_chat_temperature", 0.2))
    except (TypeError, ValueError):
        temperature = 0.2

    try:
        max_output_tokens = int(st.session_state.get("etl_chat_max_output_tokens", 4096))
    except (TypeError, ValueError):
        max_output_tokens = 4096

    try:
        top_p = float(st.session_state.get("etl_chat_top_p", 0.95))
    except (TypeError, ValueError):
        top_p = 0.95

    try:
        top_k = int(st.session_state.get("etl_chat_top_k", 40))
    except (TypeError, ValueError):
        top_k = 40

    seed_text = _clean_text(st.session_state.get("etl_chat_seed", ""))
    seed_value = None
    if seed_text:
        try:
            seed_value = int(seed_text)
        except ValueError as exc:
            raise ValueError("Seed must be an integer.") from exc

    config_kwargs: Dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max(64, max_output_tokens),
        "top_p": min(max(top_p, 0.0), 1.0),
        "top_k": max(1, top_k),
    }
    system_prompt = _clean_text(st.session_state.get("etl_chat_system_prompt", ""))
    if system_prompt:
        config_kwargs["system_instruction"] = system_prompt
    if seed_value is not None:
        config_kwargs["seed"] = seed_value

    if st.session_state.get("etl_chat_enable_thinking", False):
        thinking_kwargs: Dict[str, Any] = {}
        if st.session_state.get("etl_chat_include_thoughts", False):
            thinking_kwargs["include_thoughts"] = True
        try:
            thinking_budget = int(st.session_state.get("etl_chat_thinking_budget", 1024))
        except (TypeError, ValueError):
            thinking_budget = 1024
        if thinking_budget > 0:
            thinking_kwargs["thinking_budget"] = thinking_budget
        if thinking_kwargs:
            config_kwargs["thinking_config"] = types.ThinkingConfig(**thinking_kwargs)

    if response_modalities:
        config_kwargs["response_modalities"] = list(response_modalities)

    return types.GenerateContentConfig(**config_kwargs)


def _uploaded_files_key() -> str:
    return f"etl_chat_uploader_{int(st.session_state.get('etl_chat_uploader_nonce', 0))}"


def _attachment_paths_key() -> str:
    return f"etl_chat_attachment_paths_{int(st.session_state.get('etl_chat_uploader_nonce', 0))}"


def _prompt_fallback_key() -> str:
    return f"etl_chat_prompt_fallback_{int(st.session_state.get('etl_chat_uploader_nonce', 0))}"


def _uploaded_file_list() -> List[Any]:
    uploaded_files = st.session_state.get(_uploaded_files_key())
    if not uploaded_files:
        return []
    if isinstance(uploaded_files, list):
        return uploaded_files
    return [uploaded_files]


def _attachment_paths_value() -> str:
    return _clean_text(st.session_state.get(_attachment_paths_key(), ""))


def _attachment_preview_from_uploaded(uploaded_file: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    name = str(getattr(uploaded_file, "name", "") or "upload")
    if not _attachment_supported(name):
        return None, f"Unsupported uploaded file type: {name}"
    try:
        size_bytes = len(uploaded_file.getvalue())
    except Exception:
        size_bytes = 0
    return {
        "name": name,
        "source": "upload",
        "size_bytes": size_bytes,
    }, None


def _attachment_preview_from_path(path_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    path = _normalize_path(path_text)
    if not path.exists():
        return None, f"Attachment path not found: {path}"
    if not path.is_file():
        return None, f"Attachment path is not a file: {path}"
    if not _attachment_supported(path.name):
        return None, f"Unsupported attachment type: {path.name}"
    try:
        size_bytes = path.stat().st_size
    except Exception:
        size_bytes = 0
    return {
        "name": path.name,
        "source": str(path),
        "size_bytes": size_bytes,
    }, None


def collect_attachment_previews() -> Tuple[List[Dict[str, Any]], List[str]]:
    previews: List[Dict[str, Any]] = []
    errors: List[str] = []

    for uploaded_file in _uploaded_file_list():
        preview, error = _attachment_preview_from_uploaded(uploaded_file)
        if preview:
            previews.append(preview)
        if error:
            errors.append(error)

    raw_paths = _attachment_paths_value()
    for line in raw_paths.splitlines():
        entry = _clean_text(line)
        if not entry:
            continue
        preview, error = _attachment_preview_from_path(entry)
        if preview:
            previews.append(preview)
        if error:
            errors.append(error)

    return previews, errors


def _text_attachment_payload(name: str, text: str, source_label: str) -> str:
    text = text if isinstance(text, str) else str(text)
    header = f"Attachment: {name}"
    if source_label and source_label != "upload":
        header += f"\nPath: {source_label}"
    return f"{header}\n\n{text}"


def _build_attachment_from_uploaded(uploaded_file: Any) -> Dict[str, Any]:
    name = str(getattr(uploaded_file, "name", "") or "upload")
    if not _attachment_supported(name):
        raise ValueError(f"Unsupported uploaded file type: {name}")
    data = uploaded_file.getvalue()
    suffix = Path(name).suffix.lower()
    mime_type = _clean_text(getattr(uploaded_file, "type", "")) or _mime_type_for_name(name)
    attachment: Dict[str, Any] = {
        "name": name,
        "source": "upload",
        "size_bytes": len(data),
        "mime_type": mime_type,
    }
    if suffix in TEXT_EXTENSIONS:
        attachment["kind"] = "text"
        attachment["text"] = data.decode("utf-8", errors="replace")
    else:
        attachment["kind"] = "binary"
        attachment["data"] = data
    return attachment


def _build_attachment_from_path(path_text: str) -> Dict[str, Any]:
    path = _normalize_path(path_text)
    if not path.exists():
        raise ValueError(f"Attachment path not found: {path}")
    if not path.is_file():
        raise ValueError(f"Attachment path is not a file: {path}")
    if not _attachment_supported(path.name):
        raise ValueError(f"Unsupported attachment type: {path.name}")

    suffix = path.suffix.lower()
    attachment: Dict[str, Any] = {
        "name": path.name,
        "source": str(path),
        "size_bytes": path.stat().st_size,
        "mime_type": _mime_type_for_name(path.name),
    }
    if suffix in TEXT_EXTENSIONS:
        attachment["kind"] = "text"
        attachment["text"] = path.read_text(encoding="utf-8", errors="replace")
    else:
        attachment["kind"] = "binary"
        attachment["data"] = path.read_bytes()
    return attachment


def collect_message_attachments() -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    errors: List[str] = []

    for uploaded_file in _uploaded_file_list():
        try:
            attachments.append(_build_attachment_from_uploaded(uploaded_file))
        except Exception as exc:
            errors.append(str(exc))

    raw_paths = _attachment_paths_value()
    for line in raw_paths.splitlines():
        entry = _clean_text(line)
        if not entry:
            continue
        try:
            attachments.append(_build_attachment_from_path(entry))
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        raise ValueError("\n".join(errors))
    return attachments


def save_generated_image(data: bytes, mime_type: str, *, index: int) -> Dict[str, Any]:
    temp_dir = ensure_chat_temp_dir()
    extension = _extension_for_mime_type(mime_type)
    file_name = f"generated_{uuid.uuid4().hex[:12]}_{index}{extension}"
    path = temp_dir / file_name
    path.write_bytes(data)
    return {
        "path": str(path),
        "mime_type": mime_type,
        "name": file_name,
        "size_bytes": len(data),
    }


def build_user_parts(text: str, attachments: List[Dict[str, Any]]) -> List[types.Part]:
    parts: List[types.Part] = []
    prompt_text = _clean_text(text)
    if prompt_text:
        parts.append(types.Part.from_text(text=prompt_text))

    for attachment in attachments:
        name = str(attachment.get("name") or "attachment")
        source = str(attachment.get("source") or "")
        kind = str(attachment.get("kind") or "binary")
        if kind == "text":
            payload = _text_attachment_payload(name, str(attachment.get("text") or ""), source)
            parts.append(types.Part.from_text(text=payload))
            continue
        parts.append(types.Part.from_text(text=f"Attachment: {name}"))
        parts.append(
            types.Part.from_bytes(
                data=bytes(attachment.get("data") or b""),
                mime_type=str(attachment.get("mime_type") or "application/octet-stream"),
            )
        )

    return parts


def _is_image_attachment(attachment: Dict[str, Any]) -> bool:
    return _clean_text(attachment.get("mime_type")).lower().startswith("image/")


def _image_attachments(attachments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in attachments if isinstance(item, dict) and _is_image_attachment(item)]


def _latest_generated_image_attachment() -> Optional[Dict[str, Any]]:
    messages = list(st.session_state.get("etl_chat_messages") or [])
    for message in reversed(messages):
        for image_meta in reversed(list(message.get("generated_images") or [])):
            path_text = _clean_text(image_meta.get("path"))
            if not path_text:
                continue
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                continue
            mime_type = _clean_text(image_meta.get("mime_type")) or _mime_type_for_name(path.name)
            return {
                "name": path.name,
                "source": str(path),
                "size_bytes": path.stat().st_size,
                "mime_type": mime_type,
                "kind": "binary",
                "data": path.read_bytes(),
            }
    return None


def _prompt_requests_image_edit(prompt: str) -> bool:
    text = _clean_text(prompt).lower()
    if not text:
        return False
    direct_patterns = [
        r"\bedit (this |the )?(image|photo|picture|illustration|render)\b",
        r"\bmodify (this |the )?(image|photo|picture|illustration|render)\b",
        r"\bchange (this |the )?(image|photo|picture)\b",
        r"\bretouch\b",
        r"\bremove background\b",
        r"\breplace background\b",
        r"\brestyle\b",
        r"\binpaint\b",
        r"\boutpaint\b",
    ]
    if any(re.search(pattern, text) for pattern in direct_patterns):
        return True
    if any(token in text for token in ("edit", "modify", "change", "replace", "remove", "add ", "restyle")):
        return any(noun in text for noun in ("image", "photo", "picture", "background", "subject", "object"))
    return False


def _prompt_requests_image_generation(prompt: str) -> bool:
    text = _clean_text(prompt).lower()
    if not text:
        return False
    direct_patterns = [
        r"\bgenerate (an |a )?(image|photo|picture|illustration|render)\b",
        r"\bcreate (an |a )?(image|photo|picture|illustration|render)\b",
        r"\bmake (an |a )?(image|photo|picture|illustration|render)\b",
        r"\bdraw\b",
        r"\brender\b",
        r"\billustrate\b",
    ]
    return any(re.search(pattern, text) for pattern in direct_patterns)


def infer_request_mode(prompt: str, attachments: List[Dict[str, Any]]) -> Optional[str]:
    has_image_input = bool(_image_attachments(attachments)) or _latest_generated_image_attachment() is not None
    if _prompt_requests_image_edit(prompt):
        return "edit"
    if has_image_input and any(
        token in _clean_text(prompt).lower()
        for token in ("edit", "modify", "change", "replace", "remove", "add ", "restyle", "make the")
    ):
        return "edit"
    if _prompt_requests_image_generation(prompt):
        return "generate"
    return None


def build_image_edit_prompt(user_text: str) -> str:
    prompt = _clean_text(user_text)
    return IMAGE_EDIT_PROMPT_TEMPLATE.format(user_request=prompt or "Edit the provided image.")


def build_image_model_recommendation(model_name: str, request_mode: str) -> str:
    mode_label = "image editing" if request_mode == "edit" else "text-to-image generation"
    recommended = ", ".join(f"`{item}`" for item in IMAGE_OUTPUT_MODEL_RECOMMENDATIONS)
    return (
        f"The selected model `{model_name}` is not configured for {mode_label} output in this app. "
        f"Switch to one of these image-capable models: {recommended}."
    )


def build_missing_base_image_message() -> str:
    return (
        "To edit an image, attach a base image in this message or first generate an image in the chat, "
        "then ask for an edit in the next turn."
    )


def build_text_history_contents(history: List[Dict[str, Any]]) -> List[types.Content]:
    contents: List[types.Content] = []
    for message in history:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        message_text = _clean_text(message.get("text"))
        if role == "user" and message_text:
            contents.append(types.UserContent(parts=[types.Part.from_text(text=message_text)]))
        elif role == "assistant":
            if not message_text and list(message.get("generated_images") or []):
                message_text = f"[Assistant generated {len(list(message.get('generated_images') or []))} image(s).]"
            if message_text:
                contents.append(types.ModelContent(parts=[types.Part.from_text(text=message_text)]))
    return contents


def build_conversation_contents(
    history: List[Dict[str, Any]],
    pending_user_message: Optional[Dict[str, Any]] = None,
) -> List[types.Content]:
    contents: List[types.Content] = []
    for message in list(history) + ([pending_user_message] if pending_user_message else []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role == "user":
            user_parts = build_user_parts(
                str(message.get("text") or ""),
                list(message.get("attachments") or []),
            )
            if user_parts:
                contents.append(types.UserContent(parts=user_parts))
        elif role == "assistant":
            assistant_text = _clean_text(message.get("text"))
            if not assistant_text and list(message.get("generated_images") or []):
                assistant_text = f"[Assistant generated {len(list(message.get('generated_images') or []))} image(s).]"
            if assistant_text:
                contents.append(types.ModelContent(parts=[types.Part.from_text(text=assistant_text)]))
    return contents


def extract_response_payload(response: Any) -> Tuple[str, str, List[Dict[str, Any]]]:
    text_parts: List[str] = []
    thought_parts: List[str] = []
    generated_images: List[Dict[str, Any]] = []

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        candidate = candidates[0]
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for index, part in enumerate(parts, start=1):
            part_text = getattr(part, "text", None)
            if not part_text:
                inline_data = getattr(part, "inline_data", None)
                blob_data = getattr(inline_data, "data", None) if inline_data is not None else None
                blob_mime = _clean_text(
                    getattr(inline_data, "mime_type", None) if inline_data is not None else ""
                )
                if blob_data and blob_mime.startswith("image/"):
                    generated_images.append(
                        save_generated_image(bytes(blob_data), blob_mime, index=index)
                    )
                continue
            if bool(getattr(part, "thought", False)):
                thought_parts.append(str(part_text))
            else:
                text_parts.append(str(part_text))

    if not text_parts:
        raw_text = getattr(response, "text", None)
        if raw_text:
            text_parts.append(str(raw_text))

    answer_text = "\n\n".join(item.strip() for item in text_parts if str(item).strip()).strip()
    thought_text = "\n\n".join(item.strip() for item in thought_parts if str(item).strip()).strip()
    return answer_text, thought_text, generated_images


def run_chat_turn(user_text: str, attachments: List[Dict[str, Any]]) -> Dict[str, Any]:
    auth_mode = str(st.session_state.get("etl_chat_auth_mode", DEFAULT_AUTH_MODE))
    model_name = _clean_text(st.session_state.get("etl_chat_model", DEFAULT_MODEL))
    if not model_name:
        raise ValueError("Enter a model name before sending a request.")

    working_attachments = list(attachments)
    request_mode = infer_request_mode(user_text, working_attachments)
    if request_mode in {"generate", "edit"} and model_name not in IMAGE_OUTPUT_MODEL_IDS:
        return {
            "answer_text": build_image_model_recommendation(model_name, request_mode),
            "thought_text": "",
            "generated_images": [],
            "attachments_used": working_attachments,
            "request_mode": request_mode,
            "local_only": True,
        }

    if request_mode == "edit" and not _image_attachments(working_attachments):
        previous_image = _latest_generated_image_attachment()
        if previous_image is not None:
            working_attachments.append(previous_image)
        else:
            return {
                "answer_text": build_missing_base_image_message(),
                "thought_text": "",
                "generated_images": [],
                "attachments_used": working_attachments,
                "request_mode": request_mode,
                "local_only": True,
            }

    client = build_client(
        auth_mode=auth_mode,
        api_key=str(st.session_state.get("etl_chat_api_key", "")),
        project_id=str(st.session_state.get("etl_chat_project_id", "")),
        location=str(st.session_state.get("etl_chat_location", DEFAULT_LOCATION)),
    )
    prompt_text_for_model = build_image_edit_prompt(user_text) if request_mode == "edit" else user_text

    if request_mode in {"generate", "edit"}:
        config = build_generation_config(response_modalities=["IMAGE", "TEXT"])
        contents = build_text_history_contents(list(st.session_state.get("etl_chat_messages") or []))
        current_user_parts = build_user_parts(prompt_text_for_model, working_attachments)
        if current_user_parts:
            contents.append(types.UserContent(parts=current_user_parts))
    else:
        config = build_generation_config()
        pending_user_message = {
            "role": "user",
            "text": user_text,
            "attachments": working_attachments,
        }
        contents = build_conversation_contents(
            history=list(st.session_state.get("etl_chat_messages") or []),
            pending_user_message=pending_user_message,
        )
    if not contents:
        raise ValueError("Enter a prompt or attach at least one supported file.")

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=config,
    )
    answer_text, thought_text, generated_images = extract_response_payload(response)
    if not answer_text and not thought_text and not generated_images:
        raise RuntimeError("The model returned no visible output.")
    return {
        "answer_text": answer_text,
        "thought_text": thought_text,
        "generated_images": generated_images,
        "attachments_used": working_attachments,
        "request_mode": request_mode,
        "local_only": False,
    }


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Session")
        if st.button("New chat", use_container_width=True):
            clear_chat()
            trigger_rerun()

        auth_mode = st.radio(
            "Authentication",
            options=[AUTH_MODE_API_KEY, AUTH_MODE_VERTEX],
            key="etl_chat_auth_mode",
        )
        st.selectbox(
            "Model",
            options=SUPPORTED_MODEL_IDS,
            key="etl_chat_model",
            format_func=_format_model_option,
        )
        st.caption(
            "Image output capable: "
            + ", ".join(f"`{model_id}`" for model_id in IMAGE_OUTPUT_MODEL_RECOMMENDATIONS)
        )
        st.slider(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            step=0.1,
            key="etl_chat_temperature",
        )

        if auth_mode == AUTH_MODE_API_KEY:
            st.text_input(
                "API key",
                type="password",
                key="etl_chat_api_key",
                help="Used with direct Gemini API authentication.",
            )
            st.caption("Project ID and location are not used in API key mode.")
        else:
            st.text_input(
                "Project ID",
                key="etl_chat_project_id",
                help="Uses Vertex AI authentication with your current Google credentials.",
            )
            st.text_input("Location", key="etl_chat_location")
            st.caption("Default is `global`. Common choices: " + ", ".join(_unique_in_order(COMMON_VERTEX_LOCATIONS)))

        if pending_chat_config_change():
            st.warning("Model/project/auth settings changed. The next message will start a new chat.")
            st.caption("Current chat: " + describe_chat_config(active_chat_config()))
            st.caption("Next chat: " + describe_chat_config(current_chat_config()))
            if st.button("Start new chat with selected settings", use_container_width=True):
                clear_chat()
                trigger_rerun()

        with st.expander("Advanced", expanded=False):
            st.text_area(
                "System prompt",
                key="etl_chat_system_prompt",
                height=140,
                help="Optional system instruction applied to the full chat session.",
            )
            st.number_input(
                "Max output tokens",
                min_value=64,
                max_value=32768,
                step=64,
                key="etl_chat_max_output_tokens",
            )
            st.number_input(
                "Top K",
                min_value=1,
                max_value=100,
                step=1,
                key="etl_chat_top_k",
            )
            st.slider(
                "Top P",
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                key="etl_chat_top_p",
            )
            st.text_input(
                "Seed (optional integer)",
                key="etl_chat_seed",
                help="Leave blank unless you want reproducible sampling.",
            )
            st.checkbox(
                "Enable thinking config",
                key="etl_chat_enable_thinking",
                help="Model support varies. Unsupported models may return an API error.",
            )
            st.checkbox(
                "Show thought trace",
                key="etl_chat_include_thoughts",
                disabled=not bool(st.session_state.get("etl_chat_enable_thinking", False)),
            )
            st.number_input(
                "Thinking budget",
                min_value=0,
                max_value=8192,
                step=128,
                key="etl_chat_thinking_budget",
                disabled=not bool(st.session_state.get("etl_chat_enable_thinking", False)),
                help="0 lets the backend decide; positive values request an explicit budget.",
            )

        st.caption(
            "Supported attachments: "
            + _supported_extensions_label()
            + ". Attachments are replayed with each follow-up turn so the model keeps context."
        )


def _status_pills() -> str:
    auth_mode = str(st.session_state.get("etl_chat_auth_mode", DEFAULT_AUTH_MODE))
    model_name = html.escape(_clean_text(st.session_state.get("etl_chat_model", DEFAULT_MODEL)) or "(unset)")
    pills = [
        f"<span class='chat-pill'><strong>Mode</strong> {html.escape(auth_mode)}</span>",
        f"<span class='chat-pill'><strong>Model</strong> {model_name}</span>",
        (
            f"<span class='chat-pill'><strong>Temp</strong> "
            f"{float(st.session_state.get('etl_chat_temperature', 0.2)):.1f}</span>"
        ),
    ]
    if auth_mode == AUTH_MODE_VERTEX:
        location = html.escape(_clean_text(st.session_state.get("etl_chat_location", DEFAULT_LOCATION)) or DEFAULT_LOCATION)
        pills.append(f"<span class='chat-pill'><strong>Location</strong> {location}</span>")
    return "".join(pills)


def render_header() -> None:
    st.markdown(
        f"""
        <div class="chat-shell">
          <div class="chat-hero">
            <div>
              <div class="chat-kicker">GUI ETL Chat</div>
              <h1>Chat over PDFs, images, and text files.</h1>
              <p>
                Submit a prompt, attach source files, and continue the same Gemini conversation
                across follow-up turns without using the batch ETL workflow screens.
              </p>
            </div>
            <div class="chat-pills">{_status_pills()}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if pending_chat_config_change():
        st.info(
            "The open conversation is still pinned to "
            + describe_chat_config(active_chat_config())
            + ". Sending the next message will restart the chat with "
            + describe_chat_config(current_chat_config())
            + "."
        )


def render_pending_attachments() -> None:
    previews, errors = collect_attachment_previews()
    with st.expander("Attachments for the next message", expanded=bool(previews or errors)):
        st.file_uploader(
            "Upload files",
            type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
            accept_multiple_files=True,
            key=_uploaded_files_key(),
            help="Upload one or more PDFs, images, markdown files, or text files.",
        )
        st.text_area(
            "Or enter file paths, one per line",
            key=_attachment_paths_key(),
            height=90,
            placeholder="/absolute/path/to/file.pdf\nrelative/path/to/notes.md",
        )

        previews, errors = collect_attachment_previews()
        if previews:
            chips = []
            for item in previews:
                source = "upload" if item["source"] == "upload" else html.escape(str(item["source"]))
                chips.append(
                    "<span class='attachment-chip'>"
                    f"{html.escape(str(item['name']))}"
                    f" <span class='attachment-source'>({source}, {_human_size(int(item['size_bytes']))})</span>"
                    "</span>"
                )
            st.markdown(
                "<div class='attachment-chip-row'>" + "".join(chips) + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No pending attachments.")

        for error in errors:
            st.warning(error)


def render_message_attachments(message: Dict[str, Any]) -> None:
    attachments = list(message.get("attachments") or [])
    if not attachments:
        return
    chips: List[str] = []
    for attachment in attachments:
        name = html.escape(str(attachment.get("name") or "attachment"))
        source = str(attachment.get("source") or "")
        source_label = "upload" if source == "upload" else "path"
        size_bytes = int(attachment.get("size_bytes") or 0)
        chips.append(
            "<span class='attachment-chip'>"
            f"{name} <span class='attachment-source'>({source_label}, {_human_size(size_bytes)})</span>"
            "</span>"
        )
    st.markdown(
        "<div class='attachment-chip-row'>" + "".join(chips) + "</div>",
        unsafe_allow_html=True,
    )


def render_generated_images(message: Dict[str, Any]) -> None:
    generated_images = list(message.get("generated_images") or [])
    if not generated_images:
        return
    first_path_text = _clean_text(generated_images[0].get("path"))
    if first_path_text:
        st.caption(f"Generated image output saved under `{Path(first_path_text).parent}`")
    for image_meta in generated_images:
        path_text = _clean_text(image_meta.get("path"))
        if not path_text:
            continue
        path = Path(path_text)
        if not path.exists():
            st.warning(f"Generated image file is missing: {path}")
            continue
        caption = f"{path.name} • {_human_size(int(image_meta.get('size_bytes') or 0))}"
        st.image(str(path), caption=caption, use_container_width=True)
        st.caption(str(path))


def render_messages() -> None:
    messages = list(st.session_state.get("etl_chat_messages") or [])
    if not messages:
        st.markdown(
            """
            <div class="chat-empty">
              <strong>How to use it</strong><br/>
              1. Choose API key or Vertex AI project authentication in the sidebar.<br/>
              2. Set the model, temperature, and any advanced options you want.<br/>
              3. Add PDFs, images, markdown, or text files for the next turn, then submit a prompt below.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for message in messages:
        role = str(message.get("role") or "assistant")
        speaker = "assistant" if role != "user" else "user"
        message_text = _clean_text(message.get("text"))
        thoughts = _clean_text(message.get("thoughts"))

        if hasattr(st, "chat_message"):
            with st.chat_message(speaker):
                if message_text:
                    st.markdown(message_text)
                elif role == "user" and list(message.get("attachments") or []):
                    st.caption("(attachments only)")
                render_message_attachments(message)
                if role == "assistant":
                    render_generated_images(message)
                if role == "assistant" and thoughts:
                    with st.expander("Thought trace", expanded=False):
                        st.markdown(thoughts)
            continue

        label = "User" if role == "user" else "Assistant"
        with st.container():
            st.markdown(f"**{label}**")
            if message_text:
                st.markdown(message_text)
            elif role == "user" and list(message.get("attachments") or []):
                st.caption("(attachments only)")
            render_message_attachments(message)
            if role == "assistant":
                render_generated_images(message)
            if role == "assistant" and thoughts:
                with st.expander("Thought trace", expanded=False):
                    st.markdown(thoughts)


def render_message_fallback() -> Optional[str]:
    prompt_text = st.text_area(
        "Message",
        key=_prompt_fallback_key(),
        height=100,
        placeholder="Ask a question about the attached files or continue the conversation.",
    )
    if st.button("Send", use_container_width=True):
        return prompt_text
    return None


def render_composer() -> Optional[str]:
    if hasattr(st, "chat_input"):
        return st.chat_input("Ask a question, then press Enter")
    return render_message_fallback()


def main() -> None:
    apply_chat_theme()
    init_state()
    render_sidebar()
    render_header()
    render_messages()
    render_pending_attachments()

    prompt = render_composer()
    if prompt is None:
        return

    prompt_text = prompt if isinstance(prompt, str) else str(prompt)
    try:
        attachments = collect_message_attachments()
    except Exception as exc:
        st.error(str(exc))
        return

    if not _clean_text(prompt_text) and not attachments:
        st.error("Enter a prompt or attach at least one supported file.")
        return

    if pending_chat_config_change():
        if infer_request_mode(prompt_text, attachments) == "edit" and not _image_attachments(attachments):
            previous_image = _latest_generated_image_attachment()
            if previous_image is not None:
                attachments = list(attachments) + [previous_image]
        clear_chat()

    with st.spinner("Sending request..."):
        try:
            turn_result = run_chat_turn(prompt_text, attachments)
        except Exception as exc:
            st.error(str(exc))
            return

    answer_text = _clean_text(turn_result.get("answer_text"))
    thought_text = _clean_text(turn_result.get("thought_text"))
    generated_images = list(turn_result.get("generated_images") or [])
    attachments_used = list(turn_result.get("attachments_used") or [])

    st.session_state["etl_chat_messages"] = list(st.session_state.get("etl_chat_messages") or []) + [
        {
            "role": "user",
            "text": prompt_text,
            "attachments": attachments_used,
        },
        {
            "role": "assistant",
            "text": answer_text or ("(Generated image output below.)" if generated_images else "(No visible text output returned.)"),
            "thoughts": thought_text,
            "attachments": [],
            "generated_images": generated_images,
        },
    ]
    reset_composer()
    trigger_rerun()


if __name__ == "__main__":
    main()
