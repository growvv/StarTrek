# SpecFCG Stage 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the Stage 1 MVP of SpecFCG: a Python system that mines natural-language function cards from Android GUI traces, builds a Function Contract Graph, plans goal-driven test paths, executes them on an emulator, refines the graph, and completes missing capabilities.

**Architecture:** Five modules — Trace Collector, Graph Maintainer (card mining + graph updates), Graph Store (cards + edges + versioning), Planner (BFS/DFS/A* with LLM transition checks), Executor (uiautomator2 device + LLM state summaries). The offline core is fully testable with fakes; the ProphetAgent adapter and real device are integration layers. A thin `Pipeline` composes the modules for the CLI and benchmarks. **Superseded in the Next Round:** a card becomes a contract with no UI steps, the planner emits a task description, and a GUI agent — not a scripted replay — executes it. Tasks 1–17 below record the MVP as it was built; the Next Round section is the current design.

**Tech Stack:** Python 3.10+, pytest, PyYAML, `openai` SDK (OpenAI-compatible endpoint), `uiautomator2` (optional device extra), ADB. No graph library — the graph is small and BFS/DFS/A* are implemented directly.

**Spec:** `docs/superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md`

## Global Constraints

- Python `>=3.10`; code runs on Windows, macOS, and Linux.
- Function granularity is **user-level task** (`create_note`, `attach_photo`, `share_note`), never page-level or widget-level.
- Cards and edges are **natural language first**; no typed predicate DSL, no symbolic state tracker, no formal condition parser.
- Edge types: `enables`, `dataflow`, `sequence`; `calls` is optional and only used when a card's steps literally contain another card. **Next Round:** a card has no steps, so `calls` is removed from `EdgeType` (Task F).
- Every LLM call uses `temperature=0` and goes through the cache; model and base URL are configurable in `config/llm.yaml`.
- All LLM outputs are parsed defensively. Malformed JSON/Markdown must produce a typed error or a documented fallback — never an uncaught exception that kills a run. **Next Round:** an unparseable card is a typed `CardParseError`; the miner returns no card and skips the episode with a warning naming the trace, rather than inventing a card (Task F).
- Stage 1 apps: AnkiDroid, AmazeFileManager, OmniNotes, NewPipe, ActivityDiary, AntennaPod.
- Stage 1 data: 60 NL cases (10/app) and 30 compositional goals (5/app); held-out traces for path recall.
- Stage 1 gates: card validity ≥ 80% on 50 human-checked cards; path recall ≥ 70%; known-case completion ≥ 70%; compositional completion ≥ 50% and ≥ 20 points above ProphetAgent; ≥ 3 new capabilities/bugs.
- ProphetAgent is pinned at commit `97667bfe109e71f57d84a2f7df9bcb03aba55b11` (MIT). It is used for trace collection via its bundled Droidbot; the MVP executor uses `uiautomator2` directly. **Next Round:** the executor hands the task description to a GUI agent (`mobile_agent`), and nothing replays a recorded action.
- MVP retrieval uses keyword prefilter + LLM confirmation. Embedding retrieval is a Stage 2 optimization (documented deviation).
- MVP target resolution uses text / resource-id / LLM fallback. ProphetAgent's CUTG matcher is a Stage 2 integration (documented deviation).
- No formal verification, no completeness guarantee, no Android static call graph.
- Artifacts live under `cards/`, `graph/`, `traces/`, `runs/`, `state/`, `completion/`.

## Review Focus

These are the failure modes most likely to bite a user, and each gets a test in the owning task:

1. **Malformed LLM output** — `complete_json` raises `LLMParseError`; miner falls back to a heuristic card; executor records `check_error` instead of crashing. Owning tasks: 1, 6, 9, 11.
2. **Trace with no clear boundary or a single-step trace** — miner returns a single-episode fallback or a usable card, or an empty patch for an empty trace. Owning task: 6.
3. **Duplicate or conflicting cards/edges** — store dedupes by `(from, to, type)`, preserves evidence, and skips edges with unknown endpoints. Owning tasks: 3, 7.
4. **Planner no path or cycle** — search terminates with `None`, and the planner triggers completion rather than looping. Owning tasks: 4, 11.
5. **Executor mid-plan failure** — `RunResult` records a partial trace and the failure type; the updater must not corrupt the graph. Owning task: 9.

---

## File Structure

```text
pyproject.toml
.gitignore
config/
  llm.example.yaml
specfcg/
  __init__.py
  config.py                 # YAML config dataclasses
  models.py                 # shared dataclasses
  pipeline.py               # composes modules for CLI/e2e
  cli.py                    # argparse entry point
  llm/
    __init__.py
    client.py               # LLMClient protocol + OpenAI-compatible client
    cache.py                # disk cache wrapper
  cards/
    __init__.py
    parser.py               # Markdown card <-> FunctionCard
    store.py                # cards/*.md CRUD
  graph/
    __init__.py
    store.py                # edges.jsonl + versioning + patch application
    search.py               # BFS/DFS/A*
  traces/
    __init__.py
    recorder.py             # TraceRecorder + TraceStore
    collector.py            # TraceCollector protocol + fixture collector
  maintainer/
    __init__.py
    miner.py                # trace segmentation + card drafting
    builder.py              # edge inference
    updater.py              # failure classification + graph patches
  planner/
    __init__.py
    retrieval.py            # card retrieval
    binding.py              # parameter binding
    compiler.py             # card steps -> PlanStep
    planner.py              # graph search + plan assembly
  executor/
    __init__.py
    device.py               # Device protocol + FakeDevice + Uiautomator2Device
    summarizer.py           # UI dump -> NL state summary
    executor.py             # TestPlan execution + RunResult
  completion/
    __init__.py
    completer.py            # gap detection + hypothesis + probe
  benchmark/
    __init__.py
    cases.py                # AppSpec / NLTestCase / CompositionalGoal loaders
    metrics.py              # completion, accuracy, path recall, coverage
    runner.py               # run cases and aggregate
  integrations/
    __init__.py
    prophetagent.py         # Droidbot output parser + collector adapter
tests/
  __init__.py
  fakes.py
  fixtures/
  test_*.py
scripts/
  setup_prophetagent.sh
  run_stage1.py
benchmark/
  apps.yaml
  cases/
  goals/
```

---

