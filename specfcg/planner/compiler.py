"""Compile function-card steps into concrete UI actions."""

from __future__ import annotations

import logging
import re

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, PlanStep

logger = logging.getLogger(__name__)

_ACTIONS = {
    "click",
    "long_click",
    "input",
    "swipe",
    "back",
    "wait",
    "press",
}
_QUOTED_RE = re.compile(r"[\"“']([^\"”']+)[\"”']")
_CODE_RE = re.compile(r"`([^`]+)`")
_BACK_RE = re.compile(r"\bback\b", re.IGNORECASE)
# A step whose verb is press/hit on the system Back control navigates back,
# whatever widget the sentence names afterwards.  Mined cards describe the
# screen they leave ("Press Back ... shown by EditText id=detail_title"), and
# treating that description as the target taps the screen instead of leaving
# it -- every later step then runs one screen behind.
_BACK_KEY_RE = re.compile(
    r"^(?:press|hit)\b[^.]{0,40}\bback\b", re.IGNORECASE
)
# Hiding the soft keyboard is not navigation.  A step that presses Back to
# dismiss the keyboard, or says the keyboard is showing, is getting the IME
# out of the way; a plain ``back`` would navigate instead whenever no
# keyboard is up -- and in a freshly cleared app none is, so the step leaves
# the screen the next step needs.  The device dismisses the IME by keycode.
_DISMISS_IME_RE = re.compile(
    r"\b(?:dismiss|hide|close|put away|get rid of)\b[^.]{0,30}?"
    r"\b(?:soft\s+)?(?:keyboard|ime|input\s+method)\b"
    r"|\b(?:soft\s+)?(?:keyboard|ime)\b[^.]{0,20}?\b(?:showing|shown"
    r"|visible|displayed|open)\b",
    re.IGNORECASE,
)
_KEY_RE = re.compile(
    r"^(?:press|hit)\b.*\b(?:enter|ime|keyboard)\b", re.IGNORECASE
)
# A press of a named hardware key is a key press, not a tap: the device's
# `press` accepts key names (home, back, menu, search, delete, ...).
_NAMED_KEY_RE = re.compile(
    r"^(?:press|hit)\s+(?:the\s+)?(?:system\s+)?"
    r"(home|back|escape|esc|menu|search|delete|del|enter|recent"
    r"|volume_up|volume_down|volume_mute|camera|power)\b"
    r"(?:\s+key|\s+button)?",
    re.IGNORECASE,
)
_NAMED_KEYS = {
    "esc": "escape",
    "del": "delete",
    "recent": "recent",
}
_ENTER_RE = re.compile(
    r"(?:\b(?:press|hit)\b.*\b(?:enter|ime|keyboard)\b)"
    r"|(?:\bsubmit\b.*\bsearch\b)",
    re.IGNORECASE,
)
# A held touch is its own gesture: "Long-press the row" is neither a tap nor
# a key press, and the device exposes it as ``long_click``.
_HOLD_RE = re.compile(
    r"\b(?:long[-_ ]?press|long[-_ ]?click|long[-_ ]?tap|press and hold"
    r"|touch and hold|hold down|hold)\b",
    re.IGNORECASE,
)
# Typing verbs name the field they write into; a dialog heading named in the
# same sentence is context.  The verb is recognized at the start of a step or
# wherever an input widget is described, so "Click the Replace button" stays
# a click.
_TYPING_START_RE = re.compile(
    r"^(?:enter|input|type|fill|replace|clear|set)\b", re.IGNORECASE
)
# Cards often open with where the step happens ("In the tag dialog, click
# the option ...").  That clause is context; the verb after it is the action.
_CONTEXT_CLAUSE_RE = re.compile(
    r"^(?:in|on|from|within)\b[^,]{0,120},\s*(?=[A-Za-z])", re.IGNORECASE
)
# "description 'More options'" / "label 'Move'" name the control by its
# accessibility text even without a resource id.
_ACCESSIBLE_RE = re.compile(
    r"\b(?:description|desc|content[- ]desc|label)\b\s+"
    r"(?:is\s+)?[`'\"]([^`'\"]+)[`'\"]",
    re.IGNORECASE,
)
# The same naming with the value supplied by a binding.
_ACCESSIBLE_BOUND_RE = re.compile(
    r"\b(?:description|desc|content[- ]desc)\b[^.]{0,40}?"
    r"\{([A-Za-z_][\w-]*)\}",
    re.IGNORECASE,
)
_TYPING_RE = re.compile(
    r"\b(?:enter|input|type|fill|replace|clear|set)\b", re.IGNORECASE
)
_VISIBLE_TEXT_RE = re.compile(
    r"\bvisible\s+(?:text|label)\b\s*[`'\"]?([^`'\"|]+?)[`'\"]",
    re.IGNORECASE,
)
# A step that identifies one row among many by what it displays names the
# value that actually selects it.  The id it mentions belongs to the
# container, which is shared by every row in the list.
_ROW_TITLE_RE = re.compile(
    r"\bwhose\b.{0,140}?\b(?:displays?|displaying|shows?|reads|equals"
    r"|is)\b.{0,20}?[`'\"]?\{([A-Za-z_][\w-]*)\}",
    re.IGNORECASE,
)
_TITLED_RE = re.compile(
    r"\b(?:row|item|file|note|entry|folder)\b.{0,60}?"
    r"\b(?:titled|labeled|named|called)\b\s+[`'\"]?\{([A-Za-z_][\w-]*)\}",
    re.IGNORECASE,
)
# A step can name a control *inside* one row ("the properties button in the
# row for {file}").  That control's id repeats on every row, so the row is
# part of the selector, not a description of it.  The containment phrase is
# what distinguishes that from "the menu item labeled X", where the label is
# an attribute of the control itself.
_ROW_ANCHOR_RE = re.compile(
    r"\b(?:in|within|inside|under)\s+the\s+(?:row|item|entry)\b"
    r"[^.;]{0,40}?\b(?:for|titled|labeled|named|called|showing|displaying)\b"
    r"\s+(?:\{([A-Za-z_][\w-]*)\}|[`'\"]([^`'\"]+)[`'\"])",
    re.IGNORECASE,
)
# Ids shared by many widgets: the visible text is what selects one of them.
_GENERIC_IDS = {"android:id/title", "android:id/text1"}
_GENERIC_ENTRIES = {"title", "text1", "menu_item_text"}
# A step can say outright that the id belongs to a row in a menu or list
# ("the `复制` menu item (TextView id `...:id/title`)").  That names the same
# repeated-id situation as the well-known ids above, for builds whose ids
# are not on the list.
_SHARED_ROW_ID_RE = re.compile(
    r"\b(?:menu\s+item|item|row|entry)\b[^.]{0,60}?\bid\b",
    re.IGNORECASE,
)
_INPUT_WIDGET_RE = re.compile(
    r"\b(?:edittext|edit_text|singleedittext|text\s*(?:field|box)"
    r"|input\s*field|search\s*field|search_src_text|editor)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}")
