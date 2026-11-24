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
from .detect import (
    ALL_EXES,
    check_prerequisites,
    detect_games,
    detect_gpus,
    find_7zip,
    find_exe,
    is_rtx50,
    python_bits,
)
from .installer import Installer, InstallError, windows_launch_command
from .manifest import ManifestError
from .matcher import build_lock, read_lock, verify_lock, write_lock
from .onlinesafe import OnlineSafeError, go_online_safe, restore_mods
from .onlinesafe import status as online_status
from .paths import LOCK_NAME
from .session import Session


# --------------------------------------------------------------------------- UI
def _is_tty(stream) -> bool:
    """False for None (pythonw / windowed exe) or a stream without a working isatty()."""
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


_COLOR = _is_tty(sys.stdout) and os.environ.get("NO_COLOR") is None


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
            subprocess.run(windows_launch_command(path), check=False, cwd=str(path.parent))
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
        super().__init__(args.state_dir, args.manifest_dir, args.download_dir, args.game_dir,
                         game_build=getattr(args, "game_build", None), edition=getattr(args, "edition", None))
        self.args = args

    @property
    def profile_id(self) -> str:
        return getattr(self.args, "profile", None) or super().profile_id


def _level(level: str) -> str:
    return {ERROR: _c("31", "ERROR  "), WARNING: _c("33", "WARNING"), INFO: _c("36", "info   ")}[level]


# -------------------------------------------------------------------- commands
def _build_note(ctx: Ctx, build: str | None, edition: str | None = None) -> str:
    try:
        manifest = ctx.manifest_for(edition) if edition else ctx.base_manifest
    except ManifestError:
        manifest = ctx.base_manifest
    tested = ", ".join(manifest.tested_builds) or "none"
    if not build:
        return f"(version unreadable; tested builds: {tested})"
    if manifest.is_tested(build):
        return _c("32", "(tested build)")
    return _c("33", f"(not a tested build; tested: {tested})")


def _print_build_summary(ctx: Ctx) -> None:
    build = ctx.game_version()
    src = " (from --game-build)" if ctx.game_build_override else ""
    names = {"enhanced": "GTA V Enhanced", "legacy": "GTA V Legacy"}
    game = names.get(ctx.game_edition or "", "unknown")
    used = f"; mod list: {names[ctx.edition]}" + (" (from --edition)" if ctx.edition_override else "")
    print(f"Game edition:  {game}{used}")
    mismatch = ctx.edition_mismatch()
    if mismatch:
        print(_c("31", f"  {mismatch}"))
    print(f"Game build:    {build or 'unknown'}{src} {_build_note(ctx, build)}")
    if not build:
        return
    mods = ctx.mods()
    older = [m for m in mods if m.variant is not None and not m.unsupported]
    bad = [m for m in mods if m.unsupported]
    if older:
        print("  older versions for this build: " + ", ".join(f"{m.name} {m.version}".strip() for m in older))
    for m in bad:
        print(_c("31", f"  not available on this build: {m.unsupported}"))


def cmd_detect(ctx: Ctx) -> int:
    extra = [Path(ctx.args.set)] if ctx.args.set else []
    games = detect_games(None, extra)  # both editions
    if ctx.args.set:
        exe = find_exe(Path(ctx.args.set), ALL_EXES)
        if not exe:
            print(f"No {' / '.join(ALL_EXES)} in {ctx.args.set}")
            return 1
        ctx.config.game_dir = str(Path(ctx.args.set))
        ctx.save()
        print(f"Game folder set: {ctx.config.game_dir}")
        _print_build_summary(ctx)
        return 0
    if not games:
        print("GTA V (Enhanced or Legacy) not found automatically. Set it with:\n"
              "  leonida detect --set \"D:\\path\\to\\GTA V Enhanced\"")
        return 1
    for i, g in enumerate(games, 1):
        print(f"{i}. {g.path}  [{g.source}]  {g.edition_name}  version {g.version or 'unknown'}  "
              f"{_build_note(ctx, g.version, g.edition)}")
    if len({g.edition for g in games}) > 1:
        print("Both editions are installed. Each has its own mod list; pick the folder with `leonida detect --set`.")
    if not ctx.config.game_dir:
        ctx.config.game_dir = str(games[0].path)
        ctx.save()
        print(f"Using: {ctx.config.game_dir}")
    else:
        print(f"Current setting: {ctx.config.game_dir}")
    _print_build_summary(ctx)
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
    for f, (mid, reason) in getattr(result, "wrong", {}).items():
        m = ctx.manifest.mods.get(mid)
        print(_c("31", f"!! {f.name}: wrong edition/version of {m.name if m else mid}: {reason}"))
        if m is not None and m.pick:
            label = m.pick.get("versionLabel") or f"the version matching {m.pick.get('versionMatch')}"
            print(f"   On {m.page} download '{label}' from the All Versions list instead of the main button.")


