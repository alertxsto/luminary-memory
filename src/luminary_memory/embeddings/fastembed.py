from __future__ import annotations

from fastembed import TextEmbedding

from luminary_memory.config import Settings


class FastembedEngine:
    def __init__(
        self,
        model_name: str | None = None,
        threads: int = 1,
    ):
        self.model_name = model_name or Settings().embedding_model
        self.threads = threads
        self._model: TextEmbedding | None = None

    def _load(self) -> TextEmbedding:
        self._model = TextEmbedding(model_name=self.model_name, threads=self.threads)
        return self._model

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            self._load()
        assert self._model is not None
        return self._model

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [list(vec) if isinstance(vec, list) else vec.tolist() for vec in self.model.embed(texts)]
