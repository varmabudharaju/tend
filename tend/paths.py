"""Deprecated shim -> carryover.paths. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.paths
    import runpy

    runpy.run_module("carryover.paths", run_name="__main__", alter_sys=True)
else:
    from carryover import paths as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
