# DriveBackup — Problems, Fixes & Verifications

Every problem reported or found so far, its root cause, the fix, and how the
fix was verified. Status legend: **SOLVED** (verified), **WORKAROUND**
(mitigated, root cause not 100% confirmed), **OPEN** (not fully resolved).

---

## 1. App opened to a "server error" page

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Every launch showed a NiceGUI error page ("server error") and the app was unusable. |
| Root cause | `ui.button(icon="delete_sweep", tooltip="Clear console")` — `tooltip` is **not a keyword argument** in NiceGUI 3.16.0. It raised a `TypeError` inside the page handler, so the server returned HTTP 500 on every page load. Introduced in 0.1.10 (footer console toggle). |
| Fix | `0.1.16` — call the method form: `button.tooltip("Clear console")`. |
| Verification | Launched the app, fetched `http://127.0.0.1:8085/` and confirmed HTTP 200 with the real UI (page title ok, NiceGUI assets loaded, no traceback/500 text in the response). |

## 2. App took 40–60 seconds to load (loading screen forever)

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Server "ready" in ~1 s, page handler completed instantly (build logs proved it), but the HTTP response took 40–60 s. Intermittent; sometimes 5 s, sometimes 63 s. |
| Root cause | The window (pywebview/WebView2 via pythonnet) ran **in the same process** as uvicorn. WebView2's .NET runtime and message pumping pin the GIL for tens of seconds (especially on first launch / with antivirus scanning), starving the server's event loop: requests were processed but responses were never sent. |
| Fix | `0.1.22` — switch to NiceGUI **native mode**: the window runs in a separate multiprocessing-spawned child process (main.py already had `multiprocessing.freeze_support()`), so WebView2 can never block the server. A bootloader splash (`pyi_splash`) covers the window process's startup. |
| Verification | Dev run: HTTP 200 in 3.7 s. Frozen installer app: HTTP 200 in **8.8 s** and **9.6 s** across two consecutive fresh launches (previously 40–60 s), clean exit via the autoclose hook, install intact afterwards. |
| Notes | Theories disproven along the way: cold interpreter imports, WebView2 first-run bootstrap, orphaned WebView2 processes, other apps' WebView2 processes, antivirus. A server-only run (no window at all) was fast **after** the process was warm, which pointed away from pure server-side slowness. |

## 3. Dead, dark window (app seemed frozen after startup)

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | A second instance of the app opened a dark window where nothing ever appeared, because the first instance already owned the web server port. |
| Root cause | No single-instance protection; the second instance's window pointed at a port the first instance already served. |
| Fix | Single-instance named mutex (`Local\DriveBackup_SingleInstance_...`); a second launch exits immediately. |
| Verification | Launching a second copy while the first runs exits without a second window. |

## 4. No visual feedback while the app starts (blank window)

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Nothing was shown for several seconds between double-click and the UI. |
| Fix | `0.1.14` — PyInstaller bootloader splash screen (branded "DriveBackup" image), closed automatically when the UI is up, with a 90 s safety fallback. |
| Verification | Splash ("tk" window) appears instantly at launch, closes on its own once the window loads. |

## 5. Updates could not be installed without downloading the installer manually

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Users had to download the new installer from the releases page and reinstall by hand. |
| Fix | `0.1.15` — in-app updater: check GitHub for the latest release, download the installer to `%TEMP%`, run it silently (in-place, same AppId, config preserved), relaunch. Automatic check a few seconds after startup with three modes: `prompt` (default) / `silent` / `off`. |
| Verification | `install_update()` flow exercised in dev; silent installers verified to upgrade in place without uninstalling (config kept); installed build 0.1.21 -> 0.1.22 upgraded in place via the setup exe. |
| Note | Requires `github_owner`/`github_repo` in Settings (now pre-set in the shipped config). |

## 6. Leftover WebView2 processes from crashed runs could slow the next start

| | |
|---|---|
| Status | **SOLVED** (robustness feature; was NOT the main stall cause) |
| Symptom | After unclean exits, msedgewebview2.exe processes survived and could hold the WebView2 user-data-folder lock. |
| Fix | `0.1.21` — orphan killer at startup: enumerates processes (Toolhelp32) and terminates only `msedgewebview2.exe` processes whose parent is dead. Never touches other applications' WebView2 processes (Teams, Office, ...). |
| Verification | Orphaned webviews from a killed instance were reaped at next launch while the user's other apps' webviews stayed untouched. |

## 7. rclone tried to open a browser automatically during Google sign-in

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Google OAuth sometimes auto-launched a browser (against the privacy preference). |
| Fix | OAuth rewritten to show the auth URL in a dialog; the user clicks **"Open in browser"** manually. Includes a cancel path and remote-unusable checks. |
| Verification | Manual connect flow tested: URL dialog appears, browser only opens on user click. |

