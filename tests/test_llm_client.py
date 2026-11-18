import pytest

from specfcg.llm.cache import CachedLLMClient
from specfcg.llm.client import LLMParseError
from tests.fakes import FakeLLMClient


def test_cached_client_hits_cache(tmp_path):
    inner = FakeLLMClient(["same", "different"])
    client = CachedLLMClient(inner, tmp_path)
    assert client.complete("p") == "same"
    assert client.complete("p") == "same"
    assert inner.calls == 1


def test_cached_client_counts_hits_and_remote_calls(tmp_path):
    inner = FakeLLMClient(["same"])
    client = CachedLLMClient(inner, tmp_path)

    client.complete("p")
    client.complete("p")

    assert client.misses == 1
    assert client.hits == 1


def test_complete_json_raises_on_malformed():
    client = FakeLLMClient(["not json"])
    with pytest.raises(LLMParseError):
        client.complete_json("p", "{}")


def test_structured_requests_carry_the_configured_override(monkeypatch):
    """Qwen reasons for minutes about a large JSON prompt.

    The switch that turns thinking off belongs to the model, so it travels as
    configuration and is applied to structured calls only: a prose answer may
    still benefit from reasoning, a JSON answer is parsed either way.
    """
    from specfcg.llm.client import OpenAICompatibleClient

    sent = {}

    class _Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": '{"ok": true}'})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    class _Chat:
        completions = _Completions()

    client = OpenAICompatibleClient(
        "m", "k", "http://x",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    monkeypatch.setattr(
        client, "_sdk", lambda: type("S", (), {"chat": _Chat()})()
    )

    client.complete_json("prompt", '{"ok": true}')
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_prose_requests_do_not_carry_the_override(monkeypatch):
    from specfcg.llm.client import OpenAICompatibleClient

    sent = {}

    class _Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": "text"})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    class _Chat:
        completions = _Completions()

    client = OpenAICompatibleClient(
        "m", "k", "http://x",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    monkeypatch.setattr(
        client, "_sdk", lambda: type("S", (), {"chat": _Chat()})()
    )

    client.complete("prompt")
    assert "extra_body" not in sent
