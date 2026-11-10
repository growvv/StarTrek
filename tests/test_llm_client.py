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