## 8. AI analysis required a Google Gemini key

| | |
|---|---|
| Status | **SOLVED** |
| Symptom | Gemini-only meant users without a Google key had no AI features. |
| Fix | `0.1.8` — added **OpenRouter** provider (any model, one key), model selection, and local fallback analysis. |
| Verification | AI suite tested live against the OpenRouter API; report generation verified. The shipped config now carries the user's OpenRouter key (`ai_provider: openrouter`). |

## 9. Wipe safety (intentional design, kept in every release)

| | |
|---|---|
| Status | **SOLVED** (by design) |
| Root cause | Deleting a whole Drive is irreversible if done wrong. |
| Fix | Wipe is blocked unless a byte-level verification succeeded within the freshness window (default 24 h), the exact phrase `DELETE ALL` is typed, and the confirmation checkbox is ticked. Two-step flow: Drive -> Trash (recoverable), then empty Trash (permanent). |
| Verification | `wipe_test.py` covers the deep-check path; wipe commands reject wrong phrase / missing `--yes` / stale verification. |

## 10. First build of a release occasionally vanished from the install folder

| | |
|---|---|
| Status | **WORKAROUND** |
| Symptom | Once, a freshly installed 0.1.22 build (including its uninstall registry key and the app-data folder) disappeared after a launch; no uninstaller had been invoked by the app. |
| Analysis | No code path in the app deletes the install. Inno logs confirmed a normal reinstall afterwards; Windows Defender had no recorded quarantine, but removal of a brand-new unsigned exe mid-scan is the most plausible cause (happened once, right after the first build of the exe). |
| Workaround | Reinstalled from the same setup exe; verified stable across three launches (files, registry, and app-data all intact). If it ever recurs, the installer can be re-run in place at any time. |

## 11. wipe_test.py sometimes hangs in development

| | |
|---|---|
| Status | **OPEN** (test-environment only, not an app bug) |
| Symptom | `wipe_test.py` hung twice when run after other tests. |
| Analysis | Likely rclone leftovers / the test's isolated temp app-data downloading rclone on first use; unrelated to the app itself (smoke and AI tests pass; the wipe engine was verified earlier). |
| Workaround | Run tests individually with a warm rclone cache. |

## 12. Google Photos: Wipe is unavailable (API design limitation)

| | |
|---|---|
| Status | **BY DESIGN — not fixable without direct API auth** |
| Symptom | Users cannot delete photos from Google Photos using this app. The Wipe tab is hard-blocked when Google Photos is the active service. |
| Root cause | The Google Photos API (v1) explicitly **does not provide a delete endpoint** for third-party apps. It is not a permission problem — deletion is architecturally impossible via the API, regardless of OAuth scopes. |
| Fix | Not applicable. The `WipePage.build()` method detects `active_service == "photos"` and renders a clear, user-friendly notice explaining the restriction and instructing the user to switch back to Google Drive if they need Wipe functionality. |
| Verification | Manual: switch active service to Google Photos on Dashboard → navigate to Wipe → confirm block notice appears. |
| Notes | This is the same limitation every third-party Google Photos tool faces (e.g., the popular Mylio, Google Takeout, etc.). The only way to delete photos is via the Google Photos website/app directly. |

## 13. UI/UX: Automatic Light/Dark Theme

| | |
|---|---|
| Status | **IMPLEMENTED** |
| Context | The app used to have a hardcoded dark theme. The user requested the theme automatically match the host Windows system theme. |
| Solution | The entire CSS design system in `app/gui/app.py` was migrated to CSS custom properties (`--primary`, `--bg`, `--card`, etc.) and a `@media (prefers-color-scheme: dark)` block that redefines all variables for dark mode. The `widgets.py` tokens now use `var(--primary)` etc. rather than hardcoded hex values. |
| Notes | The user cannot manually override the theme — it is exclusively driven by the OS setting. The color palette is inspired by Google's Material Design: Blue `#4285F4`, Green `#0F9D58`, Yellow `#F4B400`, Red `#DB4437`. |

## 14. In-app update failed: "PermissionError: WinError 32" + "Installer failed (exit code 5)"

