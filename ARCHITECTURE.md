# DriveBackup Architecture & Design

This document serves to explain the inner workings, structure, and design decisions of the DriveBackup application. This context is extremely valuable for AI agents contributing to the project in the future.

## 1. Tech Stack Overview
- **UI Framework:** NiceGUI (which wraps Quasar and Vue.js).
- **Backend/Engine:** Python 3.10+, utilizing standard threading and subprocesses.
- **Data Transfer Engine:** `rclone` (bundled locally in the installer).
- **Window Management:** `pywebview` creates the native desktop window.
- **Packaging:** PyInstaller creates the executable; Inno Setup packages it into an installer.

## 2. Directory Structure
```
app/
  ├── ai/          # Integration with OpenRouter/Gemini for analysis reports
  ├── engine/      # Core logic (rclone wrappers, backup/verify/wipe pipelines)
  ├── gui/         # NiceGUI frontend (app.py, pages.py, widgets.py)
  └── utils/       # Configuration, logging, updating mechanisms
```

## 3. UI/UX Design System
The UI utilizes a "Premium Glassmorphism" aesthetic built with custom CSS injected via `app.py`.
- **Dynamic Theme:** Fully respects the host OS theme via `@media (prefers-color-scheme: light/dark)`. 
- **Google-inspired Colors:** Uses a dynamic palette mapping Google's core branding colors (Blue `#4285F4`, Green `#0F9D58`, Yellow `#F4B400`, Red `#DB4437`).
- **Animations:** All pages and components utilize smooth CSS transitions and keyframe animations (`fadeUp`).

## 4. Google Drive vs Google Photos
DriveBackup supports both Google Drive and Google Photos via `rclone`.
- **State Management:** The user selects the active service (`active_service` in `config.py`), which swaps the active remote backend between `gdrive` and `gphotos`.
- **Limitations:** While Google Drive supports full backup, verification, and wiping, **Google Photos API explicitly prohibits third-party deletion**. Consequently, the "Wipe" tab is hard-blocked when Google Photos is the active service. Additionally, Google Photos downloads are slightly compressed by Google's API, not original quality.

## 5. Security & Safety Gates
- **No API Keys Required:** `rclone` uses its public client ID. Users do not need a GCP project.
- **Local Only:** All data stays on the user's local disk. Config is stored in `%APPDATA%\DriveBackup\config.json`.
- **Wipe Protection:** The `wipe` engine requires a successful `verify` operation within the last N hours (configurable, defaults to 24). Users must explicitly type "DELETE ALL" to initiate a wipe.

## 6. Development Workflow for AI Agents
When extending this app:
1. Always test UI changes by verifying the Python compilation `python -m py_compile ...` or running the app locally.
2. If modifying `rclone` calls in `engine/rclone_manager.py`, be aware that blocking calls must be wrapped in `ctx.start_job` to avoid freezing the NiceGUI event loop.
3. Update `task.md` locally to track progress, and update `HANDOFF.md` when ending a session so the next agent has full context.
