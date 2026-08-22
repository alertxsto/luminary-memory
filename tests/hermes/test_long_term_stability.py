"""Long-lived provider invariants: concurrency, restart, and config parity."""

from __future__ import annotations

import threading
import time

from luminary_memory.hermes.config import save_config
from luminary_memory.hermes.provider import LuminaryMemoryProvider


class _FakeEngine:
    def embed(self, text: str) -> list[float]:
        value = (sum(ord(char) for char in text) % 97) + 1
        return [float(value), float(len(text) + 1), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _provider(tmp_path, **kwargs) -> LuminaryMemoryProvider:
    provider = LuminaryMemoryProvider()
    provider.initialize(
        "session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="test", **kwargs
    )
    provider._client.engine = _FakeEngine()
    return provider


def _wait_for_count(provider: LuminaryMemoryProvider, minimum: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if provider._client is not None and provider._client.count() >= minimum:
            return True
        time.sleep(0.02)
    return False


def test_writer_and_prefetch_get_distinct_thread_owned_clients(tmp_path):
    provider = _provider(tmp_path)
    barrier = threading.Barrier(3)
    clients = []
    errors = []

    def worker() -> None:
        try:
            barrier.wait(timeout=3)
            client = provider._writer_client()
            clients.append(client)
            time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001 -- surface any worker failure
            errors.append(exc)
        finally:
            provider._close_thread_client()

    threads = [threading.Thread(target=worker, name=f"probe-{i}") for i in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=3)
    for thread in threads:
        thread.join(timeout=3)

    assert not errors
    assert len(clients) == 2
    assert clients[0] is not clients[1]
    provider.shutdown()


def test_concurrent_turns_and_prefetch_survive_shutdown(tmp_path):
    provider = _provider(tmp_path)
    provider._config.update({"retain_every_n_turns": 1, "recall_sync": False})
    errors = []

    def write_turns() -> None:
        try:
            for index in range(24):
                provider.sync_turn(
                    f"user durable fact {index}",
                    f"assistant confirms fact {index}",
                    session_id="session-1",
                )
        except Exception as exc:  # noqa: BLE001 -- surface any worker failure
            errors.append(exc)

    def prefetch_turns() -> None:
        try:
            for index in range(12):
                provider.queue_prefetch(f"durable fact {index}", "session-1")
        except Exception as exc:  # noqa: BLE001 -- surface any worker failure
            errors.append(exc)

    writers = [threading.Thread(target=write_turns, name=f"writer-caller-{i}") for i in range(2)]
    prefetcher = threading.Thread(target=prefetch_turns, name="prefetch-caller")
    for thread in writers + [prefetcher]:
        thread.start()
    for thread in writers + [prefetcher]:
        thread.join(timeout=15)
    assert not errors
    assert all(not thread.is_alive() for thread in writers + [prefetcher])
    provider._retain_queue.join()
    assert _wait_for_count(provider, 24)

    provider.shutdown()
    assert provider._writer_thread is None or not provider._writer_thread.is_alive()
    assert provider._prefetch_thread is None or not provider._prefetch_thread.is_alive()


def test_concurrent_prefetch_requests_leave_no_orphan_worker(tmp_path):
    provider = _provider(tmp_path)
    provider._config.update({"recall_sync": False})
    errors = []

    def queue_requests(worker_id: int) -> None:
        try:
            for index in range(8):
                provider.queue_prefetch(f"concurrent query {worker_id}-{index}", "session-1")
        except Exception as exc:  # noqa: BLE001 -- surface race failures
            errors.append(exc)

    threads = [
        threading.Thread(
            target=queue_requests, args=(worker_id,), name=f"prefetch-caller-{worker_id}"
        )
        for worker_id in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    provider.shutdown()
    assert provider._prefetch_thread is None or not provider._prefetch_thread.is_alive()


def test_reinitialize_stops_previous_workers_before_starting_new_session(tmp_path):
    provider = _provider(tmp_path)
    old_writer = provider._writer_thread
    provider.initialize(
        "session-2", hermes_home=str(tmp_path), platform="cli", agent_identity="test"
    )

    assert provider._session_id == "session-2"
    assert provider._client is not None
    assert old_writer is None or not old_writer.is_alive()
    assert provider._writer_thread is not old_writer
    provider.shutdown()


def test_initialize_after_preflight_shutdown_starts_a_live_writer(tmp_path):
    provider = LuminaryMemoryProvider()
    provider.shutdown()
    provider.initialize(
        "session-1", hermes_home=str(tmp_path), platform="cli", agent_identity="test"
    )
    provider._client.engine = _FakeEngine()
    provider.sync_turn("durable after preflight", "confirmed", session_id="session-1")
    assert _wait_for_count(provider, 1)
    provider.shutdown()


def test_main_and_worker_clients_share_config_and_llm_enricher(tmp_path, monkeypatch):
    import luminary_memory.ingest.llm as llm_module

    class _SentinelEnricher:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def enrich(self, text):
            raise AssertionError("not called by this wiring test")

    monkeypatch.setattr(llm_module, "OpenAICompatibleEnricher", _SentinelEnricher)
    save_config(
        {
            "ingest_llm": True,
            "llm_base_url": "http://llm.test/v1",
            "llm_model": "test-model",
            "llm_timeout": 17,
            "importance_auto": False,
            "consolidate_semantic": False,
            "core_top_n": 3,
            "core_budget": 321,
            "recall_min_score": 0.42,
        },
        str(tmp_path),
    )
    provider = _provider(tmp_path)
    main = provider._client
    assert isinstance(main.enricher, _SentinelEnricher)
    assert main.settings.importance_auto is False
    assert main.settings.consolidate_semantic is False
    assert main.settings.core_top_n == 3
    assert main.settings.core_budget == 321
    assert main.settings.recall_min_score == 0.42

    worker = provider._writer_client()
    assert isinstance(worker.enricher, _SentinelEnricher)
    assert worker.settings.importance_auto is False
    assert worker.settings.consolidate_semantic is False
    provider.shutdown()
