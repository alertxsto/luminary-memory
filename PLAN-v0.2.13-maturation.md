# PLAN — v0.2.13 Maturation Pass (Polish, bukan Fitur Baru)

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.13 · **Fokus:** matengin yang sudah ada — akurasi recall, hygiene store, test komprehensif, verifikasi end-to-end di Hermes. TIDAK menambah fitur baru.

---

## Prinsip

- Semua perubahan harus **mempertahankan hasil recall identik** (diverifikasi vs baseline via benchmark quality metrics).
- Setiap task punya **test** + **verifikasi live di runtime Hermes** sebelum dianggap done.
- **Laporan + tes penuh + verifikasi hermes WAJIB sebelum push.**

---

## Fase 1 — Test Coverage Hermes (gap terbesar)

### T1.1 Test activity hook (`luminary-activity/handler.py`)
- [x] Unit test `_recent_activity()`: last_id tracking, dedup (memory ≤ last_id tidak muncul), format markdown-escape.
- [x] Unit test `_post()`: mock `urllib.request.urlopen`, verifikasi payload JSON, error handling (network fail → swallow).
- [x] Unit test `handle()`: hanya fire di `agent:end`, cooldown/skip saat store idle.
- **Gap saat ini:** `tests/hermes/test_hooks.py` hanya menguji provider hooks (`on_memory_write` dll), BUKAN activity hook yang kirim ke Telegram.
- **Status:** Done — 14 unit tests di `tests/hermes/test_activity_hook.py`, semua pass.

### T1.2 Test persistent context config
- [ ] Test env var `LUMINARY_CONTEXT_*` (sudah ada `test_context_env_vars_map_to_settings` — perlu perluas: `context_budget` truncation, `context_min_importance` filter).
- [ ] Test config.json override env (sudah ada `test_explicit_config_overrides_env_context`).

### T1.3 Test batched backend ops
- [ ] `touch_memories`, `delete_many`, `update_importances`, `get_many`, `scan_embeddings_matrix`, `top_by_importance` — beberapa sudah ada di `test_backend_sqlite.py`; perluas dengan edge: list kosong, id tidak ada.

---

## Fase 2 — Recall Accuracy (tanpa ubah hasil)

### T2.1 `health_score()` duplicate check O(N²) → blocking
- [x] **Masalah:** `health_score()` (api.py:396) menghitung duplicate_rate dengan nested loop O(N²) Jaccard terhadap 500 memory = 125k comparisons per call.
- [x] **Fix (lossless):** gunakan token-blocking (duplicate Jaccard ≥ threshold pasti share token) — hasil identik, ~10× lebih cepat.
- **Status:** Done — implemented at `api.py` health_score(), token-blocking via inverted index. Duplicate count identical to original. Verified via full test suite (338 passed, ruff clean).

### T2.2 `consolidate()` O(N²) → blocking (jika bisa lossless)
- **Masalah:** consolidate.py:71 nested loop O(N²).
- **Catatan:** v0.2.12 sempat dicoba vectorized & di-revert karena mengubah hasil (24 vs 27 merged). Jadi T2.2 HANYA jika blocking bisa dibuktikan lossless (duplicate Jaccard/cosine ≥ threshold pasti share token/embedding). Jika tidak bisa dibuktikan identik, **SKIP** (akurasi > kecepatan).

### T2.3 Recall fallback: prefer important rules, bukan cuma terbaru
- **Masalah:** saat query gak match, fallback (api.py:728) surface `temporal_recall` (memory TERBARU) — kadang noise.
- **Usulan:** fallback prioritaskan importance ≥ `prune_min_importance` dulu (rules), baru temporal. Ini **mengubah hasil recall** → perlu benchmark quality + persetujuan, bukan asal.
- **Verifikasi:** recall fallback di store kosong-match mengembalikan rule penting (bukan convo terbaru).

---

## Fase 3 — Store Hygiene

### T3.1 Whitelist default yang lebih pintar (opsional)
- Audit `ingest/whitelist.py` — apakah default regex sudah cukup menolak noise? (bukan hardcode, tetap configurable via `LUMINARY_INGEST_WHITELIST`).

### T3.2 Lifecycle scheduling di provider
- `run_lifecycle()` di provider hanya jalan di `on_session_end` kalau `auto_maintain` (LLM). Tambahkan **deterministic lifecycle pass** (cleanup/consolidate/prune) secara periodik di provider? → butuh konfirmasi desain (jangan nambah fitur tanpa kebutuhan).

---

## Fase 4 — Docs & Release Consistency

### T4.1 Audit angka benchmark (SUDAH DILAKUKAN v0.2.12)
- [x] RESULTS.md & README pakai angka terukur (77ms @5k, 9ms @1k).
- [x] Tidak ada angka stale (230ms/832ms) tersisa.

### T4.2 Re-audit semua docs vs kode
- [ ] `grep LUMINARY_*` docs vs config.py — pastikan tidak ada env var palsu.
- [ ] Konfigurasi provider (config.json) vs `_DEFAULTS` konsisten.
- [ ] ROADMAP status akurat.

---

## Fase 5 — Verifikasi End-to-End Hermes (WAJIB sebelum push)

### T5.1 Live smoke test di runtime Hermes
- [ ] Provider import & initialize di venv hermes (`/home/alertxsto/.hermes/hermes-agent/venv`).
- [ ] `prefetch()` mengembalikan persistent context + recall, anti-dup.
- [ ] `recall_status()` indicator.
- [ ] Activity hook `handle('agent:end')` memposting ke Telegram (state.json ter-update).
- [ ] Restart gateway hermes → log `luminary.log` tidak ada error baru.

### T5.2 Full test suite + lint + coverage
- [x] `pytest tests/` — semua pass (target: 338+ passed, 3 skipped pgvector).
- [x] `ruff check src tests` — clean.
- [ ] Coverage ≥ 93%.

---

## Definition of Done

| Check | Target |
|-------|--------|
| Recall hasil | IDENTIK baseline (quality metrics sama) |
| Test suite | 100% pass (termasuk activity hook baru) |
| Coverage | ≥ 93% |
| Ruff | clean |
| Hermes runtime | prefetch + persistent context + hook work live |
| Docs | tidak ada env var palsu, angka benchmark akurat |
| Laporan | sebelum push: hasil tes + verifikasi hermes dilaporkan |

---

## Task prioritization

| Priority | Task | Alasan |
|----------|------|--------|
| 🔴 P1 | T1.1 Activity hook test | Gap test terbesar; hook sudah live tapi belum ada jaring pengaman — **DONE** |
| 🔴 P1 | T2.1 health_score O(N²) | Dipanggil berkala, 125k comparisons per call — **DONE** |
| 🟡 P2 | T2.3 Recall fallback | Perbaikan akurasi nyata, tapi ubah hasil → perlu benchmark + ACC |
| 🟡 P2 | T5.1 Live Hermes smoke | Wajib sebelum tiap push |
| 🟢 P3 | T2.2 consolidate (hanya jika lossless) | Akurasi > kecepatan |
| 🟢 P3 | T4.x Docs audit | Continuity |
