"""Deprecated shim -> carryover.config. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.config
    import runpy

    runpy.run_module("carryover.config", run_name="__main__", alter_sys=True)
else:
    from carryover import config as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
