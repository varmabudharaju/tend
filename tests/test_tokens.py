from tend import tokens


def test_estimate_chars_over_four():
    assert tokens.estimate("x" * 400) == 100


def test_estimate_empty_is_zero():
    assert tokens.estimate("") == 0


def test_estimate_short_text_is_at_least_one():
    assert tokens.estimate("ab") == 1


def test_to_text_passthrough_and_json():
    assert tokens.to_text("hi") == "hi"
    assert tokens.to_text({"a": 1}) == '{"a": 1}'
    assert tokens.to_text(None) == ""
