import csv
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import DATA, connect_db, hash_phone, init_db, seed_sms_data
from app.handler import MessageHandler
from app.llm import ChatClient, LanguageModel, create_model, restricted
from app.main import create_app
from app.parser import Command
from app.templates import Reply, validate_sms
from kb.retrieve import Hit, Retriever, SentenceEmbedder, strong
from validation.retrieval_test import evaluate


class FakeEmbedder:
    model_name = "deterministic-fixture"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self.calls.append(list(texts))
        vectors = {"water": [2, 0], "rotation": [1, 1], "heat": [0, 1], "zero": [0, 0]}
        return np.array([vectors[text] for text in texts], dtype=float)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    path = tmp_path / "chunks.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["chunk_id", "source_tag", "crop", "topic", "text", "restricted"]
        )
        writer.writeheader()
        for chunk, crop, topic, text, restricted in [
            ("rice", "rice", "water", "water", "0"),
            ("general", "general", "rotation", "rotation", "0"),
            ("soy", "soybean", "water", "water", "0"),
            ("heat", "rice", "water", "heat", "0"),
            ("restricted", "rice", "water", "water", "1"),
        ]:
            writer.writerow(
                dict(
                    chunk_id=chunk,
                    source_tag="DA-HVCDP",
                    crop=crop,
                    topic=topic,
                    text=text,
                    restricted=restricted,
                )
            )
    return path


def test_cosine_filters_top3_and_load_once(corpus: Path) -> None:
    embedder = FakeEmbedder()
    retrieval = Retriever(corpus, embedder)
    corpus.unlink()
    hits = retrieval.search("water", "rice")
    assert [hit.chunk_id for hit in hits] == ["rice", "general", "heat"]
    assert hits[0].score == pytest.approx(1)
    assert hits[1].score == pytest.approx(2**-0.5)
    assert strong(hits)
    assert [hit.chunk_id for hit in retrieval.search("water", "rice", "water")] == ["rice", "heat"]
    assert retrieval.search("zero", "rice") == []
    assert retrieval.search("water", "rice", "missing") == []
    assert retrieval.search("water", "rice", k=0) == []
    assert len(retrieval.search("heat", "rice", k=1)) == 1
    assert embedder.calls[0] == ["water", "rotation", "heat"]
    assert all(len(call) == 1 for call in embedder.calls[1:])
    assert not strong([])
    assert not strong([Hit("weak", "tag", "rice", "water", "text", 0.1)])


def test_vector_cache_reuse_and_model_invalidation(corpus: Path, tmp_path: Path) -> None:
    cache = tmp_path / "vectors.npz"
    Retriever(corpus, FakeEmbedder(), cache)
    embedder = FakeEmbedder()
    retrieval = Retriever(corpus, embedder, cache)
    assert embedder.calls == []
    assert retrieval.search("water", "rice")[0].chunk_id == "rice"
    embedder.model_name = "changed-fixture"
    Retriever(corpus, embedder, cache)
    assert len(embedder.calls[-1]) == 3
    with corpus.open("a") as handle:
        handle.write("new,tag,rice,water,water,0\n")
    embedder.calls.clear()
    Retriever(corpus, embedder, cache)
    assert embedder.calls == []
    with corpus.open("a") as handle:
        handle.write("new-text,tag,rice,water,zero,0\n")
    Retriever(corpus, embedder, cache)
    assert embedder.calls == [["zero"]]


def test_real_embedder_uses_configured_name_without_loading_weights(monkeypatch) -> None:
    names = []

    def constructor(name: str) -> SimpleNamespace:
        names.append(name)
        return SimpleNamespace(encode=lambda texts: [[1, 2] for text in texts])

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=constructor)
    )
    embedder = SentenceEmbedder("configured-fixture")
    assert names == ["configured-fixture"]
    assert embedder.encode(["question"]).tolist() == [[1, 2]]


class FakeClient:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[tuple[str, str, dict]] = []

    def complete(self, system: str, user: str, schema: dict) -> str:
        self.calls.append((system, user, schema))
        return self.output


