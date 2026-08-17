import argparse
import json
import sys
from pathlib import Path

from app.ai import analyzer as ai_analyzer
from app.ai.report import generate_report, save_report
from app.engine import backup as bk
from app.engine import verify as vf
from app.engine import wipe as wp
from app.engine.rclone_manager import manager
from app.utils.config import Config, format_bytes, state_path
from app.utils.logging_utils import get_logger, log, set_console_callback

LOG = get_logger()


def _print_cb(msg, level):
    sys.stderr.write(msg + "\n")


def _cli_connect(cfg, args):
    remote = cfg.get("remote")
    manager.ensure_binary(progress=lambda t: print(t))
    print(f"rclone version: {manager.version()}")
    if manager.remote_exists(remote):
        print(f"Already connected: remote '{remote}' exists.")
        return 0
    print("\n== CONNECTING GOOGLE DRIVE ==")
    print("Open the URL below in your browser, log in with the Google account\n"
          "that owns the Drive, approve access, then paste the code here.\n")
    manager.connect(
        remote, cfg.get("export_formats"),
        auth_cb=lambda url: print("AUTH URL: " + url),
        code_cb=lambda: input("Authorization code: ").strip(),
    )
    print("Connected successfully.")
    return 0


def _cli_inventory(cfg, args):
    remote = cfg.get("remote")
    inv = manager.lsjson(remote)
    total = sum(f.get("Size", 0) for f in inv)
    print(f"{len(inv)} files, {format_bytes(total)} total")
    if args.save:
        state_path("inventory.json").write_text(json.dumps(inv, indent=1),
                                                encoding="utf-8")
        print(f"Inventory saved to {state_path('inventory.json')}")
    return 0


def _cli_backup(cfg, args):
    remote = cfg.get("remote")
    result = bk.backup(remote, args.dir,
                       transfers=int(cfg.get("transfers")),
                       checkers=int(cfg.get("checkers")),
                       line_cb=lambda m: print(m, file=sys.stderr),
                       progress_cb=lambda p, t: None)
    print(f"Backup OK: {result['files']} files, {format_bytes(result['bytes'])}")
    return 0


def _cli_verify(cfg, args):
    result = vf.verify_local(line_cb=lambda m: print(m, file=sys.stderr))
    print(f"VERIFY: {'PASS' if result['passed'] else 'FAIL'} - "
          f"{result['matched']} OK, {result['missing']} missing, "
          f"{result['mismatch']} mismatched, {result['extra']} extra")
    return 0 if result["passed"] else 1


def _cli_deepcheck(cfg, args):
    remote = cfg.get("remote")
    manifest = vf.load_manifest_for_verify()
    if not manifest:
        print("No manifest - run backup first.")
        return 2
    counts = vf.check_remote(remote, manifest["local_dir"],
                             transfers=int(cfg.get("transfers")),
                             checkers=int(cfg.get("checkers")),
                             download=True,
                             line_cb=lambda m: print(m, file=sys.stderr))
    print(f"DEEP CHECK: {counts}")
    return 0 if counts["passed"] else 1


def _cli_analyze(cfg, args):
    a = ai_analyzer.analyze()
    print(f"FILES: {a['count']}  SIZE: {format_bytes(a['size'])}")
    for k, v in sorted(a["categories"].items(), key=lambda kv: -kv[1]["size"]):
        print(f"  {k:<14} {v['count']:>7} files  {format_bytes(v['size']):>12}")
    print(f"DUPLICATES: {a['dup_count']} groups, "
          f"{format_bytes(a['dup_wasted'])} wasted")
    print(f"JUNK: {format_bytes(a['junk_size'])} across "
          f"{len(a['junk'])} categories")
    return 0


def _cli_report(cfg, args):
    analysis = ai_analyzer.analyze()
    verify = vf.load_verify_result() or None
    content = generate_report(None, verify, analysis,
                              ai_analyzer.organization_plan())
    path = save_report(content)
    print(f"Report saved: {path}")
    return 0


def _wipe_command(cfg, args, action):
    remote = cfg.get("remote")
    wp.require_fresh_verification(cfg)
    if args.phrase != "DELETE ALL":
        print("Confirmation phrase must be 'DELETE ALL' (--phrase DELETE ALL).")
        return 2
    if not args.yes:
        print("Add --yes to confirm you have reviewed the safety checks.")
        return 2
    if action == "trash":
        wp.move_to_trash(remote, line_cb=lambda m: print(m, file=sys.stderr))
    elif action == "emptytrash":
        wp.empty_trash(remote, line_cb=lambda m: print(m, file=sys.stderr))
    elif action == "purge":
        wp.purge_forever(remote, line_cb=lambda m: print(m, file=sys.stderr))
    print(f"Done: {action}")
    return 0


def main():
    set_console_callback(_print_cb)
    parser = argparse.ArgumentParser(
        prog="drivebackup", description="Google Drive backup, verify, analyze & wipe")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("connect", help="Authorize Google Drive (browser OAuth)")
    p.set_defaults(fn=_cli_connect)

    p = sub.add_parser("inventory", help="List Drive contents (file count, size)")
    p.add_argument("--save", action="store_true", help="Save inventory.json")
    p.set_defaults(fn=_cli_inventory)

    p = sub.add_parser("backup", help="Back up Drive to a local folder")
    p.add_argument("--dir", required=True)
    p.set_defaults(fn=_cli_backup)

    p = sub.add_parser("verify", help="Verify local backup against manifest")
    p.set_defaults(fn=_cli_verify)

    p = sub.add_parser("deepcheck", help="Re-download & compare against Drive")
    p.set_defaults(fn=_cli_deepcheck)

    p = sub.add_parser("analyze", help="Duplicates, junk, categories")
    p.set_defaults(fn=_cli_analyze)

    p = sub.add_parser("report", help="Generate markdown report")
    p.set_defaults(fn=_cli_report)

    for name, action in (("trash", "trash"),
                         ("emptytrash", "emptytrash"),
                         ("purge", "purge")):
        p = sub.add_parser(name, help=f"Wipe: {name} (safety-gated)")
        p.add_argument("--phrase", required=True)
        p.add_argument("--yes", action="store_true")
        p.set_defaults(fn=lambda cfg, a, _a=action: _wipe_command(cfg, a, _a))

    args = parser.parse_args()
    if not args.command:
        from app.gui.app import run
        run()
        return 0

    cfg = Config()
    try:
        manager.ensure_binary(progress=lambda t: print(t))
    except Exception as exc:
        print(f"Failed to set up rclone: {exc}")
        return 1
    try:
        return args.fn(cfg, args) or 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())