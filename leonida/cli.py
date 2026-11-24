"""`leonida` command line: detect, get, check, install, rollback, uninstall, online-safe, keys."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import PACK_NAME, __version__
from .checks import ERROR, INFO, WARNING, has_errors, hotkey_map
from .detect import check_prerequisites, detect_games, detect_gpus, find_7zip, find_exe, is_rtx50
from .installer import Installer, InstallError
from .manifest import ManifestError
from .matcher import build_lock, read_lock, verify_lock, write_lock
from .onlinesafe import OnlineSafeError, go_online_safe, restore_mods
from .onlinesafe import status as online_status
from .paths import LOCK_NAME
from .session import Session

# --------------------------------------------------------------------------- UI
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


class ConsoleUI:
    def __init__(self, assume_yes: bool = False, pause: bool = True):
        self.assume_yes = assume_yes
        self.pause = pause

    def info(self, msg: str) -> None:
        print(msg)

    def warn(self, msg: str) -> None:
        print(_c("33", "! " + msg))

    def confirm(self, msg: str, default: bool = True) -> bool:
        if self.assume_yes:
            return True
        hint = "[Y/n]" if default else "[y/N]"
        try:
            ans = input(f"{msg} {hint} ").strip().lower()
        except EOFError:
            return default
        return default if not ans else ans.startswith("y")

    def wait_done(self, title: str, steps: list[str], folder: Path | None) -> bool:
        print(_c("1", f"\n== Manual step: {title} =="))
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s}")
        if folder:
            print(f"  Files: {folder}")
            self.open_path(folder)
        if self.assume_yes:
            return True
        try:
            ans = input("Type 'done' when finished (or 'cancel'): ").strip().lower()
        except EOFError:
            return False
        return ans in ("done", "d", "y", "yes")

    def launch(self, path: Path) -> None:
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", str(path)], check=False, cwd=str(path.parent))
        else:
            self.warn(f"Run this on Windows: {path}")

    @staticmethod
    def open_path(path: Path) -> None:
        if os.environ.get("LEONIDA_NO_OPEN"):
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError:
            pass


# --------------------------------------------------------------------- context
class Ctx(Session):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args.state_dir, args.manifest_dir, args.download_dir, args.game_dir)
        self.args = args

    @property
    def profile_id(self) -> str:
        return getattr(self.args, "profile", None) or super().profile_id


def _level(level: str) -> str:
    return {ERROR: _c("31", "ERROR  "), WARNING: _c("33", "WARNING"), INFO: _c("36", "info   ")}[level]


# -------------------------------------------------------------------- commands
def cmd_detect(ctx: Ctx) -> int:
    extra = [Path(ctx.args.set)] if ctx.args.set else []
    games = detect_games(ctx.manifest.exe_names, extra)
    if ctx.args.set:
        exe = find_exe(Path(ctx.args.set), ctx.manifest.exe_names)
        if not exe:
            print(f"No {' / '.join(ctx.manifest.exe_names)} in {ctx.args.set}")
            return 1
        ctx.config.game_dir = str(Path(ctx.args.set))
        ctx.save()
        print(f"Game folder set: {ctx.config.game_dir}")
        return 0
    if not games:
        print("GTA V Enhanced not found automatically. Set it with:\n  leonida detect --set \"D:\\path\\to\\GTA V Enhanced\"")
        return 1
    for i, g in enumerate(games, 1):
        print(f"{i}. {g.path}  [{g.source}]  version {g.version or 'unknown'}")
    if not ctx.config.game_dir:
        ctx.config.game_dir = str(games[0].path)
        ctx.save()
        print(f"Using: {ctx.config.game_dir}")
    else:
        print(f"Current setting: {ctx.config.game_dir}")
    return 0


def cmd_profiles(ctx: Ctx) -> int:
    for p in ctx.manifest.profiles.values():
        mark = "*" if p.id == ctx.profile_id else " "
        print(_c("1", f"{mark} {p.id}  {p.name}"))
        print(f"    {p.description}")
        print("    " + ", ".join(m.name for m in ctx.manifest.resolve(p.id)))
    if getattr(ctx.args, "use", None):
        ctx.manifest.profile(ctx.args.use)
        ctx.config.profile = ctx.args.use
        ctx.save()
        print(f"\nProfile set: {ctx.args.use}")
    return 0


def _print_checklist(ctx: Ctx, mods, result) -> None:
    for m in mods:
        f = result.matched.get(m.id)
        mark = _c("32", "[x]") if f else "[ ]"
        print(f"{mark} {m.order:>2}. {m.name:<55} {f.name if f else m.page}")
    for f, ids in result.ambiguous.items():
        print(_c("33", f"?? {f.name} could be: {', '.join(ids)} -> leonida assign \"{f.name}\" <mod>"))
    for mid, extra in result.duplicates.items():
        print(_c("33", f"!! {mid}: using newest file, ignoring {', '.join(p.name for p in extra)}"))


def cmd_get(ctx: Ctx) -> int:
    mods = ctx.mods()
    folder = ctx.config.downloads()
    folder.mkdir(parents=True, exist_ok=True)
    print(f"{PACK_NAME} - profile '{ctx.profile_id}' - save every download into:\n  {folder}\n")
    result = ctx.matches(mods)
    missing = result.missing(mods)
    if ctx.args.open and missing and not os.environ.get("LEONIDA_NO_OPEN"):
        print(f"Opening {len(missing)} download page(s) in your browser...")
        for m in missing:
            webbrowser.open_new_tab(m.page)
            time.sleep(0.4)
    _print_checklist(ctx, mods, result)
    if ctx.args.watch:
        print("\nWatching the folder (Ctrl+C to stop)...")
        try:
            while missing:
                time.sleep(3)
                new = ctx.matches(mods)
                newly = set(new.matched) - set(result.matched)
                for mid in sorted(newly, key=lambda i: ctx.manifest.mod(i).order):
                    print(_c("32", f"  got {ctx.manifest.mod(mid).name}: {new.matched[mid].name}"))
                result, missing = new, new.missing(mods)
        except KeyboardInterrupt:
            print()
    if not missing:
        lock = build_lock(ctx.manifest.pack, ctx.manifest.version, result.matched)
        write_lock(ctx.state / LOCK_NAME, lock)
        print(_c("32", f"\nAll {len(mods)} files present. Lockfile written: {ctx.state / LOCK_NAME}"))
        return 0
    print(f"\n{len(missing)} still missing.")
    return 2


def cmd_assign(ctx: Ctx) -> int:
    ctx.manifest.mod(ctx.args.mod)
    ctx.config.assignments[Path(ctx.args.file).name] = ctx.args.mod
    ctx.save()
    print(f"{Path(ctx.args.file).name} -> {ctx.args.mod}")
    return 0


def cmd_check(ctx: Ctx) -> int:
    findings = ctx.findings()
    for f in findings:
        print(f"{_level(f.level)} {f.message}")
    if not findings:
        print(_c("32", "All checks passed."))
    return 1 if has_errors(findings) else 0


def cmd_install(ctx: Ctx) -> int:
    a = ctx.args
    game = ctx.game_dir()
    if not game:
        print("Set the game folder first: leonida detect")
        return 1
    mods = ctx.mods()
    if a.only:
        mods = [ctx.manifest.mod(i) for i in a.only]
    findings = ctx.findings(mods)
    for f in findings:
        if f.level != INFO:
            print(f"{_level(f.level)} {f.message}")
    if has_errors(findings) and not a.force and not a.dry_run:
        print("Fix the errors above (or use --force).")
        return 1
    result = ctx.matches(mods)
    done = ctx.log.installed_mods()
    todo = [m for m in mods if m.id not in done]
    if not todo:
        print("Everything in this profile is already installed.")
        return 0
    lacking = [m for m in todo if m.id not in result.matched]
    if lacking and not a.dry_run:
        print("Missing downloads: " + ", ".join(m.name for m in lacking) + "\nRun: leonida get")
        return 2
    lock = read_lock(ctx.state / LOCK_NAME)
    if lock:
        for p in verify_lock(lock, result.matched):
            print(_c("33", "! " + p))
    ui = ConsoleUI(assume_yes=a.yes, pause=not a.no_pause)
    inst = Installer(ctx.manifest, game, ctx.state, ctx.log, ui, seven_zip=find_7zip(), dry_run=a.dry_run)
    for m in todo:
        print(_c("1", f"\n--- {m.order}. {m.name} ---"))
        try:
            step = inst.install(m, result.matched.get(m.id))
        except InstallError as exc:
            print(_c("31", f"Stopped: {exc}"))
            return 1
        if step is None:
            continue
        print(_c("32", f"Step {step.id} done: {len(step.actions)} file change(s) logged."))
        if not a.no_pause and not a.yes:
            while True:
                try:
                    ans = input("Test now: launch story mode, drive a minute. "
                                "[c]ontinue / [u]ndo this step / [q]uit: ").strip().lower()
                except EOFError:
                    ans = "q"
                if ans in ("c", ""):
                    break
                if ans == "u":
                    for w in inst.rollback(step.id):
                        ui.warn(w)
                    print("Step undone.")
                    return 0
                if ans == "q":
                    return 0
    print(_c("32", "\nProfile installed." if not a.dry_run else "\nDry run finished: nothing was written."))
    return 0


def cmd_status(ctx: Ctx) -> int:
    print(f"{PACK_NAME} {__version__}   manifest {ctx.manifest.version}")
    print(f"State folder:    {ctx.state}")
    print(f"Game folder:     {ctx.config.game_dir or '(not set)'}")
    print(f"Download folder: {ctx.config.downloads()}")
    print(f"Profile:         {ctx.profile_id}")
    game = ctx.game_dir()
    if game and game.is_dir():
        print(f"Mods state:      {online_status(game, ctx.manifest.online_safe_items)}")
    steps = ctx.log.steps
    if steps:
        print("\nSteps:")
        for s in steps:
            print(f"  {s.id:>3}  {s.status:<12} {s.mod:<20} {len(s.actions)} change(s)")
    return 0


def _installer(ctx: Ctx, dry_run: bool = False) -> Installer:
    if not ctx.game_dir():
        raise SystemExit("Set the game folder first: leonida detect")
    return ctx.installer(ConsoleUI(), dry_run=dry_run)


def cmd_rollback(ctx: Ctx) -> int:
    inst = _installer(ctx, ctx.args.dry_run)
    step_id = ctx.args.step
    if step_id is None:
        last = ctx.log.last_active()
        if not last:
            print("Nothing to roll back.")
            return 0
        step_id = last.id
    try:
        warnings = inst.rollback(step_id)
    except (InstallError, KeyError) as exc:
        print(exc)
        return 1
    for w in warnings:
        print(_c("33", "! " + w))
    print(f"Step {step_id} rolled back.")
    return 0


def cmd_uninstall(ctx: Ctx) -> int:
    if not ctx.args.yes and not ConsoleUI().confirm("Undo every Leonida V step?", default=False):
        return 1
    inst = _installer(ctx, ctx.args.dry_run)
    warnings, residual = inst.uninstall()
    for w in warnings:
        print(_c("33", "! " + w))
    if residual is None:
        print("No baseline snapshot; nothing to compare.")
    elif residual.empty:
        print(_c("32", "Game folder matches the pre-install snapshot."))
    else:
        print(_c("33", f"Differences from the pre-install snapshot: {residual.summary()}"))
        for p in residual.added[:20]:
            print(f"  + {p}")
        for p in residual.changed[:20]:
            print(f"  ~ {p}")
        for p in residual.removed[:20]:
            print(f"  - {p}")
    return 0


def cmd_online_safe(ctx: Ctx) -> int:
    game = ctx.game_dir()
    if not game:
        print("Set the game folder first: leonida detect")
        return 1
    pats = ctx.manifest.online_safe_items
    try:
        if ctx.args.action == "on":
            moved = go_online_safe(game, pats, ctx.args.dry_run)
            print(f"Moved {len(moved)} item(s) out of the game folder. Safe to launch GTA Online."
                  if moved else "No mod files found in the game folder.")
        elif ctx.args.action == "off":
            moved = restore_mods(game, ctx.args.dry_run)
            print(f"Restored {len(moved)} item(s). Story mode only from here.")
        else:
            print(online_status(game, pats))
    except OnlineSafeError as exc:
        print(exc)
        return 1
    return 0


def cmd_keys(ctx: Ctx) -> int:
    if ctx.args.key_action == "set":
        ctx.config.key_overrides[f"{ctx.args.mod}/{ctx.args.action}"] = ctx.args.key
        ctx.save()
    for key, users in sorted(hotkey_map(ctx.manifest, ctx.mods(), ctx.config.key_overrides).items()):
        clash = len({u[0] for u in users}) > 1
        line = f"{key:<8} " + "; ".join(f"{ctx.manifest.mod(m).name}: {act}" for m, act in users)
        print(_c("33", line + "   <- clash") if clash else line)
    return 0


def cmd_swap(ctx: Ctx) -> int:
    ctx.manifest.resolve(ctx.profile_id, swaps={ctx.args.old: ctx.args.new})
    ctx.config.swaps[ctx.args.old] = ctx.args.new
    ctx.save()
    print(f"{ctx.args.old} -> {ctx.args.new}")
    return 0


def cmd_doctor(ctx: Ctx) -> int:
    print(f"GPU(s):        {', '.join(detect_gpus()) or 'unknown'}  (RTX 50: {is_rtx50(detect_gpus())})")
    for k, v in check_prerequisites().items():
        print(f"{k:<14} {'ok' if v else ('missing' if v is False else 'unknown')}")
    print(f"7-Zip:         {find_7zip() or 'not found (only needed for .7z/.rar)'}")
    return 0


# ----------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leonida", description=f"{PACK_NAME}: GTA VI-style GTA V Enhanced, story mode only.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--state-dir", help=argparse.SUPPRESS)
    p.add_argument("--manifest-dir", help=argparse.SUPPRESS)
    p.add_argument("--game-dir", help="GTA V Enhanced folder (overrides the saved one)")
    p.add_argument("--download-dir", help="Where mod downloads are saved")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("detect", help="Find GTA V Enhanced")
    s.add_argument("--set", metavar="PATH", help="Use this folder")
    s.set_defaults(fn=cmd_detect)

    s = sub.add_parser("profiles", help="List profiles (or --use one)")
    s.add_argument("--use", metavar="PROFILE")
    s.set_defaults(fn=cmd_profiles)

    s = sub.add_parser("get", help="Open every download page and track the downloads")
    s.add_argument("--profile")
    s.add_argument("--no-open", dest="open", action="store_false", help="Don't open browser tabs")
    s.add_argument("--watch", action="store_true", help="Keep watching until all files arrive")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("assign", help="Tell Leonida which mod a downloaded file is")
    s.add_argument("file")
    s.add_argument("mod")
    s.set_defaults(fn=cmd_assign)

    s = sub.add_parser("check", help="Run all pre-install checks")
    s.add_argument("--profile")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("install", help="Install the profile step by step")
    s.add_argument("--profile")
    s.add_argument("--only", nargs="+", metavar="MOD")
    s.add_argument("--dry-run", action="store_true", help="Show what would happen; write nothing")
    s.add_argument("--yes", action="store_true", help="Don't ask questions")
    s.add_argument("--no-pause", action="store_true", help="Skip the test pause after each step")
    s.add_argument("--force", action="store_true", help="Install despite check errors")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("status", help="Show settings and installed steps")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("rollback", help="Undo one step (default: the last)")
    s.add_argument("step", nargs="?", type=int)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_rollback)

    s = sub.add_parser("uninstall", help="Undo every step")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_uninstall)

    s = sub.add_parser("online-safe", help="'on' moves mods out (safe for Online), 'off' brings them back")
    s.add_argument("action", choices=["on", "off", "status"])
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_online_safe)

    s = sub.add_parser("keys", help="Show hotkeys and clashes, or record a rebind")
    ks = s.add_subparsers(dest="key_action")
    kset = ks.add_parser("set")
    kset.add_argument("mod")
    kset.add_argument("action")
    kset.add_argument("key")
    s.set_defaults(fn=cmd_keys, key_action=None)

    s = sub.add_parser("swap", help="Swap a mod for an alternative in the same slot (e.g. hud hud-fbicat)")
    s.add_argument("old")
    s.add_argument("new")
    s.set_defaults(fn=cmd_swap)

    s = sub.add_parser("doctor", help="GPU, prerequisites, 7-Zip")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = Ctx(args)
        return int(args.fn(ctx) or 0)
    except ManifestError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
