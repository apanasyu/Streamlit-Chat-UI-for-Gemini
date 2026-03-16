# GUI ETL Chat Dependencies

This file lists the dependencies required to move `streamlit_app/GUI_ETL_Chat.py` into another repo.

## External Python Packages

Required:

- `streamlit`
- `google-genai`

Suggested install:

```bash
pip install streamlit google-genai
```

If you want to keep dependency pinning in a project file, the minimal `requirements.txt` can be:

```text
streamlit
google-genai
```

## Python Standard Library Modules Used

No install needed. `GUI_ETL_Chat.py` uses:

- `contextlib`
- `html`
- `mimetypes`
- `os`
- `re`
- `shutil`
- `sys`
- `uuid`
- `pathlib`
- `typing`

## Local Python Files Required As-Is

These are the repo-local files imported directly by `GUI_ETL_Chat.py`:

- `streamlit_app/GUI_ETL_Chat.py`
- `streamlit_app/ui_theme.py`
- `streamlit_app/local_runtime_config.py`
- `streamlit_app/runtime_paths.py`

If you do not copy these, you must replace the imports and equivalent behavior:

- `from local_runtime_config import load_local_gemini_defaults`
- `from runtime_paths import etl_artifact_root`
- `from ui_theme import apply_streamlit_theme`

## Optional Local File

Optional config file:

- `.gemini_local_config.json`

Purpose:

- prefill default Vertex project and location

## Runtime/Auth Dependencies

### API key mode

Needs one of:

- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `GENAI_API_KEY`

Or the user can paste the API key into the sidebar.

### Vertex AI mode

Needs:

- valid Google credentials on the machine
- a real Google Cloud project ID
- a valid location

Typical setup:

```bash
gcloud auth application-default login
```

Common env vars recognized by the app:

- `GOOGLE_CLOUD_PROJECT`
- `PROJECT_ID`
- `GOOGLE_PROJECT`
- `GOOGLE_CLOUD_REGION`
- `LOCAL_GEMINI_CONFIG_PATH`

## Artifact/Temp Storage Dependency

The app writes generated images under:

```text
.artifacts/etl/gui_etl_chat_temp/<session-id>/
```

That path depends on `streamlit_app/runtime_paths.py`.

Relevant env vars:

- `ETL_ARTIFACT_ROOT`
- `STREAMLIT_ARTIFACT_ROOT`

If you do not want the shared artifact-root helper in another repo, replace:

- `etl_artifact_root()`

with your own temp/output directory function.

## Functional Dependency Breakdown

### Needed for the UI shell

- `streamlit`
- `streamlit_app/ui_theme.py`

### Needed for Gemini requests

- `google-genai`

### Needed for local Vertex defaults

- `streamlit_app/local_runtime_config.py`

### Needed for generated image temp storage

- `streamlit_app/runtime_paths.py`

## Features And What They Depend On

### Text chat

Needs:

- `streamlit`
- `google-genai`

### File attachment understanding

Needs:

- `streamlit`
- `google-genai`
- standard library file and MIME helpers

### Text -> image generation

Needs:

- `streamlit`
- `google-genai`
- temp artifact path support from `runtime_paths.py`

### Image -> edited image

Needs:

- `streamlit`
- `google-genai`
- temp artifact path support from `runtime_paths.py`

### Sidebar theme and layout

Needs:

- `streamlit_app/ui_theme.py`

## Smallest Copy Set For Another Repo

If your goal is only to make `GUI_ETL_Chat.py` work somewhere else, copy:

- `streamlit_app/GUI_ETL_Chat.py`
- `streamlit_app/ui_theme.py`
- `streamlit_app/local_runtime_config.py`
- `streamlit_app/runtime_paths.py`

Install:

```bash
pip install streamlit google-genai
```

Then run:

```bash
streamlit run streamlit_app/GUI_ETL_Chat.py
```

## Optional Simplifications In A New Repo

You can simplify the copied code if you want:

- remove `local_runtime_config.py` if you do not need `.gemini_local_config.json`
- replace `etl_artifact_root()` with a direct temp folder path
- replace `apply_streamlit_theme()` with inline CSS inside `GUI_ETL_Chat.py`

If you do that, update the imports in `GUI_ETL_Chat.py` accordingly.