def intent_output(**changes: object) -> str:
    return json.dumps(
        dict(intent="PLANT", barangay=None, water=None, crop=None, priority=None, confidence=0.9)
        | changes
    )


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "[]",
        "{}",
        intent_output(intent="INVENT"),
        intent_output(confidence=0.69),
        intent_output(confidence=1.1),
        intent_output(confidence="0.9"),
        intent_output(extra="bad"),
        intent_output(intent="OTHER"),
        intent_output(intent="REG"),
        intent_output(intent="REG", barangay="Batac", water="RAIN"),
        intent_output(intent="LAST", crop="unknown"),
        intent_output(intent="PRIO"),
    ],
)
def test_invalid_or_weak_intent_falls_back(output: str) -> None:
    assert LanguageModel(FakeClient(output)).extract("free text") is None


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"confidence": 0.7}, Command("PLANT")),
        ({"intent": "REG", "barangay": "Batac", "water": "ULAN"}, Command("REG", "BATAC ULAN")),
        ({"intent": "LAST", "crop": "palay"}, Command("LAST", "PALAY")),
        ({"intent": "PRIO", "priority": "KITA"}, Command("PRIO", "KITA")),
        ({"intent": "WHY"}, Command("WHY")),
        ({"intent": "STOP"}, Command("STOP")),
    ],
)
def test_valid_intents(changes: dict, expected: Command) -> None:
    client = FakeClient(intent_output(**changes))
    assert LanguageModel(client).extract("free text") == expected
    assert client.calls[0][2]["additionalProperties"] is False


