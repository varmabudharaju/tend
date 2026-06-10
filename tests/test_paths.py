from tend import paths


def test_home_respects_env(tend_home):
    assert paths.home() == tend_home


def test_session_dir_created(tend_home):
    d = paths.session_dir("abc")
    assert d.is_dir()
    assert d == tend_home / "sessions" / "abc"


def test_disabled_flag(tend_home):
    assert not paths.disabled()
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "disabled").touch()
    assert paths.disabled()


def test_json_roundtrip_atomic(tend_home):
    p = tend_home / "x" / "y.json"
    paths.write_json_atomic(p, {"a": 1})
    assert paths.read_json(p) == {"a": 1}
    assert paths.read_json(tend_home / "missing.json", {"d": 1}) == {"d": 1}
    assert not list(p.parent.glob("*.tmp"))
