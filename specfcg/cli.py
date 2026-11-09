"""Command-line interface for the SpecFCG pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from specfcg.cards.store import CardStore
from specfcg.completion.completer import CapabilityCompleter
from specfcg.completion.probe import DeviceProbe
from specfcg.config import AppConfig, load_config
from specfcg.executor.device import FakeDevice, Uiautomator2Device
from specfcg.executor.executor import Executor
from specfcg.executor.summarizer import StateSummarizer
from specfcg.graph.store import GraphStore
from specfcg.llm.cache import CachedLLMClient
from specfcg.llm.client import LLMClient, OpenAICompatibleClient
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.maintainer.updater import GraphUpdater
from specfcg.pipeline import Pipeline
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.planner import Planner
from specfcg.planner.retrieval import CardRetriever
from specfcg.traces.recorder import TraceParseError, trace_from_dict

_STEP_LINE_RE = re.compile(r"^\d+\.\s+action=", re.MULTILINE)

_OFFLINE_CARD = """# create_note

**Intent**: Create a new note.
**Inputs**: none
**Preconditions**: On the notes list.
**Postconditions**: A note exists.
**Effects/Outputs**: A new note in the list.
**Steps**:
1. Tap Next
**Evidence**: traces offline; 1/1 successes
"""


class _OfflineLLM:
    """Prompt-aware deterministic stand-in used by --fake-llm."""

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        if "Write one Markdown function card" in prompt:
            return _OFFLINE_CARD
        return "screen: notes list; visible: notes and a plus button"

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        if "Split this trace" in prompt:
            end = max(0, len(_STEP_LINE_RE.findall(prompt)) - 1)
            return {
                "episodes": [
                    {
                        "start": 0,
                        "end": end,
                        "name": "create_note",
                        "intent": "create a note",
                    }
                ]
            }
        if "Can this card execute" in prompt:
            return {"can_execute": True}
        if "Does executing this card satisfy" in prompt:
            return {"is_goal": True}
        if "Bind every required input" in prompt:
            return {"bindings": {}}
        if "Convert these function-card steps" in prompt:
            return {
                "steps": [
                    {"action": "click", "target": "text=Next", "args": ""}
                ]
            }
        if "Are the postconditions satisfied" in prompt:
            return {"satisfied": True}
        if "Is the goal achieved" in prompt:
            return {"achieved": True}
        if "Infer directed semantic edges" in prompt:
            return {"edges": []}
        if "Is a capability missing" in prompt:
            return {"gap": None}
        if "Propose up to" in prompt:
            return {"capabilities": []}
        if "Classify the failure" in prompt:
            return {"failure_type": "widget_failure"}
        return {}


def _build_pipeline(
    config: AppConfig, fake_llm: bool, fake_device: bool
) -> Pipeline:
    root = Path(config.paths.root)
    card_store = CardStore(root)
    store = GraphStore(root, card_store)

    llm: LLMClient
    if fake_llm:
        llm = _OfflineLLM()
    else:
        api_key = os.environ.get(config.llm.api_key_env, "")
        inner = OpenAICompatibleClient(
            config.llm.model, api_key, config.llm.base_url
        )
        llm = CachedLLMClient(inner, Path(config.llm.cache_dir))

    device = (
        FakeDevice(["offline state"], [True] * 64)
        if fake_device
        else Uiautomator2Device(config.device.serial)
    )
    builder = EdgeBuilder(llm)
    miner = CardMiner(llm, card_store)
    compiler = StepCompiler(llm)
    graph = store.load()
    planner = Planner(
        graph, llm, CardRetriever(llm), ParamBinder(llm), compiler
    )
    summarizer = StateSummarizer(llm)
    executor = Executor(device, llm, summarizer, graph)
    updater = GraphUpdater(llm, store, builder)
    completer = CapabilityCompleter(
        llm,
        store,
        miner,
        builder,
        DeviceProbe(device, compiler),
    )
    return Pipeline(
        config,
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


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _cmd_mine(pipeline: Pipeline, trace_path: Path) -> int:
    raw = json.loads(trace_path.read_text(encoding="utf-8"))
    trace = trace_from_dict(raw)
    patch = pipeline.mine_trace(trace)
    _print_json(asdict(patch))
    return 0


def _cmd_build_graph(pipeline: Pipeline, segments_path: Path | None) -> int:
    segments: list[dict[str, Any]] = []
    if segments_path is not None:
        raw = json.loads(segments_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("segments JSON must be a list")
        segments = raw
    edges = pipeline.build_graph(segments)
    _print_json([asdict(edge) for edge in edges])
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--fake-llm", action="store_true")
    parser.add_argument("--fake-device", action="store_true")


def _add_goal(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goal", required=True)
    parser.add_argument("--state", default="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specfcg")
    commands = parser.add_subparsers(dest="command", required=True)

    mine_parser = commands.add_parser("mine")
    _add_common(mine_parser)
    mine_parser.add_argument("--trace", required=True)

    build_parser = commands.add_parser("build-graph")
    _add_common(build_parser)
    build_parser.add_argument("--segments", default=None)

    plan_parser = commands.add_parser("plan")
    _add_common(plan_parser)
    _add_goal(plan_parser)

    execute_parser = commands.add_parser("execute")
    _add_common(execute_parser)
    _add_goal(execute_parser)

    refine_parser = commands.add_parser("refine")
    _add_common(refine_parser)
    _add_goal(refine_parser)

    complete_parser = commands.add_parser("complete")
    _add_common(complete_parser)
    _add_goal(complete_parser)

    run_parser = commands.add_parser("run")
    _add_common(run_parser)
    _add_goal(run_parser)
    run_parser.add_argument("--max-rounds", type=int, default=2)

    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
        pipeline = _build_pipeline(
            config, args.fake_llm, args.fake_device
        )

        if args.command == "mine":
            return _cmd_mine(pipeline, Path(args.trace))
        if args.command == "build-graph":
            segments_path = (
                Path(args.segments) if args.segments else None
            )
            return _cmd_build_graph(pipeline, segments_path)
        if args.command == "plan":
            plan = pipeline.plan(args.goal, args.state)
            _print_json(asdict(plan) if plan is not None else None)
            return 0 if plan is not None else 1
        if args.command == "execute":
            result = pipeline.execute_goal(args.goal, args.state)
            _print_json(asdict(result) if result is not None else None)
            return 0 if result is not None else 1
        if args.command == "refine":
            patch = pipeline.refine(args.goal, args.state)
            _print_json(asdict(patch) if patch is not None else None)
            return 0 if patch is not None else 1
        if args.command == "complete":
            patch = pipeline.complete(args.goal, args.state)
            _print_json(asdict(patch) if patch is not None else None)
            return 0
        if args.command == "run":
            summary = pipeline.run_goal(
                args.goal, args.state, args.max_rounds
            )
            _print_json(summary)
            return 0 if summary["goal_success"] else 1
    except (OSError, ValueError, TraceParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
