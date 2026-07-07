"""Deprecated shim -> carryover.sessionstart. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.sessionstart
    import runpy

    runpy.run_module("carryover.sessionstart", run_name="__main__", alter_sys=True)
else:
    from carryover import sessionstart as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
