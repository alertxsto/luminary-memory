"""Shipped library defaults are conservative; permissive recall is explicit."""

from luminary_memory.api import MemoryClient
from luminary_memory.config import Settings


class _Engine:
    """Unrelated texts point in different directions."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * 384
        vector[0 if "coffee" in str(text).casefold() else 1] = 1.0
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def test_settings_default_to_strict_and_evidence_required():
    settings = Settings()

    assert settings.strict_recall is True
    assert settings.evidence_required is True


def test_plain_client_abstains_on_an_unsupported_question(tmp_path):
    client = MemoryClient(db_path=str(tmp_path / "default.db"), engine=_Engine())
    try:
        client.ingest("The office has a coffee machine")

        result = client.recall("Which planet is the mission destination?")

        assert result.status == "abstain"
        assert result.memories == []
    finally:
        client.close()


def test_permissive_recall_remains_available_explicitly(tmp_path):
    client = MemoryClient(
        settings=Settings(
            db_path=str(tmp_path / "permissive.db"),
            strict_recall=False,
            evidence_required=False,
        ),
        engine=_Engine(),
    )
    try:
        client.ingest("The office has a coffee machine")

        result = client.recall("Which planet is the mission destination?")

        assert result.status != "abstain"
        assert result.memories
    finally:
        client.close()
