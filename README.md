# DriveBackup — AI Google Drive Backup & Wipe

Backs up your entire Google Drive to a location you choose, **verifies every file
byte-for-byte**, then — only after a successful verification — moves your Drive
files to Trash and empties it. AI analysis finds duplicates, junk, and suggests
an organization plan. Works without a credit card or Google Cloud project.

## How it works (safety-first)

```
1. Connect   Google sign-in via your browser (rclone's public client, no Google Cloud needed)
2. Backup    every file/folder copied to your chosen destination
3. Verify    every file checked (size + MD5; Google Docs/Sheets/Slides exported & confirmed)
4. Analyze   (optional) AI report: duplicates, junk files, org plan (free Gemini key optional)
5. Wipe      ONLY after a fresh successful verification:
             - must type "DELETE ALL" and tick the checkbox
             - step 1: all Drive files -> Trash (recoverable)
             - step 2: empty Trash (permanent)
```

Safety gates: **Wipe is blocked** unless a successful verification ran within the
last 24 hours (configurable) *and* you type the exact confirmation phrase.
Only Google Drive is touched — not Gmail, Photos, or anything else.

## Install

Windows, Python 3.10+ (tested on 3.14).

```powershell
cd D:\projects\code\DriveBackup
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python main.py          # desktop app
```

The app opens a **native desktop window** (web-based UI, no browser needed).
If a native window isn't available it falls back to your default browser at
`http://127.0.0.1:8085`. The app downloads rclone (~30 MB) on first use, with
automatic retries.

### Optional: free AI summary (Gemini)

1. Get a free API key: https://aistudio.google.com/apikey (no card needed)
2. Settings tab -> paste key, enable AI analysis

Without a key the app still works — analysis/reports are generated locally.

## Workflow in the app

| Section | What it does |
|---|---|
| Dashboard | Your journey (5 steps with status), connect button, Drive stats |
| Backup | Choose destination, start full backup, live progress |
| Verify | Byte-level check of backup vs Drive (size+MD5, optional deep download check) |
| Analyze | Duplicates/junk/top files table + AI report + organization plan |
| Wipe | Danger zone — safety gates required, 2-step trash flow |
| Settings | Destination, threads, verify freshness window, Gemini key |

The header shows current job status; the bottom console streams every engine
step with color-coded levels (info/warning/error/success). Notifications pop
up for completions and failures.

## CLI (power users)

```powershell
.\.venv\Scripts\python main.py connect          # browser auth
.\.venv\Scripts\python main.py inventory        # list what's in Drive
.\.venv\Scripts\python main.py backup --dir <folder>
.\.venv\Scripts\python main.py verify           # verify backup
.\.venv\Scripts\python main.py deepcheck        # verify + download check
.\.venv\Scripts\python main.py analyze          # duplicates/junk/org plan
.\.venv\Scripts\python main.py report           # generate markdown report
.\.venv\Scripts\python main.py trash --phrase "DELETE ALL" --yes
.\.venv\Scripts\python main.py emptytrash       # permanently empty trash
```

## Where things live

- App config / auth tokens / rclone: `%APPDATA%\DriveBackup\`
- Backups: the destination you chose (default `%USERPROFILE%\DriveBackup_Drive`)
- Reports: `%APPDATA%\DriveBackup\reports\`

## Tests

```powershell
.\.venv\Scripts\python smoke_test.py    # end-to-end pipeline on a fake local drive
.\.venv\Scripts\python wipe_test.py     # deep check + wipe execution
```

## Notes

- Google Docs/Sheets/Slides cannot be downloaded as-is; they are exported
  (docx/xlsx/pptx) and verified by presence + size. All other files are MD5-checked.
- Verification result expires (default 24 h) — re-verify before wiping, on purpose.
- UI stack: NiceGUI (Quasar/Material design) rendered in a native pywebview window.
- This is not affiliated with Google. rclone is used under its MIT license.