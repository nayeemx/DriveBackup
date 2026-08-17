"""Build the DriveBackup installer.

Usage:
  python build.py                 # build current version
  python build.py --bump patch    # bump version, then build (patch|minor|major)
  python build.py --skip-package  # only render + compile the installer
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "version.txt"
DIST = ROOT / "dist"
GENERATED_ISS = ROOT / "installer.generated.iss"
RCLONE_URL = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
RCLONE_BUILD = ROOT / "tools" / "rclone.exe"

INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
INNO_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Inno Setup 6"
ISCC = INNO_DIR / "ISCC.exe"


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def write_version(v: str):
    VERSION_FILE.write_text(v, encoding="utf-8")


def bump(part: str):
    major, minor, patch = (int(x) for x in read_version().split("."))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    write_version(f"{major}.{minor}.{patch}")
    print(f"Version bumped to {major}.{minor}.{patch}")


def fetch_rclone():
    """Locate rclone.exe and bundle it into the installer.

    Prefers the copy already installed in %APPDATA%\\DriveBackup\\tools (no
    network needed); falls back to downloading it once. The bundled copy
    lets a fresh machine connect to Google Drive offline.
    """
    if RCLONE_BUILD.exists():
        return
    installed = (Path(os.environ.get("APPDATA", "")) / "DriveBackup"
                 / "tools" / "rclone.exe")
    if installed.exists():
        RCLONE_BUILD.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(installed), str(RCLONE_BUILD))
        print(f">>> rclone ready (copied from installed app): {RCLONE_BUILD}")
        return
    print(">>> Downloading rclone for bundling ...")
    import zipfile
    from app.utils.updater import download
    dest = Path(tempfile.gettempdir()) / "rclone-current-windows-amd64.zip"
    download(RCLONE_URL, dest, progress=lambda m: print("   ", m))
    if dest.read_bytes()[:2] != b"PK":
        raise SystemExit("rclone download is not a valid zip "
                         "- download https://rclone.org/downloads/ manually.")
    with zipfile.ZipFile(dest) as zf:
        entry = next(n for n in zf.namelist() if n.endswith("/rclone.exe"))
        RCLONE_BUILD.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(entry) as src, open(RCLONE_BUILD, "wb") as out:
            out.write(src.read())
    dest.unlink(missing_ok=True)
    print(f">>> rclone ready: {RCLONE_BUILD}")


def build_package():
    fetch_rclone()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "DriveBackup",
        "--collect-all", "nicegui",
        "--collect-all", "pywebview",
        "--add-data", f"version.txt;.",
        "--add-data", f"{RCLONE_BUILD};tools",
        "--splash", "assets/splash.png",
        "main.py",
    ]
    print(">>> PyInstaller ...")
    subprocess.run(cmd, cwd=ROOT, check=True)


def ensure_iscc() -> Path:
    if ISCC.exists():
        return ISCC
    print(">>> Inno Setup not found - downloading installer ...")
    from app.utils.updater import download
    dest = Path(tempfile.gettempdir()) / "inno-setup-installer.exe"
    download(INNO_URL, dest, progress=lambda m: print("   ", m))
    if dest.read_bytes()[:2] != b"MZ":
        raise SystemExit("Inno Setup download is not a valid executable "
                         "- download https://jrsoftware.org/isdl.php manually.")
    print(f">>> Installing Inno Setup to {INNO_DIR} (per-user, no admin) ...")
    subprocess.run(
        [str(dest), "/VERYSILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART",
         f'/DIR="{INNO_DIR}"'],
        check=True,
    )
    dest.unlink(missing_ok=True)
    if not ISCC.exists():
        raise SystemExit("Inno Setup installation failed - install manually.")
    return ISCC


def build_installer(version: str):
    template = (ROOT / "installer.iss").read_text(encoding="utf-8")
    GENERATED_ISS.write_text(
        template.replace("__VERSION__", version), encoding="utf-8")
    iscc = ensure_iscc()
    print(">>> Compiling installer ...")
    subprocess.run([str(iscc), str(GENERATED_ISS)], cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description="Build DriveBackup installer")
    ap.add_argument("--bump", choices=("patch", "minor", "major"), default=None,
                    help="bump version first")
    ap.add_argument("--skip-package", action="store_true",
                    help="skip PyInstaller build (installer only)")
    args = ap.parse_args()

    if args.bump:
        bump(args.bump)
    version = read_version()
    print(f"Building DriveBackup v{version}")

    if not args.skip_package:
        build_package()
    build_installer(version)

    setup = DIST / f"DriveBackup-Setup-{version}.exe"
    size_mb = setup.stat().st_size / (1024 * 1024) if setup.exists() else 0
    print()
    print("=" * 64)
    print(f"OK: {setup}  ({size_mb:.1f} MB)")
    print()
    print("To release an update:")
    print(f"  1. git init / create a GitHub repository")
    print(f"  2. Tag the release 'v{version}' and upload "
          f"DriveBackup-Setup-{version}.exe as an asset")
    print("  3. Users click 'Check for updates' in Settings -> Settings tab")
    print(f"     with owner/repo set -> app updates in place, no reinstall.")
    print("=" * 64)


if __name__ == "__main__":
    main()