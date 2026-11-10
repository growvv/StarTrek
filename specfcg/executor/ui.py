"""Compact Android UI hierarchies for LLM prompts.

Raw uiautomator2 dumps include the status bar, taskbar, launcher, and every
layout container. That noise pushes the app's own widgets out of the
truncation window and makes every LLM call slower. This module keeps only
the target package's meaningful, user-visible nodes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def _format_node(node: ET.Element) -> str | None:
    text = node.get("text", "")
    resource_id = node.get("resource-id", "")
    description = node.get("content-desc", "")
    hint = node.get("hint", "")
    clickable = node.get("clickable") == "true"
    if not (text or description or hint or clickable):
        return None

    parts: list[str] = []
    if text:
        parts.append(f"text={text!r}")
    if resource_id:
        parts.append(f"id={resource_id!r}")
    if description:
        parts.append(f"desc={description!r}")
    if hint and not text:
        parts.append(f"hint={hint!r}")
    if clickable:
        parts.append("clickable=true")

    class_name = node.get("class", "")
    short_class = class_name.rsplit(".", 1)[-1] or "node"
    bounds = node.get("bounds", "")
    if bounds:
        parts.append(f"bounds={bounds!r}")
    return f"{short_class} " + " ".join(parts)


def compact_ui(
    xml: str,
    package: str | None = None,
    max_nodes: int = 80,
    extra_packages: tuple[str, ...] = (),
) -> str:
    """Return a compact, package-filtered view of a uiautomator2 dump.

    `extra_packages` keeps overlay windows such as the Android share
    chooser, which opens on top of the target app and would otherwise be
    filtered out even though the user (and the postcondition checker)
    needs to see it.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml

    nodes = list(root.iter("node"))
    if package:
        target_nodes = [
            node for node in nodes if node.get("package") == package
        ]
        if target_nodes:
            allowed = {package, *extra_packages}
            nodes = [
                node for node in nodes if node.get("package") in allowed
            ]

    lines: list[str] = []
    for node in nodes:
        line = _format_node(node)
        if line is not None:
            lines.append(line)
    if len(lines) > max_nodes:
        lines = lines[:max_nodes] + ["... <truncated>"]
    return "\n".join(lines)
