"""Build the module index from descriptors."""
from __future__ import annotations

from pathlib import Path

from .descriptor import Descriptor

STANDARD = Path(__file__).resolve().parents[2] / "standard"


def index_preamble(ecosystem: str, standard: Path = STANDARD) -> str:
    """The shared preamble followed by the ecosystem's consumer notes, when it has any."""
    text = (standard / "preamble.md").read_text().strip()
    notes = standard / "consumer" / f"{ecosystem}.md"
    if notes.is_file():
        text += f"\n\n## Project notes ({ecosystem})\n\n" + notes.read_text().strip()
    return text


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
        if d.setup:
            parts.append("Setup:")
            parts.extend(f"- {s}" for s in d.setup)
            parts.append("")
    return "\n".join(parts)
