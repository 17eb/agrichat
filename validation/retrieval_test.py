"""Evaluate passage hits for a CSV of farmer questions without generating advice."""

import argparse
import csv
from pathlib import Path

from app.config import Settings
from app.db import DATA
from kb.retrieve import Retriever, SentenceEmbedder


def evaluate(
    retriever: Retriever,
    questions_path: Path,
    output_path: Path = Path("validation/results/retrieval.csv"),
) -> float:
    with questions_path.open(encoding="utf-8", newline="") as handle:
        questions = list(csv.DictReader(handle))
    if not questions:
        raise ValueError("Question file is empty")
    rows = []
    for question in questions:
        hits = retriever.search(
            question["question"], question["crop"], question.get("topic") or None
        )
        expected = set(question["expected_chunk_ids"].split("|"))
        if not expected - {""}:
            raise ValueError("Each question needs an expected chunk ID")
        ids = [hit.chunk_id for hit in hits]
        rows.append(
            {
                "question": question["question"],
                "crop": question["crop"],
                "expected_chunk_ids": question["expected_chunk_ids"],
                "top3_chunk_ids": "|".join(ids),
                "hit": int(bool(expected.intersection(ids))),
            }
        )
    rate = sum(row["hit"] for row in rows) / len(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*rows[0], "top3_hit_rate"])
        writer.writeheader()
        writer.writerows({**row, "top3_hit_rate": rate} for row in rows)
    return rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questions", type=Path, help="CSV: question,crop,expected_chunk_ids,topic")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.embedding_model:
        parser.error("Set EMBEDDING_MODEL to the configured multilingual embedding model")
    retrieval = Retriever(
        DATA / "kb/kb_chunks.csv",
        SentenceEmbedder(settings.embedding_model),
        DATA / "kb/vectors.npz",
    )
    print(f"Top-3 hit rate: {evaluate(retrieval, args.questions):.1%}")


if __name__ == "__main__":
    main()
