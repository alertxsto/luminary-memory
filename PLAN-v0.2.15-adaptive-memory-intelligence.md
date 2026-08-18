# PLAN — v0.2.15 Adaptive Memory Intelligence

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.15 · **Fokus:** memory management yang "pintar" untuk agent long-running anti-amnesia — store & recall beradaptasi dengan pemakaian, tanpa menambah fitur baru yang mencolok.

**Nilai:** Sebuah memory layer harus **belajar dari pemakaian**: memori yang sering dipakai harus makin relevan (naik importance), yang jarang makin layak di-prune (turun), dan recall harus tahu aturan yang menyangkut topik query meski query-nya beda kata. Ini yang membedakan "punya store" vs "store yang pintar".

---

## Prinsip

- **Lossless dulu**: setiap perubahan recall HARUS diverifikasi hasil recall tidak memburuk (benchmark quality MRR / recall@k).
- **Pintar = adaptif, bukan heuristik kaku**: perubahan importance harus bisa diamati di test (akses → naik; jarang → turun), tanpa mengubah hasil recall top-k secara tidak terkontrol.
- Setiap task: **unit test (backend asli) + integration test (MemoryClient/recall) + verifikasi runtime** sebelum dianggap done.
- **Laporan → ACC user → commit → push** (urutan WAJIB).

---

## Fase 1 — Importance Adaptif (access-aware)

> **Akar masalah:** `estimate_importance` dipanggil pas ingest dan pas lifecycle prune. Tapi `touch_memories` (saat recall) cuma update `access_count`/`last_accessed_at`, TIDAK update importance. Jadi memori yang sering di-recall gak naik ranking-nya di persistent context / top_by_importance sampai lifecycle jalan (yang bisa berjam-hari). Agent "pintar" harusnya makin paham topik yang sering dia tanya.

### T1.1 [Core] Re-estimate importance saat recall access
- **Apa:** setelah `touch_memories(ids)`, hitung ulang importance untuk id yang di-touch menggunakan `estimate_importance` (access + recency + centrality), lalu `update_importances` batch.
- **Kenapa aman:** `estimate_importance` udah ada & teruji; akses → `access_norm` naik, `last_accessed_at` di-touch → `recency_norm` naik. Hasil: memori yang sering di-recall naik importance. Pinned rules (>=0.9) naik juga, gak masalah (sudah di-pin).
- **Guard:** jangan turunkan importance pinned di bawah 0.9; clamp tetap [0,1].
- **Test (backend asli):**
  - recall 3x → importance memori naik di atas baseline (bandingkan sebelum/sesudah via `get`).
  - memori lain yang TIDAK di-recall importance-nya TIDAK berubah.
  - pinned rule (0.95) tidak turun walau di-recall.
  - batched: banyak id di-recall → satu `update_importances` (bukan N update).

### T1.2 Lifecycle re-estimate gak boleh nurunin pinned
- **Apa:** verifikasi (regression) bahwa setelah lifecycle, pinned rules tetap >= 0.9. Sudah ada `test_lifecycle_preserves_pinned_rule_importance` — extend dengan skenario "di-recall banyak tapi pinned tetap".
- **Test:** T1.1 + lifecycle → pinned tetap 0.95, unpinned yang jarang diakses turun.

---

## Fase 2 — Recall Lebih Pintar (rule-aware + dedup konsisten)

### T2.1 [Core] Query expansion ke aturan store
> **Akar masalah:** query "buat laporan pakai tabel" — semantic mungkin match "format tabel" tapi lemah; graph expansion cuma entity. Kalau store punya aturan yang menyangkut topik query, recall harus surface aturan itu DULUAN.

- **Apa:** perluas `_expand_query` (recall/semantic.py) — selain entity graph, tambah keyword/kata kunci dari memori ber-importance tinggi (rules) yang co-occur dengan token query. Best-effort, fallback ke query asli.
- **Aman:** hasil akhir tetap lewat RRF + dedup + budget; expansion cuma menambah sinyal semantic, hasil recall tidak bisa lebih buruk dari baseline (karena query asli tetap diikutkan).
- **Test (backend asli):**
  - store berisi rule "selalu pakai markdown table" (importance 0.95) + konvo biasa; query "buat laporan" → rule muncul di top-k recall.
  - query kosong/gibberish → expansion no-op (fallback).
  - expansion error (backend aneh) → fallback ke query asli, tidak crash.

### T2.2 [Consistency] Dedup recall vs consolidate pakai threshold sama
> **Akar masalah:** recall dedup pakai `dedup_jaccard_threshold` (0.85), consolidate pakai `consolidate_jaccard_threshold` (0.9) + semantic. Bisa ada near-duplicate yang konsisten di-recall (karena threshold recall lebih longgar) tapi gak pernah di-consolidate → store menumpuk.

