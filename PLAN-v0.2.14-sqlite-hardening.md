# PLAN — v0.2.14 SQLite Backend Hardening

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.14 · **Fokus:** menguatkan backend SQLite (default) — correct-by-construction, scan lean, test backend asli, docs akurat. TIDAK menambah fitur baru.
> Lingkup sengaja dibatasi ke **SQLite** (default backend). pgvector punya test integrasi asli yang jalan di CI via `LUMINARY_PG_DSN` — di luar lingkup pass ini.

---

## Prinsip

- Semua perubahan **lossless** — hasil recall/lifecycle IDENTIK baseline; hanya buang dead code, tutup gap, tambah test & verifikasi.
- Setiap task punya **test backend asli (SQLiteBackend, bukan stub)** + **verifikasi runtime** sebelum dianggap done.
- **Laporan + test penuh + ruff + smoke hermes WAJIB sebelum push.**

---

## Fase 1 — Bersihkan & Tutup Gap Correctness

### T1.1 Buang dead constant `_FTS5_SPECIAL`
- [x] **Masalah:** `sqlite.py:17` mendefinisikan `_FTS5_SPECIAL` tapi `_sanitize_fts_query` hanya pakai regex `\w`. Constant mati.
- [x] **Fix:** hapus constant; `_sanitize_fts_query` tetap pakai regex (sudah injection-safe, term di-quote & di-OR-join).
- **Dokumen:** tidak perlu (internal).

### T1.2 Rapikan redundant import di `by_tags`
- [x] **Masalah:** `by_tags` punya `import json as _json` lokal yang menutupi `import json` di top-level.
- [x] **Fix:** pakai `json` top-level, hapus import lokal.

### T1.3 [**Correctness**] FTS5 migration rebuild guard
- [x] **Masalah:** `memories_fts` external-content + trigger `AFTER INSERT`. Kalau DB **lama** (dibuat sebelum FTS5 ada di schema) dibuka, trigger `IF NOT EXISTS` bikin tabel FTS kosong dan baris eksisting TIDAK terindex → keyword recall 0 meski store penuh. Ini persis kelas bug "recall ada tapi keyword kosong".
- [x] **Fix:** di `init_schema`, deteksi upgrade (FTS table baru dibuat) + `memories` berisi → jalankan `INSERT INTO memories_fts(memories_fts) VALUES('rebuild')` (idempotent, sekali). `count(*)` pada FTS external-content TIDAK andal (menghitung content), jadi deteksi via `sqlite_master`.
- [x] **Verifikasi:** 2 test schema baru — DB lama di-upgrade → baris lama keyword-searchable; reopen → idempotent, index tetap sync.
- **Dokumen:** `backends.md` (FTS external-content + rebuild).

---

## Fase 2 — Scan Robustness & Lean (lossless)

### T2.1 Validasi & (opsional) micro-opt `by_tags`
- **Masalah:** `by_tags` full-scan `SELECT id, tags` + parse JSON Python per row (O(N)), beda dari `by_tag_top` yang filter LIKE di DB.
- **Keputusan:** untuk store <100k ini OK oleh desain (dipanggil recall tag-scoped). Tugas: **tambah test**, bukan ubah perilaku. Bila benchmark menunjukkan bottleneck, barulah pertimbangkan LIKE-pre-filter + parse (lossless).
- **Verifikasi:** test edge: tags corrupt (`'{corrupt'`), tags kosong, substring tag (`core-x` vs `core`) — hasil konsisten dgn `by_tag_top`.

### T2.2 Assess WAL mode (opsional, bertanda risiko)
- **Masalah:** koneksi thread-local (tanpa WAL). Provider jalanin background prefetch (read) + writer thread (read/write). Tanpa WAL, reader bisa block saat writer commit pada file yang sama.
- **Keputusan:** TIDAK mengubah dulu tanpa bukti bottleneck + tanpa test concurrency. Task = **tambah test concurrency read/write** (dua thread, akses paralel) untuk membuktikan behavior sekarang aman. Bila ditemukan race/lock, upgrade ke WAL sebagai task terpisah.
- **Dokumen:** catat status di `backends.md` (thread-local connections; WAL belum diaktifkan — pertimbangan untuk concurrency lanjut).

