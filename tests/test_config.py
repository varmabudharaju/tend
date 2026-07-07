from carryover import config


def test_defaults_when_no_files():
    cfg = config.load()
    assert cfg.offload_threshold_tokens == 2500
    assert cfg.offload_tools == ("Bash", "Grep", "Glob", "WebFetch")
    assert cfg.advise_pct == 55
    assert cfg.urge_pct == 70


def test_global_override(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("offload_threshold_tokens: 1000\n")
    assert config.load().offload_threshold_tokens == 1000


def test_project_override_wins(carryover_home, tmp_path):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("advise_pct: 50\n")
    proj = tmp_path / "proj" / ".claude" / "carryover"
    proj.mkdir(parents=True)
    (proj / "config.yaml").write_text("advise_pct: 60\n")
    assert config.load(str(tmp_path / "proj")).advise_pct == 60


def test_unknown_keys_ignored(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("bogus_key: 1\n")
    cfg = config.load()
    assert not hasattr(cfg, "bogus_key")


def test_scalar_string_offload_tools(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("offload_tools: Bash\n")
    cfg = config.load()
    assert cfg.offload_tools == ("Bash",)


def test_invalid_values_fall_back_to_defaults(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text(
        "advise_pct:\n"            # empty -> None
        "offload_tools: 42\n"      # wrong type
        "state_stale_tokens: [1]\n"
        "urge_pct: notanumber\n"
        "read_guard_bytes: -1\n"   # negative
    )
    cfg = config.load()
    assert cfg.advise_pct == 55
    assert cfg.offload_tools == ("Bash", "Grep", "Glob", "WebFetch")
    assert cfg.state_stale_tokens == config.DEFAULTS["state_stale_tokens"]
    assert cfg.urge_pct == 70
    assert cfg.read_guard_bytes == 65536


def test_numeric_string_coerced(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text('advise_pct: "60"\n')
    assert config.load().advise_pct == 60


def test_top_level_list_ignored(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("- a\n- b\n")
    assert config.load().advise_pct == 55


def test_unparseable_yaml_ignored(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("advise_pct: [unclosed\n")
    assert config.load().advise_pct == 55


def test_empty_offload_tools_disables_offload(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("offload_tools: []\n")
    assert config.load().offload_tools == ()


def test_delegation_guard_default_and_bool_validation(carryover_home):
    assert config.load().delegation_guard is True
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("delegation_guard: 42\n")  # not a bool
    assert config.load().delegation_guard is True
    (carryover_home / "config.yaml").write_text("delegation_guard: false\n")
    assert config.load().delegation_guard is False


def test_comments_and_blank_lines_ignored(carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text(
        "# tuning\n\nadvise_pct: 60   # nudge earlier\n")
    assert config.load().advise_pct == 60


def test_retention_days_default_and_override(tmp_path, carryover_home):
    assert config.load().retention_days == 30
    p = tmp_path / ".claude" / "carryover"
    p.mkdir(parents=True)
    (p / "config.yaml").write_text("retention_days: 7\n")
    assert config.load(str(tmp_path)).retention_days == 7


def test_no_yaml_dependency():
    """Plugin constraint: carryover must be stdlib-only."""
    import sys
    mods_before = "yaml" in sys.modules
    cfg = config.load()
    assert cfg.advise_pct  # config works
    import carryover.config as c
    src = open(c.__file__).read()
    assert "import yaml" not in src
