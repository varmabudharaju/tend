"""Deprecated shim -> carryover.ledger. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.ledger
    import runpy

    runpy.run_module("carryover.ledger", run_name="__main__", alter_sys=True)
else:
    from carryover import ledger as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
