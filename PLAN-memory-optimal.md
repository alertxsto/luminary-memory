# PLAN — Luminary Memory Optimal (v0.2.11+)

**Goal:** Fix recurring "agent lupa aturan" — memory/recall harus deliver aturan kritis di konteks yang tepat, anti-kontradiksi, anti-kelupaan.

**Trigger:** User keseringan ngingetin format tabel (2x marah), em dash, dan aturan lain. Recall gak nge-inject aturan penting di ranking atas.

---

## Fase 1 — Aturan Kritis Selalu Muncul (recall quality)

### T1. Importance recall boost (DONE, commit 4e89e69)
- [x] `LUMINARY_IMPORTANCE_RECALL_BOOST` (default 1.0, live 1.5)
- [x] Memory importance >= 0.8 dapet bonus ranking x boost
- [x] Verified: aturan format tabel RANK 15 -> 3/5

### T2. Anti-kontradiksi aturan (DONE, manual)
- [x] Hapus entri [135] "JANGAN tabel" yang kontradiksi [168] "WAJIB table"
- [x] Naikin importance aturan kritis ke 0.95

### T3. Auto-boost aturan di ingest (BARU)
- [ ] Enricher prompt: kasih `importance: 0.9+` otomatis untuk memory berisi instruksi/aturan ("JANGAN", "WAJIB", "HARUS", "user meminta")
- [ ] `_parse_enrichment_payload` deteksi keyword aturan -> set importance tinggi
- [ ] Test: ingest "JANGAN pake em dash" -> importance >= 0.9

### T4. Rule pinning (BARU)
- [ ] Opsi `LUMINARY_PIN_RULES=true`: memory dengan importance >= 0.9 di-pin (gak ke-prune, gak ke-consolidate, gak ke-turunin importance)
- [ ] Lifecycle prune skip pinned
- [ ] Consolidate skip pinned (aturan gak boleh di-merge)

---

## Fase 2 — Recall Lebih Akurat (query quality)

### T5. Multi-lingual embedding (BARU, opsional)
- [ ] Ganti `BAAI/bge-small-en-v1.5` -> multilingual (misal `intfloat/multilingual-e5-small`) biar query Indo-English match lebih baik
- [ ] Config: `LUMINARY_EMBEDDING_MODEL` (udah ada)
- [ ] Benchmark: recall quality Indo-English sebelum/sesudah

### T6. Query expansion enhance (BARU)
- [ ] Expand query gak cuma entity graph, tapi juga synonyms/keywords dari aturan store
- [ ] Kalau query nyebut topik yang ada aturannya, inject aturan itu duluan

---

## Fase 3 — Store Hygiene (anti-bloat, anti-stale)

### T7. Auto-archive aturan lama (BARU)
- [ ] Pas ingest aturan baru yang mirip aturan lama (semantic cosine >= 0.8), REPLACE yang lama (bukan nambah) — anti-kontradiksi otomatis
- [ ] Test: ingest "WAJIB table" saat ada "JANGAN tabel" -> yang lama ke-replace/hapus

### T8. Curation prompt: aturan vs fakta (BARU)
- [ ] Enricher bedain: aturan (instruction, "JANGAN/WAJIB") -> importance 0.9, fakta biasa -> importance normal
- [ ] Work-log tetap tolak (udah ada)

### T9. Health score: kontradiksi dimension (BARU)
- [ ] Deteksi entri kontradiktif (semantic mirip tapi isi berlawanan) -> warning di health
- [ ] CLI `luminary-memory health` nampilin potensi kontradiksi

---

## Fase 4 — Tooling & Docs

### T10. Fix tool `luminary_recall` cross-thread (BARU)
- [ ] Bug: tool wrapper recall error "SQLite objects created in a thread" — client dibuat di thread beda
- [ ] Fix: thread-safe client factory di tool wrapper

### T11. Docs & skill update
- [ ] README architecture: importance boost + rule pinning
- [ ] docs/recall.md: boost, pin, multilingual
- [ ] SKILL.md: aturan kritis selalu recall
- [ ] CHANGELOG + ROADMAP v0.2.11+

---

## Verification (DoD)

| Check | Target |
|---|---|
| Test suite | 100% pass |
| Coverage | >= 90% |
| Ruff | clean |
| Aturan format tabel recall | RANK <= 3 |
| Ingest aturan baru | auto-replace lama (anti-kontradiksi) |
| Lifecycle | pinned rules gak ke-prune |
| CI | hijau |
| Docs | konsisten v0.2.11 |

---

## Roadmap mapping

- v0.2.11: Fase 1 (T1-T4) + Fase 3 (T7-T8) + Fase 4 (T10-T11)
- v0.2.12: Fase 2 (T5-T6) + Fase 3 (T9)
- (T1/T2 udah DONE, sisanya baru)
