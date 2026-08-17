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
