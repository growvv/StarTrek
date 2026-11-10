from specfcg.executor.summarizer import PlainStateSummarizer, StateSummarizer


def test_summarizer_uses_llm(fake_llm):
    fake_llm.responses = ["Current screen: Notes list\nVisible: + button"]
    assert "Notes list" in StateSummarizer(fake_llm).summarize("<xml/>")


def test_plain_summarizer_uses_no_llm_and_truncates():
    assert (
        PlainStateSummarizer().summarize("x" * 5000)
        == "x" * 2000
    )


def test_summarizer_falls_back_on_llm_error(fake_llm):
    fake_llm.responses = ["", ""]
    out = StateSummarizer(fake_llm).summarize(
        "<xml>" + "x" * 5000 + "</xml>"
    )
    assert out.startswith("<xml>")
    assert len(out) <= 2000