### T2.3 Verifikasi edge `vector_search`
- **Masalah:** brute-force OK by desain; tapi edge belum tentu teruji: `limit=None`, `qn==0` (empty query vec), 1 row, `limit > len`, relevance ordering setelah top-k.
- **Fix:** hanya **tambah test** (tidak ubah kode). Pastikan order benar & identik antara `limit` dan tanpa `limit`.
- **Dokumen:** tak perlu; `recall.md` sudah cover angka perf.

---

## Fase 3 — Test Coverage Backend SQLite (backend asli)

> Semua pakai `SQLiteBackend` beneran (tmp_path), bukan stub. Melengkapi `tests/test_backend_sqlite.py` (sebagian sudah ada: add/get, keyword rank, thread-local, top_by_importance, touch, delete_many, update_importances, scan_matrix, by_tag_top).

- [x] T3.1 `_sanitize_fts_query` — terima karakter injeksi (`*`, `NEAR`, `"`, `OR`, `(`, `-`), output aman & OR-join; empty/gibberish → `''` (zero-hit, tidak crash).
- [x] T3.2 `keyword_search` OR-join — multi-term (`"laporan pakai tabel"`) menemukan memori yang cuma match satu term (regression fix v0.2.13).
- [x] T3.3 FTS sync — after `add`, `update`, `delete`, hasil `keyword_search` merefleksikan perubahan (trigger correctness).
- [x] T3.4 `keyword_search` `limit=None` (unlimited) dan `limit=0`.
- [x] T3.5 `vector_search` — ordering top-k benar, `limit` vs `None` konsisten, empty query vec → `[]`, 1-row & limit>len aman.
- [x] T3.6 `by_tags` — multi-tag, tags corrupt fallback `[]`, konsisten dgn `by_tag_top` untuk substring.
- [x] T3.7 `temporal_scan` — hanya kembalikan (id, created_at, access_count), urut, tanpa parse JSON/embedding.
- [x] T3.8 `scan_embeddings` (pair) vs `scan_embeddings_matrix` — id/vector konsisten, float32 round-trip menjaga nilai.
- [x] T3.9 `recent` pagination edge — `limit=0` (unlimited), offset, order by created_at desc/id desc.
- [x] T3.10 Concurrency — empat thread (recall + ingest) pada satu DB, tanpa `ProgrammingError` (buktikan thread-local + T2.2).
- [x] T3.11 Embedding round-trip — set vektor, `get` balik nilai sama (float32 toleransi).

---

## Fase 4 — Docs Audit & Update

- [x] T4.1 `docs/backends.md` — perluas bagian SQLite:
  - Thread-local connections & kenapa (fix cross-thread provider).
  - FTS5 external-content + trigger + **rebuild migration** (T1.3).
  - Lean scan helpers (`top_by_importance`, `by_tag_top`, `temporal_scan`, `scan_embeddings_matrix`) yang dipakai persistent context.
  - Vector score = linear scan in-process (batas ~100k) + WAL status (T2.2).
- [x] T4.2 `docs/architecture.md` — singgung lean-scan backend di blok "Persistent context" (sudah ada, konsisten).
- [ ] T4.3 `CHANGELOG.md` + `ROADMAP.md` — versi v0.2.14 + catatan hardening.
- [ ] T4.4 `README.md` — cek angka/badge tak stale (hanya jika berubah).

---

## Definition of Done

| Check | Target |
|-------|--------|
| Recall/lifecycle hasil | IDENTIK baseline (lossless) |
| Test backend SQLite | semua pass, backend asli (bukan stub) |
| Full suite | 100% pass (regression) |
| Ruff | clean |
| Hermes runtime | smoke OK (test.sh) |
| Docs | backends.md/architecture.md/CHANGELOG/ROADMAP konsisten |
| Laporan | sebelum push: hasil test + verifikasi dilaporkan |

---

## Task prioritization

| Priority | Task | Alasan |
|----------|------|--------|
| 🔴 P1 | T1.3 FTS rebuild migration | Bug nyata kelas "keyword recall kosong" pada DB lama |
| 🔴 P1 | T3 test coverage backend | Buktikan correctness backend default |
| 🟡 P2 | T2.1 by_tags validasi + test | Konsisten & rapi, tanpa ubah hasil |
| 🟡 P2 | T2.3 vector_search edge test | Kunci accuracy recall |
| 🟡 P2 | T4 docs update | Akurasi dokumentasi |
| 🟢 P3 | T1.1/T1.2 dead code | Bersih, cepat |
| 🟢 P3 | T2.2 WAL assess | Hanya dengan bukti bottleneck + test concurrency |