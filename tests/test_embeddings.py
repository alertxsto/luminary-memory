import pytest

from luminary_memory.embeddings.fastembed import FastembedEngine


class _FakeModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def embed(self, texts):
        return [[0.1] * 384 for _ in texts]


@pytest.fixture
def fake_model(monkeypatch):
    monkeypatch.setattr(
        "luminary_memory.embeddings.fastembed.TextEmbedding",
        lambda **kw: _FakeModel(**kw),
    )


def test_embed_returns_384d(fake_model):
    e = FastembedEngine()
    vec = e.embed("hello")
    assert len(vec) == 384


def test_embed_batch_returns_one_vector_per_text(fake_model):
    e = FastembedEngine()
    vecs = e.embed_batch(["first", "second", "third"])
    assert len(vecs) == 3
    assert all(len(v) == 384 for v in vecs)


def test_model_is_loaded_lazily(fake_model):
    e = FastembedEngine()
    assert e._model is None
    e.embed("trigger load")
    assert e._model is not None


def test_model_name_and_threads_are_forwarded(fake_model):
    e = FastembedEngine(model_name="custom/model", threads=4)
    e.embed("x")
    assert e._model.kwargs["model_name"] == "custom/model"
    assert e._model.kwargs["threads"] == 4


def test_embed_batch_empty_returns_empty(fake_model):
    """An empty batch returns an empty list without touching the model."""
    e = FastembedEngine()
    assert e.embed_batch([]) == []


def test_client_uses_explicit_settings_model_cache(tmp_path, fake_model):
    from luminary_memory import MemoryClient
    from luminary_memory.config import Settings

    cache = str(tmp_path / "persistent models")
    client = MemoryClient(settings=Settings(db_path=str(tmp_path / "memory.db"), model_cache_dir=cache))
    try:
        client.engine.embed("fixture fact")
        assert client.engine._model.kwargs["cache_dir"] == cache
    finally:
        client.close()
