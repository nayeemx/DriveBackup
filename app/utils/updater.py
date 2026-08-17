import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .version import APP_VERSION, is_newer

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
USER_AGENT = "DriveBackup-Updater/{}".format(APP_VERSION)
SETUP_PATTERN = re.compile(r"DriveBackup-Setup-(\d+\.\d+\.\d+)\.exe$", re.IGNORECASE)

# Must match DefaultDirName in installer.iss
INSTALL_DIR = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DriveBackup"


class UpdateError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    asset_name: str
    asset_url: str
    size: int = 0
    notes: str = ""


def parse_release(payload: dict, current: str = APP_VERSION):
    """Extract the setup asset from a GitHub 'latest release' payload.

    Returns a ReleaseInfo if a DriveBackup-Setup-<ver>.exe asset exists and
    is newer than `current`; otherwise None.
    """
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "")
    assets = payload.get("assets") or []
    asset = None
    version = ""
    for a in assets:
        name = str(a.get("name") or "")
        m = SETUP_PATTERN.search(name)
        if m:
            asset = a
            version = m.group(1)
            break
    if asset is None:
        return None
    if not version:
        version = tag.lstrip("vV").split("-")[0]
    if not is_newer(version, current):
        return None
    return ReleaseInfo(
        version=version,
        tag=tag,
        asset_name=str(asset.get("name") or ""),
        asset_url=str(asset.get("browser_download_url") or ""),
        size=int(asset.get("size") or 0),
        notes=str(payload.get("body") or "").strip(),
    )


def fetch_latest(owner: str, repo: str, current: str = APP_VERSION,
                 timeout: int = 30):
    """Query the GitHub API for the latest release (raises UpdateError)."""
    import requests
    if not owner or not repo:
        raise UpdateError("GitHub repository not set (Settings).")
    url = GITHUB_API.format(owner=owner.strip(), repo=repo.strip())
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                            timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    if resp.status_code == 404:
        raise UpdateError("No releases found for this repository yet.")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub API error {resp.status_code}.")
    info = parse_release(resp.json(), current)
    if info is None:
        return None
    if not info.asset_url:
        raise UpdateError("Latest release has no installer asset.")
    return info


def download(url: str, dest: Path, progress=None, tries: int = 3,
             timeout: int = 120):
    """Download with retries, mirroring the rclone downloader."""
    import requests
    last = None
    for attempt in range(tries):
        try:
            with requests.get(url, stream=True, timeout=timeout) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        fh.write(chunk)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if progress:
                progress(f"Retrying download ({attempt + 1}/{tries}) ...")
    raise UpdateError(f"Failed to download update: {last}")


def install_silently(setup_path: Path) -> int:
    """Run the Inno Setup installer silently. Replaces files in place.

    The installer keeps the same AppId, so it upgrades the existing
    installation without uninstalling and preserves %APPDATA% config.
    """
    cmd = [str(setup_path), "/VERYSILENT", "/SUPPRESSMSGBOXES",
           "/NORESTART", "/SP-"]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW",
                                          0x08000000)
    proc = subprocess.run(cmd, timeout=1800, stdin=subprocess.DEVNULL,
                          **kwargs)
    return proc.returncode


def launch_installed():
    """Start the freshly installed app (Windows only)."""
    exe = INSTALL_DIR / "DriveBackup.exe"
    if not exe.exists():
        raise UpdateError(f"Installed app not found at {INSTALL_DIR}")
    os.startfile(str(exe))  # noqa: S606 - launching the app we just installed


def check_for_update(owner: str, repo: str):
    """Convenience for the GUI: (ReleaseInfo or None, error or None)."""
    try:
        return fetch_latest(owner, repo), None
    except UpdateError as exc:
        return None, str(exc)