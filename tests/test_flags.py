from carryover import flags


def test_load_empty_then_roundtrip(carryover_home):
    assert flags.load("s1") == {}
    flags.save("s1", {"state_reminder": True})
    assert flags.load("s1") == {"state_reminder": True}
