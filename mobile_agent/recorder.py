"""Writing a run's evidence to disk, in one place.

The agent's loop used to write its own artefacts: eight `write_text` calls
scattered through a 260-line `run()`, interleaved with loop control, stall
detection and verification.  A reader could not tell which of them were the
run's record and which were side effects of a branch, and adding one meant
threading another variable through the loop.

`RunRecorder` owns the directory and the files.  The loop calls named methods
— `step`, `reflection`, `result` — and the layout of a run directory is
defined here, once, rather than implied by call sites.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


class RunRecorder:
    """The artefact directory for one task run."""

    def __init__(self, out: Path) -> None:
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)

    # --- what the loop records as it goes -------------------------------

    def initial_ui(self, ui: str) -> None:
        (self.out / "initial_ui.txt").write_text(ui, encoding="utf-8")

    def memory(self, entries: list[Any]) -> None:
        (self.out / "memory.json").write_text(
            json.dumps(
                [asdict(entry) for entry in entries], ensure_ascii=False
            ),
            encoding="utf-8",
        )

    def step_before(self, step: int, ui: str) -> None:
        (self.out / f"step_{step:02d}_before.txt").write_text(
            ui, encoding="utf-8"
        )

    def step_after(self, step: int, ui: str) -> None:
        (self.out / f"step_{step:02d}_after.txt").write_text(
            ui, encoding="utf-8"
        )

    def reflection(self, step: int, text: str) -> None:
        with (self.out / "reflections.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"step": step, "text": text}, ensure_ascii=False)
                + "\n"
            )

    # --- what the run leaves behind -------------------------------------

    def finish(
        self,
        *,
        result: Any,
        steps: list[dict[str, Any]],
        final_ui: str,
        done_summary: str,
    ) -> None:
        """Write the run's summary and its final state.

        `result.json` and `steps.json` are what every downstream reader
        consumes; `final_ui.txt` and `done_summary.txt` are for a person
        reading one run by hand.
        """
        (self.out / "result.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.out / "steps.json").write_text(
            json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.out / "final_ui.txt").write_text(final_ui, encoding="utf-8")
        (self.out / "done_summary.txt").write_text(
            done_summary, encoding="utf-8"
        )
