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
