# PLAN — Persistent Memory Context (Anti-Lupa, LongMemEval-Ready)

**Problem nyata (dibuktikan hari ini):** Agent lupa aturan format tabel 3x berturut, padahal aturan ada di store. Recall query-based gagal deliver aturan kritis ke konteks yang tepat.

**Root cause (dianalisa, bukan tebakan):**
1. `system_prompt_block()` STATIS — cuma nulis "memories are automatically injected", TANPA isi. Agent gak punya akses aturan kecuali pas recall query match.
2. Recall dependen query — query "laporan status" gak match "format tabel", jadi aturan gak ke-recall.
3. Memory gak persistent — tiap turn recall ulang dari 0, aturan penting tenggelam di ranking.
4. Context window 1M token, memory cuma 3K (0.3%) — ruang LEGA, sayang gak dipake.

---

## Fase 1 — Persistent Rule Injection (system prompt) 🔴 PRIORITAS

**Konsep:** `system_prompt_block()` inject top memories by importance LANGSUNG ke system prompt — SELALU ada di context, gak tergantung query.

**Status: ✅ DONE (v0.2.11).** Persistent-context build berjalan setiap turn (bukan hanya session-start system prompt, yang byte-stable untuk prompt caching), di-merge dengan query recall, dan di-dedup agar tidak dobel.

| Task | Detail | Verifikasi |
|---|---|---|
| T1.1 | `system_prompt_block()` inject top-N memories (importance >= `context_min_importance`) | ✅ Test: prompt berisi aturan format tabel |
| T1.2 | Rules (importance >= 0.9) ALWAYS included, fakta lain by rank | ✅ top-N by importance; pinned rules never pruned |
| T1.3 | Config: `LUMINARY_CONTEXT_TOP_N` (default 8), `LUMINARY_CONTEXT_BUDGET` (default 2000 tokens) | ✅ Env override works |
| T1.4 | Token cap: potong ke budget biar gak ngebloat | ✅ Test: total < budget |
| T1.5 | Cache: prompt block di-cache per session, gak recompute tiap turn | ✅ Recompute per-turn via lean scan (5ms @5k), cached per turn |
| T1.6 | **ANTI-DUPLIKAT WAJIB**: system prompt inject dan prefetch recall harus **dedup** — memory yang udah di system prompt gak boleh muncul lagi di prefetch (dan sebaliknya) | ✅ `_injected_ids` tracked per turn; recall skips injected |

**Impact:** Aturan format tabel, em dash, no-tag SELALU di context gw → gak mungkin lupa. Cost: ~2K token / 1M = 0.2%.

---

## Fase 2 — Rule Pinning & Anti-Kontradiksi

**Status: ✅ DONE (v0.2.11, commit 07ad344).**

| Task | Detail | Verifikasi |
|---|---|---|
| T2.1 | Rule pinning: memory importance >= 0.9 di-pin (gak ke-prune/consolidate/turunin) | ✅ Test: lifecycle gak hapus pinned |
| T2.2 | Auto-replace: ingest aturan baru yang semantic-similar (>= 0.85) ke aturan lama → REPLACE bukan nambah | ✅ Test: "WAJIB table" replace "JANGAN tabel" |
| T2.3 | Enricher: aturan baru set importance 0.9 otomatis (udah T3, verify) | ✅ Summary-only rule detection; raw transcript tidak di-flag |

---

## Fase 3 — Recall Quality (support)

| Task | Detail | Verifikasi |
|---|---|---|
| T3.1 | Multi-lingual embedding (opsional, `LUMINARY_EMBEDDING_MODEL`) | Benchmark Indo-English recall |
| T3.2 | Query expansion: kalau query nyebut topik yang ada aturannya, inject aturan itu duluan | Test: "buat laporan" -> format tabel muncul |

---

## Fase 4 — Verification & Benchmark

| Task | Detail |
|---|---|
| T4.1 | Test suite: semua Fase 1-3 covered, coverage >= 90% |
| T4.2 | Simulasi LongMemEval: recall fakta lama setelah N turn tanpa query ulang |
| T4.3 | Benchmark: context overhead vs recall accuracy |
| T4.4 | Docs + skill update + CHANGELOG + ROADMAP |

---

## DoD (Definition of Done)

| Check | Target |
|---|---|
| System prompt berisi aturan kritis | ✅ selalu (top-8 by importance) |
| Aturan format tabel di context | ✅ gak perlu query match (persistent every turn) |
| Lifecycle gak hapus pinned rules | ✅ |
| Aturan baru replace yang lama | ✅ anti-kontradiksi |
| Context overhead | <= 2000 token (0.2% dari 1M) |
| Test + coverage | 100% pass, >= 93% |
| CI | hijau |

---

## Timeline

| Release | Isi |
|---|---|
| v0.2.11 | Fase 1 (T1.1-T1.6) + Fase 2 (T2.1-T2.3) — ✅ rilis |
| v0.2.12 | Performance (vectorized scans, batched writes, lean persistent scan) — ✅ rilis |
| v0.2.13+ | Fase 3 (T3.1-T3.2) + Fase 4 (T4.1-T4.4) |
