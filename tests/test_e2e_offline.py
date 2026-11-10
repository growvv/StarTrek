from __future__ import annotations

from types import SimpleNamespace

from specfcg.cards.store import CardStore
from specfcg.completion.completer import CapabilityCompleter
from specfcg.config import AppConfig
from specfcg.executor.device import FakeDevice
from specfcg.executor.executor import Executor
from specfcg.executor.summarizer import StateSummarizer
from specfcg.graph.store import GraphStore
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.maintainer.updater import GraphUpdater
from specfcg.pipeline import Pipeline
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.planner import Planner
from specfcg.planner.retrieval import CardRetriever
from tests.fakes import FakeLLMClient, FakeProbe

CARD_MARKDOWN = """# create_note

**Intent**: Create a new note and share it.
**Inputs**: none
**Preconditions**: On the notes list.
**Postconditions**: A note exists and is shared.
**Effects/Outputs**: A new shared note.
**Steps**:
1. Tap Next
**Evidence**: traces t1; 1/1 successes
"""


def _fixture_env(tmp_path, sample_trace):
    llm = FakeLLMClient(
        [
            {
                "episodes": [
                    {"start": 0, "end": 3, "name": "create_note"},
                ]
            },
            CARD_MARKDOWN,
            {
                "cards": [
                    {
                        "name": "create_note",
                        "can_execute": True,
                        "is_goal": True,
                    }
                ]
            },
            {"steps": [{"action": "click", "target": "text=Next"}]},
            "Notes list with a plus button",
            {"satisfied": True},
            {"achieved": True},
        ]
    )
    device = FakeDevice(["Notes list", "Editor"], [True])
    card_store = CardStore(tmp_path)
    store = GraphStore(tmp_path, card_store)
    builder = EdgeBuilder(llm)
    miner = CardMiner(llm, card_store)
    graph = store.load()
    planner = Planner(
        graph,
        llm,
        CardRetriever(llm),
        ParamBinder(llm),
        StepCompiler(llm),
    )
    executor = Executor(device, llm, StateSummarizer(llm), graph)
    updater = GraphUpdater(llm, store, builder)
    completer = CapabilityCompleter(
        llm, store, miner, builder, FakeProbe()
    )
    pipeline = Pipeline(
        AppConfig(),
        llm,
        device,
        store,
        card_store,
        miner,
        builder,
        planner,
        executor,
        updater,
        completer,
    )
    return SimpleNamespace(
        pipeline=pipeline,
        trace=sample_trace,
        llm=llm,
        device=device,
    )


def test_offline_pipeline_mines_plans_executes_and_refines(
    tmp_path, sample_trace
):
    fixture_env = _fixture_env(tmp_path, sample_trace)
    pipeline = fixture_env.pipeline

    pipeline.mine_trace(fixture_env.trace)
    assert "create_note" in pipeline.card_store.all()

    plan = pipeline.plan("create a note and share it", "Notes list")
    assert plan is not None

    result = pipeline.executor.execute(plan)
    assert result.goal_success

    patch = pipeline.updater.update(result)
    assert patch.reason
