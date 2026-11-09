# SpecFCG Stage 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Stage 1 MVP of SpecFCG: a Python system that mines natural-language function cards from Android GUI traces, builds a Function Contract Graph, plans goal-driven test paths, executes them on an emulator, refines the graph, and completes missing capabilities.

**Architecture:** Five modules — Trace Collector, Graph Maintainer (card mining + graph updates), Graph Store (cards + edges + versioning), Planner (BFS/DFS/A* with LLM transition checks), Executor (uiautomator2 device + LLM state summaries). The offline core is fully testable with fakes; the ProphetAgent adapter and real device are integration layers. A thin `Pipeline` composes the modules for the CLI and benchmarks.

**Tech Stack:** Python 3.10+, pytest, PyYAML, `openai` SDK (OpenAI-compatible endpoint), `uiautomator2` (optional device extra), ADB. No graph library — the graph is small and BFS/DFS/A* are implemented directly.

**Spec:** `docs/superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md`

## Global Constraints

- Python `>=3.10`; code runs on Windows, macOS, and Linux.
- Function granularity is **user-level task** (`create_note`, `attach_photo`, `share_note`), never page-level or widget-level.
- Cards and edges are **natural language first**; no typed predicate DSL, no symbolic state tracker, no formal condition parser.
- Edge types: `enables`, `dataflow`, `sequence`; `calls` is optional and only used when a card's steps literally contain another card.
- Every LLM call uses `temperature=0` and goes through the cache; model and base URL are configurable in `config/llm.yaml`.
- All LLM outputs are parsed defensively. Malformed JSON/Markdown must produce a typed error or a documented fallback — never an uncaught exception that kills a run.
- Stage 1 apps: AnkiDroid, AmazeFileManager, OmniNotes, NewPipe, ActivityDiary, AntennaPod.
- Stage 1 data: 60 NL cases (10/app) and 30 compositional goals (5/app); held-out traces for path recall.
- Stage 1 gates: card validity ≥ 80% on 50 human-checked cards; path recall ≥ 70%; known-case completion ≥ 70%; compositional completion ≥ 50% and ≥ 20 points above ProphetAgent; ≥ 3 new capabilities/bugs.
- ProphetAgent is pinned at commit `97667bfe109e71f57d84a2f7df9bcb03aba55b11` (MIT). It is used for trace collection via its bundled Droidbot; the MVP executor uses `uiautomator2` directly.
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

- [ ] **Step 1: Initialize the repo and branch**

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

- [ ] **Step 2: Write the failing tests**

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

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_config.py tests/test_llm_client.py -v`

Expected: FAIL with import errors (`load_config`/`CachedLLMClient` not defined).

- [ ] **Step 4: Implement the config, client, cache, and fakes**

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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_config.py tests/test_llm_client.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_card_parser.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the models and parser**

Parser rules: the first line is `# name`; headings are `**Intent**:`, `**Inputs**:`, `**Preconditions**:`, `**Postconditions**:`, `**Effects/Outputs**:`, `**Steps**:`, `**Evidence**:`. Steps are numbered lines after the `**Steps**:` heading. Evidence parses `traces t1, t2; 2/3 successes` into `evidence=["t1","t2"]`, `success_count=2`, `attempt_count=3`; if no counts, both stay 0. Missing required headings raise `CardParseError`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_card_parser.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_card_store.py tests/test_graph_store.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the stores**

`CardStore` uses `cards/<slug>.md`; slug lowercases and replaces non-alphanumerics with `_`. `all()` logs and skips malformed files. `GraphStore` loads `graph/edges.jsonl`; `apply_patch` handles `new_cards`, `card_updates`, `edge_updates` (`add`/`update`/`remove`), `split` (delete the old card; replacements come from `new_cards`), and `merge` (keep the first card, merge evidence, delete the second, rewrite edges). `backup()` copies `cards/` and `graph/edges.jsonl` to `graph/versions/<timestamp>/`. `restore()` replaces both from the backup.

`neighbors(name, type=None)` returns outgoing edges ordered by type priority: `enables`, `dataflow`, `sequence`, `calls`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_card_store.py tests/test_graph_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_graph_search.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `search`**

Use adjacency from `graph.edges`. BFS uses `collections.deque` of paths; DFS uses a list as a stack; A* uses `heapq` with `(cost + heuristic(card), cost, path)`. Edge priority: `enables`, `dataflow`, `sequence`, `calls`. Mark candidates visited before enqueueing; skip visited candidates. Return `None` when the frontier is exhausted.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_graph_search.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_trace_recorder.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement recorder/store/collector**

Trace JSON is `{"trace_id": ..., "app": ..., "steps": [Step fields]}`. `TraceParseError(Exception)` wraps JSON/shape errors. `FixtureCollector` filters by `trace.app` and returns an empty list when none match.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_trace_recorder.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_miner.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the miner**