def test_model_disabled_never_constructs_client(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_ENABLED", "0")

    def forbidden(settings: Settings) -> FakeClient:
        pytest.fail("Disabled model client constructed")

    assert create_model(Settings.from_env(), forbidden) is None
    monkeypatch.setattr("app.main.create_model", lambda config: create_model(config, forbidden))
    settings = Settings(db_path=str(tmp_path / "app.db"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "output",
    [
        '{"order":[0,0]}',
        '{"order":[2,0]}',
        '{"order":[true,0]}',
        '{"order":["1",0]}',
        '{"order":[1]}',
        '{"order":[1,0],"text":"dose 10"}',
        "bad",
        "null",
        "[]",
        '{"order":null}',
    ],
)
def test_wording_rejects_anything_but_permutation(output: str) -> None:
    reply = Reply("T_PLANT", "Payo: palay 12. I-text ang WHY.")
    assert (
        LanguageModel(FakeClient(output)).word(reply, ["Payo: palay 12.", "I-text ang WHY."])
        == reply
    )


def test_wording_reorders_whole_slots_and_validates_sms() -> None:
    client = FakeClient('{"order":[1,0]}')
    model = LanguageModel(client)
    reply = Reply("T_PLANT", "Payo: palay 12. I-text ang WHY.")
    worded = model.word(reply, ["Payo: palay 12.", "I-text ang WHY."])
    assert worded.text == "I-text ang WHY. Payo: palay 12."
    assert validate_sms(worded.text)
    assert model.word(reply, ["invented", "advice"]) == reply
    for text in ["x" * 151, "emoji \U0001f600"]:
        unsafe = Reply("T_PLANT", text + " end")
        assert model.word(unsafe, [text, "end"]) == unsafe


def test_client_timeout_retry_and_strict_request(monkeypatch) -> None:
    calls = []

    def post(url: str, **kwargs) -> httpx.Response:
        calls.append((url, kwargs))
        if len(calls) == 1:
            raise httpx.ReadTimeout("fixture")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": intent_output()}}]},
        )

    monkeypatch.setattr(httpx, "post", post)
    settings = Settings(
        llm_endpoint="https://endpoint.invalid/chat/completions",
        llm_model="deployment-fixture",
        llm_key="fixture",
    )
    assert LanguageModel(ChatClient(settings)).extract("free text") == Command("PLANT")
    assert len(calls) == 2
    request = calls[0][1]
    assert request["timeout"] == 8
    assert request["json"]["temperature"] == 0
    assert request["json"]["response_format"]["json_schema"]["strict"] is True
    calls.clear()

    def fail(url: str, **kwargs) -> httpx.Response:
        calls.append(url)
        raise httpx.ConnectError("fixture")

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(httpx.ConnectError):
        LanguageModel(ChatClient(settings)).extract("free text")
    assert len(calls) == 2


def test_prompts_and_logs_remove_phone_like_text(caplog) -> None:
    phone = "+" + "123456789012"
    client = FakeClient(intent_output())
    with caplog.at_level(logging.INFO):
        LanguageModel(client).extract("text " + phone)
    assert phone not in client.calls[0][1]
    assert phone not in caplog.text
    assert "template_id=T_FALLBACK" in caplog.text


class Gateway:
    def send(self, recipient: str, text: str) -> None:
        assert validate_sms(text)


@pytest.mark.parametrize(
    "text",
    [
        "WHY doses",
        "PLANT pataba",
        "chemical",
        "fertilizer",
        "peste",
        "pesticides",
        "dilution ratio",
        "concentration",
        "abono",
        "dosis",
        "Ilang 10 ml kada litro?",
        "10ml",
        "dilute 1:10",
    ],
)
def test_restricted_topics_bypass_every_command_and_model(tmp_path: Path, text: str) -> None:
    settings = Settings(
        db_path=str(tmp_path / "app.db"), phone_hash_secret="fixture", llm_enabled=True
    )
    init_db(settings.db_path)
    client = FakeClient(intent_output())
    reply = MessageHandler(settings, Gateway(), LanguageModel(client)).handle("synthetic", text)
    assert reply.template_id == "T_REFER"
    assert client.calls == []


@pytest.mark.parametrize("crop", ["rice", "mungbean", "soybean"])
@pytest.mark.parametrize("score", [0.1, 0.9])
@pytest.mark.parametrize("availability", ["hits", "empty", "absent", "raising"])
def test_why_retrieves_sources_and_retains_fixed_reasons(
    tmp_path: Path, crop: str, score: float, availability: str, caplog
) -> None:
    settings = Settings(db_path=str(tmp_path / "app.db"), phone_hash_secret="fixture")
    init_db(settings.db_path)
    seed_sms_data(settings.db_path)
    phone = hash_phone("synthetic", settings)
    with connect_db(settings.db_path) as connection:
        connection.execute(
            "INSERT INTO farmers (phone_hash,barangay_code,water_source) VALUES (?,'BATAC','ULAN')",
            (phone,),
        )
        connection.execute(
            "INSERT INTO messages (phone_hash,direction,text,template_id,context) "
            "VALUES (?,'out','stored recommendation',?,?)",
            (
                phone,
                "T_PLANT",
                json.dumps({"crop": crop, "reasons": ["R_LEGUME"], "source": "stored-source"}),
            ),
        )

    class Retrieval:
        def search(self, question: str, requested_crop: str) -> list[Hit]:
            assert requested_crop == crop
            if availability == "raising":
                raise RuntimeError("retrieval fixture failure")
            if availability == "empty":
                return []
            return [Hit("approved", "DA-HVCDP", crop, "rotation", "Must never be sent", score)]

    handler = MessageHandler(
        settings, Gateway(), retriever=None if availability == "absent" else Retrieval()
    )
    reply = handler.handle("synthetic", "WHY")
    assert validate_sms(reply.text)
    if availability == "raising" or (
        crop == "rice" and availability != "absent" and (score < 0.4 or availability != "hits")
    ):
        assert reply.template_id == "T_REFER"
        assert "Kulang" in reply.text and "technician" in reply.text
    else:
        assert reply.template_id == "T_WHY"
        assert ("DA-HVCDP" if availability == "hits" else "stored-source") in reply.text
        assert "Must never be sent" not in reply.text
        assert "tumutulong ito sa lupa" in reply.text
    if availability == "raising":
        assert "WHY retrieval failed" in caplog.text


def test_evaluation_writes_top3_hit_rate(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions = tmp_path / "questions.csv"
    questions.write_text("question,crop,expected_chunk_ids\nwater,rice,rice\nwater,rice,soy\n")
    monkeypatch.chdir(tmp_path)
    output = Path("validation/results/retrieval.csv")
    assert evaluate(Retriever(corpus, FakeEmbedder()), questions) == 0.5
    with output.open() as handle:
        rows = list(csv.DictReader(handle))
    assert [row["hit"] for row in rows] == ["1", "0"]
    assert all(row["top3_hit_rate"] == "0.5" for row in rows)
    assert rows[0]["top3_chunk_ids"] == "rice|general|heat"


def test_retriever_is_initialized_once_at_startup(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialized = []
    embedder = FakeEmbedder()

    def make_embedder(name: str) -> FakeEmbedder:
        initialized.append(name)
        return embedder

    def make_retriever(chunks: Path, model: FakeEmbedder, vectors: Path) -> Retriever:
        assert chunks == DATA / "kb/kb_chunks.csv"
        assert vectors == DATA / "kb/vectors.npz"
        return Retriever(corpus, model, tmp_path / "startup.npz")

    monkeypatch.setattr("app.main.SentenceEmbedder", make_embedder)
    monkeypatch.setattr("app.main.Retriever", make_retriever)
    settings = Settings(db_path=str(tmp_path / "app.db"), embedding_model="configured-fixture")
    application = create_app(settings)
    with TestClient(application) as client:
        for _ in range(2):
            assert client.get("/health").status_code == 200
        retrieval = application.state.message_handler.retriever
        assert retrieval.search("water", "rice")[0].chunk_id == "rice"
        assert retrieval.search("water", "rice")[0].chunk_id == "rice"
    assert initialized == ["configured-fixture"]
    assert [len(call) for call in embedder.calls] == [3, 1, 1]


@pytest.mark.parametrize("text", ["6:30 ng umaga", "Kailan ako magtatanim?", "ml", "1:10"])
def test_restricted_allows_clock_times_and_plain_questions(text: str) -> None:
    assert not restricted(text)


@pytest.mark.parametrize("text", ["10ml", "2.5 mg", "100 ppm", "3 cc", "mix 1:10", "1:10 halo"])
def test_restricted_units_and_mixing_ratios(text: str) -> None:
    assert restricted(text)


@pytest.mark.parametrize(
    "text,template", [("STOP na po, ayoko na ng spray", "T_STOP_OK"), ("HELP pesticide", "T_HELP")]
)
def test_stop_and_help_take_priority_over_restrictions(
    tmp_path: Path, text: str, template: str
) -> None:
    settings = Settings(
        db_path=str(tmp_path / "app.db"), phone_hash_secret="fixture", llm_enabled=True
    )
    init_db(settings.db_path)
    seed_sms_data(settings.db_path)
    phone = hash_phone("synthetic", settings)
    with connect_db(settings.db_path) as connection:
        connection.execute(
            "INSERT INTO farmers (phone_hash,barangay_code,water_source) VALUES (?,'BATAC','ULAN')",
            (phone,),
        )
        connection.execute(
            "INSERT INTO messages (phone_hash,direction,text) VALUES (?,'in','old')", (phone,)
        )
    client = FakeClient(intent_output())
    reply = MessageHandler(settings, Gateway(), LanguageModel(client)).handle("synthetic", text)
    assert reply.template_id == template
    assert client.calls == []
    if template == "T_STOP_OK":
        with connect_db(settings.db_path) as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM farmers WHERE phone_hash = ?", (phone,)
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM messages WHERE phone_hash = ?", (phone,)
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize("failure", [httpx.ConnectError("fixture"), ValueError("fixture")])
def test_real_language_model_failure_records_event(tmp_path: Path, failure: Exception) -> None:
    class FailingClient:
        def complete(self, system: str, user: str, schema: dict) -> str:
            raise failure

    settings = Settings(
        db_path=str(tmp_path / "app.db"), phone_hash_secret="fixture", llm_enabled=True
    )
    init_db(settings.db_path)
    handler = MessageHandler(settings, Gateway(), LanguageModel(FailingClient()))
    assert handler.handle("synthetic", "free text").template_id == "T_FALLBACK"
    with connect_db(settings.db_path) as connection:
        events = [row[0] for row in connection.execute("SELECT type FROM events ORDER BY id")]
    assert events == ["model_call_failed", "fallback_used"]


def test_validation_uses_repository_kb_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    from validation import retrieval_test

    def make_retriever(chunks: Path, embedder: object, vectors: Path) -> object:
        assert chunks == DATA / "kb/kb_chunks.csv"
        assert vectors == DATA / "kb/vectors.npz"
        return object()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMBEDDING_MODEL", "configured-fixture")
    monkeypatch.setattr(sys, "argv", ["retrieval_test", "questions.csv"])
    monkeypatch.setattr(retrieval_test, "SentenceEmbedder", lambda name: object())
    monkeypatch.setattr(retrieval_test, "Retriever", make_retriever)
    monkeypatch.setattr(retrieval_test, "evaluate", lambda retriever, questions: 1.0)
    retrieval_test.main()
    assert "100.0%" in capsys.readouterr().out


def test_cache_reuses_hashes_across_order_and_metadata_changes(
    corpus: Path, tmp_path: Path
) -> None:
    cache = tmp_path / "vectors.npz"
    Retriever(corpus, FakeEmbedder(), cache)
    with corpus.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    rows.reverse()
    rows[1]["source_tag"] = "updated-tag"
    rows[1]["chunk_id"] = "updated-id"
    rows[1]["text"] = "zero"
    with corpus.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    embedder = FakeEmbedder()
    retrieval = Retriever(corpus, embedder, cache)
    assert embedder.calls == [["zero"]]
    hits = retrieval.search("water", "rice")
    assert hits[0].chunk_id == "rice"
    assert next(hit for hit in hits if hit.chunk_id == "updated-id").source_tag == "updated-tag"
    second = FakeEmbedder()
    Retriever(corpus, second, cache)
    assert second.calls == []


def test_cache_key_ignores_text_hash_column(corpus: Path, tmp_path: Path) -> None:
    cache = tmp_path / "vectors.npz"
    with corpus.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    fields = [*(reader.fieldnames or []), "text_hash"]
    for row in rows:
        row["text_hash"] = "fixed"

    def write() -> None:
        with corpus.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    write()
    Retriever(corpus, FakeEmbedder(), cache)
    rows[0]["text"] = "zero"
    write()
    embedder = FakeEmbedder()
    Retriever(corpus, embedder, cache)
    assert embedder.calls == [["zero"]]
