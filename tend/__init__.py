"""Deprecated package: import from `carryover` instead.

Every `tend.<mod>` is a thin shim re-exporting `carryover.<mod>`, kept so pre-rename
installs (settings.json / hooks that invoke `python3 -m tend.<mod>`) keep working
until users re-run install. New code should import `carryover`.
"""