def cmd_get(ctx: Ctx) -> int:
    mods = ctx.mods()
    folder = ctx.config.downloads()
    folder.mkdir(parents=True, exist_ok=True)
    print(f"{PACK_NAME} - profile '{ctx.profile_id}' - save every download into:\n  {folder}\n")
    result = ctx.matches(mods)
    missing = result.missing(mods)
    to_open = missing
    if getattr(ctx.args, "auto", False) and missing:
        from . import downloader

        last = [0.0]

        def show(done: int, total: int | None) -> None:
            now = time.monotonic()
            if total is not None and done < total and now - last[0] < 0.25:
                return
            last[0] = now
            mb = f"{done / 1048576:.1f}"
            line = f"{mb} / {total / 1048576:.1f} MB ({done * 100 // max(total, 1)}%)" if total else f"{mb} MB"
            print(f"\r    {line}   ", end="", flush=True)

        plans = [(m, downloader.plan_for(m)) for m in missing]
        browser_ids: list[str] = []
        auto = [(m, p) for m, p in plans if p.mode == "auto"]
        if auto:
            print(f"Downloading {len(auto)} file(s) from the authors' own releases/links...")
        for m, plan in auto:
            print(f"  {m.name}")
            try:
                path = downloader.download(plan, folder, progress=show)
                print(_c("32", f"\r    saved {path.name}") + " " * 20)
            except downloader.DownloadError as exc:
                print()
                print(_c("33", f"    ! {exc}"))
                browser_ids.append(m.id)
        browser_ids += [m.id for m, p in plans if p.mode == "browser"]
        browser = [m for m in missing if m.id in browser_ids]
        if browser:
            print("\nDownload these from the author's page (click Download there, save into the folder above):")
            for m in browser:
                print(f"  - {m.name}: {m.page}")
        manual = [m for m, p in plans if p.mode == "manual"]
        if manual:
            print("\nGet these yourself (not downloadable automatically):")
            for m in manual:
                print(f"  - {m.name} [{m.source}]: {m.page}")
        print()
        result = ctx.matches(mods)
        missing = result.missing(mods)
        to_open = [m for m in browser if m in missing]
    if ctx.args.open and to_open and not os.environ.get("LEONIDA_NO_OPEN"):
        print(f"Opening {len(to_open)} download page(s) in your browser...")
        for m in to_open:
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
    mismatch = ctx.edition_mismatch()
    if mismatch:  # never, not even with --force: the two editions' mods don't mix
        print(_c("31", mismatch))
        return 1
    if has_errors(findings) and not a.force and not a.dry_run:
        print("Fix the errors above (or use --force).")
        return 1
    skipped = [m for m in mods if m.unsupported]
    if skipped:
        print(_c("33", "Skipping (not available on this game build): " + ", ".join(m.name for m in skipped)))
        mods = [m for m in mods if not m.unsupported]
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
        for p in verify_lock(lock, result.matched, only=[m.id for m in todo]):
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
    gpus = detect_gpus()
    print(f"GPU(s):        {', '.join(gpus) or 'unknown'}  (RTX 50: {is_rtx50(gpus)})")
    for k, v in check_prerequisites().items():
        print(f"{k:<14} {'ok' if v else ('missing' if v is False else 'unknown')}")
    print(f"7-Zip:         {find_7zip() or 'not found (only needed for .7z/.rar)'}")
    bits = python_bits()
    print(f"Python:        {sys.version.split()[0]} ({bits}-bit)")
    if ctx.game_dir() or ctx.game_build_override:
        _print_build_summary(ctx)
    paid = [m for m in ctx.manifest.mods.values() if m.tier == "paid"]
    if paid:
        print("Paid mods (optional add-ons; Leonida never uses leaked or re-uploaded copies):")
        for m in paid:
            state = "paid" if m.is_paid else _c("32", "free now")
            print(f"  {m.name}: {state}; free route: {ctx.manifest.free_route_text(m.id)}")
    if sys.platform == "win32" and bits != 64:
        ConsoleUI().warn("This Python is 32-bit. The engine works, but the GUI (PySide6) needs 64-bit Python 3.10+ from python.org.")
    return 0