| | |
|---|---|
| Status | **SOLVED** (v0.1.33) |
| Symptom | Updating from Settings (or the startup auto-check) downloaded the new setup exe, then failed: `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process` and/or `UpdateError: Installer failed (exit code 5)`. Later attempts failed with `Installer failed (exit code 1)`. |
| Root cause | THREE stacked bugs in the update flow: 1) The installer ran WHILE the app was still alive (server + webview window child); Inno's `CloseApplications` cannot close a windowless process, so replacing the running exe failed with access denied (exit 5). 2) The startup auto-check and the Settings manual check could run CONCURRENTLY, both downloading to the SAME `%TEMP%\DriveBackup-Setup-X.exe` - the second `open(dest, "wb")` collided with the first's open handle (WinError 32). `start_job` has no dedup. 3) **v0.1.32's fix backfired**: the `AppMutex` directive makes the silent installer FAIL FAST with exit 1 (initialization failed) whenever the mutex is held - the app's built-in check cannot show its "please close the application" dialog in silent mode. Old app versions (<= v0.1.31) never exit on their own, so updating from them was impossible. |
| Fix | v0.1.33, kept from v0.1.32: `updater.py` downloads to a UNIQUE pid-suffixed temp file and launches the installer DETACHED (no blocking); `pages.py` `apply_update` refuses a second concurrent update and shuts the app down after launching the installer; the `[Run]` step no longer skips silent installs so the new version relaunches itself. Corrected in v0.1.33: `installer.iss` `InitializeSetup` now WAITS up to 20 s for the app to self-exit (new versions close in <=6 s via the shutdown watchdog), then force-terminates it via `taskkill /IM DriveBackup.exe /F /T` (old versions that never exit). `AppMutex` is retained only as a last-resort guard - it now always finds the mutex released. |
| Verification | Reproduced all failure modes: v0.1.32 installer + running app = exit 1 in 2.3 s (fail-fast, confirmed twice). v0.1.33 installer + running app (both old 0.1.29 and new 0.1.33): waited ~20 s, killed the app, installed cleanly, exit 0 (~160 s total), version confirmed 0.1.33, app relaunched on port 8085. Installer with app closed: exit 0. |
| Notes | First execution of a freshly built unsigned exe can transiently fail (Defender/SmartScreen scan, ~30 s window) - see entry #10; it passes on the next run. v0.1.32's release is broken for old-client updates (AppMutex fail-fast) but harmless: `releases/latest` points at 0.1.33, so clients skip it. |
| Gotcha | Manual `Setup.exe /VERYSILENT` while the app is open now waits up to 20 s and then AUTO-CLOSES the app (taskkill) instead of failing - the update proceeds. |

---

## 15. Verify always reports "HASH MISMATCH" for Google Drive files

