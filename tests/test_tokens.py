from tend import tokens


def test_estimate_chars_over_four():
    assert tokens.estimate("x" * 400) == 100


def test_estimate_empty_is_zero():
    assert tokens.estimate("") == 0


def test_estimate_short_text_is_at_least_one():
    assert tokens.estimate("ab") == 1


def test_to_text_passthrough_and_json():
    assert tokens.to_text("hi") == "hi"
    assert tokens.to_text(None) == ""
    out = tokens.to_text({"a": 1, "b": [1, 2]})
    assert "\n" in out          # line-addressable, not one escaped line
    assert '"a": 1' in out


def test_to_text_bash_dict_renders_streams():
    s = tokens.to_text({"stdout": "out line\n", "stderr": "boom", "interrupted": False})
    assert s == "out line\n--- stderr ---\nboom"


def test_to_text_bash_dict_stdout_only():
    assert tokens.to_text({"stdout": "just out\n", "stderr": ""}) == "just out\n"


def test_to_text_unicode_not_escaped():
    assert "héllo" in tokens.to_text({"k": "héllo"})
