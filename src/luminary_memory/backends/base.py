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

    def delete_many(self, ids: list[int]) -> None:
        """Batch delete; default falls back to per-item delete. Subclasses may override."""
        for _id in ids:
            self.delete(_id)

    def get_many(self, ids: list[int]) -> dict[int, Memory]:
        """Batch get; default falls back to per-item get. Subclasses may override."""
        out: dict[int, Memory] = {}
        for _id in ids:
            m = self.get(_id)
            if m is not None:
                out[_id] = m
        return out

    @abstractmethod
    def keyword_search(self, query: str, limit: int | None) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def vector_search(self, vec: list[float], limit: int | None) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def count(self) -> int: ...