### Task 1: Foundation — config and LLM client

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `config/llm.example.yaml`, `specfcg/__init__.py`, `specfcg/config.py`, `specfcg/llm/__init__.py`, `specfcg/llm/client.py`, `specfcg/llm/cache.py`, `tests/__init__.py`, `tests/fakes.py`, `tests/test_config.py`, `tests/test_llm_client.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - `LLMConfig`, `DeviceConfig`, `PathConfig`, `AppConfig` dataclasses in `specfcg/config.py`.
  - `load_config(path: Path) -> AppConfig`.
  - `LLMClient` Protocol with `complete(prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str` and `complete_json(prompt: str, schema_hint: str, *, system: str | None = None) -> dict`.
  - `OpenAICompatibleClient(model: str, api_key: str, base_url: str | None = None)`.
  - `CachedLLMClient(inner: LLMClient, cache_dir: Path)`.
  - `LLMParseError(Exception)`.
  - `FakeLLMClient` in `tests/fakes.py` with `responses: list[str | dict]` and a `calls` counter.

- [x] **Step 1: Initialize the repo and branch**

```bash
git init
git checkout -b feat/specfcg-mvp
```

Create `pyproject.toml`:

```toml
[project]
name = "specfcg"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["pyyaml>=6.0", "openai>=1.60"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]
device = ["uiautomator2>=3.0"]

[project.scripts]
specfcg = "specfcg.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `.gitignore` with `.venv/`, `__pycache__/`, `.pytest_cache/`, `.cache/`, `runs/`, `traces/`, `third_party/`.

- [x] **Step 2: Write the failing tests**

`tests/test_config.py`:

```python
def test_load_config_merges_defaults(tmp_path):
    p = tmp_path / "llm.yaml"
    p.write_text("llm:\n  model: test-model\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm.model == "test-model"
    assert cfg.llm.temperature == 0.0
    assert cfg.paths.cards == "cards"
```

`tests/test_llm_client.py`:

```python
def test_cached_client_hits_cache(tmp_path):
    inner = FakeLLMClient(["same", "different"])
    client = CachedLLMClient(inner, tmp_path)
    assert client.complete("p") == "same"
    assert client.complete("p") == "same"
    assert inner.calls == 1

def test_complete_json_raises_on_malformed():
    client = FakeLLMClient(["not json"])
    with pytest.raises(LLMParseError):
        client.complete_json("p", "{}")
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py tests/test_llm_client.py -v`

Expected: FAIL with import errors (`load_config`/`CachedLLMClient` not defined).

- [x] **Step 4: Implement the config, client, cache, and fakes**

`specfcg/config.py`:

```python
@dataclass
class LLMConfig:
    model: str = "gpt-4.1"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    temperature: float = 0.0
    cache_dir: str = ".cache/llm"

@dataclass
class DeviceConfig:
    serial: str | None = None
    timeout_s: int = 30

@dataclass
class PathConfig:
    root: str = "."
    cards: str = "cards"
    graph: str = "graph"
    traces: str = "traces"
    runs: str = "runs"
    state: str = "state"
    completion: str = "completion"

@dataclass
class AppConfig:
    llm: LLMConfig
    device: DeviceConfig
    paths: PathConfig

def load_config(path: Path) -> AppConfig: ...
```

`specfcg/llm/client.py`: `LLMClient` Protocol, `LLMParseError`, `OpenAICompatibleClient` (lazy `from openai import OpenAI`), `complete_json` extracts the first JSON object from the response (handles ```json fences) and raises `LLMParseError` on failure.

`specfcg/llm/cache.py`: `CachedLLMClient` computes `sha256(method + "\0" + prompt + "\0" + system + "\0" + temperature)` and stores raw responses / JSON dicts under `<cache_dir>/<hash>.json`. Cache hit does not call `inner`.

`tests/fakes.py`: `FakeLLMClient` pops from `responses`; `complete` returns the string; `complete_json` parses a string or returns a dict; increments `calls`.

- [x] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py tests/test_llm_client.py -v`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore config specfcg tests
git commit -m "chore: scaffold specfcg with config and LLM client"
```

---

### Task 2: Shared models and function-card parser

**Files:**
- Create: `specfcg/models.py`, `specfcg/cards/__init__.py`, `specfcg/cards/parser.py`, `tests/test_models.py`, `tests/test_card_parser.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - Dataclasses `Step`, `Trace`, `FunctionCard`, `Edge`, `Graph`, `Goal`, `PlanStep`, `TestPlan`, `RunResult`, `CardPatch`, `GraphPatch`, `MissingCapability` in `specfcg/models.py`.
  - `EdgeType = Literal["enables", "dataflow", "sequence", "calls"]`.
  - `FailureType = Literal["precondition_mismatch", "widget_failure", "trace_failure", "postcondition_failure", "goal_failure", "environment_failure", "check_error"]`.
  - `parse_card(text: str) -> FunctionCard` and `render_card(card: FunctionCard) -> str` in `specfcg/cards/parser.py`.
  - `CardParseError(Exception)`.

Key fields:

```python
@dataclass
class FunctionCard:
    name: str
    intent: str
    inputs: list[str]
    preconditions: str
    postconditions: str
    effects_outputs: str
    steps: list[str]
    evidence: list[str] = field(default_factory=list)
    success_count: int = 0
    attempt_count: int = 0

@dataclass
class CardPatch:
    new_cards: list[FunctionCard] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
```

- [x] **Step 1: Write the failing tests**

`tests/test_card_parser.py`:

```python
def test_card_round_trip(sample_card):
    assert parse_card(render_card(sample_card)) == sample_card

def test_parse_card_missing_heading_raises():
    with pytest.raises(CardParseError):
        parse_card("# broken\n\n**Intent**: only intent")

def test_parse_evidence_counts(sample_card):
    card = parse_card(render_card(sample_card))
    assert card.success_count == 2
    assert card.attempt_count == 3
    assert card.evidence == ["t1", "t2"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_card_parser.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the models and parser**

Parser rules: the first line is `# name`; headings are `**Intent**:`, `**Inputs**:`, `**Preconditions**:`, `**Postconditions**:`, `**Effects/Outputs**:`, `**Steps**:`, `**Evidence**:`. Steps are numbered lines after the `**Steps**:` heading. Evidence parses `traces t1, t2; 2/3 successes` into `evidence=["t1","t2"]`, `success_count=2`, `attempt_count=3`; if no counts, both stay 0. Missing required headings raise `CardParseError`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_card_parser.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/models.py specfcg/cards tests/test_models.py tests/test_card_parser.py
git commit -m "feat: add shared models and function-card parser"
```

---

### Task 3: Card store, graph store, and versioning

**Files:**
- Create: `specfcg/cards/store.py`, `specfcg/graph/__init__.py`, `specfcg/graph/store.py`, `tests/test_card_store.py`, `tests/test_graph_store.py`

**Interfaces:**
- Consumes: `FunctionCard`, `Edge`, `Graph`, `GraphPatch` from Task 2.
- Produces:
  - `CardStore(root: Path)`: `save(card)`, `load(name) -> FunctionCard`, `all() -> dict[str, FunctionCard]`, `delete(name)`.
  - `GraphStore(root: Path, cards: CardStore)`: `load() -> Graph`, `edges() -> list[Edge]`, `apply_patch(patch: GraphPatch) -> None`, `backup() -> Path`, `restore(version: Path) -> None`, `neighbors(name: str, type: str | None = None) -> list[Edge]`.
  - `GraphStore` dedupes edges by `(from_card, to_card, type)`; a duplicate updates `description` and merges `evidence`.

- [x] **Step 1: Write the failing tests**

`tests/test_card_store.py`:

```python
def test_card_store_saves_and_loads(tmp_path, sample_card):
    store = CardStore(tmp_path)
    store.save(sample_card)
    assert store.load(sample_card.name) == sample_card

def test_malformed_card_file_is_skipped(tmp_path, sample_card):
    store = CardStore(tmp_path)
    store.save(sample_card)
    (tmp_path / "cards" / "broken.md").write_text("# broken", encoding="utf-8")
    assert list(store.all()) == [sample_card.name]
```

`tests/test_graph_store.py`:

```python
def test_duplicate_edge_is_deduped(tmp_path, sample_card, another_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    cards.save(another_card)
    store = GraphStore(tmp_path, cards)
    store.apply_patch(GraphPatch(edge_updates=[
        {"from": sample_card.name, "to": another_card.name, "type": "enables",
         "action": "add", "description": "d1", "evidence": ["t1"]}
    ]))
    store.apply_patch(GraphPatch(edge_updates=[
        {"from": sample_card.name, "to": another_card.name, "type": "enables",
         "action": "add", "description": "d2", "evidence": ["t2"]}
    ]))
    edges = store.edges()
    assert len(edges) == 1
    assert edges[0].description == "d2"
    assert edges[0].evidence == ["t1", "t2"]

def test_backup_and_restore(tmp_path, sample_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    store = GraphStore(tmp_path, cards)
    version = store.backup()
    store.apply_patch(GraphPatch(card_updates=[
        {"name": sample_card.name, "fields": {"Intent": "changed"}}
    ]))
    store.restore(version)
    assert store.load().cards[sample_card.name].intent == sample_card.intent
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_card_store.py tests/test_graph_store.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the stores**

`CardStore` uses `cards/<slug>.md`; slug lowercases and replaces non-alphanumerics with `_`. `all()` logs and skips malformed files. `GraphStore` loads `graph/edges.jsonl`; `apply_patch` handles `new_cards`, `card_updates`, `edge_updates` (`add`/`update`/`remove`), `split` (delete the old card; replacements come from `new_cards`), and `merge` (keep the first card, merge evidence, delete the second, rewrite edges). `backup()` copies `cards/` and `graph/edges.jsonl` to `graph/versions/<timestamp>/`. `restore()` replaces both from the backup.

`neighbors(name, type=None)` returns outgoing edges ordered by type priority: `enables`, `dataflow`, `sequence`, `calls`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_card_store.py tests/test_graph_store.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/cards/store.py specfcg/graph tests/test_card_store.py tests/test_graph_store.py
git commit -m "feat: add card store, graph store, and versioning"
```

---

### Task 4: Graph search (BFS/DFS/A*)

**Files:**
- Create: `specfcg/graph/search.py`, `tests/test_graph_search.py`

**Interfaces:**
- Consumes: `Graph`, `Edge` from Task 2.
- Produces:

```python
def search(
    graph: Graph,
    start: str | None,
    can_execute: Callable[[str], bool],
    is_goal: Callable[[str], bool],
    strategy: Literal["bfs", "dfs", "astar"] = "bfs",
    max_depth: int = 8,
    heuristic: Callable[[str], float] | None = None,
) -> list[str] | None
```

Semantics: `start=None` means all cards are initial candidates; otherwise expand neighbors of `start`. The returned list is the card execution path. `can_execute` gates expansion. `is_goal` is checked on each candidate; the path ends at the goal card. Cycles are prevented with a visited set; `max_depth` bounds the path length.

- [x] **Step 1: Write the failing tests**

```python
def test_bfs_finds_shortest_path(simple_graph):
    path = search(simple_graph, None, lambda c: True, lambda c: c == "C", "bfs")
    assert path == ["A", "C"]

def test_cycle_does_not_loop(simple_graph):
    assert search(simple_graph, "A", lambda c: True, lambda c: c == "Z", "bfs") is None

def test_max_depth_respected(long_chain):
    assert search(long_chain, None, lambda c: True, lambda c: c == "Z", "dfs", max_depth=3) is None

def test_astar_uses_heuristic(simple_graph):
    path = search(simple_graph, None, lambda c: True, lambda c: c == "C", "astar",
                  heuristic=lambda c: 0.0)
    assert path is not None and path[-1] == "C"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_graph_search.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement `search`**

Use adjacency from `graph.edges`. BFS uses `collections.deque` of paths; DFS uses a list as a stack; A* uses `heapq` with `(cost + heuristic(card), cost, path)`. Edge priority: `enables`, `dataflow`, `sequence`, `calls`. Mark candidates visited before enqueueing; skip visited candidates. Return `None` when the frontier is exhausted.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_graph_search.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/graph/search.py tests/test_graph_search.py
git commit -m "feat: add BFS/DFS/A* graph search"
```

---

### Task 5: Trace recording and collector

**Files:**
- Create: `specfcg/traces/__init__.py`, `specfcg/traces/recorder.py`, `specfcg/traces/collector.py`, `tests/test_trace_recorder.py`

**Interfaces:**
- Consumes: `Step`, `Trace` from Task 2.
- Produces:
  - `TraceRecorder(app: str, trace_id: str)`: `record(step: Step) -> None`, `trace() -> Trace`, `save(path: Path) -> None`.
  - `TraceStore(root: Path)`: `save(trace: Trace) -> Path`, `load(trace_id: str) -> Trace`, `all() -> list[Trace]`.
  - `TraceCollector` Protocol: `collect(app: str, policy: str = "greedy_dfs") -> list[Trace]`.
  - `FixtureCollector(root: Path)` loads all JSON traces under a directory.

- [x] **Step 1: Write the failing tests**

```python
def test_trace_round_trip(tmp_path, sample_trace):
    store = TraceStore(tmp_path)
    path = store.save(sample_trace)
    assert store.load(sample_trace.trace_id) == sample_trace
    assert path.exists()

def test_fixture_collector_returns_traces(tmp_path, sample_trace):
    store = TraceStore(tmp_path)
    store.save(sample_trace)
    assert FixtureCollector(tmp_path).collect("omninotes") == [sample_trace]

def test_malformed_trace_json_raises(tmp_path):
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(TraceParseError):
        TraceStore(tmp_path).load("bad")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_trace_recorder.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement recorder/store/collector**

Trace JSON is `{"trace_id": ..., "app": ..., "steps": [Step fields]}`. `TraceParseError(Exception)` wraps JSON/shape errors. `FixtureCollector` filters by `trace.app` and returns an empty list when none match.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_trace_recorder.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/traces tests/test_trace_recorder.py
git commit -m "feat: add trace recorder, store, and fixture collector"
```

---

### Task 6: Function-card miner

**Files:**
- Create: `specfcg/maintainer/__init__.py`, `specfcg/maintainer/miner.py`, `tests/test_miner.py`

**Interfaces:**
- Consumes: `Trace`, `FunctionCard`, `CardPatch` (Task 2); `LLMClient` (Task 1); `CardStore` (Task 3).
- Produces:
  - `CardMiner(llm: LLMClient, cards: CardStore)`.
  - `segment(trace: Trace) -> list[dict]` where each dict is `{"start": int, "end": int, "name": str, "intent": str}`.
  - `draft(episode: dict, trace: Trace) -> FunctionCard`.
  - `mine(trace: Trace) -> CardPatch` with `segments` filled for `{trace_id, start, end, card}`.

- [x] **Step 1: Write the failing tests**

```python
def test_segment_returns_llm_boundaries(fake_llm, sample_trace):
    fake_llm.responses = [{"episodes": [
        {"start": 0, "end": 1, "name": "create_note", "intent": "create a note"},
        {"start": 2, "end": 3, "name": "share_note", "intent": "share a note"},
    ]}]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert [s["name"] for s in segments] == ["create_note", "share_note"]

def test_segment_invalid_boundaries_falls_back_to_single_episode(fake_llm, sample_trace):
    fake_llm.responses = [{"episodes": [{"start": 5, "end": 99}]}]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert len(segments) == 1
    assert segments[0]["start"] == 0

def test_mine_empty_trace_returns_empty_patch(fake_llm, empty_trace):
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(empty_trace)
    assert patch.new_cards == [] and patch.segments == []

def test_mine_single_step_trace_produces_card(fake_llm, single_step_trace):
    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 0, "name": "open_app", "intent": "open the app"}]},
        "# open_app\n\n**Intent**: open the app\n**Inputs**: none\n**Preconditions**: app closed\n**Postconditions**: app is open\n**Effects/Outputs**: none\n**Steps**:\n1. Tap the icon\n**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(single_step_trace)
    assert patch.new_cards[0].name == "open_app"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_miner.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the miner**

Prompts:

- Segmentation: "Split this trace into user-level function episodes. Return JSON `{episodes:[{start,end,name,intent}]}`. Boundaries are inclusive step indices."
- Card drafting: "Write a Markdown function card with headings Intent, Inputs, Preconditions, Postconditions, Effects/Outputs, Steps, Evidence. Use the trace evidence."

Validation: segments must be non-overlapping, sorted, within `[0, len(steps)-1]`; otherwise fall back to one episode spanning the whole trace. `draft` parses the LLM Markdown with `parse_card`; on `CardParseError`, build a minimal card from the episode (`name`, `intent`, `steps=[step.action + " " + step.target]`, empty pre/post). `mine` merges with an existing card of the same name by appending evidence and incrementing counts; otherwise adds a new card. `mine` returns an empty patch for an empty trace. Each segment maps to `{"trace_id": trace.trace_id, "start": episode["start"], "end": episode["end"], "card": card.name}`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_miner.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/maintainer tests/test_miner.py
git commit -m "feat: add trace segmentation and function-card mining"
```

---

### Task 7: Edge builder

**Files:**
- Create: `specfcg/maintainer/builder.py`, `tests/test_edge_builder.py`

**Interfaces:**
- Consumes: `FunctionCard`, `Edge`, `CardPatch` segments (Tasks 2, 6); `LLMClient` (Task 1).
- Produces:
  - `EdgeBuilder(llm: LLMClient)`.
  - `build(cards: dict[str, FunctionCard], segments: list[dict]) -> list[Edge]`: adds `sequence` edges between consecutive cards in each trace, and LLM-inferred `enables`/`dataflow` edges for card pairs seen together.
  - `infer_semantic(cards: dict[str, FunctionCard]) -> list[Edge]`: LLM returns `{"edges":[{"from":...,"to":...,"type":"enables|dataflow","description":...}]}`.

- [x] **Step 1: Write the failing tests**

```python
def test_build_sequence_edges_from_segments(fake_llm, two_cards):
    segments = [
        {"trace_id": "t1", "start": 0, "end": 1, "card": "create_note"},
        {"trace_id": "t1", "start": 2, "end": 3, "card": "share_note"},
    ]
    fake_llm.responses = [{"edges": []}]
    edges = EdgeBuilder(fake_llm).build(two_cards, segments)
    assert any(e.from_card == "create_note" and e.to_card == "share_note"
               and e.type == "sequence" for e in edges)

def test_build_semantic_edges_from_llm(fake_llm, two_cards):
    fake_llm.responses = [{"edges": [
        {"from": "create_note", "to": "share_note", "type": "enables",
         "description": "a created note can be shared"}
    ]}]
    edges = EdgeBuilder(fake_llm).build(two_cards, [])
    assert edges[0].type == "enables"

def test_build_skips_unknown_card_names(fake_llm, two_cards):
    fake_llm.responses = [{"edges": [
        {"from": "missing", "to": "share_note", "type": "enables", "description": "x"}
    ]}]
    assert EdgeBuilder(fake_llm).infer_semantic(two_cards) == []
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_edge_builder.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the builder**

Sequence edges: group segments by `trace_id`, sort by `start`, add an edge for each consecutive pair. Semantic edges: send card names/intents/pre/post to the LLM; validate `from`/`to` exist and `type` is `enables` or `dataflow`; skip invalid entries. Deduplicate by `(from, to, type)` and merge evidence.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_edge_builder.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/maintainer/builder.py tests/test_edge_builder.py
git commit -m "feat: add sequence and semantic edge builder"
```

---

### Task 8: Device abstraction and state summarizer

**Files:**
- Create: `specfcg/executor/__init__.py`, `specfcg/executor/device.py`, `specfcg/executor/summarizer.py`, `tests/test_device.py`, `tests/test_summarizer.py`

**Interfaces:**
- Consumes: `LLMClient` (Task 1).
- Produces:
  - `Device` Protocol: `start_app(app: str) -> None`, `dump_ui() -> str`, `execute(action: str, target: str, args: str = "") -> bool`, `screenshot(path: Path) -> None`.
  - `FakeDevice(states: list[str], action_results: list[bool])`.
  - `Uiautomator2Device(serial: str | None = None)` (lazy import of `uiautomator2`).
  - `StateSummarizer(llm: LLMClient)` with `summarize(ui_dump: str) -> str`.

- [x] **Step 1: Write the failing tests**

```python
def test_fake_device_returns_states_in_order():
    d = FakeDevice(["s1", "s2"], [True, False])
    assert d.dump_ui() == "s1"
    assert d.execute("click", "Save") is True
    assert d.dump_ui() == "s2"
    assert d.execute("click", "Missing") is False

def test_summarizer_uses_llm(fake_llm):
    fake_llm.responses = ["Current screen: Notes list\nVisible: + button"]
    assert "Notes list" in StateSummarizer(fake_llm).summarize("<xml/>")

def test_summarizer_falls_back_on_llm_error(fake_llm):
    fake_llm.responses = ["", ""]
    out = StateSummarizer(fake_llm).summarize("<xml>" + "x" * 5000 + "</xml>")
    assert out.startswith("<xml>")
    assert len(out) <= 2000
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_device.py tests/test_summarizer.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the device and summarizer**

`FakeDevice` pops states and action results; `dump_ui` returns the current state (last one repeats); `execute` records calls. `Uiautomator2Device` maps actions:
- `click`: `d(text=target).click()` if target starts with `text=`, else `d(resourceId=target).click()`.
- `input`: `d(text=target).set_text(args)`.
- `back`: `d.press("back")`.
- `swipe`: `d.swipe(...)` with `args` formatted `x1,y1,x2,y2`.
- `wait`: `time.sleep(float(args or 1))`.

`StateSummarizer` prompts: "Summarize this Android UI hierarchy in at most 6 lines: current screen, visible widgets, user state, known entities, recent actions." On any exception or empty response, return `ui_dump[:2000]`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_device.py tests/test_summarizer.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/executor tests/test_device.py tests/test_summarizer.py
git commit -m "feat: add device abstraction and state summarizer"
```

---

### Task 9: Executor

**Files:**
- Create: `specfcg/executor/executor.py`, `tests/test_executor.py`

**Interfaces:**
- Consumes: `TestPlan`, `PlanStep`, `RunResult`, `Trace`, `Step`, `Graph`, `FailureType` (Task 2); `Device`, `FakeDevice` (Task 8); `StateSummarizer` (Task 8); `LLMClient` (Task 1).
- Produces:
  - `Executor(device: Device, llm: LLMClient, summarizer: StateSummarizer, graph: Graph)`.
  - `execute(plan: TestPlan) -> RunResult`.

Behavior: start the app, summarize the initial UI, execute each `PlanStep` in order, record before/after states, then after the last step of each card ask the LLM whether the card's postconditions hold. At the end ask the LLM whether the goal is achieved. `success = all steps succeeded and all postconditions satisfied and goal_success`.

- [x] **Step 1: Write the failing tests**

```python
def test_execute_success_returns_goal_success(fake_device, fake_llm, sample_graph, sample_plan):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "ok"},   # card postcondition
        {"achieved": True, "reason": "ok"},    # goal
    ]
    result = Executor(fake_device, fake_llm, StateSummarizer(fake_llm), sample_graph).execute(sample_plan)
    assert result.success and result.goal_success

