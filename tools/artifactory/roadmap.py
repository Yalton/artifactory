"""Score an exported roadmap (bd jsonl) for the roadmap experiment."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# The brief's checker contracts as the brief writes them (group and action names keep their
# backticks, so plain prose such as "the player" does not count as a copied contract).
CONTRACTS = ["`player`", "`keeper`", "`dialogue`", "res://rooms/courtyard.tscn", "res://rooms/hall.tscn",
             "res://rooms/tower.tscn", "`interact`"]

_MODULES_LINE = re.compile(r"^\s*Modules:[ \t]*(.*)$", re.MULTILINE)


def _word(term: str, text: str, flags: int = 0) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags) is not None


def score_roadmap(jsonl_path: Path, kits: list[str], contracts: list[str]) -> dict:
    rows = [json.loads(line) for line in Path(jsonl_path).read_text().splitlines() if line.strip()]
    beads = [b for b in rows if b.get("_type", "issue") == "issue"]
    named: set[str] = set()
    unknown: set[str] = set()
    missing: list[str] = []
    gap_dialogue = False
    for b in beads:
        text = b.get("description") or ""
        lines = _MODULES_LINE.findall(text)  # every Modules: line counts; the names are their union
        if not lines:
            missing.append(b["id"])
        for line in lines:
            for name in (n.strip() for n in line.split(",")):
                if name and name.lower() != "none":
                    (named if name in kits else unknown).add(name)
        if "gap" in (b.get("labels") or []) and _word("dialogue", f"{b.get('title', '')}\n{text}", re.I):
            gap_dialogue = True
    texts = [b.get("description") or "" for b in beads]
    return {
        "beads": len(beads),
        "by_status": dict(Counter(b.get("status", "") for b in beads)),
        "kits_named": sorted(named),
        "unknown_modules": sorted(unknown),
        "no_modules_line": missing,
        "gap_covers_dialogue": gap_dialogue,
        "contracts": [c for c in contracts if any(_word(c, t) for t in texts)],
    }


def format_score(s: dict, kits: list[str]) -> str:
    unnamed = [k for k in kits if k not in s["kits_named"]]
    status = ", ".join(f"{k} {v}" for k, v in sorted(s["by_status"].items())) or "none"
    return "\n".join([
        f"beads: {s['beads']} ({status})",
        f"kits named ({len(s['kits_named'])}/{len(kits)}): {', '.join(s['kits_named']) or 'none'}",
        f"kits not named: {', '.join(unnamed) or 'none'}",
        f"unknown modules: {', '.join(s['unknown_modules']) or 'none'}",
        f"beads without a Modules line: {', '.join(s['no_modules_line']) or 'none'}",
        f"gap bead covers dialogue: {'yes' if s['gap_covers_dialogue'] else 'no'}",
        f"contracts in bead text: {', '.join(s['contracts']) or 'none'}",
    ])
