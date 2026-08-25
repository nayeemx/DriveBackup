import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from ..utils.config import APP_DIR
from ..utils.logging_utils import get_logger

TOOLS_DIR: Path = APP_DIR / "tools"
RCLONE_EXE: Path = TOOLS_DIR / "rclone.exe"
RCLONE_URL: str = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
LOG = get_logger()


def _bundled_binary() -> Optional[Path]:
    """rclone.exe shipped inside the installer (PyInstaller onedir/_MEIPASS).

    Returns a path to the bundled binary, or None if the app was not
    installed with one (e.g. dev checkout).
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "tools" / "rclone.exe")
    candidates.append(Path(sys.executable).parent / "tools" / "rclone.exe")
    for c in candidates:
        if c.exists():
            return c
    return None


def _no_window_kwargs() -> dict[str, int]:
    """Keep console-subsystem children (rclone) from flashing a terminal.

    A GUI app (no console) spawning a console exe without this flag makes
    Windows create a visible console window for the child.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW",
                                         0x08000000)}
    return {}


class RcloneError(RuntimeError):
    pass


class RcloneManager:
    def __init__(self, exe_path: Optional[Union[str, Path]] = None) -> None:
        self.exe: Optional[Path] = Path(exe_path) if exe_path else self._find_binary()
        self._token_path: Path = APP_DIR / "rclone.conf"

    # ---------------------------------------------------------------- binary
    def _find_binary(self) -> Optional[Path]:
        for candidate in (RCLONE_EXE,):
            if candidate.exists():
                return candidate
        found = shutil.which("rclone")
        if found:
            return Path(found)
        return None

    def ensure_binary(self, progress: Optional[Callable[[str], None]] = None) -> Path:
        if self.exe and self.exe.exists():
            return self.exe
        bundled = _bundled_binary()
        if bundled:
            TOOLS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(bundled), str(RCLONE_EXE))
            self.exe = RCLONE_EXE
            LOG.info(f"rclone bundled with app - copied to {RCLONE_EXE}")
            return self.exe
        LOG.info("rclone not found - downloading ...")
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = TOOLS_DIR / "rclone.zip"
        if progress:
            progress("Downloading rclone (~30 MB) ...")
        self._download(RCLONE_URL, zip_path, progress)
        if progress:
            progress("Extracting rclone ...")
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                target = (TOOLS_DIR / info.filename).resolve()
                if not str(target).startswith(str(TOOLS_DIR.resolve())):
                    raise RcloneError(f"Zip entry attempts path traversal: {info.filename}")
            zf.extractall(TOOLS_DIR)
        zip_path.unlink()
        matches = list(TOOLS_DIR.glob("rclone-*-windows-amd64/rclone.exe"))
        if not matches:
            raise RcloneError("rclone.zip did not contain the expected executable")
        extracted = matches[0]
        shutil.move(str(extracted), str(RCLONE_EXE))
        shutil.rmtree(extracted.parent, ignore_errors=True)
        self.exe = RCLONE_EXE
        LOG.info(f"rclone installed at {RCLONE_EXE}")
        return self.exe

    def _download(self, url: str, dest: Path,
                  progress: Optional[Callable[[str], None]] = None,
                  tries: int = 3, timeout: int = 120) -> None:
        import requests
        last: Optional[Exception] = None
        for attempt in range(tries):
            try:
                with requests.get(url, stream=True, timeout=timeout) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            fh.write(chunk)
                return
            except (requests.RequestException, OSError) as exc:
                last = exc
                LOG.warning(f"Download failed (attempt {attempt + 1}): {exc}")
                if progress:
                    progress(f"Retrying download ({attempt + 1}/{tries}) ...")
        raise RcloneError(f"Failed to download rclone: {last}")

    def version(self) -> str:
        out = self.run(["version"], capture=True, log_output=False)
        return out.strip().splitlines()[0] if out else "unknown"

    # ------------------------------------------------------------------ runner
    def run(self, args: list[str], capture: bool = False,
            stdin_data: Optional[str] = None, log_output: bool = True,
            timeout: int = 7200,
            cwd: Optional[Union[str, Path]] = None) -> str:
        if not self.exe or not self.exe.exists():
            self.ensure_binary()
        cmd = [str(self.exe), "--config", str(self._token_path)] + args
        LOG.debug(f"rclone: {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_data,
                stdin=None if stdin_data is not None else subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
                **_no_window_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RcloneError(f"rclone timed out: {' '.join(args[:2])}") from exc
        stdout: str = proc.stdout or ""
        stderr: str = proc.stderr or ""
        if log_output:
            for line in stdout.splitlines():
                LOG.info(line)
            for line in stderr.splitlines():
                if line.startswith("NOTICE"):
                    continue
                level = "ERROR" if line.strip().startswith("ERROR") else "INFO"
                getattr(LOG, level.lower())(line)
        if capture:
            return stdout.strip()
        if proc.returncode != 0:
            raise RcloneError(stderr.strip() or f"rclone exited {proc.returncode}")
        return stdout.strip()

    def stream(self, args: list[str], line_cb: Callable[[str], None],
               timeout: int = 7200) -> bool:
        if not self.exe or not self.exe.exists():
            self.ensure_binary()
        cmd = [str(self.exe), "--config", str(self._token_path)] + args
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        )
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    line_cb(line)
        finally:
            try:
                proc.stdout.close()
            except (AttributeError, OSError):
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise RcloneError("rclone process timed out")
        if proc.returncode != 0:
            raise RcloneError(f"rclone exited with code {proc.returncode}")
        return True

    # ------------------------------------------------------------------ remote
    def listremotes(self) -> list[str]:
        out = self.run(["listremotes"], capture=True)
        return [r for r in out.splitlines() if r]

    def remote_exists(self, name: str) -> bool:
        return f"{name}:" in self.listremotes()

    def remote_usable(self, name: str) -> bool:
        """True if the remote actually works (has a valid token).

        Requires real 'about' output - an empty or missing remote makes
        rclone return exit 0 with no output, which must NOT count as usable.
        Google Drive returns 'Total:'; Google Photos returns 'Photos:'/'Videos:'.
        """
        try:
            out = self.run(["about", f"{name}:"], capture=True, timeout=60,
                           log_output=False)
            if not out:
                return False
            lower = out.lower()
            # Drive: "Total:", "Used:", "Free:"
            # Google Photos: "Photos:", "Videos:", "Albums:"
            return any(kw in lower for kw in ("total", "photos:", "videos:"))
        except RcloneError:
            return False

    def disconnect(self, remote: str,
                   line_cb: Callable[[str], None] = LOG.info) -> bool:
        """Revoke the token and remove the remote from rclone's config.

        The account is fully disconnected: the stored token is deleted, so
        the next Connect starts a fresh OAuth sign-in (pick another account).
        """
        if not self.remote_exists(remote):
            line_cb(f"{remote}: nothing to disconnect")
            return True
        try:
            self.run(["config", "disconnect", f"{remote}:"], capture=True,
                     log_output=False)
        except RcloneError:
            pass
        self.run(["config", "delete", remote], capture=True, log_output=False)
        return True

    def connect(self, remote: str, backend_type: str,
                export_formats: Optional[str],
                auth_cb: Optional[Callable[[str, threading.Event], None]],
                code_cb: Optional[Callable[[], Optional[str]]]) -> bool:
        if self.remote_exists(remote) and self.remote_usable(remote):
            return True
        if self.remote_exists(remote):
            LOG.warning("Existing remote has no working token - reconnecting ...")
            try:
                self.run(["config", "delete", remote], log_output=False)
            except RcloneError:
                pass
            LOG.info("No remote configured - starting OAuth connection ...")
        args = [
            "config", "create", remote, backend_type,
            "config_is_local=true",
            "--non-interactive=false",
        ]
        if backend_type == "drive":
            args.append(f"drive_export_formats={export_formats}")
        elif backend_type == "google photos":
            args.append("read_only=false")
        proc = subprocess.Popen(
            [str(self.exe), "--config", str(self._token_path)] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        )
        url: Optional[str] = None
        code_sent: bool = False
        cancel_event = threading.Event()

        def write_line(text: str) -> None:
            try:
                proc.stdin.write(text + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

        def read_output() -> None:
            nonlocal url, code_sent
            buffer = ""
            while True:
                if cancel_event.is_set():
                    proc.terminate()
                    return
                chunk = proc.stdout.read(1)
                if not chunk:
                    break
                buffer += chunk
                if not url:
                    m = re.search(
                        r"https?://(?:accounts\.google\.com|127\.0\.0\.1:53682)[^\s]*",
                        buffer)
                    if m:
                        url = m.group(0)
                        if auth_cb:
                            auth_cb(url, cancel_event)
                is_code_prompt = ("verification code" in buffer.lower()
                                  or "authorization code" in buffer.lower()
                                  or "paste it here" in buffer.lower())
                tail = buffer[-60:].rstrip("\r\n")
                is_prompt = tail.endswith("> ") or "(y/n)" in tail.lower()
                if is_code_prompt and not code_sent:
                    code_sent = True
                    code = code_cb() if code_cb else None
                    if code:
                        write_line(code)
                    else:
                        proc.terminate()
                elif is_prompt and not code_sent:
                    # Answer "n" to auto-config: rclone must NOT open the
                    # browser itself - the user opens the URL from the app
                    # dialog (privacy: never launch a browser unasked).
                    write_line("n" if "use auto config" in tail.lower()
                               else "")
                while "\n" in buffer:
                    line, _, buffer = buffer.partition("\n")
                    LOG.info(line.rstrip("\r"))

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        proc.wait()
        reader.join(timeout=10)
        ok = proc.returncode == 0 and self.remote_usable(remote)
        if not ok and self.remote_exists(remote):
            try:
                self.run(["config", "delete", remote], log_output=False)
            except RcloneError:
                pass
        if proc.returncode != 0:
            raise RcloneError(f"rclone config failed (code {proc.returncode})")
        if not ok:
            raise RcloneError("Authentication failed - no working token "
                              "(did you approve access in the browser?)")
        LOG.info(f"Connected: {remote} configured successfully")
        return True

    # ---------------------------------------------------------------- commands
    def about(self, remote: str) -> dict[str, str]:
        out = self.run(["about", f"{remote}:"], capture=True)
        parsed: dict[str, str] = {}
        for line in out.splitlines():
            key, _, value = line.partition(":")
            if key.strip():
                parsed[key.strip().lower()] = value.strip()
        return parsed

    def about_cached(self, remote: str, ttl: int = 60) -> dict[str, str]:
        """about() with a short TTL cache.

        The UI polls stats regularly; hitting the network (and Google's
        rate limits) every page build makes rclone about take 3-5s, which
        must never block the event loop.
        """
        import time
        cache: dict[str, tuple[dict[str, str], float]] = getattr(self, "_about_cache", {})
        lock = getattr(self, "_about_cache_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._about_cache_lock = lock
        with lock:
            cached, ts = cache.get(remote, (None, 0))
        now = time.time()
        if cached is not None and now - ts < ttl:
            return cached
        try:
            result = self.about(remote)
        except RcloneError:
            if cached is not None:
                return cached
            raise
        with lock:
            self._about_cache = {**cache, remote: (result, now)}
        return result

    def lsjson(self, remote: str, root: str = "",
               trashed: bool = False) -> list[dict[str, Any]]:
        args = ["lsjson", "--recursive", "--files-only", "--hash",
                "--fast-list", "-M"]
        if trashed:
            args.append("--drive-trashed-only")
        args.append(f"{remote}:{root}")
        out = self.run(args, capture=True)
        if not out:
            return []
        try:
            start = out.index("[")
            return json.loads(out[start:])
        except (ValueError, json.JSONDecodeError) as exc:
            raise RcloneError(f"Failed to parse lsjson output: {exc}") from exc

    def copy(self, remote: str, local_dir: Union[str, Path],
             transfers: int, checkers: int,
             line_cb: Callable[[str], None], root: str = "",
             extra_args: Optional[list[str]] = None,
             gphotos_proxy: str = "") -> bool:
        args = [
            "copy", f"{remote}:{root}", str(local_dir),
            "--create-empty-src-dirs",
            "--checksum",
            "--fast-list",
            "--transfers", str(transfers),
            "--checkers", str(checkers),
            "--stats", "2s",
            "--stats-one-line",
            "--stats-log-level", "NOTICE",
            "-v",
        ]
        if gphotos_proxy:
            args += ["--gphotos-proxy", gphotos_proxy]
        if extra_args:
            args += list(extra_args)
        return self.stream(args, line_cb)

    def check(self, remote: str, local_dir: Union[str, Path],
              transfers: int, checkers: int, download: bool,
              line_cb: Callable[[str], None], root: str = "",
              gphotos_proxy: str = "") -> bool:
        args = [
            "check", f"{remote}:{root}", str(local_dir),
            "--fast-list",
            "--transfers", str(transfers),
            "--checkers", str(checkers),
            "-v",
        ]
        if download:
            args.append("--download")
        if gphotos_proxy:
            args += ["--gphotos-proxy", gphotos_proxy]
        return self.stream(args, line_cb)

    def backend_type(self, remote: str) -> str:
        out = self.run(["config", "show", remote, "--json"], capture=True,
                       log_output=False)
        try:
            return json.loads(out).get("type", "")
        except (ValueError, json.JSONDecodeError):
            return ""

    def delete_all(self, remote: str, use_trash: bool,
                   line_cb: Callable[[str], None], root: str = "") -> bool:
        args = [
            "delete", f"{remote}:{root}",
            "--fast-list",
            "-v",
        ]
        if use_trash and self.backend_type(remote) == "drive":
            args.append("--drive-use-trash")
        return self.stream(args, line_cb)

    def delete_files(self, remote: str, files: list[str], use_trash: bool,
                     line_cb: Callable[[str], None],
                     root: str = "") -> bool:
        """Delete exactly the listed files (relative paths, one per line).

        Uses rclone's --files-from-raw so paths are taken literally -
        no globbing, no accidental matches.
        """
        if not files:
            return True
        tmp: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".txt", delete=False,
                    encoding="utf-8", newline="\n") as fh:
                for p in files:
                    fh.write(str(p).replace("\\", "/") + "\n")
                tmp = fh.name
            args = [
                "delete", f"{remote}:{root}",
                "--files-from-raw", tmp,
                "--fast-list",
                "-v",
            ]
            if use_trash and self.backend_type(remote) == "drive":
                args.append("--drive-use-trash")
            return self.stream(args, line_cb)
        finally:
            if tmp:
                import time
                for _ in range(10):
                    try:
                        os.unlink(tmp)
                        break
                    except OSError:
                        time.sleep(0.2)
                else:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        LOG.warning(f"Could not remove temp file: {tmp}")

    def empty_trash(self, remote: str,
                    line_cb: Callable[[str], None]) -> bool:
        if self.backend_type(remote) != "drive":
            LOG.info(f"{remote}: no trash support - nothing to empty")
            return True
        return self.stream(["cleanup", f"{remote}:"], line_cb)


manager = RcloneManager()