def cmd_verify(ctx: Ctx) -> int:
    from .verify import FAILED, NOT_SEEN, OK, WARN, verify_session

    if not ctx.game_dir():
        raise SystemExit("Set the game folder first: leonida detect")
    results = verify_session(ctx)
    if not results:
        print("Nothing installed by Leonida V yet, so there is nothing to verify.")
        return 0
    tags = {OK: _c("32", "OK      "), FAILED: _c("31", "FAILED  "), WARN: _c("33", "WARNING "),
            NOT_SEEN: _c("36", "NOT SEEN")}
    for r in results:
        print(f"{tags.get(r.status, 'info    ')} {r.message}")
        if r.line and ctx.args.lines:
            print(f"           {r.log}: {r.line}")
    for d in ctx.settings_drift():  # locked settings changed since install
        print(f"{_c('33', 'WARNING ')} {d.message()}")
    failed = sum(r.status == FAILED for r in results)
    unseen = sum(r.status == NOT_SEEN for r in results)
    if failed:
        print(_c("31", f"\n{failed} problem(s) found in the game's logs."))
    elif unseen:
        print("\nStart the game once (story mode), quit it, then run `leonida verify` again.")
    return 1 if failed else 0


def cmd_pack(ctx: Ctx) -> int:
    from . import packs

    a, base = ctx.args, ctx.base_manifest
    if a.action == "list":
        cur = ctx.pack_choice()
        for pk in base.packs.values():
            mark = "*" if pk.id == cur.pack else " "
            print(_c("1", f"{mark} {pk.id}  {pk.name}"))
            if pk.description:
                print(f"    {pk.description}")
            n = sum(len(v) for v in base.addons_for(pk.id).values())
            extra = f"; variants: {', '.join(v.id for v in pk.variants)}" if pk.variants else ""
            print(f"    {len(base.resolve_pack(pk.id))} mods with its default add-ons; {n} add-on(s){extra}")
        return 0
    if a.action == "choose":
        addons = None if a.addons is None else [x for x in a.addons.split(",") if x and x != "none"]
        before = {m.id for m in ctx.mods()}
        choice = ctx.choose_pack(a.pack, addons, a.variant)
        after = {m.id for m in ctx.mods()}
        print(f"Modpack: {base.get_pack(choice.pack).name}" + (f" ({choice.variant})" if choice.variant else ""))
        installed = ctx.log.installed_mods()
        leaving = sorted((before - after) & installed)
        if leaving:
            if a.rollback:
                for line in packs.rollback_mods(ctx, ConsoleUI(assume_yes=True), set(leaving)):
                    print("  " + line)
            else:
                print("Installed but not in this pack: " + ", ".join(leaving)
                      + "\n  Roll them back with: leonida pack choose " + a.pack + " --rollback")
        new = sorted(after - before)
        if new:
            print("New in the selection: " + ", ".join(new) + "  (leonida get, then leonida install)")
        return 0
    # addons
    cur = ctx.pack_choice()
    chosen = list(ctx.chosen_addons())
    if a.add or a.remove:
        chosen = [x for x in chosen if x not in (a.remove or [])] + [x for x in (a.add or []) if x not in chosen]
        ctx.choose_pack(cur.pack, chosen, cur.variant)
    for cat, items in base.addons_for(cur.pack).items():
        print(_c("1", base.categories[cat].name if cat in base.categories else cat))
        for ad in items:
            mark = _c("32", "[x]") if ad.id in chosen else "[ ]"
            print(f"  {mark} {ad.id}  {ad.name}  ({', '.join(ad.mods)})")
    if not base.addons_for(cur.pack):
        print(f"{base.get_pack(cur.pack).name} has no add-ons.")
    return 0


