# DriveBackup — Google Drive & Photos Backup, Verify & Wipe

A Windows desktop app that backs up your entire Google Drive to a location you
choose, **verifies every file byte-for-byte**, and — only after a successful
verification — moves your Drive files to Trash and empties it. AI analysis
finds duplicates, junk, and suggests an organization plan. Works without a
credit card or a Google Cloud project.

## Install (recommended: installer from GitHub)

Download the latest `DriveBackup-Setup-<version>.exe` from the
[releases page](https://github.com/nayeemx/DriveBackup/releases) and run it.
The app installs per-user (no admin needed) and updates itself in place from
Settings -> Updates.

- Installed to `%LOCALAPPDATA%\DriveBackup\`
- Config, tokens and rclone live in `%APPDATA%\DriveBackup\`
- No credit card, no Google Cloud project, no background services

## How it works (safety-first)

```
1. Connect   Google sign-in via your browser (rclone's public client)
2. Backup    every file/folder copied to your chosen destination
3. Verify    every file checked (size + MD5; Google Docs/Sheets/Slides exported & confirmed)
4. Analyze   (optional) AI report: duplicates, junk files, org plan (BYOK)
5. Wipe      ONLY after a fresh successful verification:
             - must type "DELETE ALL" and tick the checkbox
             - step 1: all Drive files -> Trash (recoverable)
             - step 2: empty Trash (permanent)
```

Safety gates: **Wipe is blocked** unless a successful verification ran within
the last 24 hours (configurable) *and* you type the exact confirmation phrase.
Only Google Drive is touched during Wipe. (See Google Photos limits below).

## Google Photos Support & API Limitations

The app can also connect to Google Photos. You can select your active service on the Dashboard.
However, **Google explicitly restricts their Google Photos API** for third-party apps:
1. **No Deletions**: It is impossible to delete photos from Google Photos using this app. As a result, the **Wipe** feature is hard-blocked when Google Photos is active.
2. **Quality**: Downloads through the API are slightly compressed (not "original quality" byte-for-byte).

## Updates

- Settings -> Updates -> **Check for updates** (manual), or set
  **Automatic updates** to `prompt` (ask first, default), `silent`, or `off`.
- On startup the app checks the GitHub releases page a few seconds after the
  window opens.
- The update downloads the new installer to `%TEMP%`, runs it silently, and
  relaunches the app — your config and Google connection are preserved.

## AI analysis (optional, BYOK)

Works with **OpenRouter** (any model, one key) or **Google Gemini**:

1. OpenRouter: get a free key at https://openrouter.ai/keys (small usage credit)
2. Settings tab -> paste key, choose provider, enable AI analysis
3. Analysis includes: duplicates, junk files, category overview, and a
   suggested organization plan

Without a key the app still works — analysis and reports are generated
locally.

## Using the app

| Section | What it does |
|---|---|
| Dashboard | Your journey (5 steps with status), connect button, Drive stats |
| Backup | Choose destination, start full backup, live progress |
| Verify | Byte-level check of backup vs Drive (size+MD5, optional deep download check) |
| Analyze | Duplicates/junk/top files table + AI report + organization plan |
| Wipe | Danger zone — safety gates required, 2-step trash flow |
| Settings | Destination, threads, verify freshness window, AI key, updates |

The header shows current job status; the bottom console streams every engine
step with color-coded levels. Notifications pop up for completions and
failures.

## Development

Windows, Python 3.10+ (tested on 3.14).

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py          # desktop app
```

Build the installer (PyInstaller + Inno Setup):

```powershell
.\.venv\Scripts\python build.py --bump patch
```

Tests:

```powershell
.\.venv\Scripts\python smoke_test.py    # end-to-end pipeline on a fake local drive
.\.venv\Scripts\python ai_test.py       # AI analysis on sample data
.\.venv\Scripts\python wipe_test.py     # deep check + wipe execution
```

## Known issues & fixes

Every problem found so far, its root cause, the fix, and how it was verified
is tracked in [PROBLEMS.md](PROBLEMS.md).

## Notes

- Google Docs/Sheets/Slides cannot be downloaded as-is; they are exported
  (docx/xlsx/pptx) and verified by presence + size. All other files are
  MD5-checked.
- Verification result expires (default 24 h) — re-verify before wiping, on purpose.
- UI stack: NiceGUI (Quasar/Material) served by uvicorn, rendered in a native
  window (separate window process, so a busy WebView2 can never stall the app).
  Includes a Premium Glassmorphism design system that automatically shifts between
  Light and Dark mode matching your Windows OS preference.
- Not affiliated with Google. rclone is used under its MIT license.
