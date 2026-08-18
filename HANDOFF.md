# HANDOFF.md — DriveBackup session resume

If you open a new chat and type **"show"**, the assistant reads this file to
restore context and continue from where the last session ended.

## Project
DriveBackup — Windows desktop app (NiceGUI + pywebview, PyInstaller + Inno Setup).
Public repo: https://github.com/nayeemx/DriveBackup (owner `nayeemx`, repo `DriveBackup`).
App: backup / verify / wipe files on your own Google Drive; per-file selection,
disconnect account, AI analysis report (OpenRouter key optional).

## Current state (last session ended)
- **Latest released version: v0.1.28** — live on GitHub
  https://github.com/nayeemx/DriveBackup/releases/tag/v0.1.28
  (DriveBackup-Setup-0.1.28.exe, 53.9 MB, state=uploaded).
- v0.1.28 is **installed** on this machine (`%LOCALAPPDATA%\DriveBackup`, version.txt = 0.1.28)
  and app was verified running on port 8085 (HTTP 200). App may not be running now.
- v0.1.27 release also live; v0.1.25 asset confirmed uploaded (earlier timeout was a false alarm).
- Repo is PUBLIC — other people can download and install the app.

## What v0.1.28 added (installability on any Windows 10/11 64-bit machine)
1. rclone.exe bundled inside installer (no first-run download, works offline);
   app copies bundle → `%APPDATA%\DriveBackup\tools\rclone.exe` on first use.
   Verified: moved app rclone aside → relaunch → restored from bundle (81.2 MB).
2. Free-port selection (`pick_port()` in app/gui/app.py): scans 8085+ for a free
   port. Needed because this machine's WSL relay (wslrelay.exe) squats on 8080
   and silently answers probes — earlier "app is up" checks on 8080 were false
   positives. Verify the app via its ACTUAL listener port, never 8080.
3. Installer (installer.iss) auto-installs WebView2 runtime if missing (common on
   Windows 10) via `DownloadTemporaryFile` + `/silent /install` bootstrapper;
   falls back to browser mode with an explanatory message.
4. Installer requires 64-bit Windows 10+ (`ArchitecturesAllowed=x64compatible`,
   `MinVersion=10.0`).

## Earlier session work (already released)
- File selection: Backup "Only these files" + Wipe "Select files to wipe"
  (rclone `--files-from-raw`), pickers auto-fetch live lsjson from Drive.
- Disconnect account: Dashboard button, `RcloneManager.disconnect()`.
- UI/UX pass per "UI UX Pro Max" skill (cloned read-only at
  `C:\Users\in15\AppData\Local\Temp\opencode\uuux`): responsive drawer,
  4-step journey guide on Dashboard, stats grid, etc.
- **Premium Glassmorphism & Auto-Theming**: Switched from flat design to a premium, layered UI utilizing `prefers-color-scheme` to automatically adapt to Windows Dark/Light mode using Google-inspired colors.
- **Google Photos Integration**: Refactored `rclone_manager` and `config.py` to support `active_service` (`drive` vs `photos`). Google Photos connects correctly, but **API limitations prohibit deleting photos** so the Wipe tab is locked when Photos is active.
- v0.1.27: picker redesign (Name/Folder/Size columns, internal scrolling,
  selection persists across close/reopen).
- Event-loop fix (jobs run off the UI thread).

## Commands
- Build: `& .venv\Scripts\python.exe build.py --bump patch` (from repo root).
  Build log: `build-log.txt` (gitignored). rclone fetched from
  `%APPDATA%\DriveBackup\tools\rclone.exe` at build time (or downloaded once).
- Install silently: `DriveBackup-Setup-X.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`
- UX tests: `& .venv\Scripts\python.exe -m pytest tests\test_ux.py -q -p nicegui.testing.user_plugin -p pytest_asyncio -o main_file=`
  (isolated APPDATA → `%TEMP%\db_ux_appdata`; never touches real app state).
- Smoke test: `& .venv\Scripts\python.exe smoke_test.py` (sections incl. 7 = selective backup, 10 = disconnect).
- Release: `gh release create v0.1.XX "D:\projects\code\DriveBackup\dist\DriveBackup-Setup-0.1.XX.exe" --title "v0.1.XX" --notes "..."` — run from workdir `D:\projects\code\DriveBackup` (gh needs git context). Long timeout; verify with `gh release view v0.1.XX --json assets`.
- `python` on PATH is the hermes venv (no PyInstaller) — always use `.venv\Scripts\python.exe`.

## Key paths
- Repo: `D:\projects\code\DriveBackup` (git, main branch, tags v0.1.XX).
- Install: `%LOCALAPPDATA%\DriveBackup` (version.txt inside `_internal\`).
- App config: `%APPDATA%\DriveBackup\config.json` (remote `gdrive`, ai_api_key — NEVER commit).
- rclone binary/config: `%APPDATA%\DriveBackup\tools\rclone.exe`, `rclone.conf` (preserved across installs).

## Open items / next steps
1. **PipelineChips needs active_remote fix**: `widgets.py → PipelineChips.refresh()` still calls `ctx.config.get("remote")` on line ~175. Update to `ctx.config.active_remote` for consistency.
2. **BackupPage and VerifyPage** also use `ctx.config.get("remote")` — review and update all occurrences to use `ctx.config.active_remote`.
3. (Optional) Custom Google OAuth client_id support — rclone's shared client_id
   is being retired in 2026; add config keys + Settings fields + pass
   `drive_client_id`/`drive_client_secret` to `config create`.
4. (Optional) Polish README.md with install instructions/screenshots for outside users.
5. SmartScreen warning on first install (unsigned exe) — only fix is a paid code-signing cert.
6. wipe_test.py hangs in dev env (test-env artifact, not an app bug).

## Gotchas
- Never probe the app on port 8080 (wslrelay). Use netstat for the DriveBackup process listener.
- gh commands: run with workdir = repo root, or they fail "not a git repository".
- Inno DownloadTemporaryFile signature: (Url, BaseName, SHA256, OnDownloadProgress) — returns Int64, raises on failure.
- Start-Process needs absolute installer path.