from __future__ import annotations

from abc import ABC, abstractmethod

from luminary_memory.types import Memory


class MemoryBackend(ABC):
    @abstractmethod
    def add(self, m: Memory) -> int: ...
    @abstractmethod
    def get(self, id: int) -> Memory | None: ...
    @abstractmethod
    def update(self, m: Memory) -> None: ...
    @abstractmethod
    def delete(self, id: int) -> None: ...
    @abstractmethod
    def all(self) -> list[Memory]: ...

    def add_many(self, memories: list[Memory]) -> list[int]:
        """Batch insert; default falls back to per-item add. Subclasses may override."""
        return [self.add(m) for m in memories]

    @abstractmethod
    def keyword_search(self, query: str, limit: int | None) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def vector_search(self, vec: list[float], limit: int | None) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def count(self) -> int: ...
