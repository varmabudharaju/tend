"""tend CLI: status, report, handoff, on/off, install-hook, uninstall-hook, statusline-wrap."""
import argparse
import os
import time
from pathlib import Path

from . import config, ctxmetrics, install, ledger, paths, state


def _session_mtime(d):
    """Newest mtime in d, tolerating files that vanish mid-scan (atomic-write tmps)."""
    times = []
    try:
        with os.scandir(d) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        times.append(entry.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    if times:
        return max(times)
    try:
        return d.stat().st_mtime
    except OSError:
        return 0.0


def latest_session():
    root = paths.home() / "sessions"
    if not root.exists():
        return None
    dirs = [d for d in root.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=_session_mtime).name


def cmd_status(args) -> int:
    sid = args.session or latest_session()
    if not sid:
        print("no tend sessions recorded yet")
        return 0
    if args.session and not (paths.home() / "sessions" / sid).is_dir():
        print(f"no such session: {sid}")
        return 1
    summary = ledger.load_summary(sid)
    pct = ctxmetrics.used_pct(sid)
    print(f"session  {sid}")
    newest = _session_mtime(paths.home() / "sessions" / sid)
    if newest:
        print(f"last hook activity {(time.time() - newest) / 60:.1f}m ago")
    pct_s = f"{pct:.0f}%" if pct is not None else "unknown"
    print(f"context  {pct_s} ({summary.get('context_total', 0):,} tok)")
    print(f"stale    {ledger.stale_tokens(summary):,} tok of stale tool results")
    cfg = config.load(args.cwd)
    print(f"bloat    {ledger.bloat_tokens(summary, cfg.offload_threshold_tokens):,} tok in oversized results")
    sp = state.path_for(args.cwd)
    if sp.exists():
        age_h = (time.time() - sp.stat().st_mtime) / 3600
        print(f"STATE.md updated {age_h:.1f}h ago ({sp})")
    else:
        print("STATE.md missing for this project")
    top = ledger.top_results(summary, 3)
    if top:
        print("top results:")
        for r in top:
            mark = "  STALE" if r.get("stale") else ""
            print(f"  {r['tokens']:>8,} tok  {r.get('tool') or '?'} {r.get('file') or ''}{mark}")
    return 0


def cmd_report(args) -> int:
    sid = args.session or latest_session()
    if not sid:
        print("no tend sessions recorded yet")
        return 0
    if args.session and not (paths.home() / "sessions" / sid).is_dir():
        print(f"no such session: {sid}")
        return 1
    summary = ledger.load_summary(sid)
    print(f"# tend report - session {sid}\n")
    print(f"context total : {summary.get('context_total', 0):,} tok")
    print(f"output total  : {summary.get('output_total', 0):,} tok")
    print(f"stale results : {ledger.stale_tokens(summary):,} tok")
    print(f"degraded      : {summary.get('degraded')}")
    print("\n## tool results by size")
    for r in ledger.top_results(summary, 20):
        mark = "  STALE" if r.get("stale") else ""
        print(f"  {r['tokens']:>8,} tok  {r.get('tool') or '?'} {r.get('file') or ''}{mark}")
    outputs = sorted((paths.session_dir(sid) / "outputs").glob("*.txt"))
    if outputs:
        print(f"\n## offloaded outputs ({len(outputs)})")
        for p in outputs:
            print(f"  {p}")
    agents = summary.get("agents", {})
    if agents:
        print(f"\n## subagents ({len(agents)})")
        for aid, a in agents.items():
            status = "done" if a.get("stopped") else "running"
            print(f"  {aid}  {a.get('type') or '?'}  {status}")
    snaps = sorted((paths.session_dir(sid)).glob("precompact-*.json"))
    if snaps:
        print(f"\n## compaction snapshots ({len(snaps)})")
        for p in snaps:
            print(f"  {p.name}")
    return 0


def cmd_handoff(args) -> int:
    sp = state.path_for(args.cwd)
    if not sp.exists():
        print(f"No STATE.md at {sp} - nothing to hand off. "
              "Ask Claude to write it, or start a session to seed the template.")
        return 1
    age_h = (time.time() - sp.stat().st_mtime) / 3600
    print(f"STATE.md ({sp}) - updated {age_h:.1f}h ago")
    if age_h > 4:
        print("WARNING: state may be stale; ask Claude to update it before switching sessions.")
    print("\nA new session in this project will auto-load:\n")
    print(sp.read_text(encoding="utf-8"))
    return 0


def cmd_on(args) -> int:
    (paths.home() / "disabled").unlink(missing_ok=True)
    print("tend enabled")
    return 0


def cmd_off(args) -> int:
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "disabled").touch()
    print("tend disabled (hooks exit immediately)")
    return 0


def cmd_install(args) -> int:
    try:
        install.install(args.settings)
    except install.SettingsError as e:
        print(str(e))
        return 1
    print(f"tend hooks + statusline installed into {args.settings}")
    print("Restart your Claude Code session to activate.")
    return 0


def cmd_uninstall(args) -> int:
    try:
        install.uninstall(args.settings)
    except install.SettingsError as e:
        print(str(e))
        return 1
    print(f"tend removed from {args.settings}")
    return 0


def cmd_wrap_statusline(args) -> int:
    try:
        install.wrap_statusline(args.settings)
    except install.SettingsError as e:
        print(str(e))
        return 1
    print(f"statusline wrapped in {args.settings} (original saved; tend uninstall-hook restores it)")
    return 0


def cmd_statusline_wrap(args) -> int:
    from . import statusline

    return statusline.main()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tend", description="Context-hygiene harness for Claude Code")
    sub = parser.add_subparsers(dest="command", required=True)
    default_settings = str(Path.home() / ".claude" / "settings.json")

    for name, fn, opts in [
        ("status", cmd_status, ["session", "cwd"]),
        ("report", cmd_report, ["session", "cwd"]),
        ("handoff", cmd_handoff, ["cwd"]),
        ("on", cmd_on, []),
        ("off", cmd_off, []),
        ("install-hook", cmd_install, ["settings"]),
        ("uninstall-hook", cmd_uninstall, ["settings"]),
        ("wrap-statusline", cmd_wrap_statusline, ["settings"]),
        ("statusline-wrap", cmd_statusline_wrap, []),
    ]:
        p = sub.add_parser(name)
        if "session" in opts:
            p.add_argument("--session", default=None)
        if "cwd" in opts:
            p.add_argument("--cwd", default=".")
        if "settings" in opts:
            p.add_argument("--settings", default=default_settings)
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
