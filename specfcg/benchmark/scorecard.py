"""The experiment scorecard: five 0-100 dimensions computed from records.

The score is a function of what the experiments wrote, never a typed-in
number.  Keeping it here, rather than inside the report script, is what lets
every iteration be recorded into the same history and drawn as one curve.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# (key, label, how the dimension is measured)
#
# Unguided traversal reachability is deliberately NOT a dimension: it is a
# property of the app, identical for every system measured on it, so giving it
# weight would move the score without measuring any capability.  It is
# reported as the control the graph is compared against.
DIMENSIONS = [
    ("graph", "图完整度", "源码功能清单覆盖率"),
    ("calibration", "探针标定", "100 − |预测 − 实际|"),
    ("selfopt", "自优化增益", "补图新增功能占清单比例"),
    ("task", "任务成功率", "20 步上限内 specfcg 通过率"),
]


def _selfopt_flat(record: dict | None) -> dict:
    """The runner's {summary, rounds} shape, flattened."""
    if not record:
        return {}
    if isinstance(record.get("summary"), dict):
        return {**record["summary"], "records": record.get("rounds") or []}
    return record


def measured(record: dict | None, kind: str) -> dict | None:
    """A record only if it measured something.

    Both experiments that read the seed graph are vacuous on a complete
    one: the growth run finds nothing to grow and saves zero rounds, the
    probe run finds nothing to probe and saves an empty list.  Such a
    record is not evidence that the system gained nothing -- it is
    evidence that the experiment was pointed at a graph with no gaps, and
    reading it as a score would replace a real measurement with a zero.

    The runners ask the same question before writing, so a vacuous record
    is never produced and an existing real one is never overwritten.
    """
    if not record:
        return None
    if kind == "selfopt":
        return record if (record.get("summary") or {}).get("rounds") else None
    calibration = record.get("calibration") or {}
    probes = record.get("probes") or calibration.get("probes")
    return record if probes else None


def coverage_from_disk(
    app: str, runs: Path, root: Path | None = None
) -> "CoverageReport | None":
    """The graph dimension, asked of the graph rather than read from a record.

    ``coverage.json`` stores what the matcher returned on the day the
    experiment ran.  Correcting the matcher -- dropping the inventory's
    ``cards`` hints from the score, because they are the answer key of one
    particular build -- leaves every stored record describing a rule the code
    no longer applies.  Both inputs are on disk, so the scorecard recomputes
    instead of trusting a snapshot: the same call the experiment makes.
    """
    from specfcg.benchmark.coverage_eval import (
        graph_coverage,
        load_inventory,
    )
    from specfcg.cards.store import CardStore
    from specfcg.graph.store import GraphStore

    runs = Path(runs)
    root = Path(root) if root is not None else runs.parents[1]
    graph_root = runs / app / "graph"
    inventory = root / "benchmark" / "coverage" / f"{app}.yaml"
    if not graph_root.exists() or not inventory.exists():
        return None
    cards = CardStore(graph_root).all()
    if not cards:
        return None
    graph = GraphStore(graph_root, CardStore(graph_root)).load()
    return graph_coverage(load_inventory(inventory), graph)


# The graph arm was called "specfcg" before Task F renamed it "graph".
# Records keep the name they were written with, so both are read.
_GRAPH_AGENT_NAMES = {"graph", "specfcg"}
# The raw-goal arm is a control, never a dimension: its success is the
# agent's competence, and only the paired difference is the graph's.
_RAW_AGENT_NAMES = {"raw"}


def app_score(entry: dict) -> dict[str, float]:
    """Per-app scores, each 0-100 and computed from its saved records."""
    coverage = entry.get("coverage") or {}
    calib = (entry.get("probes") or {}).get("calibration") or {}
    selfopt = _selfopt_flat(entry.get("selfopt"))
    rows = next(
        (
            bench.get("rows") or []
            for bench in entry.get("bench") or []
            if bench and bench.get("agent") in _GRAPH_AGENT_NAMES
        ),
        [],
    )
    total = selfopt.get("total") or coverage.get("functions") or 0
    gained = (selfopt.get("covered_end", 0) or 0) - (
        selfopt.get("covered_start", 0) or 0
    )
    return {
        "graph": round(100 * float(coverage.get("score") or 0.0), 1),
        "calibration": round(
            100
            - 100
            * abs(
                float(calib.get("predicted") or 0.0)
                - float(calib.get("actual") or 0.0)
            ),
            1,
        )
        # A calibration over no probes is a perfect prediction of nothing.
        if calib.get("probes")
        else 0.0,
        "selfopt": round(100 * gained / total, 1) if total else 0.0,
        "task": round(
            100 * sum(1 for row in rows if row.get("success")) / len(rows), 1
        )
        if rows
        else 0.0,
    }


def _success_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    return 100 * sum(1 for row in rows if row.get("success")) / len(rows)


