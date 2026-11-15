"""Render PROVENANCE.md from data/provenance.csv.

Run from the repository root: python -m scripts.build_provenance
"""

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "provenance.csv"
TARGET = ROOT / "PROVENANCE.md"

FIELDS = (
    ("Source", "source_url"),
    ("Accessed (UTC)", "accessed_utc"),
    ("Terms", "license_or_terms"),
    ("Script", "script"),
    ("Notes", "notes"),
)

HEADER = """# Provenance

Where each data file in `data/` came from, when it was accessed and under which terms.
This file is generated from `data/provenance.csv`.
Edit the CSV, then run `python -m scripts.build_provenance`.
Where a source states no terms, the entry says so and the terms are marked as not verified.
"""


def render(source: Path = SOURCE) -> str:
    """Return the Markdown text for every row of the provenance CSV, grouped by dataset."""
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            groups[row["dataset"]].append(row)
    lines = [HEADER]
    for dataset, rows in groups.items():
        lines.append(f"## {dataset}\n")
        for row in rows:
            lines.append(f"### `{row['file']}`\n")
            for label, key in FIELDS:
                value = row[key].strip()
                if value:
                    lines.append(f"- {label}: {value}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> None:
    TARGET.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
