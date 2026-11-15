"""Local cosine retrieval over approved knowledge-base chunks."""

import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from engine.params import RETRIEVAL_THRESHOLD


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> NDArray[np.float64]: ...


class SentenceEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> NDArray[np.float64]:
        return np.asarray(self.model.encode(list(texts)), dtype=float)


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source_tag: str
    crop: str
    topic: str
    text: str
    score: float


class Retriever:
    def __init__(
        self, chunks_path: Path, embedder: Embedder, vectors_path: Path | None = None
    ) -> None:
        self.embedder = embedder
        with chunks_path.open(encoding="utf-8", newline="") as handle:
            self.chunks = [row for row in csv.DictReader(handle) if row["restricted"] == "0"]
        model = getattr(embedder, "model_name", type(embedder).__qualname__)
        hashes = [hashlib.sha256(row["text"].encode()).hexdigest() for row in self.chunks]
        cached: dict[tuple[str, str], NDArray[np.float64]] = {}
        self.vectors = np.empty((0, 0))
        if not self.chunks:
            return
        if vectors_path is not None and vectors_path.exists():
            with np.load(vectors_path, allow_pickle=False) as cache:
                if {"model", "hashes", "vectors"} <= set(cache.files):
                    vectors = cache["vectors"]
                    if (
                        vectors.ndim != 2
                        or len(vectors) != len(cache["hashes"])
                        or not np.isfinite(vectors).all()
                    ):
                        raise ValueError("Invalid cached vectors")
                    cached = {
                        (str(cache["model"]), str(text_hash)): vector
                        for text_hash, vector in zip(cache["hashes"], vectors, strict=True)
                    }
        missing = {
            text_hash: row["text"]
            for text_hash, row in zip(hashes, self.chunks, strict=True)
            if (model, text_hash) not in cached
        }
        if missing:
            vectors = np.asarray(embedder.encode(list(missing.values())), dtype=float)
            if vectors.ndim != 2 or len(vectors) != len(missing) or not np.isfinite(vectors).all():
                raise ValueError("Invalid chunk vectors")
            cached.update(
                ((model, text_hash), vector)
                for text_hash, vector in zip(missing, vectors, strict=True)
            )
        self.vectors = np.asarray([cached[model, text_hash] for text_hash in hashes])
        if vectors_path is not None and missing:
            vectors_path.parent.mkdir(parents=True, exist_ok=True)
            model_hashes = list(dict.fromkeys(hashes))
            np.savez(
                vectors_path,
                model=model,
                hashes=model_hashes,
                vectors=np.asarray([cached[model, text_hash] for text_hash in model_hashes]),
            )
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        self.vectors = self.vectors / np.where(norms == 0, 1, norms)

    def search(self, question: str, crop: str, topic: str | None = None, k: int = 3) -> list[Hit]:
        candidates = [
            i
            for i, row in enumerate(self.chunks)
            if row["crop"] in {crop, "general"} and (topic is None or row["topic"] == topic)
        ]
        if not candidates or k <= 0:
            return []
        query = np.asarray(self.embedder.encode([question]), dtype=float)[0]
        if query.shape != (self.vectors.shape[1],) or not np.isfinite(query).all():
            raise ValueError("Invalid query vector")
        norm = np.linalg.norm(query)
        if norm == 0:
            return []
        scores = self.vectors[candidates] @ (query / norm)
        order = np.argsort(-scores, kind="stable")[:k]
        return [
            Hit(
                **{
                    key: self.chunks[candidates[i]][key]
                    for key in ("chunk_id", "source_tag", "crop", "topic", "text")
                },
                score=float(scores[i]),
            )
            for i in order
        ]


def strong(hits: Sequence[Hit]) -> bool:
    return bool(hits) and hits[0].score >= RETRIEVAL_THRESHOLD