def cmd_custom(ctx: Ctx) -> int:
    from . import custommods

    a = ctx.args
    if a.action == "list":
        entries = ctx.custom_entries()
        if not entries:
            print("No mods of your own yet. Add one: leonida custom add --name \"My mod\" --file D:\\mods\\x.zip")
        for e in sorted(entries, key=lambda e: e.get("order", 0)):
            where = e.get("file") or e.get("page")
            state = "" if e.get("enabled", True) else "  (off)"
            print(f"{e.get('order', '?'):>3}. {e['id']}  {e['name']}  [{e.get('method') or 'auto'}]  {where}{state}")
        return 0
    if a.action == "remove":
        if custommods.remove(ctx.state, a.id):
            print(f"Removed {a.id} from your mods (anything it installed stays until you roll it back).")
            return 0
        print(_c("31", f"No mod of yours is called {a.id}."))
        return 1
    if a.action == "export":
        print(f"Saved to {custommods.export(ctx.state, Path(a.out))}")
        return 0
    entry = custommods.add(ctx.state, ctx.manifest_for(ctx.edition), name=a.name, file=a.file, page=a.page,
                           archive=a.archive, files=a.files, to=a.to, method=a.method, order=a.order,
                           mod_id=a.id, run=a.run)
    print(f"Added {entry['id']} ({entry['name']}). It's part of your selection now: leonida check, then leonida install.")
    return 0


def cmd_settings(ctx: Ctx) -> int:
    from . import settings as S

    a = ctx.args
    if a.action in ("unlock", "lock"):
        ctx.base_manifest.mod(a.mod)
        S.set_unlocked(ctx.state, a.mod, a.file.replace("\\", "/"), a.key, a.action == "unlock")
        print(f"{a.mod} {a.file}: {a.key} is " + ("unlocked: Leonida leaves your value alone." if a.action == "unlock"
                                                  else "locked again: `leonida settings apply` writes Leonida's value."))
        return 0
    if not ctx.game_dir():
        raise SystemExit("Set the game folder first: leonida detect")
    if a.action == "apply":
        lines = ctx.apply_settings(ConsoleUI(), dry_run=a.dry_run)
        for line in lines:
            print(f"  {line}")
        print("Every locked setting is already right." if not lines and not a.dry_run else "")
        return 0
    drifted = {(d.wanted.mod, d.wanted.file, d.wanted.key): d for d in ctx.settings_drift()}
    unlocked = S.unlocked(ctx.state)
    installed = ctx.log.installed_mods()
    shown = 0
    for m in ctx.manifest.mods.values():
        if m.id not in installed or not m.settings:
            continue
        print(_c("1", m.name))
        for w in ctx.settings_for(m):
            d = drifted.get((w.mod, w.file, w.key))
            state = _c("33", f"DRIFT (now {d.have!r})") if d else _c("32", "ok")
            print(f"  {w.file}: {w.key} = {w.value}  {state}" + (f"  - {w.why}" if w.why else ""))
            shown += 1
        for k in sorted(u for u in unlocked if u.startswith(f"{m.id}|")):
            print(f"  {k.split('|', 1)[1].replace('|', ': ')}  (unlocked)")
    if not shown:
        print("No locked settings for the installed mods.")
    return 1 if drifted else 0


def cmd_playtest(ctx: Ctx) -> int:
    from .playtest import CRASHED, HANG, PASSED, playtest
    from .verify import FAILED, OK, WARN

    print(f"{PACK_NAME} play test: starts GTA through PlayGTAV.exe, waits for story mode, reads the mods' logs.")
    rep = playtest(ctx, timeout=ctx.args.timeout, keep_running=ctx.args.keep_running,
                   progress=lambda msg: print(f"  {msg}", flush=True))
    color = {PASSED: "32", CRASHED: "31", HANG: "31"}.get(rep.status, "33")
    print()
    print(_c(color, f"{rep.status.upper()}: {rep.message}"))
    for n in rep.notes:
        print(f"  note: {n}")
    for e in rep.evidence:
        print(f"  evidence: {e}")
    tags = {OK: _c("32", "OK      "), FAILED: _c("31", "FAILED  "), WARN: _c("33", "WARNING ")}
    for r in rep.results:
        print(f"  {tags.get(r.status, 'info    ')} {r.message}")
    return 0 if rep.ok else 1


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 2 * 86400:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} days ago"


