"""Context compaction must never become an implicit memory write path."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def _init_provider(tmp_path):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    return p


def test_pre_compress_never_persists_transcript_fragments(tmp_path):
    p = _init_provider(tmp_path)
    msgs = [
        {"role": "user", "content": "ALWAYS use markdown tables in telegram"},
        {"role": "user", "content": "regla de formato para la respuesta"},
    ]
    p.on_pre_compress(msgs)
    assert p._client.count() == 0
    p.shutdown()


def test_pre_compress_no_rule_no_write(tmp_path):
    p = _init_provider(tmp_path)
    p.on_pre_compress([{"role": "user", "content": "oh oke sipp"}])
    assert p._client.count() == 0
    p.shutdown()
