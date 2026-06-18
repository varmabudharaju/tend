"""CLI: python3 -m bench mechanical [--out DIR] [--iters N]"""
import argparse
import datetime
import sys

from . import mechanical


def main(argv=None):
    p = argparse.ArgumentParser(prog="bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mechanical", help="run the deterministic Phase 1 benchmark")
    m.add_argument("--out", default=".benchmarks", help="output directory")
    m.add_argument("--iters", type=int, default=40,
                   help="subprocess latency iterations per hook")

    b = sub.add_parser("behavioral", help="run the live tend ON/OFF A/B (uses API key)")
    b.add_argument("--out", default=".benchmarks", help="output directory")
    b.add_argument("--model", default="claude-haiku-4-5-20251001", help="model id")
    b.add_argument("--repeats", type=int, default=2, help="repeats per arm")
    b.add_argument("--arms", default="on,off", help="comma list: on,off")
    b.add_argument("--workload", default="recall",
                   choices=["recall", "highload", "handoff"],
                   help="recall=light flood; highload=force toward compaction; "
                        "handoff=fresh-session STATE restore A/B")
    b.add_argument("--flood-turns", type=int, default=3,
                   help="number of forcing flood turns (highload)")
    b.add_argument("--log-tokens", type=int, default=9000,
                   help="approx tokens per flood log file")

    it = sub.add_parser("interactive",
                        help="human-in-the-loop A/B for tend's /clear handoff")
    it.add_argument("--setup", action="store_true", help="create sandboxes + print protocol")
    it.add_argument("--score", action="store_true", help="grade recall from transcripts")

    args = p.parse_args(argv)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")

    if args.cmd == "mechanical":
        _results, md = mechanical.run(args.out, stamp, iters=args.iters)
        print(md)
        print(f"\n[bench] wrote {args.out}/mechanical-{stamp}.{{json,md}}")
        return 0
    if args.cmd == "behavioral":
        from . import behavioral
        _results, md = behavioral.run_pilot(
            args.out, stamp, model=args.model, repeats=args.repeats,
            arms=tuple(a.strip() for a in args.arms.split(",") if a.strip()),
            kind=args.workload, flood_turns=args.flood_turns, log_tokens=args.log_tokens)
        print("\n" + md)
        print(f"[bench] wrote {args.out}/behavioral-{stamp}.{{json,md}}")
        return 0
    if args.cmd == "interactive":
        from . import interactive
        if args.score:
            interactive.score()
        else:
            interactive.setup()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
