from __future__ import annotations

from abc import ABC, abstractmethod

from luminary_memory.types import Memory


class MemoryBackend(ABC):
    @abstractmethod
    def add(self, m: Memory) -> int: ...

    def add_with_status(self, m: Memory) -> tuple[int, bool]:
        """Insert *m* and report whether a new row was created.

        The second value is important for idempotent callers: a backend can
        resolve a concurrent exact duplicate without making the API write a
        second episode, evidence row, or graph edge for the same fact.
        Lightweight/custom backends keep the old contract through this
        default implementation.
        """
        return self.add(m), True
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

    def add_many_with_status(self, memories: list[Memory]) -> list[tuple[int, bool]]:
        """Batch variant of :meth:`add_with_status` for backend parity."""
        return [self.add_with_status(m) for m in memories]

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

    def find_by_hash(self, content_hash: str, scope: dict | None = None) -> Memory | None:
        """Return an exact-content match in the requested scope, if any."""
        from luminary_memory.scope import memory_matches_scope

        for memory in self.all():
            if memory.content_hash == content_hash and memory_matches_scope(memory, scope):
                return memory
        return

    def find_by_claim_key(self, claim_key: str, scope: dict | None = None) -> list[Memory]:
        """Return active claims for a canonical subject/predicate key."""
        from luminary_memory.scope import memory_matches_scope

        return [
            memory
            for memory in self.all()
            if memory.claim_key == claim_key
            and memory_matches_scope(memory, scope, active_only=False)
        ]

    def record_event(
        self,
        event_type: str,
        memory_id: int | None,
        before: dict | None = None,
        after: dict | None = None,
        actor: str | None = None,
    ) -> None:
        """Append an audit event when the backend supports an event table."""
        return

    def add_evidence(
        self,
        memory_id: int,
        quote: str,
        source_id: str | None = None,
        observed_at: str | None = None,
        extractor: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        """Persist a provenance row when the backend supports it."""
        return

    def record_episode(self, episode_id: str, content: str, **metadata) -> None:
        """Persist immutable source text when the backend has an episode ledger."""
        return

    def add_claim(self, memory_id: int, claim: dict, **scope) -> None:
        """Persist a structured claim when the backend supports claim storage."""
        return

    def sync_claim_status(
        self,
        memory_id: int,
        status: str,
        valid_to: str | None = None,
    ) -> None:
        """Keep derived claim rows aligned with a memory lifecycle mutation."""
        return

    def rehome_memory_references(self, source_id: int, target_id: int) -> None:
        """Move derived references before a hard-delete consolidation.

        Backends with provenance tables override this. The no-op default keeps
        lightweight/custom backends compatible with lifecycle operations.
        """
        return

    @abstractmethod
    def keyword_search(
        self,
        query: str,
        limit: int | None,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def vector_search(
        self,
        vec: list[float],
        limit: int | None,
        scope: dict | None = None,
        include_global: bool = True,
    ) -> list[tuple[Memory, float]]: ...
    @abstractmethod
    def count(self) -> int: ...
