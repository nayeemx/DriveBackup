from .rclone_manager import manager
from .verify import verify_fresh
from ..utils.config import Config
from ..utils.logging_utils import get_logger

LOG = get_logger()


class SafetyGateError(RuntimeError):
    pass


def require_fresh_verification(config: Config):
    ok, message = verify_fresh(hours=config.get("verify_freshness_hours", 24))
    if not ok:
        raise SafetyGateError(
            "WIPE BLOCKED: " + message +
            "\nRun a successful verification first (Verify tab). "
            "This is the safety gate that protects your data."
        )
    return message


def require_confirmation(phrase_typed: str, expected: str = "DELETE ALL"):
    if phrase_typed.strip().upper() != expected:
        raise SafetyGateError(
            f"Confirmation phrase must be exactly '{expected}'. "
            f"Got '{phrase_typed.strip() or '<empty>'}'."
        )


def move_to_trash(remote, line_cb=LOG.info, root=""):
    LOG.warning("WIPE STEP 1: moving ALL Drive files to Trash ...")
    manager.delete_all(remote, use_trash=True, line_cb=line_cb, root=root)
    LOG.info("All files moved to Trash.")


def empty_trash(remote, line_cb=LOG.info):
    LOG.warning("WIPE STEP 2: permanently emptying Trash ...")
    manager.empty_trash(remote, line_cb=line_cb)
    LOG.info("Trash emptied. Drive is now empty.")


def purge_forever(remote, line_cb=LOG.info, root=""):
    LOG.warning("ADVANCED: permanently deleting ALL files (skip Trash) ...")
    manager.delete_all(remote, use_trash=False, line_cb=line_cb, root=root)
    LOG.info("Drive permanently wiped.")