def test_execute_records_partial_trace_on_step_failure(fake_device, fake_llm, sample_graph, sample_plan):
    fake_device = FakeDevice(["start", "after1"], [True, False])
    fake_llm.responses = ["Current screen: start"]
    result = Executor(fake_device, fake_llm, StateSummarizer(fake_llm), sample_graph).execute(sample_plan)
    assert not result.success
    assert result.failure_type == "widget_failure"
    assert result.new_trace is not None
    assert len(result.new_trace.steps) == 2

def test_execute_check_error_does_not_crash(fake_device, fake_llm, sample_graph, sample_plan):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = ["Current screen: start", "not json", "not json"]
    result = Executor(fake_device, fake_llm, StateSummarizer(fake_llm), sample_graph).execute(sample_plan)
    assert result.failure_type == "check_error"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_executor.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the executor**

Group `plan.steps` by `card` while preserving order. For each step: capture `before = device.dump_ui()`, call `device.execute`, capture `after`, append a `Step` to the trace, append a result dict. On `False`, set `failure_type="widget_failure"`, stop, and return. After a card's last step, call `llm.complete_json` with the state summary and `card.postconditions`; on `LLMParseError`, set `failure_type="check_error"` and stop. At the end, check the goal; if not achieved, `failure_type="goal_failure"`. Use a `run-<uuid>` trace id.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_executor.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/executor/executor.py tests/test_executor.py
git commit -m "feat: add test-plan executor with postcondition and goal checks"
```

---

### Task 10: Card retrieval and parameter binding

**Files:**
- Create: `specfcg/planner/__init__.py`, `specfcg/planner/retrieval.py`, `specfcg/planner/binding.py`, `tests/test_retrieval.py`, `tests/test_binding.py`

**Interfaces:**
- Consumes: `FunctionCard`, `Goal` (Task 2); `LLMClient` (Task 1).
- Produces:
  - `CardRetriever(llm: LLMClient, top_k: int = 20)` with `retrieve(goal: Goal, cards: dict[str, FunctionCard]) -> list[str]`.
  - `ParamBinder(llm: LLMClient)` with `bind(card: FunctionCard, goal: Goal, state: str, prior_outputs: dict[str, str]) -> dict[str, str] | None`.

Retrieval rules: if `len(cards) <= top_k`, return all names; otherwise score by keyword overlap between the goal and `intent + name`, keep the top `top_k`, then ask the LLM to confirm/drop names. On malformed LLM output, return the keyword list.

Binding rules: the LLM returns `{"bindings": {"param": "value"}}`; values may reference `$prior_param` or `$output`. The binder substitutes `prior_outputs`. If a required input is missing, return `None`.

- [x] **Step 1: Write the failing tests**

```python
def test_retrieve_returns_all_when_small(fake_llm, two_cards):
    assert set(CardRetriever(fake_llm).retrieve(Goal("create and share a note"), two_cards)) == {
        "create_note", "share_note"
    }

def test_bind_uses_goal_values_and_prior_outputs(fake_llm, two_cards):
    fake_llm.responses = [{"bindings": {"note": "$create_note.output", "channel": "email"}}]
    out = ParamBinder(fake_llm).bind(
        two_cards["share_note"], Goal("share via email"), "note exists",
        {"create_note.output": "Trip"},
    )
    assert out == {"note": "Trip", "channel": "email"}

def test_bind_missing_required_returns_none(fake_llm, two_cards):
    fake_llm.responses = [{"bindings": {}}, {"bindings": {}}]
    assert ParamBinder(fake_llm).bind(
        two_cards["share_note"], Goal("share"), "state", {}
    ) is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_retrieval.py tests/test_binding.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement retrieval and binding**

`CardRetriever` uses a simple token-overlap score (lowercase, split on non-alphanumerics). The LLM prompt returns `{"keep": ["name", ...]}`; validate names. `ParamBinder` sends the card's `inputs`, `goal.description`, `state`, and `prior_outputs`; substitutes `$key` values; returns `None` if a required input is still missing after one retry.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_retrieval.py tests/test_binding.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/planner tests/test_retrieval.py tests/test_binding.py
git commit -m "feat: add card retrieval and parameter binding"
```

---

### Task 11: Step compiler and planner

**Files:**
- Create: `specfcg/planner/compiler.py`, `specfcg/planner/planner.py`, `tests/test_compiler.py`, `tests/test_planner.py`

**Interfaces:**
- Consumes: `Graph`, `Goal`, `TestPlan`, `PlanStep`, `FunctionCard` (Task 2); `search` (Task 4); `CardRetriever` (Task 10); `ParamBinder` (Task 10); `LLMClient` (Task 1).
- Produces:
  - `StepCompiler(llm: LLMClient)` with `compile(card: FunctionCard, bindings: dict[str, str]) -> list[PlanStep]`.
  - `Planner(graph: Graph, llm: LLMClient, retriever: CardRetriever, binder: ParamBinder, compiler: StepCompiler, strategy: str = "astar", max_depth: int = 8)` with `plan(goal: Goal, state: str) -> TestPlan | None`.

Planner behavior: retrieve candidates; run `search` with `can_execute` and `is_goal` LLM checks (cached per `(card, state)`); for each card in the path, bind parameters (passing prior `effects_outputs`/outputs), compile steps, concatenate; assertions = `[goal.description] + [card.postconditions for card in path]`. Return `None` when no path is found or a required binding fails.

- [x] **Step 1: Write the failing tests**

```python
def test_compile_steps_parses_actions(fake_llm, two_cards):
    fake_llm.responses = [{"steps": [
        {"action": "click", "target": "text=Save", "args": ""},
        {"action": "input", "target": "text=Title", "args": "Trip"},
    ]}]
    steps = StepCompiler(fake_llm).compile(two_cards["create_note"], {"title": "Trip"})
    assert [s.action for s in steps] == ["click", "input"]

def test_plan_finds_path_and_steps(fake_llm, sample_graph):
    fake_llm.responses = [
        {"can_execute": True}, {"is_goal": False},
        {"can_execute": True}, {"is_goal": True},
        {"bindings": {"title": "Trip"}},
        {"steps": [{"action": "click", "target": "text=+", "args": ""}]},
        {"bindings": {}},
        {"steps": [{"action": "click", "target": "text=Share", "args": ""}]},
    ]
    plan = Planner(sample_graph, fake_llm, CardRetriever(fake_llm),
                   ParamBinder(fake_llm), StepCompiler(fake_llm)).plan(
                       Goal("create and share a note"), "start")
    assert plan is not None
    assert plan.path == ["create_note", "share_note"]
    assert len(plan.steps) == 2

def test_plan_returns_none_when_no_path(fake_llm, sample_graph):
    fake_llm.responses = [{"can_execute": False}, {"can_execute": False}]
    assert Planner(sample_graph, fake_llm, CardRetriever(fake_llm),
                   ParamBinder(fake_llm), StepCompiler(fake_llm)).plan(
                       Goal("impossible"), "start") is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_compiler.py tests/test_planner.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the compiler and planner**

`StepCompiler` prompt: "Convert these function-card steps and bindings into UI actions. Return JSON `{steps:[{action,target,args}]}`; action is click/input/swipe/back/wait; target uses `text=...` or `resourceId=...`." Fallback regex: lines starting with `Tap`/`Click` → click; `Enter`/`Input`/`Type` → input; `Swipe` → swipe; `Back` → back; otherwise `click` with the whole line as target.

`Planner` closures: `can_execute(card)` calls `llm.complete_json` with "Can this card execute in this state? Return `{can_execute: bool, reason: str}`"; `is_goal(card)` calls "Does executing this card satisfy the goal or its postconditions? Return `{is_goal: bool, reason: str}`". Cache responses in a dict keyed by `(card, state)`. On `LLMParseError`, treat `can_execute=False` and `is_goal=False`. Build the plan only if all bindings succeed; otherwise return `None`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_compiler.py tests/test_planner.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/planner/compiler.py specfcg/planner/planner.py tests/test_compiler.py tests/test_planner.py
git commit -m "feat: add step compiler and graph planner"
```

---

### Task 12: Graph updater

**Files:**
- Create: `specfcg/maintainer/updater.py`, `tests/test_updater.py`

**Interfaces:**
- Consumes: `RunResult`, `GraphPatch`, `FailureType` (Task 2); `LLMClient` (Task 1); `GraphStore` (Task 3); `EdgeBuilder` (Task 7).
- Produces:
  - `GraphUpdater(llm: LLMClient, store: GraphStore, builder: EdgeBuilder)`.
  - `classify_failure(result: RunResult) -> FailureType | None`: returns `result.failure_type` if present, otherwise `None` on success; uses rules first and only asks the LLM for ambiguous cases.
  - `update(result: RunResult) -> GraphPatch`: success updates evidence and adds edges from the new trace; failure asks the LLM for a patch, validates it, applies it, and rolls back if the patch is invalid.

- [x] **Step 1: Write the failing tests**

```python
def test_success_updates_evidence(fake_llm, graph_store, successful_result):
    patch = GraphUpdater(fake_llm, graph_store, EdgeBuilder(fake_llm)).update(successful_result)
    assert any(u["name"] == "create_note" for u in patch.card_updates)
    graph_store.apply_patch(patch)
    assert graph_store.load().cards["create_note"].attempt_count >= 1