def control(entries: list[dict]) -> dict[str, float]:
    """The control measurements, reported beside the score, never scored.

    ``random`` is traversal without a graph.  ``raw`` is the same agent as the
    graph arm, given the user's own words instead of the graph's description:
    the ablation's second arm.  Neither is folded into the overall score.
    """
    random_values = [
        100 * float((entry.get("random") or {}).get("score_union") or 0.0)
        for entry in entries
    ]
    random_values = [value for value in random_values if value]
    raw_values = []
    for entry in entries:
        for bench in entry.get("bench") or []:
            if bench and bench.get("agent") in _RAW_AGENT_NAMES:
                raw_values.append(_success_rate(bench.get("rows") or []))
    return {
        "random": (
            round(sum(random_values) / len(random_values), 1)
            if random_values
            else 0.0
        ),
        "raw": (
            round(sum(raw_values) / len(raw_values), 1) if raw_values else 0.0
        ),
    }


def scorecard(entries: list[dict]) -> dict:
    """Per-app scores, the mean of each dimension, and the equal-weight mean."""
    apps = {entry["app"]: app_score(entry) for entry in entries}
    if not apps:
        dims = {key: 0.0 for key, _label, _source in DIMENSIONS}
        return {
            "apps": {},
            "dims": dims,
            "control": control(entries),
            "overall": 0.0,
        }
    dims = {
        key: round(sum(scores[key] for scores in apps.values()) / len(apps), 1)
        for key, _label, _source in DIMENSIONS
    }
    return {
        "apps": apps,
        "dims": dims,
        "control": control(entries),
        "overall": round(sum(dims.values()) / len(DIMENSIONS), 1),
    }


def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _first(*paths: Path) -> dict | list | None:
    """The first existing record among the candidate paths."""
    for path in paths:
        record = _load(path)
        if record is not None:
            return record
    return None


def _first_measured(kind: str, *paths: Path) -> dict | list | None:
    """The first record that actually measured its dimension.

    A run pointed at a graph with no gaps saves a vacuous record rather
    than no record, so "the newest file" is not the same question as "the
    measurement".  Falling through to the next candidate keeps a real
    measurement from being replaced by an empty one.
    """
    for path in paths:
        record = measured(_load(path), kind)
        if record is not None:
            return record
    return None


def collect_entries(runs: Path) -> list[dict]:
    """One entry per app, read from the layout the experiment scripts write.

    The complete-graph runs live in ``experiments/``; probes and the
    self-optimization curve deliberately run on an incomplete seed graph, so
    their records live in ``seed-experiments/``.  Both are the same
    measurement of the app, so each dimension falls back to the seed run.

    Coverage is the exception: the graph and the inventory are both on disk,
    so it is recomputed rather than read back.  A stored number was produced
    by whichever matcher existed that day; reading it would score a rule the
    code no longer applies, and a corrected matcher could never move the
    curve.  ``coverage`` therefore carries the fresh report, and
    ``coverage_record`` keeps what the run saved for the reader who wants to
    see both.
    """
    entries = []
    for app_dir in sorted(Path(runs).iterdir()):
        if not app_dir.is_dir():
            continue
        experiments = app_dir / "experiments"
        seed = app_dir / "seed-experiments"
        bench = sorted(app_dir.glob("*/summary.json"))
        fresh = coverage_from_disk(app_dir.name, runs)
        entries.append(
            {
                "app": app_dir.name,
                "coverage": fresh.as_record() if fresh is not None else _first(
                    experiments / "coverage.json", seed / "coverage.json"
                ),
                "coverage_record": _first(
                    experiments / "coverage.json", seed / "coverage.json"
                ),
                "random": _first(
                    experiments / "random.json", seed / "random.json"
                ),
                "probes": _first_measured(
                    "probes",
                    experiments / "probes.json",
                    seed / "probes.json",
                ),
                "selfopt": _first_measured(
                    "selfopt",
                    experiments / "selfopt.json",
                    seed / "selfopt.json",
                ),
                "seed_coverage": _load(seed / "coverage.json"),
                "bench": [_load(path) for path in bench],
                "shots": sorted(
                    str(path) for path in app_dir.glob("*/shots/*.png")
                ),
            }
        )
    return entries


def load_history(path: Path) -> list[dict]:
    """The recorded points, in order; an absent or broken file is empty."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    points = data.get("points") if isinstance(data, dict) else None
    return points if isinstance(points, list) else []


def record_point(
    path: Path,
    label: str,
    card: dict,
    dimensions: list[tuple[str, str, str]] | None = None,
) -> dict:
    """Append one iteration to the history; re-recording a label replaces it.

    Re-running the same measurement must not bend the curve: the point for a
    label is updated in place, so the curve shows one dot per iteration that
    actually happened, not one dot per command that was typed.
    """
    path = Path(path)
    points = load_history(path)
    labels = [key for key, _label, _source in (dimensions or DIMENSIONS)]
    point = {
        "iteration": 0,
        "label": label,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dims": {key: card["dims"].get(key, 0.0) for key in labels},
        "per_app": {
            app: {key: scores.get(key, 0.0) for key in labels}
            for app, scores in card.get("apps", {}).items()
        },
        "control": dict(card.get("control") or {}),
        "overall": card["overall"],
    }
    if points and points[-1].get("label") == label:
        point["iteration"] = points[-1].get("iteration", 0)
        points[-1] = point
    else:
        point["iteration"] = len(points)
        points.append(point)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"points": points}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return point
