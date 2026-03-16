# GUI ETL Chat
<img width="3456" height="1698" alt="image" src="https://github.com/user-attachments/assets/622b28b3-5320-4a15-aa34-e79b3d5cee13" />

`GUI_ETL_Chat.py` is a standalone Streamlit chat UI for Gemini that supports:

- text chat
- PDF/image/text attachment -> text response
- text -> image generation
- image -> edited image generation
- API key auth or Vertex AI project auth

Run it with:

```bash
streamlit run streamlit_app/GUI_ETL_Chat.py
```

## What It Does

The app provides a ChatGPT-style interface with:

- persistent chat history inside the Streamlit session
- model selection from a curated Gemini dropdown
- temperature and advanced generation controls
- file upload plus local path entry for attachments
- automatic handling of image-capable vs text-only models
- inline display of generated images saved to a temp artifact directory

## Supported Input Types

The composer accepts:

- `.pdf`
- `.txt`
- `.md`
- `.markdown`
- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.bmp`
- `.tif`
- `.tiff`

## Supported Models In The Current App

The current dropdown includes:

- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite-preview`
- `gemini-3.1-flash-image-preview`
- `gemini-3-flash-preview`
- `gemini-3-pro-image-preview`
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`
- `gemini-2.5-flash-image`

Models currently treated as image-output capable:

- `gemini-3.1-flash-image-preview`
- `gemini-3-pro-image-preview`
- `gemini-2.5-flash-image`

If the user asks for image generation or image editing while a text-only model is selected, the app responds with a model-switch recommendation instead of making the wrong request.

## Authentication Modes

The sidebar supports two auth modes.

### 1. API key

Uses:

- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `GENAI_API_KEY`

The user can also paste the key directly into the sidebar.

### 2. Vertex AI project

Uses:

- project ID entered in the sidebar or loaded from local config/env
- location entered in the sidebar
- current Google credentials on the machine

Typical setup:

```bash
gcloud auth application-default login
```

Useful env vars:

- `GOOGLE_CLOUD_PROJECT`
- `PROJECT_ID`
- `GOOGLE_PROJECT`
- `GOOGLE_CLOUD_REGION`

## Local Config File

The app optionally reads local defaults from:

```text
.gemini_local_config.json
```

Supported keys in that JSON:

- `google_project`
- `project_id`
- `gcp_project_id`
- `region`
- `location`
- `google_region`
- `gcp_location`

You can also override the config path with:

```bash
export LOCAL_GEMINI_CONFIG_PATH=/absolute/path/to/.gemini_local_config.json
```

## Image Generation And Editing Behavior

The app has three request paths.

### 1. Normal chat

Used for:

- text-only chat
- document/image understanding
- follow-up questions on prior responses

This path uses normal `generate_content(...)` behavior without image output modalities.

### 2. Text -> image

Triggered by prompts such as:

- "draw image of Germany and France"
- "generate an image of a red chair"
- "create a product photo of a watch"

This path sets:

- `response_modalities=["IMAGE", "TEXT"]`

Returned image bytes are saved to disk and rendered in the chat.

### 3. Image -> edited image

Triggered by prompts that imply editing, such as:

- "edit this image"
- "change the background"
- "replace the chair fabric with velvet"
- "remove the logo"

This path:

- wraps the user request in an explicit edit prompt
- sends the base image as inline bytes
- sets `response_modalities=["IMAGE", "TEXT"]`

If the user does not attach a new base image but the previous assistant turn generated one, the app can reuse that last generated image for the next edit request.

## Chat Session Behavior

Model, auth mode, project ID, and location are treated as chat-scoped settings.

If the user changes any of these in the sidebar:

- the current conversation is considered pinned to the old config
- the UI shows that the settings changed
- the next message starts a new chat automatically with the newly selected config
- the sidebar also provides a button to restart immediately

This avoids accidental mixing of messages across different models or projects.

## Generated Image Storage

Generated images are written under:

```text
.artifacts/etl/gui_etl_chat_temp/<session-id>/
```

That location comes from `etl_artifact_root()` in `streamlit_app/runtime_paths.py`.

The root can be changed with:

- `ETL_ARTIFACT_ROOT`
- `STREAMLIT_ARTIFACT_ROOT`

## Files To Copy Into Another Repo

If you want this capability in another repo with minimal code movement, copy these files:

- `streamlit_app/GUI_ETL_Chat.py`
- `streamlit_app/ui_theme.py`
- `streamlit_app/local_runtime_config.py`
- `streamlit_app/runtime_paths.py`

Optional:

- `.gemini_local_config.json`

## Recommended Minimal Folder Layout

```text
your_repo/
  streamlit_app/
    GUI_ETL_Chat.py
    ui_theme.py
    local_runtime_config.py
    runtime_paths.py
  .gemini_local_config.json   # optional
  requirements.txt
```

## Minimal Requirements

At minimum, the app needs:

- `streamlit`
- `google-genai`

See `GUI_ETL_Chat_dependencies.md` for the full migration checklist.

## Notes For Migration

If you move this into a separate repo:

1. Keep the four Python files together unless you also rewrite the local imports.
2. Preserve the `BASE_DIR` logic or replace it with normal package imports.
3. Preserve `runtime_paths.py` or replace `etl_artifact_root()` with your own artifact/temp-directory logic.
4. Preserve `local_runtime_config.py` or remove local default loading if you do not need it.
5. Preserve the image-output path in `GUI_ETL_Chat.py`; it is what makes text -> image and image edits show up in the browser.

## Smoke Test

After moving files, verify these cases:

1. API key mode + text question.
2. API key mode + PDF/image attachment -> text response.
3. Image-capable model + prompt like `Generate an image of a red bicycle in a studio`.
4. Image-capable model + attached image + prompt like `Edit this image: change the background to white`.
5. Switch model mid-chat and verify the app starts a new conversation with the new config.
