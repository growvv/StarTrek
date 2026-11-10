from specfcg.maintainer.builder import EdgeBuilder


def test_build_sequence_edges_from_segments(fake_llm, two_cards):
    segments = [
        {"trace_id": "t1", "start": 0, "end": 1, "card": "create_note"},
        {"trace_id": "t1", "start": 2, "end": 3, "card": "share_note"},
    ]
    fake_llm.responses = [{"edges": []}]
    edges = EdgeBuilder(fake_llm).build(two_cards, segments)
    assert any(
        edge.from_card == "create_note"
        and edge.to_card == "share_note"
        and edge.type == "sequence"
        for edge in edges
    )


def test_build_semantic_edges_from_llm(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": "create_note",
                    "to": "share_note",
                    "type": "enables",
                    "description": "a created note can be shared",
                }
            ]
        }
    ]
    edges = EdgeBuilder(fake_llm).build(two_cards, [])
    assert edges[0].type == "enables"


def test_infer_semantic_prompt_includes_card_inputs(fake_llm, two_cards):
    fake_llm.responses = [{"edges": []}]

    EdgeBuilder(fake_llm).infer_semantic(two_cards)

    prompt = fake_llm.prompts[0]
    assert "inputs=" in prompt
    assert "title" in prompt
    assert "dataflow" in prompt


def test_build_skips_unknown_card_names(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": "missing",
                    "to": "share_note",
                    "type": "enables",
                    "description": "x",
                }
            ]
        }
    ]
    assert EdgeBuilder(fake_llm).infer_semantic(two_cards) == []


def test_infer_semantic_returns_empty_on_malformed_output(fake_llm, two_cards):
    fake_llm.responses = ["not json"]
    assert EdgeBuilder(fake_llm).infer_semantic(two_cards) == []


def test_sequence_edges_do_not_call_llm(fake_llm, two_cards):
    segments = [
        {"trace_id": "t1", "start": 0, "end": 1, "card": "create_note"},
        {"trace_id": "t1", "start": 2, "end": 3, "card": "share_note"},
    ]
    edges = EdgeBuilder(fake_llm).sequence_edges(two_cards, segments)
    assert len(edges) == 1
    assert fake_llm.calls == 0


def test_infer_semantic_skips_non_string_endpoint(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": ["create_note"],
                    "to": "share_note",
                    "type": "enables",
                }
            ]
        }
    ]
    assert EdgeBuilder(fake_llm).infer_semantic(two_cards) == []


def test_infer_semantic_skips_non_string_type(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": "create_note",
                    "to": "share_note",
                    "type": ["enables"],
                }
            ]
        }
    ]
    assert EdgeBuilder(fake_llm).infer_semantic(two_cards) == []


def test_sequence_edges_skip_non_string_card(fake_llm, two_cards):
    segments = [
        {
            "trace_id": "t1",
            "start": 0,
            "end": 0,
            "card": ["create_note"],
        }
    ]
    assert EdgeBuilder(fake_llm).sequence_edges(two_cards, segments) == []


def test_infer_semantic_dedupes_and_merges_evidence(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": "create_note",
                    "to": "share_note",
                    "type": "enables",
                    "description": "first",
                    "evidence": ["t1"],
                },
                {
                    "from": "create_note",
                    "to": "share_note",
                    "type": "enables",
                    "description": "second",
                    "evidence": ["t2"],
                },
            ]
        }
    ]
    edges = EdgeBuilder(fake_llm).infer_semantic(two_cards)
    assert len(edges) == 1
    assert edges[0].description == "second"
    assert edges[0].evidence == ["t1", "t2"]