def test_invalid_patch_does_not_corrupt_graph(fake_llm, graph_store, failed_result):
    fake_llm.responses = [{"card_updates": [{"name": "missing", "fields": {}}]}]
    patch = GraphUpdater(fake_llm, graph_store, EdgeBuilder(fake_llm)).update(failed_result)
    assert patch.card_updates == []
    assert "missing" not in graph_store.load().cards
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the updater**

On success: increment `attempt_count` and `success_count` for each card in `result.plan.path`; add `sequence` edges from `result.new_trace` via `EdgeBuilder`; return the patch. On failure: prompt the LLM with `result` + current cards/edges, asking for JSON `{card_updates, new_cards, edge_updates, split, merge, reason}`; validate every card name and edge endpoint; if invalid, return an empty patch. Before applying a non-empty patch, call `store.backup()`; if `apply_patch` raises, call `store.restore(version)` and return an empty patch.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/maintainer/updater.py tests/test_updater.py
git commit -m "feat: add failure classification and graph updater"
```

---

### Task 13: Capability completer

**Files:**
- Create: `specfcg/completion/__init__.py`, `specfcg/completion/completer.py`, `tests/test_completer.py`

**Interfaces:**
- Consumes: `Goal`, `MissingCapability`, `GraphPatch` (Task 2); `LLMClient` (Task 1); `GraphStore` (Task 3); `CardMiner` (Task 6); `EdgeBuilder` (Task 7).
- Produces:
  - `ProbeRunner` Protocol: `run(capability: MissingCapability, state: str) -> Trace | None`.
  - `CapabilityCompleter(llm: LLMClient, store: GraphStore, miner: CardMiner, builder: EdgeBuilder, probe: ProbeRunner, max_hypotheses: int = 5, max_probes: int = 3, max_rounds: int = 2)`.
  - `complete(goal: Goal, state: str) -> GraphPatch | None`.

- [x] **Step 1: Write the failing tests**

```python
def test_no_gap_returns_none(fake_llm, graph_store, card_miner, edge_builder, fake_probe):
    fake_llm.responses = [{"gap": None}]
    assert CapabilityCompleter(fake_llm, graph_store, card_miner, edge_builder, fake_probe)\
        .complete(Goal("already reachable"), "state") is None

def test_complete_adds_card_on_successful_probe(fake_llm, graph_store, card_miner, edge_builder,
                                                fake_probe, probe_trace):
    fake_llm.responses = [
        {"gap": "need attach_photo"},
        {"capabilities": [{"name": "attach_photo", "intent": "attach a photo",
                           "preconditions": "note exists", "postconditions": "photo attached",
                           "inputs": ["note", "photo"], "probe": ["open note", "tap attach"],
                           "confidence": 0.8}]},
        "# attach_photo\n\n**Intent**: attach a photo\n**Inputs**: note, photo\n**Preconditions**: note exists\n**Postconditions**: photo attached\n**Effects/Outputs**: note has photo\n**Steps**:\n1. Tap attach\n**Evidence**: traces t9; 1/1 successes",
    ]
    fake_probe.trace = probe_trace
    patch = CapabilityCompleter(fake_llm, graph_store, card_miner, edge_builder, fake_probe)\
        .complete(Goal("attach a photo"), "state")
    assert patch is not None
    assert any(c.name == "attach_photo" for c in patch.new_cards)

def test_budget_limits_hypotheses(fake_llm, graph_store, card_miner, edge_builder, fake_probe):
    fake_llm.responses = [{"gap": "need x"}]
    fake_probe.trace = None
    assert CapabilityCompleter(fake_llm, graph_store, card_miner, edge_builder, fake_probe,
                               max_hypotheses=1, max_probes=1).complete(
                                   Goal("x"), "state") is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_completer.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the completer**

`detect_gap` prompt: "Given goal, cards, and state, is a capability missing? Return `{gap: string|null, blocked_precondition: string}`." `hypothesize` prompt: "Propose up to N missing capabilities as JSON `{capabilities:[...]}`." For each hypothesis, call `probe.run`; if a trace is returned, call `miner.mine(trace)`, add semantic/sequence edges via `EdgeBuilder`, validate the new card with `parse_card`, and return a combined `GraphPatch`. On failure, append `{goal, capability, reason}` to `completion/negative.jsonl` and continue. Stop at `max_hypotheses`, `max_probes`, or `max_rounds`. `ProbeRunner` is injected; tests use a fake.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_completer.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/completion tests/test_completer.py
git commit -m "feat: add capability gap detection and graph completion"
```

---

### Task 14: Pipeline and CLI

**Files:**
- Create: `specfcg/pipeline.py`, `specfcg/cli.py`, `config/llm.example.yaml`, `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/test_e2e_offline.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces:
  - `Pipeline(config: AppConfig, llm: LLMClient, device: Device, store: GraphStore, card_store: CardStore, miner: CardMiner, builder: EdgeBuilder, planner: Planner, executor: Executor, updater: GraphUpdater, completer: CapabilityCompleter)`.
  - `Pipeline.mine_trace(trace: Trace) -> CardPatch`.
  - `Pipeline.build_graph(segments: list[dict]) -> list[Edge]`.
  - `Pipeline.plan(goal_text: str, state: str = "") -> TestPlan | None`.
  - `Pipeline.run_goal(goal_text: str, state: str = "", max_rounds: int = 2) -> dict`.
  - `main(argv: list[str] | None = None) -> int` in `specfcg/cli.py`.
  - CLI commands: `mine`, `build-graph`, `plan`, `execute`, `refine`, `complete`, `run`.

- [x] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
def test_cli_mine_creates_cards(tmp_path, monkeypatch, sample_trace):
    # arrange config + fixture trace + FakeLLMClient responses
    code = main(["mine", "--config", str(cfg), "--trace", str(trace_path), "--fake-llm"])
    assert code == 0
    assert (tmp_path / "cards" / "create_note.md").exists()
```

`tests/test_e2e_offline.py`:

```python
def test_offline_pipeline_mines_plans_executes_and_refines(tmp_path, fixture_env):
    pipeline = fixture_env.pipeline
    pipeline.mine_trace(fixture_env.trace)
    assert "create_note" in pipeline.card_store.all()
    plan = pipeline.plan("create a note and share it", "Notes list")
    assert plan is not None
    result = pipeline.executor.execute(plan)
    assert result.goal_success
    result = pipeline.updater.update(result)
    assert result.reason
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py tests/test_e2e_offline.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the pipeline and CLI**

`Pipeline` wires the components. `run_goal` loops: `plan`; if no plan, `completer.complete` and retry; else `execute`, `updater.update`, and stop on success or `max_rounds`. CLI uses `argparse`; `--fake-llm` uses `FakeLLMClient` with a small canned script, `--fake-device` uses `FakeDevice`; otherwise it builds `OpenAICompatibleClient` and `Uiautomator2Device`. `mine` writes cards/edges; `plan` prints `TestPlan` JSON; `execute` prints `RunResult` JSON; `refine` prints the patch; `complete` prints the patch or `null`; `run` prints a JSON summary.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py tests/test_cli.py tests/test_e2e_offline.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/pipeline.py specfcg/cli.py config tests/test_pipeline.py tests/test_cli.py tests/test_e2e_offline.py
git commit -m "feat: add pipeline orchestration and CLI"
```

---

### Task 15: ProphetAgent integration adapter

**Files:**
- Create: `specfcg/integrations/__init__.py`, `specfcg/integrations/prophetagent.py`, `scripts/setup_prophetagent.sh`, `tests/test_prophetagent_parser.py`, `tests/fixtures/prophetagent/events.json`

**Interfaces:**
- Consumes: `Trace`, `Step` (Task 2); `TraceCollector` protocol (Task 5).
- Produces:
  - `PROPHETAGENT_COMMIT = "97667bfe109e71f57d84a2f7df9bcb03aba55b11"`.
  - `ProphetAgentCollector(repo_path: Path, output_root: Path, device_serial: str | None = None)` with `collect(app: str, apk_path: Path, policy: str = "greedy_dfs", count: int = 500, timeout_s: int = 600) -> list[Trace]`.
  - `parse_droidbot_output(output_dir: Path, app: str) -> list[Trace]`.

- [x] **Step 1: Write the failing parser test**

`tests/test_prophetagent_parser.py`:

```python
def test_parse_droidbot_output_builds_traces(fixture_dir):
    traces = parse_droidbot_output(fixture_dir, "omninotes")
    assert len(traces) == 1
    assert traces[0].trace_id.startswith("omninotes-")
    assert traces[0].steps[0].action == "click"
    assert traces[0].steps[0].target

def test_parse_missing_events_returns_empty(tmp_path):
    assert parse_droidbot_output(tmp_path, "omninotes") == []
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_prophetagent_parser.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement the adapter**

`parse_droidbot_output` reads `events.json` (list or `{"events": [...]}`), groups events by their trace/state sequence, and maps `event_type`/`event_str`/`from_state`/`to_state`/`view_str` to our `Step` fields. It skips events without a target and never raises on missing optional files; a missing `events.json` returns `[]`. `collect` runs:

```bash
python start.py -a <apk> -o <output_dir> -policy <policy> -count <count> -timeout <timeout>
```

from `repo_path`, then parses the output. `scripts/setup_prophetagent.sh` clones the repo and checks out the pinned commit.

- [x] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_prophetagent_parser.py -v`

Expected: PASS.

- [x] **Step 5: Manual integration check**

Run on one emulator/app:

```bash
bash scripts/setup_prophetagent.sh
specfcg mine --config config/llm.yaml --trace <output_dir>/events.json
```

Expected: a trace is parsed and a card is produced. Record the output directory in `runs/`.

- [x] **Step 6: Commit**

```bash
git add specfcg/integrations scripts/setup_prophetagent.sh tests/test_prophetagent_parser.py tests/fixtures/prophetagent
git commit -m "feat: add ProphetAgent Droidbot output adapter"
```

---

### Task 16: Benchmark harness

**Files:**
- Create: `specfcg/benchmark/__init__.py`, `specfcg/benchmark/cases.py`, `specfcg/benchmark/metrics.py`, `specfcg/benchmark/runner.py`, `tests/test_metrics.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `Graph`, `RunResult` (Task 2).
- Produces:
  - `AppSpec(name, package, apk_path)`.
  - `NLTestCase(id, app, text)` and `CompositionalGoal(id, app, text, assertions)`.
  - `load_apps(path)`, `load_cases(path)`.
  - `completion_rate(results)`, `action_accuracy(results)`, `path_recall(graph, held_out)`, `coverage(graph, executed_cards, executed_edges)`.
  - `Runner(run_case: Callable[[str], RunResult])` with `run(cases) -> list[dict]`.

- [x] **Step 1: Write the failing tests**

```python
def test_completion_rate():
    assert completion_rate([success_result, failure_result]) == 0.5

def test_action_accuracy():
    assert action_accuracy([success_result]) == 1.0

def test_path_recall():
    assert path_recall(graph, [["create_note", "share_note"]]) == 1.0

def test_coverage_counts():
    cov = coverage(graph, {"create_note"}, {("create_note", "share_note", "enables")})
    assert cov["node"] > 0
    assert cov["edge"] > 0
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py tests/test_runner.py -v`

Expected: FAIL with `ImportError`.

- [x] **Step 3: Implement cases, metrics, and runner**

