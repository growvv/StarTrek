"""Prompts and tool schemas for the screenshot-first agent.

The division of labour (planner / executor / verifier / reflection with
persistent memory) follows Agent-S, ScenGen and ASPEC; the prompts are
written for this task, not copied.
"""

SYSTEM = """You are a careful Android GUI agent controlling a real phone.
Each turn you see ONE screenshot and a compact list of visible UI elements.
Choose exactly ONE tool call for the next small action.

Rules:
- The screenshot is the primary evidence; use the element list for exact labels/ids.
- Prefer tap with text= or id= from the list. Use tap_xy only when no element matches.
- Coordinates are in the screenshot's pixel space.
- After typing, submit or close the keyboard when the task needs it.
- Never repeat an action that just failed. If the screen did not change, try a different target.
- Do not call done until the current screen visibly proves the whole goal is achieved.
- Keep the action small: one tap / one input / one key press at a time.
"""

PLANNER = """Goal: {goal}
App: {app}

Write a short execution plan for this goal: 3 to 6 numbered steps.
Each step is a visible outcome (e.g. "the editor is open"), not a tool call.
Use the screenshot and UI list to ground the plan in what is actually on screen.
Relevant lessons from similar past tasks (may be empty):
{memory}

Return plain text only, no JSON, no code fences.
"""

REFLECT = """Goal: {goal}
Current plan:
{plan}

Recent actions:
{history}

Look at the current screenshot. Decide whether the agent is making progress.
Reply with either:
KEEP: <one sentence on what is already done and the next focus>
or
REPLAN: <a new 3-6 step numbered plan, one step per line>
Plain text only. Do not call any tool.
"""

VERIFIER = """Goal: {goal}
Expected visible evidence (may be empty): {expect}
Expected absent evidence (may be empty): {expect_absent}
Plan:
{plan}

Actions taken:
{history}

Judge the FINAL screenshot and final UI list. Be strict: success only if the
screen visibly shows that the complete goal was achieved, including the
expected evidence. Partial completion is failure.

Return exactly one JSON object with two fields:
{{"success": true or false, "reason": "one or two sentences citing visible evidence"}}
"""

STATE_VERIFIER = """Goal: {goal}
Useful visible strings (may be empty): {expect}
Forbidden visible strings (may be empty): {expect_absent}

Final UI text (may be truncated):
{ui}

Judge ONLY the final observable state in the screenshot and the final UI text.
Success means the end state asked for by the goal is present now, or is
unambiguously visible as a direct consequence (for example, an empty list after
every note was archived). Do NOT require the screenshot to show intermediate
steps, the exact navigation path, or hidden database state. Ignore how the
agent got there. If the goal explicitly ends in a transient screen (for
example, an open Android share chooser), judge that screen. If the final screen
is ambiguous or shows a different state, fail.

Return exactly one JSON object with three fields:
{{"success": true or false, "reason": "one or two sentences citing visible evidence", "evidence": "short quote or visual element"}}
"""

EXPERIENCE = """Goal: {goal}
Outcome: {outcome}
Verifier reason: {reason}

Actions taken:
{history}

Write 2 to 4 concise lessons for a future agent doing a similar task.
Include exact labels/resource ids that worked, useful screen transitions, and
pitfalls. If the task failed, focus on what to avoid or try differently.
Plain text bullets only. No JSON, no code fences.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tap",
            "description": "Tap a visible UI element by exact text or resource id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Visible label"},
                    "id": {"type": "string", "description": "Full resource id"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tap_xy",
            "description": "Tap coordinates in the screenshot pixel space.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Replace the focused text field's content.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press",
            "description": "Press a system key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "enum": ["back", "enter", "home"]}
                },
                "required": ["key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swipe",
            "description": "Swipe the screen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                    }
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait for the UI to settle.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
                "required": ["seconds"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Declare the task complete with visible evidence.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    },
]