def cmd_self_update(ctx: Ctx) -> int:
    from . import updater
    from .downloader import DownloadError

    a = ctx.args
    project = updater.project_dir()
    kind = updater.install_kind(project)
    print(f"{PACK_NAME} {updater.__version__} ({kind} install)")
    if a.reinstall:
        try:
            print(_c("32", updater.request_reinstall(project)))
        except DownloadError as exc:
            print(_c("31", str(exc)))
            return 1
        return 0
    previous = updater.cached_check(ctx.state)
    if previous is not None:
        print(f"Last check: {_ago(previous.age)} (latest then: {previous.latest or 'no release'})")
    try:
        info = updater.check(cache_dir=ctx.state, max_age=0)
    except DownloadError as exc:
        print(_c("31", f"Could not check for updates: {exc}"))
        if previous is None or a.force or not a.check:
            return 1
        info = previous
        print(f"Showing the saved result from {_ago(info.age)}.")
    if info.latest is None:
        if a.force:
            print(_c("31", "No Leonida V release has been published yet."))
            return 1
        print("No Leonida V release published yet.")
        return 0
    print(f"Latest release: {info.latest}  {info.page}")
    if not info.newer and not a.force:
        print(_c("32", "You have the latest version.") + "  (leonida self-update --force reinstalls it)")
        return 0
    if info.notes and info.newer:
        print("\n" + info.notes.strip()[:1200] + "\n")
    if a.check:
        print("Update available. Run: leonida self-update" if info.newer else "Run: leonida self-update --force")
        return 0
    last = [-1]

    def show(done: int, total: int | None) -> None:
        pct = done * 100 // total if total else -1
        if pct != last[0]:
            last[0] = pct
            print(f"\r  {done / 1048576:.1f} MB" + (f" ({pct}%)" if total else ""), end="", flush=True)

    try:
        msg = updater.apply(info, project, ctx.state, progress=show, force=a.force)
    except DownloadError as exc:
        print()
        print(_c("31", str(exc)))
        return 1
    print()
    print(_c("32", msg))
    return 0


def cmd_modpack(ctx: Ctx) -> int:
    from . import modpack as mp

    out = Path(ctx.args.out) if ctx.args.out else ctx.state / mp.ASSET
    try:
        new = mp.build_modpack(ctx)
        data = mp.merge(mp.load_file(out), new) if out.is_file() else new
    except mp.ModpackError as exc:
        print(_c("31", str(exc)))
        return 1
    build, section = next(iter(new["builds"].items()))
    mp.write_file(out, data)
    print(f"Recorded {len(section['mods'])} mod file(s) for game build {build} -> {out}")
    if len(data["builds"]) > 1:
        print(f"  {out.name} now covers builds: {', '.join(data['builds'])}")
    mods = ctx.mods()
    left_out = [m for m in mods if not m.unsupported and m.id not in section["mods"]]
    if left_out:
        print(_c("33", "  not downloaded, left out: " + ", ".join(m.name for m in left_out)))
    bad = [m for m in mods if m.unsupported]
    if bad:
        print(_c("33", "  not available on this build: " + ", ".join(m.name for m in bad)))
    rehost = [m.name for m in mods if m.redistributable]
    print("  re-hostable (mods.json has permission): " + (", ".join(rehost) or "none; every file comes from its author"))
    return 0


