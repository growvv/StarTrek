from specfcg.executor.summarizer import StateSummarizer


def test_summarizer_uses_llm(fake_llm):
    fake_llm.responses = ["Current screen: Notes list\nVisible: + button"]
    assert "Notes list" in StateSummarizer(fake_llm).summarize("<xml/>")


def test_summarizer_falls_back_on_llm_error(fake_llm):
    fake_llm.responses = ["", ""]
    out = StateSummarizer(fake_llm).summarize(
        "<xml>" + "x" * 5000 + "</xml>"
    )
    assert out.startswith("<xml>")
    assert len(out) <= 2000
