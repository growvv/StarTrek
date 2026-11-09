from specfcg.config import load_config


def test_load_config_merges_defaults(tmp_path):
    p = tmp_path / "llm.yaml"
    p.write_text("llm:\n  model: test-model\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm.model == "test-model"
    assert cfg.llm.temperature == 0.0
    assert cfg.paths.cards == "cards"
