# HANDOFF.md — DriveBackup session resume

If you open a new chat and type **"show"**, the assistant reads this file to
restore context and continue from where the last session ended.

## Project
DriveBackup — Windows desktop app (NiceGUI + pywebview, PyInstaller + Inno Setup).
Public repo: https://github.com/nayeemx/DriveBackup (owner `nayeemx`, repo `DriveBackup`).
App: backup / verify / wipe files on your own Google Drive; per-file selection,
disconnect account, AI analysis report (OpenRouter key optional).

## Current state (last session ended)
- **Latest released version: v0.1.34** — live on GitHub
  https://github.com/nayeemx/DriveBackup/releases/tag/v0.1.34
- v0.1.34 fixes verify hash mismatch, Google Photos remote detection, and adds
  gphotosdl proxy support for original quality Google Photos downloads.
- v0.1.33 fixes the in-app updater end-to-end (PROBLEMS.md #14).
- **Installed app on this machine: v0.1.33** (will be upgraded by end-to-end verification).
- Repo is PUBLIC — other people can download and install the app.

## Session work (v0.1.34 — DONE, RELEASED)
- **Bug fix: Verify hash mismatch** (PROBLEMS.md #15):
  `md5_of_file()` in `backup.py:23-31` was computing SHA-256 (64 hex chars)
  instead of MD5 (32 hex chars). Local verify always reported "HASH MISMATCH"
  for files with Drive MD5 hashes. Fixed by changing `hashlib.sha256()` to
  `hashlib.md5()`.
- **Bug fix: Google Photos remote_usable()** (PROBLEMS.md #16):
  `remote_usable()` in `rclone_manager.py:211-226` checked for `"total"` in
  `rclone about` output, but Google Photos returns `"Photos:"` / `"Videos:"`
  without a `"Total:"` line. Fixed by accepting any of `"total"`, `"photos:"`,
  or `"videos:"` keywords.
- **Feature: gphotosdl proxy for original quality Google Photos** (PROBLEMS.md #17):
  Google Photos API delivers compressed images by default. Added `--gphotos-proxy`
  support via the gphotosdl headless browser proxy. Config key `gphotos_proxy`
  in config.py, passed to rclone copy/check commands. Settings UI card added
  with proxy URL input and link to gphotosdl setup instructions.

### Files changed in v0.1.34
- `app/engine/backup.py` — fixed `md5_of_file()` hash algorithm, added `gphotos_proxy` param
- `app/engine/verify.py` — added `gphotos_proxy` param to `check_remote()`
- `app/engine/rclone_manager.py` — fixed `remote_usable()`, added `gphotos_proxy` to `copy()`/`check()`
- `app/utils/config.py` — added `gphotos_proxy` default
- `app/gui/pages.py` — added Google Photos proxy settings card, passed proxy to backup/verify calls

## Session work (v0.1.30 / v0.1.31 — DONE)
- v0.1.30 built locally (dist/DriveBackup-Setup-0.1.30.exe, 39.8 MB) — NOT released separately:
  - Auto Light/Dark theme (prefers-color-scheme, Google Material palette), see PROBLEMS.md #13.
  - Google Photos integration (active_service in config.py, Dashboard selector, Wipe hard-block).
- **v0.1.31 (RELEASED)**: fixed `ctx.config.get("remote")` -> `ctx.config.active_remote`
  in ALL live call sites (pages.py lines 458/529/582/777/1196/1263). On fresh
  installs `get("remote")` returned None and blocked Backup/Verify/Wipe after connecting.
  `tabs.py` is DEAD legacy code (customtkinter, imported nowhere) — left untouched.

## Session work (v0.1.32 / v0.1.33 — DONE, v0.1.33 RELEASED)
- User's installed v0.1.29 failed to update: "PermissionError: WinError 32" + exit 5, then exit 1.
  Full story + fix in PROBLEMS.md #14. Three stacked bugs:
  1. Installer ran while app alive -> exit 5 (access denied replacing running exe).
  2. Auto-check + manual check downloaded concurrently to the SAME %TEMP% file -> WinError 32.
  3. v0.1.32's AppMutex directive FAILS FAST (exit 1, ~2 s) in silent mode whenever the app
     holds the mutex - old app versions never exit on their own, so updates from <=0.1.31 were impossible.
- **FINAL FIX (v0.1.33)**: installer.iss `InitializeSetup` waits up to 20 s for the app to
  self-exit (new versions: <=6 s watchdog), then `taskkill /IM DriveBackup.exe /F /T` (old
  versions). AppMutex kept only as last-resort guard. Plus the v0.1.32 changes kept: detached
  installer launch, unique pid-suffixed temp file, concurrent-update guard, [Run] relaunch
  (no skipifsilent).
- **VERIFIED END-TO-END on this machine**: app running + v0.1.33 installer -> ~20 s wait ->
  app force-closed -> clean install (exit 0, ~160 s) -> version 0.1.33 installed; app relaunch
  verified on port 8085. Machine is now ON v0.1.33 (upgraded by the test itself).
- v0.1.33 live at https://github.com/nayeemx/DriveBackup/releases/tag/v0.1.33
- GOTCHA: manual `Setup.exe /VERYSILENT` with app open now waits <=20 s then AUTO-CLOSES the app.
- Known transient: FIRST execution of a freshly built unsigned exe can fail once (Defender scan,
  ~30 s) - PROBLEMS.md #10 precedent; next run is clean.

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
1. (Optional) Custom Google OAuth client_id support — rclone's shared client_id
   is being retired in 2026; add config keys + Settings fields + pass
   `drive_client_id`/`drive_client_secret` to `config create`.
2. (Optional) Polish README.md with install instructions/screenshots for outside users.
3. SmartScreen warning on first install (unsigned exe) — only fix is a paid code-signing cert.
4. wipe_test.py hangs in dev env (test-env artifact, not an app bug).
5. Optionally delete dead `app/gui/tabs.py` (customtkinter legacy, imported nowhere).
6. Commit + push the v0.1.31..v0.1.33 changes (pages.py, updater.py, installer.iss,
   HANDOFF.md, PROBLEMS.md) — repo is clean except these.
7. (Optional) Test the IN-APP update flow once more when a newer release exists:
   Settings -> Check for updates from the running v0.1.33 app (the installer-side
   was verified; the app-side self-exit after launching the installer was code-reviewed).

## Gotchas
- Never probe the app on port 8080 (wslrelay). Use netstat for the DriveBackup process listener.
- gh commands: run with workdir = repo root, or they fail "not a git repository".
- Inno DownloadTemporaryFile signature: (Url, BaseName, SHA256, OnDownloadProgress) — returns Int64, raises on failure.
- Start-Process needs absolute installer path.