"""v0.2.18: on_pre_compress persists only the most important (rule-bearing)
messages before context compaction, as a safety net for durable rules."""

from luminary_memory.hermes.provider import LuminaryMemoryProvider


def _init_provider(tmp_path):
    p = LuminaryMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="cli", agent_identity="test")
    return p


def test_pre_compress_persists_important_rule_only(tmp_path):
    p = _init_provider(tmp_path)
    msgs = [
        {"role": "user", "content": "ALWAYS use markdown tables in telegram"},
        {"role": "user", "content": "halo apa kabar"},
    ]
    p.on_pre_compress(msgs)
    contents = [m.content.lower() for m in p._client.list(limit=0)]
    assert any("markdown" in c for c in contents), "important rule must be persisted"
    assert not any("apa kabar" in c for c in contents), "chit-chat must not be persisted"
    p.shutdown()


def test_pre_compress_no_rule_no_write(tmp_path):
    p = _init_provider(tmp_path)
    p.on_pre_compress([{"role": "user", "content": "oh oke sipp"}])
    assert p._client.count() == 0
    p.shutdown()