_INLINE_TARGET_RE = re.compile(
    r"(?P<key>resourceId|text|desc|description|content-desc)="
    r"(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)'|(?P<bare>[^\s`\"',;)]+))"
)
_BARE_ID_RE = re.compile(r"[A-Za-z_][\w.]*:id/\w+")
_TARGET_PREFIXES = (
    "text=",
    "resourceId=",
    "desc=",
    "description=",
    "content-desc=",
)
# A step that only asserts something is visible is not an action: compiled
# as a click it taps a control the screen may not have.
_VERIFY_RE = re.compile(
    r"^(?:confirm|verify|ensure|check|assert|validate|wait\s+(?:for|until))\b",
    re.IGNORECASE,
)


class StepCompiler:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _substitute(text: str, bindings: dict[str, str]) -> str:
        for key, value in bindings.items():
            text = text.replace("{" + key + "}", str(value))
            text = text.replace("$" + key, str(value))
        return text

    @staticmethod
    def _clean_target(value: str) -> str:
        return re.sub(r"^[`\"']+|[`\"']+$", "", value.strip()).strip()

    @classmethod
    def _inline_target(cls, text: str) -> str:
        """Return a canonical target from `key=value` (quotes allowed)."""
        match = _INLINE_TARGET_RE.search(text)
        if not match:
            return ""
        value = (
            match.group("dq")
            or match.group("sq")
            or match.group("bare")
            or ""
        ).strip()
        if match.group("bare") is not None:
            value = value.rstrip(".,;:)")
        if not value:
            return ""
        return f"{match.group('key')}={value}"

    @classmethod
    def _explicit_target(cls, step: str) -> str:
        """Return a concrete target encoded directly in a card step."""
        for token in _CODE_RE.findall(step):
            token = token.strip()
            inline = cls._inline_target(token)
            if inline:
                return inline
            if token.startswith(_TARGET_PREFIXES):
                return cls._clean_target(token)
            if ":id/" in token:
                bare = _BARE_ID_RE.search(token)
                if bare:
                    return f"resourceId={bare.group(0)}"
                return f"resourceId={cls._clean_target(token)}"
        inline = cls._inline_target(step)
        if inline:
            return inline
        match = _BARE_ID_RE.search(step)
        if match:
            return f"resourceId={match.group(0)}"
        return ""

    @staticmethod
    def _verb(step: str) -> str | None:
        """The gesture a step performs, from its own wording.

        A card step is either prose ("Long-press the row titled X") or an
        already-compiled action ("long_click text=X").  Both state the verb
        first, and the verb -- not the widget named afterwards -- decides
        what the device does.
        """
        lower = _CONTEXT_CLAUSE_RE.sub("", step.lower().lstrip())
        if _HOLD_RE.search(step):
            return "long_click"
        if _TYPING_START_RE.match(lower):
            return "input"
        if lower.startswith(("tap", "click", "select ", "choose ", "press ")):
            return "click"
        # A step that describes an input widget and says what is written into
        # it is a typing step even when the sentence starts with the screen
        # ("In the Rename dialog, replace the text in EditText X with Y").
        if _INPUT_WIDGET_RE.search(step) and _TYPING_RE.search(step):
            return "input"
        if _BARE_ID_RE.search(step) or _INLINE_TARGET_RE.search(step):
            return "click"
        return None

    @classmethod
    def _field_target(cls, step: str) -> str:
        """The input widget a typing step writes into.

        A typing sentence names its surroundings too -- the dialog title, the
        screen -- and those are usually the first ids it mentions.  The field
        is the id introduced as an input widget.
        """
        for match in _BARE_ID_RE.finditer(step):
            window = step[max(0, match.start() - 80) : match.start()]
            if _INPUT_WIDGET_RE.search(window):
                return f"resourceId={match.group(0)}"
        for match in _CODE_RE.finditer(step):
            window = step[max(0, match.start() - 80) : match.start()]
            if not _INPUT_WIDGET_RE.search(window):
                continue
            target = cls._explicit_target(match.group(0))
            if target:
                return target
        return ""

    @staticmethod
    def _named_value(step: str, bindings: dict[str, str]) -> str | None:
        """The bound visible label a step acts on, when it names no widget."""
        names: list[str] = []
        label = re.search(
            r"\b(?:label|text|titled|named|called|displaying|displays)\b"
            r"\s+(?:is\s+)?[`'\"]?\{([A-Za-z_][\w-]*)\}",
            step,
            re.IGNORECASE,
        )
        if label:
            names.append(label.group(1))
        names.extend(_PLACEHOLDER_RE.findall(step))
        for name in names:
            value = bindings.get(name)
            if value is not None and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def _quoted_label(step: str) -> str | None:
        """The visible label a step names in quotes or code spans.

        Cards write a label three ways -- "Move", `Move`, or an inline
        target -- and the first two are the same selector to the device.
        """
        candidates = _QUOTED_RE.findall(step) + _CODE_RE.findall(step)
        for candidate in candidates:
            label = candidate.strip()
            # A quoted resource id is an id, not a visible label.
            if (
                not label
                or ":id/" in label
                or "=" in label
                or "{" in label
                or label.startswith(_TARGET_PREFIXES)
            ):
                continue
            return label
        return None

    @staticmethod
    def _bound_label(
        step: str, target: str, bindings: dict[str, str]
    ) -> str | None:
        """Return the visible label a click step uses as a selector."""
        if not target.startswith("resourceId="):
            return None
        names: list[str] = []
        label = re.search(
            r"\b(?:label|text|titled|named)\b\s+(?:is\s+)?"
            r"\{([A-Za-z_][\w-]*)\}",
            step,
            re.IGNORECASE,
        )
        if label:
            names.append(label.group(1))
        for pattern in (_ROW_TITLE_RE, _TITLED_RE):
            match = pattern.search(step)
            if match:
                names.append(match.group(1))

        entry = target.rsplit("/", 1)[-1].lower()
        if re.search(r"title|text|label|name", entry):
            names.extend(_PLACEHOLDER_RE.findall(step))

        for name in names:
            value = bindings.get(name)
            if value is not None and str(value).strip():
                return str(value)
        # A repeated id distinguishes nothing: ``android:id/title`` and
        # ``...:id/title`` are the text view of every row in a menu or list,
        # so the id alone clicks whichever row comes first.  There the label
        # the step names is the selector, whether it is written as "visible
        # text 'Copy'" or as a code span the step introduces as the item.
        entry = target.rsplit("/", 1)[-1].lower()
        if entry in _GENERIC_IDS or entry in _GENERIC_ENTRIES or (
            _SHARED_ROW_ID_RE.search(step)
        ):
            quoted = _VISIBLE_TEXT_RE.search(step)
            if quoted:
                return quoted.group(1).strip()
            label = StepCompiler._quoted_label(step)
            if label is not None:
                return label
        return None

    @staticmethod
    def _row_value(step: str, bindings: dict[str, str]) -> str | None:
        """The visible title that selects one row among many."""
        for pattern in (_ROW_TITLE_RE, _TITLED_RE):
            match = pattern.search(step)
            if not match:
                continue
            value = bindings.get(match.group(1))
            if value is not None and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def _row_anchor(step: str, bindings: dict[str, str]) -> str | None:
        """The visible label of the row a control inside it belongs to."""
        for match in _ROW_ANCHOR_RE.finditer(step):
            name, literal = match.group(1), match.group(2)
            if name:
                value = bindings.get(name)
                if value is not None and str(value).strip():
                    return str(value)
                continue
            label = (literal or "").strip()
            # "the item labeled `text='Archive'`" names the control, not a
            # row containing it.
            if label and "=" not in label and ":id/" not in label:
                return label
        return None

    @staticmethod
    def _input_args(step: str, bindings: dict[str, str]) -> str | None:
        for name in _PLACEHOLDER_RE.findall(step):
            if name in bindings:
                return str(bindings[name])
        lower = step.lower()
        for name, value in bindings.items():
            if re.search(rf"\b{re.escape(name.lower())}\b", lower):
                return str(value)
        if len(bindings) == 1:
            return str(next(iter(bindings.values())))
        return None

    @classmethod
    def _explicit(
        cls, card: FunctionCard, bindings: dict[str, str]
    ) -> list[PlanStep] | None:
        """Compile cards whose steps already name concrete UI targets.

        Mined cards usually embed resource ids observed in the trace. Parsing
        those directly avoids an LLM round trip and avoids model drift. Cards
        without explicit targets still go through the LLM compiler.
        """
        steps: list[PlanStep] = []
        for line in card.steps:
            cleaned = line.strip()
            if not cleaned:
                continue
            lower = cleaned.lower()

            if _VERIFY_RE.match(cleaned):
                continue

            # The verb is the action.  A Back or Enter step names the screen
            # or field it acts on as context; compiling that name into a tap
            # would touch the screen instead of leaving it.
            if _BACK_KEY_RE.match(cleaned):
                if _DISMISS_IME_RE.search(cleaned):
                    steps.append(
                        PlanStep(
                            card=card.name,
                            action="press",
                            target="",
                            args="111",
                        )
                    )
                else:
                    steps.append(
                        PlanStep(card=card.name, action="back", target="")
                    )
                continue
            if _KEY_RE.match(cleaned):
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="press",
                        target="",
                        args="enter",
                    )
                )
                continue
            named = _NAMED_KEY_RE.match(cleaned)
            if named:
                key = named.group(1).lower()
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="press",
                        target="",
                        args=_NAMED_KEYS.get(key, key),
                    )
                )
                continue

            if "swipe" in lower:
                numbers = re.findall(r"-?\d+", cleaned)
                if len(numbers) < 4:
                    return None
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="swipe",
                        target="",
                        args=",".join(numbers[:4]),
                    )
                )
                continue

            if lower.startswith("wait"):
                numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="wait",
                        target="",
                        args=numbers[0] if numbers else "1",
                    )
                )
                continue

            target = cls._substitute(
                cls._explicit_target(cleaned), bindings
            )
            if not target and _BACK_RE.search(lower):
                steps.append(
                    PlanStep(card=card.name, action="back", target="")
                )
                continue
            if not target and _ENTER_RE.search(lower):
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="press",
                        target="",
                        args="enter",
                    )
                )
                continue

            action = cls._verb(cleaned)
            if action is None:
                return None
            if action == "input":
                # The field, not the dialog heading the sentence starts with.
                target = cls._substitute(
                    cls._field_target(cleaned), bindings
                ) or target
                if not target:
                    return None
                args = cls._input_args(cleaned, bindings)
                if args is None:
                    return None
                steps.append(
                    PlanStep(
                        card=card.name,
                        action=action,
                        target=target,
                        args=args,
                    )
                )
                continue
            if not target:
                # A tap or hold whose object is named only by its visible
                # label still has a concrete target: the label itcls.
                if action not in {"click", "long_click"}:
                    return None
                accessible = _ACCESSIBLE_RE.search(cleaned)
                bound_desc = _ACCESSIBLE_BOUND_RE.search(cleaned)
                if accessible:
                    target = "desc=" + cls._substitute(
                        accessible.group(1).strip(), bindings
                    )
                elif bound_desc and bindings.get(bound_desc.group(1)):
                    target = f"desc={bindings[bound_desc.group(1)]}"
                else:
                    label = cls._named_value(cleaned, bindings) or (
                        cls._quoted_label(cleaned)
                    )
                    if label is None:
                        return None
                    target = f"text={label}"
            elif action in {"click", "long_click"}:
                # The row a step selects is the one displaying its title;
                # the container id it names matches every row.
                row = cls._row_value(cleaned, bindings)
                if row is not None:
                    target = f"text={row}"
                else:
                    # A control that repeats on every row ("the properties
                    # button") only means one of them through the row named
                    # in the same step.
                    anchor = cls._row_anchor(cleaned, bindings)
                    if anchor is not None:
                        target = f"within=text={anchor}|{target}"
            label = cls._bound_label(cleaned, target, bindings)
            if label is not None:
                target = f"{target}|text={label}"
            steps.append(
                PlanStep(card=card.name, action=action, target=target)
            )
        return steps or None

    @classmethod
    def explicit_steps(
        cls, card: FunctionCard, bindings: dict[str, str] | None = None
    ) -> list[PlanStep] | None:
        """The card's steps as UI actions, without asking the model.

        This is the same parse ``compile`` runs before it would reach for
        the model: a card whose steps name concrete controls resolves to
        exactly the actions the device would be sent.  Exposed because that
        is what a card *does*, and two cards that do the same thing are one
        function however differently they are worded.
        """
        return cls._explicit(card, bindings or {})

    def _fallback(
        self, card: FunctionCard, bindings: dict[str, str]
    ) -> list[PlanStep]:
        steps: list[PlanStep] = []
        for line in card.steps:
            cleaned = line.strip()
            if not cleaned:
                continue
            lower = cleaned.lower()
            if _HOLD_RE.search(cleaned):
                action = "long_click"
            elif lower.startswith(("tap", "click")):
                action = "click"
            elif lower.startswith(("enter", "input", "type")):
                action = "input"
            elif lower.startswith("swipe"):
                action = "swipe"
            elif lower.startswith("back"):
                action = "back"
            elif lower.startswith(("press ", "hit ")):
                action = "press"
            else:
                action = "click"

            quoted = _QUOTED_RE.search(cleaned)
            target = quoted.group(1) if quoted else cleaned
            args = "enter" if action == "press" else ""
            if action == "input":
                for name, value in bindings.items():
                    if name.lower() in lower:
                        args = str(value)
                        break
            steps.append(
                PlanStep(
                    card=card.name,
                    action=action,
                    target=self._substitute(target, bindings),
                    args=args,
                )
            )
        if not steps:
            steps.append(
                PlanStep(card=card.name, action="wait", target="", args="1")
            )
        return steps

    def compile(
        self,
        card: FunctionCard,
        bindings: dict[str, str],
        *,
        state: str = "",
    ) -> list[PlanStep]:
        explicit = self._explicit(card, bindings)
        if explicit is not None:
            return explicit

        step_lines = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(card.steps, 1)
        )
        screen = (
            f"Screen this step runs on:\n{state[:3000]}\n\n" if state else ""
        )
        prompt = (
            f"Convert these function-card steps and bindings into concrete "
            f"UI actions.\nCard: {card.name}\nIntent: {card.intent}\n"
            f"Bindings: {bindings}\nSteps:\n{step_lines}\n\n"
            f"{screen}"
            "Return JSON {steps:[{action,target,args}]}; action is "
            "click/long_click/input/swipe/back/wait/press; target uses "
            "text=..., desc=..., or resourceId=...; press uses args=enter for "
            "the keyboard search/enter key. long_click is a held touch on a "
            "control; press is a hardware key. A control's label must be "
            "written exactly as the screen writes it. "
            "A control the step names may sit below the fold of a scrollable "
            "list; name it anyway. The device scrolls to a target it cannot "
            "see, so a missing row is not a reason to invent a different "
            "route."
        )
        schema = '{"steps": [{"action": "click", "target": "text=Save", "args": ""}]}'
        try:
            data = self.llm.complete_json(prompt, schema)
        except LLMParseError as exc:
            logger.warning("step compilation failed: %s", exc)
            return self._fallback(card, bindings)

        raw_steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(raw_steps, list):
            return self._fallback(card, bindings)

        steps: list[PlanStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip().lower()
            if action not in _ACTIONS:
                continue
            target = self._substitute(
                str(item.get("target", "")), bindings
            )
            steps.append(
                PlanStep(
                    card=card.name,
                    action=action,
                    target=self._clean_target(target),
                    args=self._substitute(
                        str(item.get("args", "")), bindings
                    ),
                )
            )
        return steps or self._fallback(card, bindings)
