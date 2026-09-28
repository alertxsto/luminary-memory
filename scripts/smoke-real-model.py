#!/usr/bin/env python3
"""Release smoke for a real default Fastembed model and semantic top hit."""

import os
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="luminary-model-smoke-") as root:
        os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path(root) / "fastembed"))
        os.environ.setdefault("HF_HOME", str(Path(root) / "huggingface"))
        from luminary_memory.backends.sqlite import SQLiteBackend
        from luminary_memory.config import Settings
        from luminary_memory.embeddings.fastembed import FastembedEngine
        from luminary_memory.recall.semantic import semantic_recall
        from luminary_memory.types import Memory

        engine = FastembedEngine()
        assert engine.model_name == Settings().embedding_model
        contents = [
            "A cat sleeps on the couch in the living room.",
            "The PostgreSQL database uses a multicolumn index for search.",
            "The rocket fuel valve is located beside the launch pad.",
        ]
        vectors = engine.embed_batch(contents)
        assert all(len(vec) == Settings().embedding_dim for vec in vectors)
        backend = SQLiteBackend(str(Path(root) / "semantic.db"))
        try:
            for content, vector in zip(contents, vectors):
                backend.add(Memory(content=content, embedding=vector))
            ranked = semantic_recall(backend, engine, "Where does the feline nap?", limit=3)
            assert ranked and ranked[0][0].content == contents[0], [
                (memory.content, score) for memory, score, _ in ranked
            ]
            assert ranked[0][1] > ranked[1][1], "default model failed to separate unrelated facts"
        finally:
            backend.close()
        print(f"real {engine.model_name}: feline/cat semantic recall ranked above database and rocket")


if __name__ == "__main__":
    main()