- **Apa:** dokumentasi + verifikasi; JIKA terbukti gap nyata di benchmark, samakan baseline threshold (config, bukan hardcode) dengan default konsisten. **TIDAK mengubah hasil recall** tanpa benchmark.
- **Test:** near-duplicate Jaccard 0.86 → recall dedup collapse; consolidate threshold 0.9 TIDAK merge (documented behavior). Verifikasi konsistensi config default.

### T2.3 [Hardening] Fallback recall: aturan penting dulu (tiered)
- **Apa:** sudah ada di T2.3 v0.2.13 (importance fallback sebelum temporal). Perkuat: pastikan fallback TIDAK menurunkan hasil (jika temporal memberi konteks yang valid, jangan diganti rule yang gak relevan).
- **Test:** fallback penting dulu tetap ada; temporal fallback masih jalan kalau gak ada rule; gabungan strategi normal tidak terpengaruh.

---

## Fase 3 — Store Hygiene Adaptif

### T3.1 Consolidate aware importance (aturan baru vs lama)
- **Apa:** saat consolidate, master harusnya yang importance-nya lebih tinggi (bukan cuma content terpanjang), selama masih pinned-safe.
- **Aman:** hanya pilih master antar non-pinned; pinned selalu jadi master kalau ada.
- **Test:** dua duplikat, satu importance 0.8 satu 0.3 → survivor punya importance 0.8 (content terbaik + importance terbaik).

### T3.2 Prune adaptif: kalau importance auto, jangan prune memori yang baru diakses
- **Apa:** verifikasi: memori dengan `last_accessed_at` baru (mis. < 24h) TIDAK di-prune oleh `max_count` cap kalau importance masih di atas threshold (kecuali cap mutlak). Ini melindungi "yang baru dipakai" dari eviction dini.
- **Test:** store penuh, 2 memori baru diakses + 1 lama → yang lama di-prune duluan.

---

## Fase 4 — Testing Komprehensif & Regression

### T4.1 Benchmark quality regression (WAJIB)
- Jalankan `benchmarks/` (MRR / recall@k) sebelum & sesudah Fase 1-3. **Hasil TIDAK boleh turun** (MRR baseline 1.0).
- Report angka di PLAN/CHANGELOG.

### T4.2 Full suite + lint + coverage
- `pytest tests/` — semua pass (target: 355+).
- `ruff check src tests` — clean.
- Coverage ≥ 93%.
- `hermes/test.sh` — smoke OK.

### T4.3 Test concurrency (regression)
- Access-aware importance saat recall berjalan dari thread berbeda (prefetch background) → tidak ada `ProgrammingError`, importance tetap di-update.

---

## Fase 5 — Docs & Release

- [ ] T5.1 `docs/lifecycle.md` — importance adaptif: access → naik; re-estimate saat recall; pinned safe.
- [ ] T5.2 `docs/recall.md` — query expansion ke rules; dedup threshold konsistensi.
- [ ] T5.3 `CHANGELOG.md` + `ROADMAP.md` + README (jika angka berubah) — v0.2.15.
- [ ] T5.4 `PLAN-v0.2.15-adaptive-memory-intelligence.md` status update.

---

## Definition of Done

| Check | Target |
|-------|--------|
| Recall quality (MRR/recall@k) | TIDAK turun (baseline 1.0) |
| Importance adaptif | akses → naik, jarang → turun, pinned aman (test) |
| Query expansion | rule muncul di top-k untuk query topik (test) |
| Full suite | 100% pass |
| Coverage | ≥ 93% |
| Ruff | clean |
| Hermes runtime | smoke OK |
| Docs | lifecycle.md / recall.md / CHANGELOG / ROADMAP konsisten |
| Proses | Laporan → ACC → commit → push |

---

## Task prioritization

| Priority | Task | Alasan |
|----------|------|--------|
| 🔴 P1 | T1.1 Importance adaptif saat recall | Inti "store pintar" — belajar dari pemakaian |
| 🔴 P1 | T2.1 Query expansion ke rules | Recall nyambung ke aturan topik tanpa query exact |
| 🟡 P2 | T3.1 Consolidate importance-aware master | Store makin bersih, survivor terbaik |
| 🟡 P2 | T3.2 Prune protect yang baru diakses | Gak evict memori hangat |
| 🟡 P2 | T4.x Benchmark + test penuh | Jaring pengaman lossless |
| 🟢 P3 | T2.2/T2.3 Consistency & hardening | Depend pada bukti benchmark |

---

## Referensi

- `src/luminary_memory/lifecycle/importance.py` — `estimate_importance` (access/recency/centrality).
- `src/luminary_memory/api.py` (recall, `touch_memories`) — titik re-estimate saat access.
- `src/luminary_memory/recall/semantic.py` — `_expand_query`.
- `src/luminary_memory/recall/dedup.py` + `lifecycle/consolidate.py` — threshold dedup vs consolidate.
- Plan lama: `PLAN-memory-optimal.md` (T5 multi-lingual, T6 query expansion, T9 health kontradiksi — masih pending di luar scope ini).
