"""Statusline wrapper: tee exact context metrics to disk, then run the original statusline."""
import json
import subprocess
import sys

from . import paths


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    sid = data.get("session_id")
    if sid:
        try:
            paths.write_json_atomic(paths.session_dir(sid) / "ctx.json", data)
        except Exception:
            pass
    orig = paths.read_json(paths.home() / "statusline-original.json")
    if orig and orig.get("command"):
        try:
            res = subprocess.run(
                orig["command"], shell=True, input=raw, capture_output=True, text=True, timeout=10
            )
            sys.stdout.write(res.stdout)
            return 0
        except Exception:
            pass
    model = (data.get("model") or {}).get("display_name", "")
    pct = (data.get("context_window") or {}).get("used_percentage")
    line = model or "tend"
    if pct is not None:
        line += f" | ctx {pct:.0f}%"
    sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