def cmd_update(ctx: Ctx) -> int:
    from . import modpack as mp
    from . import modupdate as mu
    from .downloader import DownloadError

    a = ctx.args
    if a.skip:
        mod_id, _, version = a.skip.partition("@")
        ctx.base_manifest.mod(mod_id)
        mu.skip_version(ctx.state, mod_id, version or None)
        print(f"Won't offer {mod_id} {version} again." if version else f"Cleared the skipped version of {mod_id}.")
        return 0
    if a.mod:
        ctx.base_manifest.mod(a.mod)
    try:
        pack = mp.load_file(Path(a.modpack)) if a.modpack else mp.fetch_latest()
    except DownloadError as exc:
        print(_c("31", f"Could not get the modpack: {exc}"))
        return 1
    if pack is None:
        print("No modpack published yet (no modpack.json in the latest Leonida V release).")
        return 0
    rel = pack.get("_release") or {}
    if rel:
        state = "verified against SHA256SUMS" if rel.get("verified") else _c("33", "not verified: no SHA256SUMS")
        print(f"Modpack from release {rel.get('tag')} ({state})")
    plan = mu.plan_updates(ctx, pack, only=a.mod)
    print(f"Game build {plan.build or 'unknown'}; modpack set for build {plan.modpack_build or '-'}")
    for line in plan.summary():
        print("  " + (_c("31", line) if line.startswith("HELD") else line))
    if plan.held:
        return 1
    if a.check or not plan.pending:
        if plan.pending:
            print(f"{len(plan.pending)} update(s) available. Run: leonida update")
        return 0
    last = [-1]

    def show(done: int, total: int | None) -> None:
        pct = done * 100 // total if total else -1
        if pct != last[0]:
            last[0] = pct
            print(f"\r  {done / 1048576:.1f} MB" + (f" ({pct}%)" if total else ""), end="", flush=True)

    ui = ConsoleUI(assume_yes=a.yes)
    try:
        report = mu.run_updates(ctx, plan, ui, progress=show)
    except DownloadError as exc:
        print(_c("31", str(exc)))
        return 1
    print()
    for line in report:
        print(line)
    return 0


