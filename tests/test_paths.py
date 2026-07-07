from carryover import paths


def test_home_respects_env(carryover_home):
    assert paths.home() == carryover_home


def test_session_dir_created(carryover_home):
    d = paths.session_dir("abc")
    assert d.is_dir()
    assert d == carryover_home / "sessions" / "abc"


def test_disabled_flag(carryover_home):
    assert not paths.disabled()
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "disabled").touch()
    assert paths.disabled()


def test_json_roundtrip_atomic(carryover_home):
    p = carryover_home / "x" / "y.json"
    paths.write_json_atomic(p, {"a": 1})
    assert paths.read_json(p) == {"a": 1}
    assert paths.read_json(carryover_home / "missing.json", {"d": 1}) == {"d": 1}
    assert not list(p.parent.glob("*.tmp"))