Prompts:

- Segmentation: "Split this trace into user-level function episodes. Return JSON `{episodes:[{start,end,name,intent}]}`. Boundaries are inclusive step indices."
- Card drafting: "Write a Markdown function card with headings Intent, Inputs, Preconditions, Postconditions, Effects/Outputs, Steps, Evidence. Use the trace evidence."

Validation: segments must be non-overlapping, sorted, within `[0, len(steps)-1]`; otherwise fall back to one episode spanning the whole trace. `draft` parses the LLM Markdown with `parse_card`; on `CardParseError`, build a minimal card from the episode (`name`, `intent`, `steps=[step.action + " " + step.target]`, empty pre/post). `mine` merges with an existing card of the same name by appending evidence and incrementing counts; otherwise adds a new card. `mine` returns an empty patch for an empty trace. Each segment maps to `{"trace_id": trace.trace_id, "start": episode["start"], "end": episode["end"], "card": card.name}`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_miner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_edge_builder.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the builder**

Sequence edges: group segments by `trace_id`, sort by `start`, add an edge for each consecutive pair. Semantic edges: send card names/intents/pre/post to the LLM; validate `from`/`to` exist and `type` is `enables` or `dataflow`; skip invalid entries. Deduplicate by `(from, to, type)` and merge evidence.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_edge_builder.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_device.py tests/test_summarizer.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the device and summarizer**

`FakeDevice` pops states and action results; `dump_ui` returns the current state (last one repeats); `execute` records calls. `Uiautomator2Device` maps actions:
- `click`: `d(text=target).click()` if target starts with `text=`, else `d(resourceId=target).click()`.
- `input`: `d(text=target).set_text(args)`.
- `back`: `d.press("back")`.
- `swipe`: `d.swipe(...)` with `args` formatted `x1,y1,x2,y2`.
- `wait`: `time.sleep(float(args or 1))`.

`StateSummarizer` prompts: "Summarize this Android UI hierarchy in at most 6 lines: current screen, visible widgets, user state, known entities, recent actions." On any exception or empty response, return `ui_dump[:2000]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_device.py tests/test_summarizer.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_executor.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the executor**

Group `plan.steps` by `card` while preserving order. For each step: capture `before = device.dump_ui()`, call `device.execute`, capture `after`, append a `Step` to the trace, append a result dict. On `False`, set `failure_type="widget_failure"`, stop, and return. After a card's last step, call `llm.complete_json` with the state summary and `card.postconditions`; on `LLMParseError`, set `failure_type="check_error"` and stop. At the end, check the goal; if not achieved, `failure_type="goal_failure"`. Use a `run-<uuid>` trace id.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_executor.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_retrieval.py tests/test_binding.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement retrieval and binding**

`CardRetriever` uses a simple token-overlap score (lowercase, split on non-alphanumerics). The LLM prompt returns `{"keep": ["name", ...]}`; validate names. `ParamBinder` sends the card's `inputs`, `goal.description`, `state`, and `prior_outputs`; substitutes `$key` values; returns `None` if a required input is still missing after one retry.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_retrieval.py tests/test_binding.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_compiler.py tests/test_planner.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the compiler and planner**

`StepCompiler` prompt: "Convert these function-card steps and bindings into UI actions. Return JSON `{steps:[{action,target,args}]}`; action is click/input/swipe/back/wait; target uses `text=...` or `resourceId=...`." Fallback regex: lines starting with `Tap`/`Click` → click; `Enter`/`Input`/`Type` → input; `Swipe` → swipe; `Back` → back; otherwise `click` with the whole line as target.

`Planner` closures: `can_execute(card)` calls `llm.complete_json` with "Can this card execute in this state? Return `{can_execute: bool, reason: str}`"; `is_goal(card)` calls "Does executing this card satisfy the goal or its postconditions? Return `{is_goal: bool, reason: str}`". Cache responses in a dict keyed by `(card, state)`. On `LLMParseError`, treat `can_execute=False` and `is_goal=False`. Build the plan only if all bindings succeed; otherwise return `None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_compiler.py tests/test_planner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the updater**

On success: increment `attempt_count` and `success_count` for each card in `result.plan.path`; add `sequence` edges from `result.new_trace` via `EdgeBuilder`; return the patch. On failure: prompt the LLM with `result` + current cards/edges, asking for JSON `{card_updates, new_cards, edge_updates, split, merge, reason}`; validate every card name and edge endpoint; if invalid, return an empty patch. Before applying a non-empty patch, call `store.backup()`; if `apply_patch` raises, call `store.restore(version)` and return an empty patch.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_completer.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the completer**