# ----------------------------------------------------------------------- parser
def shortcut_target() -> tuple[Path, str, bool]:
    """(what the shortcut starts, its icon, run minimized): LeonidaV.exe in the frozen build, else the portable kit's
    Start-Leonida.bat (next to leonida-v, or inside a source checkout) with the logo .ico."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).with_name("LeonidaV.exe")
        return exe, f"{exe},0", False
    project = Path(__file__).resolve().parent.parent
    bat = next((b for b in (project.parent / "Start-Leonida.bat", project / "Start-Leonida.bat") if b.is_file()),
               project / "Start-Leonida.bat")
    return bat, str(Path(__file__).resolve().parent / "gui" / "assets" / "leonida.ico"), True


def cmd_shortcuts(ctx: Ctx) -> int:
    from . import shortcuts as SC

    target, icon, minimized = shortcut_target()
    if not target.is_file():
        print(_c("31", f"Can't make shortcuts: {target} doesn't exist."))
        return 1
    try:
        made = SC.create(target, icon=icon, workdir=target.parent, minimized=minimized,
                         desktop=not ctx.args.no_desktop)
    except SC.ShortcutError as exc:
        print(_c("31", f"Could not create the shortcuts: {exc}"))
        return 1
    for lnk in made:
        print(f"Shortcut: {lnk}")
    if not made:
        print("No shortcuts made (not Windows, or LEONIDA_NO_SHORTCUTS=1).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leonida", description=f"{PACK_NAME}: GTA VI-style GTA V Enhanced, story mode only.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--state-dir", help=argparse.SUPPRESS)
    p.add_argument("--manifest-dir", help=argparse.SUPPRESS)
    p.add_argument("--game-dir", help="GTA V Enhanced folder (overrides the saved one)")
    p.add_argument("--edition", choices=("enhanced", "legacy"),
                   help="Use this edition's mod list (default: from the game folder's exe)")
    p.add_argument("--game-build", metavar="BUILD",
                   help="Treat the game as this build, e.g. 1.0.1013.20 (overrides detection; for testing)")
    p.add_argument("--download-dir", help="Where mod downloads are saved")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shortcuts", help="Make the 'Leonida V' Start menu and desktop shortcuts "
                                         "(same as --create-shortcuts)")
    s.add_argument("--no-desktop", action="store_true", help="Only the Start menu shortcut")
    s.set_defaults(fn=cmd_shortcuts)

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
    s.add_argument("--auto", action="store_true",
                   help="Download what the authors publish directly (GitHub releases / direct links) first")
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

    s = sub.add_parser("verify", help="Read the mods' logs after a game start: which installed mods really loaded")
    s.add_argument("--lines", action="store_true", help="Also print the log line behind each result")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("pack", help="Modpacks: list them, choose one, pick its add-ons")
    ps = s.add_subparsers(dest="action", required=True)
    ps.add_parser("list", help="The modpacks to choose from")
    pc = ps.add_parser("choose", help="Choose a modpack")
    pc.add_argument("pack")
    pc.add_argument("--addons", metavar="ID,ID", help="Add-ons to use (default: the pack's own; 'none' for none)")
    pc.add_argument("--variant", metavar="ID")
    pc.add_argument("--rollback", action="store_true", help="Roll back installed mods that aren't in the new pack")
    pa = ps.add_parser("addons", help="Show the current pack's add-ons by category, or change them")
    pa.add_argument("--add", action="append", metavar="ID")
    pa.add_argument("--remove", action="append", metavar="ID")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("custom", help="Your own mods: add any mod (a file or a page) to Leonida's installs")
    cs = s.add_subparsers(dest="action", required=True)
    ca = cs.add_parser("add", help="Add (or replace) one of your mods")
    ca.add_argument("--name", required=True)
    src = ca.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="The mod's archive or file on your disk")
    src.add_argument("--page", help="The mod's page (its download is recognised by --archive)")
    ca.add_argument("--archive", action="append", metavar="GLOB", help="How its download is named")
    ca.add_argument("--files", action="append", metavar="NAME", help="A file from the archive to copy (repeatable)")
    ca.add_argument("--to", default=".", help="Folder in the game folder the --files go to (default: the game folder)")
    ca.add_argument("--method", choices=("copy", "generic", "guided", "run"))
    ca.add_argument("--run", metavar="EXE", help="For --method run: the installer to start")
    ca.add_argument("--order", type=int, help="Position among your mods (they install after Leonida's)")
    ca.add_argument("--id")
    cr = cs.add_parser("remove", help="Remove one of your mods from the list")
    cr.add_argument("id")
    cs.add_parser("list", help="Your mods")
    ce = cs.add_parser("export", help="Save your mods' list to share it")
    ce.add_argument("out")
    s.set_defaults(fn=cmd_custom)

    s = sub.add_parser("settings", help="Locked mod settings: show (with drift), apply, unlock/lock a key")
    ss = s.add_subparsers(dest="action", required=True)
    ss.add_parser("show", help="The locked settings of the installed mods and any drift")
    sa = ss.add_parser("apply", help="Write the locked values again (after a variant switch or drift)")
    sa.add_argument("--dry-run", action="store_true")
    for name in ("unlock", "lock"):
        su = ss.add_parser(name, help=f"{name.title()} one key")
        su.add_argument("mod")
        su.add_argument("file")
        su.add_argument("key")
    s.set_defaults(fn=cmd_settings)

    s = sub.add_parser("playtest", help="Start the game (PlayGTAV.exe), wait for story mode, check the mods' logs")
    s.add_argument("--timeout", type=float, default=300.0, metavar="S",
                   help="Seconds to wait for story mode after starting (default 300)")
    s.add_argument("--keep-running", action="store_true", help="Leave the game running afterwards")
    s.set_defaults(fn=cmd_playtest)

    s = sub.add_parser("self-update", help="Update Leonida V itself from its GitHub releases")
    s.add_argument("--check", action="store_true", help="Only check whether a newer version exists")
    s.add_argument("--force", action="store_true",
                   help="Reinstall the latest release even if it isn't newer (repairs a broken copy)")
    s.add_argument("--reinstall", action="store_true",
                   help="Offline repair: reinstall the Python package on the next Start-Leonida.bat")
    s.set_defaults(fn=cmd_self_update)

    s = sub.add_parser("modpack", help="Build modpack.json (the tested mod files) from your downloads")
    ms = s.add_subparsers(dest="action", required=True)
    mb = ms.add_parser("build", help="Record the matched downloads for this game build")
    mb.add_argument("--profile")
    mb.add_argument("--out", metavar="FILE", help="Where to write it (an existing file gets this build merged in)")
    s.set_defaults(fn=cmd_modpack)

    s = sub.add_parser("update", help="Update installed mods to the latest modpack's tested versions")
    s.add_argument("--check", action="store_true", help="Only show what would change")
    s.add_argument("--mod", metavar="ID", help="Update only this mod")
    s.add_argument("--skip", metavar="ID@VERSION", help="Don't offer this version again (ID alone clears it)")
    s.add_argument("--modpack", metavar="FILE", help="Use a local modpack.json instead of the latest release")
    s.add_argument("--yes", action="store_true", help="Don't ask questions")
    s.add_argument("--profile")
    s.set_defaults(fn=cmd_update)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--create-shortcuts" in argv:  # the frozen build's option: an alias of the shortcuts command
        argv = ["shortcuts" if a == "--create-shortcuts" else a for a in argv]
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
