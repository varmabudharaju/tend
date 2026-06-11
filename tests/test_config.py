from tend import config


def test_defaults_when_no_files():
    cfg = config.load()
    assert cfg.offload_threshold_tokens == 2500
    assert cfg.offload_tools == ("Bash", "Grep", "Glob", "WebFetch")
    assert cfg.advise_pct == 55
    assert cfg.urge_pct == 70


def test_global_override(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("offload_threshold_tokens: 1000\n")
    assert config.load().offload_threshold_tokens == 1000


def test_project_override_wins(tend_home, tmp_path):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("advise_pct: 50\n")
    proj = tmp_path / "proj" / ".claude" / "tend"
    proj.mkdir(parents=True)
    (proj / "config.yaml").write_text("advise_pct: 60\n")
    assert config.load(str(tmp_path / "proj")).advise_pct == 60


def test_unknown_keys_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("bogus_key: 1\n")
    cfg = config.load()
    assert not hasattr(cfg, "bogus_key")


def test_scalar_string_offload_tools(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("offload_tools: Bash\n")
    cfg = config.load()
    assert cfg.offload_tools == ("Bash",)


def test_invalid_values_fall_back_to_defaults(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
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


def test_numeric_string_coerced(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('advise_pct: "60"\n')
    assert config.load().advise_pct == 60


def test_top_level_list_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("- a\n- b\n")
    assert config.load().advise_pct == 55


def test_unparseable_yaml_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("advise_pct: [unclosed\n")
    assert config.load().advise_pct == 55


def test_empty_offload_tools_disables_offload(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("offload_tools: []\n")
    assert config.load().offload_tools == ()


def test_delegation_guard_default_and_bool_validation(tend_home):
    assert config.load().delegation_guard is True
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("delegation_guard: 42\n")  # not a bool
    assert config.load().delegation_guard is True
    (tend_home / "config.yaml").write_text("delegation_guard: false\n")
    assert config.load().delegation_guard is False