Metrics formulas:
- `completion_rate = successful results / total`.
- `action_accuracy = successful steps / total steps`.
- `path_recall = held-out paths reconstructible in the graph / total held-out paths` (a path is reconstructible if every consecutive pair exists as an edge).
- `coverage = {node: executed_cards / total_cards, edge: executed_edges / total_edges}`.
- `Runner` calls `run_case(case.id)` and collects `{case_id, success, goal_success, steps, failure_type}`.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py tests/test_runner.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add specfcg/benchmark tests/test_metrics.py tests/test_runner.py
git commit -m "feat: add benchmark cases, metrics, and runner"
```

---

### Task 17: Stage 1 data manifest and report

**Files:**
- Create: `benchmark/apps.yaml`, `benchmark/cases/*.yaml`, `benchmark/goals/*.yaml`, `scripts/run_stage1.py`, `tests/test_stage1_manifest.py`

**Interfaces:**
- Consumes: Task 16 loaders/metrics, Task 14 pipeline.
- Produces:
  - `scripts/run_stage1.py` loads apps/cases/goals, runs the pipeline, and writes `runs/stage1_report.json`.
  - `tests/test_stage1_manifest.py` asserts the Stage 1 data counts.

- [x] **Step 1: Write the failing manifest test**

```python
def test_stage1_manifest_has_6_apps_60_cases_30_goals():
    apps = load_apps(Path("benchmark/apps.yaml"))
    cases = load_cases(Path("benchmark/cases"))
    goals = load_cases(Path("benchmark/goals"))
    assert len(apps) == 6
    assert len(cases) == 60
    assert len(goals) == 30
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_stage1_manifest.py -v`

Expected: FAIL with missing files.

- [x] **Step 3: Create the Stage 1 data**

`benchmark/apps.yaml` lists AnkiDroid, AmazeFileManager, OmniNotes, NewPipe, ActivityDiary, AntennaPod with package names and APK paths under `third_party/apks/`. `benchmark/cases/<app>.yaml` has 10 NL cases per app. `benchmark/goals/<app>.yaml` has 5 compositional goals per app with assertions. Use the app versions recorded in `apps.yaml`; do not use apps released after the LLM training cutoff for the main results.

- [x] **Step 4: Implement the runner**

`scripts/run_stage1.py` builds the pipeline (real or fake via flags), runs each case, aggregates metrics, and writes `runs/stage1_report.json` with `{apps, cases, goals, completion_rate, action_accuracy, path_recall, coverage, cost}`. Print a one-line summary.

- [x] **Step 5: Run the manifest test to verify it passes**

Run: `python -m pytest tests/test_stage1_manifest.py -v`

Expected: PASS.

- [x] **Step 6: Smoke-run the offline report**

Run: `python scripts/run_stage1.py --fake --limit 3`

Expected: `runs/stage1_report.json` exists and contains the three cases.

- [x] **Step 7: Commit**

```bash
git add benchmark scripts/run_stage1.py tests/test_stage1_manifest.py
git commit -m "feat: add Stage 1 data manifest and evaluation report"
```

---

## Next Round: the card is a contract, the plan is a description, the agent executes

**Why this round exists.** The graph was being used to *replay* an app: a
card stored the taps that had worked, the compiler turned them back into
taps, and the executor sent them again.  A replay can only repeat what was
recorded, so its success rate measures the recorder, not the map.  What the
graph is for is the opposite — to describe the app's functions well enough
that a GUI agent, handed a task it has never run, can carry it out, and to
say which functions must happen, in what order, and what each one needs and
leaves behind.  So:

- a card becomes a **contract** (intent, inputs, pre/postconditions,
  effects) and names no UI action;
- the planner's output becomes a **task description** rendered from the
  contracts on the chosen path — overall goal, ordered subgoals, the value
  each subgoal needs, what each leaves behind;
- the **executor hands that description to a GUI agent**.  Nothing sends a
  recorded tap.

The claim then becomes falsifiable in the only way that matters: give the
same agent, on the same device, the same tasks twice — once with the raw
goal, once with the graph-derived description — and count the paired
difference.

**What this round deliberately leaves alone.** Trace collection
(`specfcg/traces/scripted.py`, `scripts/build_app_graph.py` without
`--skip-collect`) still drives scripted actions: that is how the reference
corpus is made, not how a planned task runs.  `RandomTraversalAgent` stays —
it is a control.  `ParamBinder` stays: it turns goal values into contract
values and reads only `card.inputs`, never steps.

**Execution order.** F → G → H → C → A → B → D → E.  F is the architecture
change and must land first; C edits the builder the rebuild in A calls; A
before B; B before D, which is conditional on what B measures.

**Letter mapping, so earlier notes still read.** A (rebuild) and B
(re-measure) keep their meaning.  **C changes meaning**: it was "behavioural
duplicates from compiled actions", which a step-less card makes incomputable;
it becomes duplicate functions read from the contracts.  **D changes
meaning**: it was "make calibration discriminate", it becomes calibration
over agent runs, still conditional on B.  E stays the ledger.  F–H are the
new group: the contract, the description and the agent (F), the probe path
end to end (G), the ablation (H).

**Why F is one task and not three.** Deleting `FunctionCard.steps` removes
the compiler's input; deleting the compiler empties `TestPlan.steps`; an
empty `TestPlan.steps` leaves the executor with nothing to send.  Split
across three commits, each would build green while the system did nothing on
a device — the worst kind of green, and it would need a shim to get there.
The three are one interface change, so they land as one commit with the TDD
cycles kept separate inside the task.

**State at the start of this round:** 448 tests pass; the committed graphs
were built 2026-08-26/27 by the quadratic builder and their coverage, probe
and self-optimization records predate the corrected matcher.  Device
`47261FDAS00DTQ` is attached and the gateway answers.  The four graphs hold
93 cards and 353 edges; 157 of omninotes' 193 edges are LLM-asserted
`enables` with no execution evidence.

**Scorecard consequence, stated up front.** The `task` dimension stops
meaning "the compiled script replayed" and starts meaning "the agent, given
the graph's description, reached the goal".  That is a different quantity, so
the curve is discontinuous at this point; the report says so instead of
drawing one line through both.  The raw-goal arm is a *control*, reported
beside the score like random traversal and never folded into it — its success
is the agent's competence, and only the paired difference is the graph's
contribution.

**Review focus (this round), each with a test in its owning task.**

1. **A card still carrying a Steps section** — migration must reject it
   loudly rather than let the prose leak into the preceding section (F).
2. **An app the caller already prepared** — the agent acts from the current
   screen and never launches, so seeded files and onboarding survive it (F).
3. **A crashing or stalling agent** — the run yields a trace with an error,
   not an exception that kills the benchmark (F).
4. **An agent that reports `done` on an unachieved screen** — the
   programmatic oracle, never the agent's claim, decides success (F, H).

---

### Task F: the card is a contract, the plan is a description, the agent executes

**Files:**
- Modify: `specfcg/models.py:52-62` (`FunctionCard` — no `steps`), `:100-114`
  (`TestPlan` — `description`, no `steps`), `:146-154` (`MissingCapability`),
  `:8-18` (`EdgeType`, `EDGE_PRIORITY` — no `calls`)
- Modify: `specfcg/cards/parser.py` (`_REQUIRED`, `_SECTION_RE`, `_STEP_RE`,
  `_parse_steps`, `render_card`)
- Create: `scripts/migrate_cards.py`
- Modify: `specfcg/maintainer/miner.py:41-53` (`_CARD_PROMPT`), `:92-161`
  (`_ground_inputs`), `:341-355` (`_fallback_card`), `:369-394` (`draft`),
  `:396-460` (`mine`)
- Modify: `specfcg/maintainer/updater.py:31-46`, `:84`, `:177-195`, `:235-243`,
  `:315-330`
- Modify: `specfcg/graph/store.py:16-60` (field aliases, `_coerce`,
  `_split_values`)
- Modify: `specfcg/completion/completer.py:24-32` (`ProbeRunner` — `run`
  gains `app`), `:85-140` (hypothesis prompt), `:196-212` (merge tuple)
- Rewrite: `specfcg/completion/probe.py` (`AgentProbe`; `cli.py` constructs
  it for the completer, so the old `DeviceProbe` cannot outlive the compiler)
- Create: `specfcg/planner/describer.py`
- Modify: `specfcg/planner/planner.py:33-56`, `:372-425`
- Delete: `specfcg/planner/compiler.py`, `tests/test_compiler.py`
- Delete: `specfcg/benchmark/granularity.py`, `scripts/measure_granularity.py`,
  `tests/test_benchmark_granularity.py`, `tests/test_measure_granularity.py`
  (behavioural equivalence without behaviour; C replaces it with a reader),
  and the granularity column in `scripts/build_bench_report.py`
- Create: `specfcg/executor/agent.py` (`AgentTrace`, `GuiAgent`)
- Create: `specfcg/executor/mobile_agent_backend.py`
- Rewrite: `specfcg/executor/executor.py`
- Modify: `specfcg/benchmark/agents.py` (`GraphAgent`; delete `execute_plan`
  and `SpecFCGAgent`)
- Modify: `mobile_agent/agent.py` — `run()` acts from the current screen and
  no longer launches; `verify: bool = True` (the backend passes `False` and
  writes no memory entry); per-step UI text; `initial_ui`/`final_ui` on
  `TaskResult`
- Modify: `scripts/run_agent_tasks.py` (launch explicitly; `run()` no longer
  does)
- Modify: `specfcg/cli.py:38-48`, `:108-121`, `:155-175`
- Modify: `specfcg/config.py` (`AgentConfig`), `config/llm.bench.yaml`
- Modify: `tests/fakes.py` (add `ScriptedAgent` — a `GuiAgent` with
  `tasks`/`apps`/`max_steps` recorded and canned `steps`, `done`, `final_ui`,
  `error`), `tests/conftest.py:31-77`, `:167-188`
- Modify: `docs/superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md`
  (§5.1, §5.2, §6.2, §6.3, §6.4, §6.5)
- Test: `tests/test_card_parser.py`, `tests/test_migrate_cards.py`,
  `tests/test_miner.py`, `tests/test_describer.py`, `tests/test_planner.py`,
  `tests/test_executor.py`, `tests/test_benchmark_agents.py`,
  `tests/test_updater.py`, `tests/test_graph_store.py`, `tests/test_models.py`,
  `tests/test_pipeline.py`, `tests/test_e2e_offline.py`

**Interfaces:**
- Produces: `FunctionCard(name, intent, inputs, preconditions, postconditions,
  effects_outputs, evidence, success_count, attempt_count)`.
- Produces: `CardMiner.draft(episode, trace) -> FunctionCard | None`.
- Produces: `scripts/migrate_cards.py::migrate(text: str) -> str`.
- Produces: `TaskDescriber.describe(goal: str, subgoals:
  list[tuple[FunctionCard, dict[str, str]]]) -> str` — deterministic, no LLM.
- Produces: `TestPlan(goal, path, description: str = "", assertions, app)`.
- Produces: `AgentTrace(steps: list[Step], initial_ui: str = "", final_ui: str
  = "", done: bool = False, error: str = "")`
- Produces: `GuiAgent` (Protocol) with two methods and no policy:
  `observe(app: str) -> str` (the compact UI text the planner reads) and
  `run(task: str, max_steps: int, *, app: str) -> AgentTrace`.  The app travels
  with the call because one pipeline serves every app.
- Produces: `MobileAgentBackend(serial, model, fallback_model, out_root)`, a
  `GuiAgent`.  One `VLM` and one `ExperienceStore` live on it; the store is
  read (a lesson from an earlier judged run may apply) and never written,
  because the backend runs the agent with `verify=False`.  One
  `AndroidDevice` per app, so observation and action go through the same
  client.
- Produces: `Executor(agent: GuiAgent, llm: LLMClient, graph: Graph,
  summarizer: StateSummarizer | None = None, max_steps: int = 20)`;
  `execute(plan, max_steps: int | None = None) -> RunResult`;
  `trace.metadata["task_description"]`.  `max_steps` defaults to the
  executor's configured budget and an explicit value overrides it for one
  run, so every existing `execute(plan)` caller keeps working and the
  benchmark can pass its per-task cap.  The executor launches nothing: the
  caller owns the app's state, and the agent acts from the screen it finds.
- Produces: `GraphAgent(pipeline)` — a `Callable[[BenchTask], AgentRun]` that
  plans and then calls `pipeline.executor.execute(plan,
  max_steps=task.max_steps)`; `reached_cards = list(plan.path)` when the run
  succeeded, `[]` otherwise
- Produces: `AgentConfig(model, fallback_model, max_steps)` in
  `specfcg/config.py`, read from `config/llm.bench.yaml`'s `agent:` block
- Produces: `AgentProbe(agent: GuiAgent, max_steps: int = 10).run(capability:
  MissingCapability, state: str, app: str = "") -> Trace | None`; `ProbeRunner`
  gains the `app` parameter
- Consumes: `mobile_agent.MobileAgent`, `mobile_agent.VLM`,
  `mobile_agent.memory.ExperienceStore`

- [x] **Step 1: Write the failing parser tests**

```python
def test_card_with_a_steps_section_is_rejected():
    text = (
        "# create_note\n\n**Intent**: Create a note.\n"
        "**Inputs**: none\n**Preconditions**: The list is open.\n"
        "**Postconditions**: The note exists.\n**Effects/Outputs**: none\n"
        "**Steps**:\n1. Tap '+'. 2. Tap 'Save'.\n**Evidence**: traces t1\n"
    )
    with pytest.raises(CardParseError, match="Steps"):
        parse_card(text)


def test_rendered_card_round_trips_without_steps(sample_card):
    assert "**Steps**" not in render_card(sample_card)
    assert parse_card(render_card(sample_card)) == sample_card
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_card_parser.py -q`

Expected: FAIL — Steps is a required section today, so the first test parses
without raising and the renderer emits the section.

- [x] **Step 3: Remove `steps` from the model, the format and the store**

Delete the field from `FunctionCard`.  Drop `"Steps"` from `_REQUIRED` and
`_SECTION_RE`, and add `_RETIRED = ("Steps",)`: a card that still declares
one raises `CardParseError("the Steps section was removed: a card is a
contract, not a script")`.  The rejection is deliberate — without it the
heading is unrecognised and its prose is silently absorbed into the preceding
section.  Delete `_parse_steps`, `_STEP_RE`, and the Steps block in
`render_card`.

Then the store and the updater: drop `GraphStore._FIELD_ALIASES["steps"]`, the
`numbered=` parameter of `_coerce`/`_split_values` (it only ever meant steps);
`GraphUpdater._EXECUTABLE_FIELDS`, `_PATCH_SCHEMA`'s `{"Steps": [...]}`
example, `_card_detail`'s `Steps:` block, and the `steps=` argument in
`_new_cards`'s `FunctionCard(...)`.

- [x] **Step 4: Write the failing miner tests**

```python
def test_card_prompt_asks_for_a_contract_not_a_script(fake_llm, sample_trace):
    CardMiner(fake_llm, CardStore(tmp_path)).draft(_episode(), sample_trace)
    prompt = fake_llm.prompts[-1]
    assert "**Steps**" not in prompt
    assert "**Postconditions**" in prompt and "**Preconditions**" in prompt


def test_an_unparseable_card_yields_no_card(fake_llm, sample_trace):
    fake_llm.reply = "I cannot write this card."
    assert CardMiner(fake_llm, CardStore(tmp_path)).draft(
        _episode(), sample_trace
    ) is None


def test_a_trace_value_baked_into_the_contract_becomes_an_input(
    fake_llm, sample_trace
):
    # The model writes the run's own file name into the postcondition
    # instead of a placeholder; the start screen proves it is data.
    fake_llm.reply = _card(postconditions="bench_new.txt now exists.")
    card = CardMiner(fake_llm, CardStore(tmp_path)).draft(
        _episode(), sample_trace
    )
    assert "bench_new.txt" not in card.postconditions
    assert any(i.startswith("item_label") for i in card.inputs)
```

- [x] **Step 5: Run them to verify they fail**

Run: `python -m pytest tests/test_miner.py -q`

Expected: FAIL — the prompt demands Steps, `draft` falls back to a card built
from trace actions, and grounding walks `card.steps`.

- [x] **Step 6: Rewrite the prompt and ground the contract**

`_CARD_PROMPT` asks for Intent, Inputs, Preconditions, Postconditions,
Effects/Outputs, Evidence, and states the rule the format now enforces:
describe what the function requires and produces; name no UI action.  Keep
the generalisation instruction — the contract now carries the placeholders
("refer to them as {name} in Intent, Preconditions and Postconditions").
Delete `_fallback_card`: a card with no contract is a name, not evidence.
`draft` returns `None` on `CardParseError`/`LLMParseError` after logging, and
`mine` skips that episode with a warning naming the trace id.

Rename `_ground_inputs` to `_ground_contract`, keyed on `intent +
preconditions + postconditions + effects_outputs` instead of `card.steps`:
(1) every `{name}` in the contract that is not declared becomes an input;
(2) a trace value appearing literally in the contract **and** on the start
screen is data — replace it with `{item_label}` and declare it; (3) a declared
control input records the label the build actually showed (`; observed: '...'`).
The trace's steps are still read here — as evidence of what the screen showed,
which is what grounding is.

- [x] **Step 7: Write the failing migration test**

```python
LEGACY = """# copy_file

**Intent**: Copy {source} into {dest}.
**Inputs**: source (required): the file. dest (required): the folder.
**Preconditions**: The browser shows {source}.
**Postconditions**: A copy of {source} exists in {dest}.
**Effects/Outputs**: Creates a duplicate.
**Steps**:
1. Long-press {source}.
2. Tap the copy command.
**Evidence**: traces copy-file; 3/3 successes
"""


def test_migration_removes_only_the_steps_section():
    migrated = migrate(LEGACY)
    assert "**Steps**" not in migrated and "copy command" not in migrated
    assert "**Postconditions**: A copy of {source} exists in {dest}." in migrated
    assert parse_card(migrated).name == "copy_file"
    assert migrate(migrated) == migrated          # idempotent
```

- [x] **Step 8: Implement `migrate` and the script wrapper**

`migrate` drops a line matching `^\*\*Steps\*\*` and every following line up
to the next `^\*\*` heading or end of file; it rewrites nothing else, which is
what makes it idempotent.  The script takes one or more graph roots, migrates
every `cards/*.md`, and prints the count per root.

- [x] **Step 9: Write the failing describer tests**

```python
def test_description_states_the_goal_then_each_subgoal_in_order(
    sample_card, another_card
):
    text = TaskDescriber().describe(
        "Create a note titled Grocery list",
        [(sample_card, {"title": "Grocery list"}), (another_card, {})],
    )
    assert text.startswith("Overall goal: Create a note titled Grocery list")
    assert text.index("1. create_note") < text.index("2. share_note")
    assert "title = Grocery list" in text
    assert "Postconditions: A note with the given title appears" in text
    assert "tap" not in text.lower() and "click" not in text.lower()


def test_a_value_bound_from_an_earlier_subgoal_says_where_it_came_from(
    sample_card, another_card
):
    text = TaskDescriber().describe(
        "Share the note just created",
        [(sample_card, {}), (another_card, {"note": "Draft"})],
    )
    assert "note = Draft (from subgoal 1)" in text


def test_an_unbound_input_is_a_named_gap_not_a_failure(sample_card):
    text = TaskDescriber().describe("Do it", [(sample_card, {})])
    assert "title = <unbound: not named in the goal or earlier outputs>" in text
```

- [x] **Step 10: Run them to verify they fail**

Run: `python -m pytest tests/test_describer.py -q`

Expected: FAIL with `ModuleNotFoundError: specfcg.planner.describer`.

- [x] **Step 11: Implement `TaskDescriber`**

Fixed layout, five fields per subgoal:

```text
Overall goal: <goal>

Subgoals, in order:
1. <card.name> — <card.intent>
   Inputs: <name> = <value>[(from subgoal N)]; ...
   Preconditions: <card.preconditions>
   Postconditions: <card.postconditions>
   Reliability: <success>/<attempt> observed successes

2. ...
```

Input names come from the card's declarations, split the way `ParamBinder`
splits them; any the plan did not bind render as the unbound marker.  The
describer emits no action verb, and a test asserts it.

- [x] **Step 12: Replace the compiler in `TestPlan` and `compile_path`**

`TestPlan.steps` becomes `description: str = ""`; delete `PlanStep`.
`compile_path` binds each card with `ParamBinder`, collects `(card, bindings)`
pairs, calls `describer.describe(goal.description, pairs)`, and keeps
appending subgoals and postconditions to `assertions`.  A `None` from the
binder no longer aborts the plan: pass `{}` and let the description name the
gap — a compiled step could not carry a gap, a description can, and the agent
can see the screen.  `Planner.__init__` takes `describer: TaskDescriber | None
= None`.

`git rm specfcg/planner/compiler.py tests/test_compiler.py` — 41 tests for a
component that no longer exists, deleted on purpose.  Same step, same reason:
`git rm specfcg/benchmark/granularity.py scripts/measure_granularity.py
tests/test_benchmark_granularity.py tests/test_measure_granularity.py` (it
measures compiled action sets).

`completion/probe.py` is rewritten here rather than deleted: `cli.py` builds
it for the completer, so a commit without it does not import.  `DeviceProbe`
becomes `AgentProbe(agent, max_steps=10)` — `run(capability, state, app="")`
renders the hypothesis as a task: its intent, preconditions and
postconditions, the current state, and nothing about how to get there.  It
calls `agent.run(text, max_steps, app=app)`, returns a `Trace` of the agent's
steps with `metadata["final_state"]`, and `None` when nothing was acted.  The
`app` comes from the caller because `MissingCapability` names a capability,
not a package: the completer holds a `Goal` whose `app` is the package, and it
passes it through.  The
`MissingCapability.probe` field, `_CAPABILITY_SCHEMA`'s `"probe": []` and the
hypothesis prompt's "short probe plan. The first step must name a control
that is visible on the current screen" go with it: asking the model to guess
a control sequence before anyone has seen the screen was the same mistake in
miniature.  The `ProbeRunner` protocol gains the `app` parameter.
`_patch_from_trace` is unchanged — it already mines the card from the trace
the probe returns.  The four `DeviceProbe` tests in `tests/test_pipeline.py`
are rewritten against `AgentProbe` in the same step:

```python
def test_a_hypothesis_is_probed_by_the_agent_not_by_compiled_lines():
    agent = ScriptedAgent(steps=[Step(action="click", target="text=New")])
    trace = AgentProbe(agent).run(
        MissingCapability(name="add_tag", intent="Add a tag"), "",
        app="it.feio.android.omninotes.foss",
    )
    assert "Add a tag" in agent.tasks[0]
    assert agent.apps == ["it.feio.android.omninotes.foss"]
    assert [step.target for step in trace.steps] == ["text=New"]


def test_a_probe_that_acts_nothing_yields_no_trace():
    assert AgentProbe(ScriptedAgent(steps=[])).run(
        MissingCapability(name="add_tag", intent="Add a tag"), ""
    ) is None
```

- [x] **Step 13: Write the failing executor tests**

```python
def test_the_agent_receives_the_plan_description():
    agent = ScriptedAgent(steps=[Step(action="click", target="text=+")])
    plan = _plan(description="Overall goal: create a note\n1. create_note — ...")
    Executor(agent, _llm(), _graph(), max_steps=20).execute(plan)
    assert agent.tasks == [plan.description]
    assert agent.apps == [plan.app]
    assert agent.max_steps == 20


def test_the_goal_check_not_the_agent_decides_success():
    # The agent reports done; the goal check sees no note in the final UI.
    agent = ScriptedAgent(steps=[], done=True, final_ui="notes list, empty")
    result = Executor(agent, _llm(says_achieved=False), _graph()).execute(_plan())
    assert result.success is False
    assert result.failure_type == "goal_failure"
    assert result.new_trace.metadata["task_description"] == _plan().description


def test_a_crashing_agent_yields_a_trace_not_an_exception():
    agent = ScriptedAgent(error="adb disconnected")
    result = Executor(agent, _llm(), _graph()).execute(_plan())
    assert result.success is False and result.failure_type == "environment_failure"
```

- [x] **Step 14: Run them to verify they fail**

Run: `python -m pytest tests/test_executor.py -q`

Expected: FAIL — `Executor` takes a device and replays `plan.steps`.

- [x] **Step 15: Write the protocol, the backend and the executor**

`GuiAgent` is a two-method protocol and no policy.  `MobileAgentBackend` holds
the serial, the two model names and an output root, plus one
`VLM(models=(model, fallback_model))`, one `ExperienceStore` and a cached
`AndroidDevice` per package.  `observe(app)` returns `device(app).ui_text()`.
`run` calls `MobileAgent.run` — constructed with `verify=False` — on
`TaskSpec(id=sha256(task)[:16], app=app, app_name=app, goal=task,
max_steps=max_steps)` and converts the result into `AgentTrace`: `tap` →
`click` (`text=`/`resourceId=` from args), `tap_xy` → `click` with
`args="x,y"`, `type_text` → `input`, `press` → `press`, `swipe` → `swipe`;
`done` ends the run.  `AndroidDevice` connects lazily, so caching one per app
costs nothing until it is used, and the agent observes and acts through the
same client — which is what lets `Executor` drop its `device` argument.

`MobileAgent` changes to match.  `run()` no longer calls
`self.device.start_app()`: `app_start(stop=True)` restarts the process, which
would wipe the state the benchmark's `prepare_state` just seeded, and a probe
would wipe the screen the hypothesis was written about.  The agent's contract
becomes "act from the screen you find", and launching is the caller's job —
`prepare_state` already does it, `fresh_app` already does it, and
`scripts/run_agent_tasks.py` launches after `reset_app` (its `--no-reset`
path must launch explicitly, which is the one caller that changes).  `run()`
also writes `initial_ui.txt` and `step_NN_before.txt` / `step_NN_after.txt`
beside the screenshots it already saves, and returns `initial_ui` / `final_ui`
on `TaskResult`; on the exception path `final_ui` stays empty and `error` is
set, which is what makes Step 13's third test pass.

It also gains `verify: bool = True`.  With `verify=False` the agent reports
what it did and stops: `_verify` is not called (it is one VLM call per task
that would answer a question the caller already answers), `success` is left
`False`, `reason` reads "verification deferred to the caller", and no memory
entry is written — a lesson learned from an unjudged run is a guess, and the
store is only honest when something judged the run.  The backend constructs
`MobileAgent(..., verify=False)`; `scripts/run_agent_tasks.py` keeps the
default, because there the agent's own verifier *is* the verdict.

`Executor(agent, llm, graph, summarizer=None, max_steps=20)` — no `device`:
the agent owns the device, and `max_steps` is the configured budget.
`execute(plan, max_steps=None)` builds a `Trace` whose `start_state` is the
summarizer's reading of `agent_run.initial_ui` (or the first 2000 characters
when no summarizer is given), calls
`self.agent.run(plan.description, max_steps, app=plan.app or plan.goal.app)`,
appends the returned `Step`s with `step_results =
[{"action","target","args","success","before","after"}]` and **no** `card`
key, then asks the existing `_GOAL_SCHEMA` over goal + `plan.assertions` + the
action log + `final_ui`.  Delete `_step_line`, `_groups`, `_POST_SCHEMA` and
the per-card postcondition loop: attribution is whole-path now, and
`GraphUpdater._segments` already falls back to `plan.path` when no step names
a card.  An `AgentTrace.error` becomes `failure_type="environment_failure"`
with the error text, not an exception.  Callers that plan and then execute
(`GraphAgent`, `run_pilot`, `run_probes`, `run_selfopt`) read the screen with
`pipeline.executor.agent.observe(app)` instead of `pipeline.device.dump_ui()`,
so the state the plan is made from is the state the agent acts on.
`pipeline.device` stays for what it is still right for: trace collection,
`set_app`, and the scripts that never execute a plan.  The CLI's `execute`,
`refine` and `run` commands take `--app` and must now call
`pipeline.device.start_app(args.app)` before the first plan — they relied on
the executor's launch, and the caller owning the launch is exactly the
correction.  The offline path passes `fake_device`, where `start_app` is a
no-op on the fake.

- [x] **Step 16: Rewrite the benchmark adapter**

`agents.py` keeps `RandomTraversalAgent` and gains `GraphAgent(pipeline)`: a
callable on the `BenchTask` —
`state = pipeline.executor.agent.observe(task.app)`, then
`pipeline.plan(task.goal, state, app=task.app)`, then
`pipeline.executor.execute(plan, max_steps=task.max_steps)` — translating
`RunResult` into `AgentRun`:
`steps` from `step_results`, `observed_ui` from each step's `before_state`
plus the final UI, `predicted_path=list(plan.path)`, `reached_cards =
list(plan.path)` only when the run succeeded.  Observation and action are the
same client, so the state the plan is made from is the state the agent acts
on.  The agent callable now takes the task rather than `(goal, max_steps)`,
because the app is part of what the agent needs and the runner already has
it: `TaskRunner.run(task, agent: Callable[[BenchTask], AgentRun])` and
`RandomTraversalAgent.__call__(task)` (it reads `task.max_steps`; the device
it holds is the task's app, set once per run by the script).  Delete
`execute_plan` and
`SpecFCGAgent`.  `scripts/run_mobileworld_bench.py`'s `--agent` choices become
`graph` and `random`, and the summary records `"agent": "graph"`, so script
and scorecard agree on the name now and in H.

- [x] **Step 17: Update the offline stand-in, the config and the spec**

`_OfflineLLM` loses the "Convert these function-card steps" and "Are the
postconditions satisfied" branches, and `_OFFLINE_CARD` loses its Steps
block.  `AgentConfig(model, fallback_model, max_steps)` joins `AppConfig`;
`config/llm.bench.yaml` gains `agent: {model: auto/deepseek-v4.1-flash,
fallback_model: auto/deepseek-v4.1-flash, max_steps: 20}`; `build_pipeline`
constructs `MobileAgentBackend(config.device.serial, config.agent.model,
config.agent.fallback_model, Path(config.paths.root) / "agent")` and passes
it to `Executor`.  `build_pipeline` keeps constructing
`Uiautomator2Device` for `pipeline.device`: that is the script-facing device
(`dump_ui`, `set_app`, `screenshot`), used by `run_pilot`, `run_selfopt`,
`run_graph_experiments` and trace collection.  The backend builds its own
`AndroidDevice` per app — the agent-facing one (`ui_text`, actions).  Two
device abstractions on one phone is the status quo (`AdbOps` already sits
beside `Uiautomator2Device`), and merging them would touch trace collection,
which this round leaves alone.  What changes is that *planning* reads the
screen through the agent when a plan will be executed, so the state the plan
is made from is the state the agent acts on.  With `fake_device`,
`build_pipeline` wires `ScriptedAgent(...)` instead of the backend, and the
offline pipeline runs end to end without a phone.

Spec edits: §5.1 Planner row becomes "goal + state → 图搜索 → function 序列 + 参数绑定 +
任务描述"; Executor row becomes "把任务描述交给 GUI agent 执行，校验 goal 与 postcondition";
§5.2 step 5 drops "重放步骤"; §6.2's card format and card-validity criterion drop
Steps; §6.3 drops the `calls` edge (a card can no longer contain another
card's steps); §6.4 step 5 becomes "把路径上的卡片契约按参数串成任务描述"; §6.5 states that
the executor is a GUI agent, not a script.

- [x] **Step 18: Migrate the four graphs and run the suite**

```
python -m pytest tests/test_card_parser.py tests/test_miner.py tests/test_migrate_cards.py tests/test_describer.py tests/test_planner.py tests/test_executor.py tests/test_benchmark_agents.py tests/test_updater.py tests/test_graph_store.py -q
PYTHONPATH=. python scripts/migrate_cards.py runs/mobileworld/activitydiary/graph runs/mobileworld/amaze/graph runs/mobileworld/markor/graph runs/mobileworld/omninotes/graph
python -m pytest -q
```

Expected: 93 cards migrated, every card still parses, and the full suite green
with a `ScriptedAgent` where the device-backed one would go.  No test asserts
on a replayed step or on `card.steps`.

- [x] **Step 19: Smoke one task on the device**

```
PYTHONPATH=. python -c "
from specfcg.executor.mobile_agent_backend import MobileAgentBackend
a = MobileAgentBackend('47261FDAS00DTQ',
                       'auto/deepseek-v4.1-flash', 'auto/deepseek-v4.1-flash',
                       'runs/smoke/agent')
t = a.run('Create a note titled Smoke test and save it.', 10,
          app='it.feio.android.omninotes.foss')
print(len(t.steps), t.done, t.error, t.initial_ui[:80])
"
```

Expected: non-empty `t.steps`, each with a `before_state`; `done` is the
agent's claim and no code path uses it as the verdict.

- [x] **Step 20: Commit**

```bash
git add specfcg mobile_agent/agent.py scripts/migrate_cards.py tests config/llm.bench.yaml docs/superpowers/specs
git commit -m "refactor(cards): a card is a contract, a plan is a description, an agent executes"
```

---

### Task G: probes and completion run through the agent

F rebuilt `AgentProbe` so the code compiles; this task makes the probe path
actually run through the agent end to end — the completer passes the package,
`cli.py` wires the probe to the backend, and the experiment script's probes
execute through the executor instead of replaying a compiled plan.

**Files:**
- Modify: `specfcg/completion/completer.py` (pass `goal.app` to `probe.run`)
- Modify: `specfcg/cli.py` (`build_pipeline` wires `AgentProbe(executor.agent)`)
- Modify: `scripts/run_graph_experiments.py:137-200` (`run_probes`)
- Modify: `tests/fakes.py` (`FakeProbe.run(capability, state, app="")`
  records `apps`)
- Test: `tests/test_completer.py`, `tests/test_run_graph_experiments.py`,
  `tests/test_pipeline.py` (the four rewritten probe tests)

**Interfaces:**
- Consumes: `AgentProbe` and `GuiAgent` (F), `Executor` (F)

- [x] **Step 1: Write the failing wiring test**

The probe itself is tested in F.  What F cannot test is that the package
reaches it:

```python
def test_the_completer_gives_the_probe_the_goal_s_package(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe, probe_trace
):
    fake_probe.trace = probe_trace
    fake_llm.reply_json = {"capabilities": [_capability()]}
    CapabilityCompleter(fake_llm, graph_store, card_miner, edge_builder,
                        fake_probe).complete(
        Goal(description="add a tag", app="it.feio.android.omninotes.foss"), ""
    )
    assert fake_probe.apps == ["it.feio.android.omninotes.foss"]
```

- [x] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_completer.py -q`

Expected: FAIL — `FakeProbe` records no `apps`, and `complete` calls
`probe.run(capability, state)` without the package.

- [x] **Step 3: Pass the package through and wire the probe**

`CapabilityCompleter.complete` calls
`self.probe.run(capability, state, app=goal.app)`; `tests/fakes.py`'s
`FakeProbe` records each `app` it was given.  `build_pipeline` constructs
`AgentProbe(executor.agent)` where it used to construct
`DeviceProbe(device, compiler)` — the same agent, so a probe acts through the
client that observed the screen.  F already removed
`MissingCapability.probe`, `_CAPABILITY_SCHEMA`'s `"probe": []` and the
"short probe plan" clause; G only checks the completer still runs without
them.

- [x] **Step 4: Reroute `run_probes`**

`run_probes` keeps its predicted path and executes it through the pipeline's
executor (`pipeline.plan_path(...)` then `pipeline.executor.execute(plan)`
after `fresh_app`), reading the pre-plan state with
`pipeline.executor.agent.observe(package)`; the observed evidence is each
step's `before_state` plus the final UI, so "reached" means the agent's
screens showed the function.  The prediction stays about the graph's route —
that is the quantity calibration scores.

- [x] **Step 5: Run the completer, pipeline and experiment tests**

Run: `python -m pytest tests/test_completer.py tests/test_pipeline.py tests/test_run_graph_experiments.py -q`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add specfcg scripts tests
git commit -m "feat(completion): probe a hypothesized capability with the agent"
```

---

### Task H: the ablation — one agent, two strings

**Files:**
- Modify: `specfcg/benchmark/agents.py` (`RawGoalAgent`)
- Modify: `specfcg/benchmark/suite_runner.py:30-79` (`AgentRun.task_text`,
  `TaskOutcome.task_text`, `as_record()`)
- Modify: `specfcg/benchmark/scorecard.py:91-140` (`task` reads the graph arm;
  `control` gains `raw`)
- Modify: `scripts/run_mobileworld_bench.py` (`--agent graph|raw|random`)
- Modify: `scripts/build_bench_report.py` (paired table)
- Test: `tests/test_benchmark_agents.py`, `tests/test_benchmark_scorecard.py`,
  `tests/test_benchmark_report.py`, `tests/test_benchmark_suite_runner.py`

**Interfaces:**
- Produces: `GraphAgent(pipeline)` and `RawGoalAgent(agent: GuiAgent)` — both
  `Callable[[BenchTask], AgentRun]`; `TaskRunner.run(task, agent)` calls
  `agent(task)`.
- Produces: `AgentRun.task_text: str`, `TaskOutcome.task_text: str`, and
  `"task_text"` in `as_record()` — the exact string the agent was given.
- Consumes: `GraphAgent` (F), `GuiAgent` (F)

- [x] **Step 1: Write the failing tests**

```python
def test_the_two_arms_differ_only_in_the_string_the_agent_receives():
    goal = "Create a note titled Grocery list"
    task = _task(goal=goal)
    graph_agent = ScriptedAgent()
    RawGoalAgent(graph_agent)(task)
    GraphAgent(_pipeline(agent=graph_agent,
                         description="Overall goal: " + goal))(task)
    assert graph_agent.tasks == [goal, "Overall goal: " + goal]
    assert graph_agent.apps == [task.app, task.app]


def test_the_task_dimension_reads_the_graph_arm_only():
    entry = {"bench": [
        {"agent": "graph", "rows": [{"success": True}, {"success": False}]},
        {"agent": "raw", "rows": [{"success": True}, {"success": True}]},
    ]}
    assert app_score(entry)["task"] == 50.0
    assert control([entry])["raw"] == 100.0
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_benchmark_agents.py tests/test_benchmark_scorecard.py -q`

Expected: FAIL — there is no raw arm and `app_score` reads `agent == "graph"`
with no `control()["raw"]`.

- [x] **Step 3: Implement the second arm and record the string**

Both arms share one model, one device and one runner; the only difference is
the string.  `run_mobileworld_bench.py` gains `--agent raw` and writes
`bench-graph/summary.json` / `bench-raw/summary.json`.  Neither arm launches
anything: `prepare_state` already launched the app and ran onboarding, and
the agent acts from the screen it finds.  No experience file is threaded
through either arm, because the backend runs with `verify=False` and writes
no memory entry — there is nothing to leak between arms, and pretending to
separate a store neither arm writes to would be decoration.
`RawGoalAgent` calls `agent.run(task.goal, task.max_steps, app=task.app)` and
wraps the `AgentTrace` in an `AgentRun` with `reached_cards=[]` and no
predicted path — it has no graph to attribute anything to.

- [x] **Step 4: Point the scorecard and the report at the new quantity**

`app_score` reads rows with `agent == "graph"`; `control()` returns
`{"random": ..., "raw": ...}`.  `build_bench_report.py` gains a paired table
per app — both-pass, graph-only, raw-only, both-fail — and per-task rows
showing each arm's `task_text`.  The overview states the level-versus-delta
distinction and that the task dimension is discontinuous here.

- [x] **Step 5: Run the benchmark tests**

Run: `python -m pytest tests/test_benchmark_agents.py tests/test_benchmark_scorecard.py tests/test_benchmark_report.py tests/test_benchmark_suite_runner.py -q`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add specfcg/benchmark scripts/run_mobileworld_bench.py scripts/build_bench_report.py tests
git commit -m "feat(bench): ablation between the raw goal and the graph's task description"
```

---

### Task C: duplicate functions, read from contracts

**Why the meaning changes.** The old measure compiled each card's steps and
compared the resulting `(action, control)` sets.  A card has no steps now, so
behavioural equivalence is not computable without executing both cards — a
device run per pair.  What is computable is the contract: the semantic-edge
call already reads every card's intent, inputs, preconditions,
postconditions and effects, so asking it, in the same call, which cards
describe the same function costs no extra call.

**This is a reported diagnosis, not a score.** With the actions gone there is
no deterministic oracle for "same function", and an LLM judgement must not be
dressed up as a measurement.  It is reported beside the graph dimensions for
a person to inspect, and the groups are never merged automatically.

**Files:**
- Modify: `specfcg/maintainer/builder.py:13-16`, `:99-169`
- Modify: `specfcg/pipeline.py:126-136` (write the groups)
- Create: `scripts/measure_duplicates.py`
- Modify: `scripts/build_bench_report.py:403-430`, `:455-510` (the
  "granularity" column and the duplicate-group listing)
- Test: `tests/test_edge_builder.py`, `tests/test_benchmark_duplicates.py`

**Interfaces:**
- Produces: `SemanticResult(edges: list[Edge], same_function: list[list[str]])`;
  `EdgeBuilder.infer_semantic(cards) -> SemanticResult` and `build(cards,
  segments) -> SemanticResult`.
- Produces: `graph/same_function.json` — `{"groups": [[...], ...]}` per app.
  `Pipeline.build_graph` keeps returning `list[Edge]` (three callers and their
  tests depend on it); it takes `.edges` from the result and writes the groups
  beside the edges.  The groups are read from disk by whoever wants them,
  which is the point: they are reported, not consumed.

- [x] **Step 1: Write the failing builder test**

```python
def test_the_semantic_call_reports_groups_and_drops_unknown_names(fake_llm):
    fake_llm.reply_json = {"edges": [], "same_function": [
        ["create_note", "add_note"],      # a real group
        ["create_note", "invented_card"], # dropped: unknown name
        ["share_note"],                   # dropped: not a group
    ]}
    result = EdgeBuilder(fake_llm).infer_semantic(two_cards)
    assert result.same_function == [["create_note", "add_note"]]
    assert result.edges == []
```

- [x] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_edge_builder.py -q`

Expected: FAIL — `infer_semantic` returns a bare list, so `.same_function`
does not exist.

- [x] **Step 3: Extend the schema, parse, and persist**

Add `"same_function": [["create_note", "add_note"]]` to `_EDGE_SCHEMA` and to
the prompt ("also list groups of cards that describe the same user-level
function").  Validate every name against `cards`, drop groups shorter than
two or naming an unknown card, and dedupe.  `Pipeline.build_graph` writes
`graph/same_function.json` beside the edges and returns `result.edges`, so
its three callers and their tests keep working unchanged.

- [x] **Step 4: Replace the measure with a reader**

`measure_duplicates.py` reads each app's `same_function.json` and prints the
groups; the report's "granularity" column becomes a "duplicate groups" column
with the count and the members, and `_granularity_groups` reads
`same_function.json` instead of `granularity.json`.  The report says
explicitly that this is a model judgement, not a measured score, and that the
old behavioural number measured a different card format and is not
comparable.  `runs/mobileworld/granularity.json` stays on disk as a historical
record and is no longer read.

- [x] **Step 5: Run the tests**

Run: `python -m pytest tests/test_edge_builder.py tests/test_benchmark_duplicates.py tests/test_pipeline.py -q`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add specfcg scripts tests
git commit -m "feat(graph): read duplicate functions from the contracts, and say it is a judgement"
```

---

### Task A: rebuild the four graphs with the current builder

**Files:** none (a run); outputs under `runs/mobileworld/<app>/graph`.

Runs after C, so the rebuild writes the `same_function` groups in the same
single semantic call.

- [ ] A1: rebuild each app from the traces already on disk

```
PYTHONPATH=. python scripts/build_app_graph.py --app activitydiary --skip-collect --config config/llm.bench.yaml
PYTHONPATH=. python scripts/build_app_graph.py --app amaze --skip-collect --config config/llm.bench.yaml
PYTHONPATH=. python scripts/build_app_graph.py --app markor --skip-collect --config config/llm.bench.yaml
PYTHONPATH=. python scripts/build_app_graph.py --app omninotes --skip-collect --config config/llm.bench.yaml
```

Expected: one `semantic edges` journal frame per app (the builder derives the
edges once, after the last trace), no card file containing `**Steps**`, and no
duplicate card for a trace mined twice.  `scripts/measure_graph_cost.py`
confirms the call count from the journal itself.

- [ ] A2: record coverage, duplicate groups and the card count

```
PYTHONPATH=. python scripts/measure_duplicates.py
PYTHONPATH=. python scripts/measure_graph_cost.py
python -m pytest -q
```

Expected: coverage is recomputed by the current matcher and is allowed to
differ from the recorded 84.5% mean — a rebuild is a different graph.  The
`merge_notes` / `merge_two_notes` pair should appear in one duplicate group.
A card the new miner could not give a contract to is absent, and its trace id
is in the mining log — a smaller graph with honest cards beats a larger one
with names.

- [ ] A3: regenerate the replay pages from the new journals

```
PYTHONPATH=. python scripts/build_graph_page.py --app activitydiary
PYTHONPATH=. python scripts/build_graph_page.py --app amaze
PYTHONPATH=. python scripts/build_graph_page.py --app markor
PYTHONPATH=. python scripts/build_graph_page.py --app omninotes
```

---

### Task B: re-measure the device dimensions

**Files:** none (runs); records under `runs/mobileworld/<app>/experiments`
and `bench-graph` / `bench-raw`.

- [ ] B1: re-run random traversal and probes on the rebuilt graphs

```
PYTHONPATH=. python scripts/run_graph_experiments.py --app activitydiary --serial 47261FDAS00DTQ --config config/llm.bench.yaml
```

(and the other three apps)

Expected: a probe record with a non-constant `predicted_confidence` across
probes.  Three of the four recorded runs predicted 0.45 for every probe, which
makes the bias-only calibration score uninformative; if the rebuilt graphs
still produce one value, the estimator — not the graph — is what Task D
changes.  Each probe's "reached" now means the agent's screens showed the
function.

- [ ] B2: re-run the self-optimization curve from a fresh seed

```
PYTHONPATH=. python scripts/run_selfopt.py --app activitydiary --rounds 4 --serial 47261FDAS00DTQ --config config/llm.bench.yaml
```

(and the other three apps)

Expected: `--rounds 4` matches the recorded runs, so the gain is comparable.
A run that grows nothing saves no record.  Completion now probes with the
agent, so a round costs more tokens than it did — record that in the report
rather than hiding it.

- [ ] B3: run both arms of the ablation on all four apps

```
PYTHONPATH=. python scripts/run_mobileworld_bench.py --app activitydiary --agent graph --serial 47261FDAS00DTQ --config config/llm.bench.yaml
PYTHONPATH=. python scripts/run_mobileworld_bench.py --app activitydiary --agent raw   --serial 47261FDAS00DTQ --config config/llm.bench.yaml
```

(and the other three apps, both arms)

Expected: two summaries per app with the same `tasks`, `seed` and model; every
row carries `task_text`, and the graph arm's text is the description from
`TestPlan`.

- [ ] B4: record the point and rebuild the report

```
PYTHONPATH=. python scripts/record_score.py --label agent-execution
PYTHONPATH=. python scripts/build_bench_report.py
```

Expected: one new point whose four dimensions all come from records written
by the current code.  Do not compare it with the earlier points as if only the
graphs changed: the coverage matcher, the card format, the executor and the
task definition all changed.  The report carries that sentence.

---

### Task D: calibration over agent runs

**Why the meaning changes.** A probe used to predict whether a compiled path
would execute; it now predicts whether a description will lead an agent to the
function's evidence.  The "actual" side of the comparison is therefore agent
behaviour, and the prediction has to be about the same thing.

**Files:** `specfcg/benchmark/exploration.py` (`calibration`),
`specfcg/benchmark/scorecard.py` (calibration dimension),
`tests/test_benchmark_exploration.py`.

- [ ] D1: write the failing test — a constant estimate scores no better than
      the base rate

```python
def test_a_constant_estimate_earns_only_the_base_rate():
    probes = [_probe(predicted=0.45, reached=hit)
              for hit in (True, False, True, False)]
    assert brier(probes) >= brier(
        [_probe(predicted=0.5, reached=p.reached) for p in probes]
    )
```

- [ ] D2: implement only if B1 shows the estimator is still constant

Deliberately conditional.  If the rebuilt graphs produce distinct predictions,
the bias score already measures something and the Brier change is
unnecessary.  Measure first.  If it is still constant, replace the dimension
with a Brier score over the probes and say in the report that the old bias
number rewarded a constant.

- [ ] D3: state in the report what the dimension can and cannot see

The prediction is about the graph's route, the observation is about the
agent's walk; an agent that ignores a correct route and an agent that finds
the function despite a wrong one both appear as prediction error.  A single
number cannot separate those, and the report says so rather than implying the
graph was right or wrong.

---

### Task E: keep the ledger current

- [ ] E1: after each task above, tick the steps that ran and record the
  command and the result, so the plan never again reads as untouched while
  the work is in the tree.

---

### Self-Review (this round)

**Spec coverage.** Every part of the correction has an owning task: cards as
contracts, the plan as a description and the agent as the executor (F); the
probe rebuilt against the agent (F) and wired through the completer (G); the
paired ablation (H); duplicates under the new model (C); rebuild (A);
re-measure (B); calibration (D); the ledger (E).  Spec text is edited inside F
and G — the format, the architecture section and the probe definition travel
with the code that changes them.

**Type consistency.** `FunctionCard` has no `steps` from F onward, and F
updates every consumer it can reach in one commit.  `TestPlan.description` is
produced in F and consumed by F's executor and by both arms in H.  `AgentTrace`
is produced by `GuiAgent` (F) and consumed by `Executor` (F), `AgentProbe` (F)
and both arms (H).  `Step` (a trace record) is never confused with `PlanStep`,
which is deleted with its last producer.  The bench agent name is `graph`
everywhere — script, summary, scorecard — from F onward.

**Deliberate deletions, each named with the design it belonged to:**
`specfcg/planner/compiler.py` and its 41 tests (compiling contracts back into
taps), `PlanStep`, `execute_plan` (replay), `SpecFCGAgent` (the replay
adapter), `granularity.py` and its two test files (behavioural equivalence
without behaviour), `MissingCapability.probe` (a guessed control sequence),
`DeviceProbe`, `StepCompiler`, `_fallback_card` (a card invented from trace
actions), the `calls` edge type (one card containing another's steps).

**Limits to state in the report, not to hide.**
- The 20-task suite is too small for a significance claim over the paired
  difference.  This round makes the comparison possible and honest; the suite
  has to grow before the delta can be called a result.
- Card attribution of a run is whole-path, so `card_rate` now moves in
  path-sized steps and the per-card success counts are coarser than before.
- Duplicate detection is an LLM judgement.  It is reported, never scored, and
  never merged automatically.
- The agent's own verifier is disabled for planned runs (`verify=False`), so
  its self-reported `done` is recorded and ignored; the programmatic oracle
  decides.  A consequence worth stating: the experience memory stays empty on
  those runs, so a planned run cannot teach the agent anything it did not
  already know.  That is deliberate — an unjudged run is not evidence — and it
  is also why the ablation measures the graph's description and not the
  agent's self-improvement.

**Placeholders:** none.  Every step has a file, an interface, a test and a
command.

---

## Self-Review

**Spec coverage:** Every spec section maps to a task:
- Function card / FCG / state summary / goal / test plan → Tasks 2, 3, 4, 6, 7.
- Trace collection → Task 5 (fixtures) + Task 15 (ProphetAgent).
- Card mining / graph building → Tasks 6, 7.
- Planning / execution → Tasks 8, 9, 10, 11.
- Graph maintenance → Task 12.
- Capability completion → Task 13.
- CLI / multi-round loop → Task 14.
- Evaluation → Tasks 16, 17.
- Review-focus failure modes → tests in Tasks 1, 3, 4, 6, 7, 9, 11.

**Type consistency:** `FunctionCard`, `Edge`, `Graph`, `CardPatch`, `GraphPatch`, `TestPlan`, `RunResult` are defined once in Task 2 and reused by name. `CardPatch.segments` is produced by Task 6 and consumed by Task 7. `GraphStore` is created with `(root, cards)` everywhere. `Executor.execute(plan)` uses the graph injected at construction.

**Known deviations (documented):**
- MVP retrieval is keyword + LLM, not embedding. The spec allows embedding as the default; this plan defers it to Stage 2 to avoid a heavy dependency.
- MVP target resolution is text / resource-id / LLM fallback; ProphetAgent's CUTG matcher is deferred to Stage 2 because it requires neo4j + semantic-agent setup. Trace collection still uses ProphetAgent's Droidbot at the pinned commit.

**Placeholders:** None. Every task has a concrete file, interface, test, and verification command.