`detect_gap` prompt: "Given goal, cards, and state, is a capability missing? Return `{gap: string|null, blocked_precondition: string}`." `hypothesize` prompt: "Propose up to N missing capabilities as JSON `{capabilities:[...]}`." For each hypothesis, call `probe.run`; if a trace is returned, call `miner.mine(trace)`, add semantic/sequence edges via `EdgeBuilder`, validate the new card with `parse_card`, and return a combined `GraphPatch`. On failure, append `{goal, capability, reason}` to `completion/negative.jsonl` and continue. Stop at `max_hypotheses`, `max_probes`, or `max_rounds`. `ProbeRunner` is injected; tests use a fake.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_completer.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py tests/test_e2e_offline.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the pipeline and CLI**

`Pipeline` wires the components. `run_goal` loops: `plan`; if no plan, `completer.complete` and retry; else `execute`, `updater.update`, and stop on success or `max_rounds`. CLI uses `argparse`; `--fake-llm` uses `FakeLLMClient` with a small canned script, `--fake-device` uses `FakeDevice`; otherwise it builds `OpenAICompatibleClient` and `Uiautomator2Device`. `mine` writes cards/edges; `plan` prints `TestPlan` JSON; `execute` prints `RunResult` JSON; `refine` prints the patch; `complete` prints the patch or `null`; `run` prints a JSON summary.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py tests/test_cli.py tests/test_e2e_offline.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing parser test**

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

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_prophetagent_parser.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the adapter**

`parse_droidbot_output` reads `events.json` (list or `{"events": [...]}`), groups events by their trace/state sequence, and maps `event_type`/`event_str`/`from_state`/`to_state`/`view_str` to our `Step` fields. It skips events without a target and never raises on missing optional files; a missing `events.json` returns `[]`. `collect` runs:

```bash
python start.py -a <apk> -o <output_dir> -policy <policy> -count <count> -timeout <timeout>
```

from `repo_path`, then parses the output. `scripts/setup_prophetagent.sh` clones the repo and checks out the pinned commit.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_prophetagent_parser.py -v`

Expected: PASS.

- [ ] **Step 5: Manual integration check**

Run on one emulator/app:

```bash
bash scripts/setup_prophetagent.sh
specfcg mine --config config/llm.yaml --trace <output_dir>/events.json
```

Expected: a trace is parsed and a card is produced. Record the output directory in `runs/`.

- [ ] **Step 6: Commit**

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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py tests/test_runner.py -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement cases, metrics, and runner**

Metrics formulas:
- `completion_rate = successful results / total`.
- `action_accuracy = successful steps / total steps`.
- `path_recall = held-out paths reconstructible in the graph / total held-out paths` (a path is reconstructible if every consecutive pair exists as an edge).
- `coverage = {node: executed_cards / total_cards, edge: executed_edges / total_edges}`.
- `Runner` calls `run_case(case.id)` and collects `{case_id, success, goal_success, steps, failure_type}`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py tests/test_runner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

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

- [ ] **Step 1: Write the failing manifest test**

```python
def test_stage1_manifest_has_6_apps_60_cases_30_goals():
    apps = load_apps(Path("benchmark/apps.yaml"))
    cases = load_cases(Path("benchmark/cases"))
    goals = load_cases(Path("benchmark/goals"))
    assert len(apps) == 6
    assert len(cases) == 60
    assert len(goals) == 30
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_stage1_manifest.py -v`

Expected: FAIL with missing files.

- [ ] **Step 3: Create the Stage 1 data**

`benchmark/apps.yaml` lists AnkiDroid, AmazeFileManager, OmniNotes, NewPipe, ActivityDiary, AntennaPod with package names and APK paths under `third_party/apks/`. `benchmark/cases/<app>.yaml` has 10 NL cases per app. `benchmark/goals/<app>.yaml` has 5 compositional goals per app with assertions. Use the app versions recorded in `apps.yaml`; do not use apps released after the LLM training cutoff for the main results.

- [ ] **Step 4: Implement the runner**

`scripts/run_stage1.py` builds the pipeline (real or fake via flags), runs each case, aggregates metrics, and writes `runs/stage1_report.json` with `{apps, cases, goals, completion_rate, action_accuracy, path_recall, coverage, cost}`. Print a one-line summary.

- [ ] **Step 5: Run the manifest test to verify it passes**

Run: `python -m pytest tests/test_stage1_manifest.py -v`

Expected: PASS.

- [ ] **Step 6: Smoke-run the offline report**

Run: `python scripts/run_stage1.py --fake --limit 3`

Expected: `runs/stage1_report.json` exists and contains the three cases.

- [ ] **Step 7: Commit**

```bash
git add benchmark scripts/run_stage1.py tests/test_stage1_manifest.py
git commit -m "feat: add Stage 1 data manifest and evaluation report"
```

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
