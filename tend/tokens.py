"""Deprecated shim -> carryover.tokens. See tend/__init__.py."""
if __name__ == "__main__":  # legacy: python3 -m tend.tokens
    import runpy

    runpy.run_module("carryover.tokens", run_name="__main__", alter_sys=True)
else:
    from carryover import tokens as _mod

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