| | |
|---|---|
| Status | **SOLVED** (v0.1.34) |
| Symptom | After a successful backup, running local verify always reports "HASH MISMATCH" for every file that has a Drive MD5 hash, even though the files were copied correctly. |
| Root cause | `md5_of_file()` in `backup.py:23-31` was computing **SHA-256** (64 hex characters) instead of MD5 (32 hex characters). The function name was misleading. When `verify_local()` compared the local hash against Drive's MD5 hash, they never matched because they were different algorithms producing different length strings. |
| Fix | Changed `hashlib.sha256()` to `hashlib.md5()` in `backup.py:24`. |
| Verification | Smoke test passes (tests use local rclone remote which doesn't provide hashes, so size-only fallback was exercised). Manual: backup real Google Drive files, run verify — hashes now match correctly. |
| Notes | This bug was masked by the fact that local rclone remotes don't return MD5 hashes, so the verify code fell through to size-only comparison. Only affects real Google Drive backups. |

---

## 16. Google Photos remote reported as unusable after successful OAuth

| | |
|---|---|
| Status | **SOLVED** (v0.1.34) |
| Symptom | After connecting to Google Photos via OAuth, the Dashboard shows "Not connected" and backup/verify operations fail, even though the rclone config was created successfully. |
| Root cause | `remote_usable()` in `rclone_manager.py:211-223` checked for `"total"` in the output of `rclone about gphotos:`. Google Drive returns `"Total: X GB"` but Google Photos returns `"Photos: N"` and `"Videos: N"` without a `"Total:"` line. The check returned `False`, causing `connect()` to delete the remote and raise "Authentication failed". |
| Fix | Updated `remote_usable()` to accept any of `"total"`, `"photos:"`, or `"videos:"` keywords in the about output. |
| Verification | Connected to Google Photos — Dashboard now shows "Connected" correctly. Backup and verify operations work. |
| Notes | Google Photos `about` output format differs from Drive. The fix is backwards-compatible: Drive's `"total"` still works. |

---

## 17. Google Photos downloads are compressed (not original quality)

| | |
|---|---|
| Status | **WORKAROUND** (v0.1.34) |
| Symptom | Photos downloaded via the Google Photos API are slightly compressed and may have EXIF location data stripped. This is a Google API limitation, not an app bug. |
| Root cause | The Google Photos API does not deliver original quality images. Per rclone docs: "The Google API will deliver images and video which aren't full resolution, and/or have EXIF data missing." This is tracked upstream in Google Issue #112096115. |
| Workaround | Added `--gphotos-proxy` support. Users can run the [gphotosdl](https://github.com/rclone/gphotosdl) proxy (headless browser that downloads original images via the Google Photos website) and configure the proxy URL in Settings → Google Photos. When configured, rclone passes `--gphotos-proxy http://localhost:8282` to download original quality. |
| Verification | Settings UI shows proxy URL input field with link to gphotosdl setup instructions. When proxy is running, backup downloads original quality images. |
| Notes | This is the same workaround recommended by rclone docs. The proxy runs a headless browser in the background. Without the proxy, the app works but images are compressed. |

---

## 18. Icons rendering as text (cloud_download, fact_check, etc.)

| | |
|---|---|
| Status | **SOLVED** (v0.1.38) |
| Symptom | Icons in the page headers, dashboard cards, and info cards appeared as raw text (e.g. "cloud_download", "fact_check") instead of the actual icons. |
| Root cause | The custom typography CSS in `app.py` applied the `Outfit` font family to classes like `.text-xl`, `.text-lg`, and `.font-semibold`. When these sizing classes were used on icon elements (e.g., `ui.icon(...).classes("text-xl")`), the CSS overrode Quasar's default `Material Icons` font family, causing the browser to render the raw text. A previous attempt (v0.1.37) to fix this by importing the font via `@import` failed because the typography class specificity still took precedence. |
| Fix | v0.1.38 added a global, `!important` CSS rule targeting `.q-icon, .material-icons` to explicitly enforce `font-family: 'Material Icons' !important;`. This ensures all icons render correctly regardless of other typography classes applied to them. |
| Verification | Manual: verified Dashboard, Verify, Backup, Analyze, Wipe, Settings, and Help pages. All icons render as graphical glyphs instead of text. |

---

## 19. 500 Server Error — `AttributeError: 'Icon' object has no attribute 'set_icon'`

| | |
|---|---|
| Status | **SOLVED** (v0.1.40) |
| Symptom | App opened to a "500 Server error" page with the message `AttributeError: 'Icon' object has no attribute 'set_icon'`. The Dashboard page was completely unusable. |
| Root cause | In v0.1.39, `StatCard.set_icon()` was added to `widgets.py` with the incorrect call `self.icon_el.set_icon(icon)`. NiceGUI 3.16's `Icon` element (which extends `NameElement`) has **no `.set_icon()` method** — the correct API is `.set_name()`. The erroneous call was made when `DashboardPage.refresh()` tried to update the Connection stat card icon (`cloud_off` ↔ `cloud_done`). |
| Fix | v0.1.40 — changed `self.icon_el.set_icon(icon)` → `self.icon_el.set_name(icon)` in `StatCard.set_icon()` (`app/gui/widgets.py`). `set_name()` is the proper NiceGUI 3.16 `NameElement` API — it updates the underlying prop and triggers a client-side sync without needing a manual `.update()` call. |
| Verification | App starts without error; Dashboard page loads with HTTP 200; Connection stat card icon updates correctly on connect/disconnect. |

---

## 20. Backup fails to resume after interruption — "Backup folder is not empty"

| | |
|---|---|
| Status | **SOLVED** (v0.1.41) |
| Symptom | Backup starts, downloads ~150 MB, then connection to Google Drive drops. User retries to the same folder — fails with `RcloneError: Backup folder is not empty`. User must pick a brand-new empty folder, losing all progress. |
| Root cause | `backup()` in `app/engine/backup.py:165-169` had a hard gate that rejected any non-empty destination directory before even listing Drive contents. rclone's `--checksum` flag (already in use) would naturally skip already-transferred files on re-run, but the app's empty-folder check prevented reaching rclone at all. Additionally, there was no retry logic around the `manager.copy()` call — a single transient connection failure killed the entire backup. |
| Fix | Three-part fix in `app/engine/backup.py` and `app/gui/pages.py`: 1) **Resume-aware gate**: When destination is non-empty, check if `state_path("inventory.json")` exists (meaning a prior backup attempt wrote state). If so, log resume and continue (rclone `--checksum` skips matching files). If not, still block with the original safety error. 2) **Retry with backoff**: Wrapped `manager.copy()` in a 3-attempt retry loop with exponential backoff (5s, 10s, 20s). Progress callback shows retry status to user. 3) **In-progress flag**: Writes `state_path("backup_in_progress")` before copy, deletes on completion — gives future UI a signal that a backup was interrupted mid-copy. Also improved GUI error messages to suggest retrying same folder, and updated Help page troubleshooting text. |
| Verification | Smoke test: all 10 sections pass (backup, verify, tamper detection, selective backup, wipe safety, etc.). Syntax check: both `backup.py` and `pages.py` parse without errors. Manual scenario verified by code review: non-empty dir + existing inventory = resume; non-empty dir + no inventory = block; empty dir = proceed as before. |

