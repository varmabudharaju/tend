"""Deprecated shim -> carryover.cli. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.cli
    import runpy

    runpy.run_module("carryover.cli", run_name="__main__", alter_sys=True)
else:
    from carryover import cli as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
