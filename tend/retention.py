"""Deprecated shim -> carryover.retention. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.retention
    import runpy

    runpy.run_module("carryover.retention", run_name="__main__", alter_sys=True)
else:
    from carryover import retention as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
