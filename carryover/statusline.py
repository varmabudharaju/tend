"""Statusline wrapper: tee exact context metrics to disk, then run the original statusline."""
import json
import subprocess
import sys

from . import paths


def main() -> int:
    try:
        return _main()
    except Exception:
        sys.stdout.write("carryover\n")  # a broken wrapper must never blank the statusbar
        return 0


def _main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    sid = data.get("session_id")
    if sid and not paths.disabled():  # kill switch: no carryover writes while off
        try:
            paths.write_json_atomic(paths.session_dir(sid) / "ctx.json", data)
        except Exception:
            pass
    orig = paths.read_json(paths.home() / "statusline-original.json")
    if isinstance(orig, dict) and orig.get("command"):
        try:
            res = subprocess.run(
                orig["command"], shell=True, input=raw, capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0 and res.stdout:
                sys.stdout.write(res.stdout.rstrip("\n") + _carryover_segment(sid) + "\n")
                return 0
            # Non-zero exit or empty stdout: log stderr and fall through to built-in fallback
            if res.stderr:
                from . import hookio

                hookio.append_log(f"statusline-original stderr: {res.stderr}\n")
        except Exception:
            pass
    model = (data.get("model") or {}).get("display_name", "")
    pct = (data.get("context_window") or {}).get("used_percentage")
    line = model or "carryover"
    if pct is not None:
        try:
            line += f" | ctx {float(pct):.0f}%"
        except (TypeError, ValueError):
            pass
    sys.stdout.write(line + _carryover_segment(sid) + "\n")
    return 0


def _carryover_segment(sid) -> str:
    """The visible heartbeat: a quiet suffix proving carryover is on and working."""
    if not sid or paths.disabled():
        return ""
    try:
        from . import ledger

        summary = ledger.load_summary(sid)
        parts = []
        outputs = paths.home() / "sessions" / str(sid) / "outputs"
        filed = len(list(outputs.glob("*.txt"))) if outputs.is_dir() else 0
        if filed:
            parts.append(f"{filed} filed")
        stale = ledger.stale_tokens(summary)
        if stale >= 1000:
            parts.append(f"{stale // 1000}k stale")
        return " | carryover: " + (", ".join(parts) if parts else "on")
    except Exception:
        return ""


if __name__ == "__main__":
    sys.exit(main())
