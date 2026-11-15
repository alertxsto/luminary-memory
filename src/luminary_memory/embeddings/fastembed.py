from __future__ import annotations

import logging
from pathlib import Path

from fastembed import TextEmbedding

from luminary_memory.config import Settings

logger = logging.getLogger(__name__)


class FastembedEngine:
    def __init__(
        self,
        model_name: str | None = None,
        threads: int = 1,
        cache_dir: str | None = None,
    ):
        settings = Settings()
        self.model_name = model_name or settings.embedding_model
        self.cache_dir = cache_dir or settings.model_cache_dir or None
        self.threads = threads
        self._model: TextEmbedding | None = None

    def _model_is_cached(self) -> bool:
        """True when the weights are already on disk.

        fastembed stores each model under ``models--<org>--<name>``, so the
        basename is enough to tell a warm cache from a first run.
        """
        if not self.cache_dir:
            return True
        root = Path(self.cache_dir).expanduser()
        if not root.is_dir():
            return False
        stem = self.model_name.rsplit("/", 1)[-1]
        return any(child.is_dir() and stem in child.name for child in root.iterdir())

    def _load(self) -> TextEmbedding:
        if self.cache_dir:
            # fastembed downloads into the cache on first use; a missing parent
            # turns that into a confusing download error instead of a mkdir.
            Path(self.cache_dir).expanduser().mkdir(parents=True, exist_ok=True)
        if not self._model_is_cached():
            # A first run blocks on a large download. Say so instead of looking
            # like a hang on a fresh machine.
            logger.warning(
                "embedding model %s is not cached in %s yet; the first run "
                "downloads it and can take a few minutes",
                self.model_name,
                self.cache_dir,
            )
        self._model = TextEmbedding(
            model_name=self.model_name, threads=self.threads, cache_dir=self.cache_dir,
        )
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
