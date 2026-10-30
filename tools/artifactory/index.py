"""Build the module index from descriptors."""
from __future__ import annotations

from .descriptor import Descriptor


def build_index(descriptors: list[Descriptor], preamble: str) -> str:
    parts = [preamble.strip(), ""]
    for d in sorted(descriptors, key=lambda d: d.name):
        parts.append(f"## {d.name}")
        parts.append("")
        parts.append(d.summary)
        parts.append("")
        parts.append("Use instead of writing:")
        parts.extend(f"- {r}" for r in d.replaces)
        parts.append("")
        parts.append("```")
        parts.append(d.install)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)
