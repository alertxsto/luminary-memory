# PLAN — v0.2.15 Core Memory Integrity & 100% Verified Tests

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.15 · **Fokus:** memastikan **core memory** (DB-backed, tag `core`) punya sumber konten yang TEPAT — hanya dari DB (tag `core`), TIDAK PERNAH dari `_injected_ids`/recall — plus test yang 100% verified (bukan asumsi).

> **Latar belakang (dari review user):** ada salah paham bahwa core memory diisi dari `_injected_ids`. Yang benar: `_injected_ids` adalah **tracker anti-duplikasi**, bukan sumber isi. Core dibangun dari `by_tag_top(tag="core")` di DB. Plan ini mengunci invariant itu dengan test eksplisit, dan memperkuat integrity test yang ada.

> **Catatan penting — "importance hidup" vs "confidence score":** Untuk memori yang sering dipakai agar naik ke persistent context, sistem TIDAK perlu nilai confidence/conf terpisah. Yang dibutuhkan adalah **importance yang up-to-date**:
> - Persistent context (`_build_persistent_context`) memilih dari `top_by_importance(top_n, min_importance)` — sort `importance DESC, access_count DESC`, filter `importance >= context_min_importance` (default **0.0** = semua lolos).
> - Jadi memori yang sering di-recall harus **naik importance-nya di DB** supaya otomatis naik ranking ke top-N persistent context.
> - Masalah sekarang: `touch_memories` (saat recall) hanya menaikkan `access_count`/`last_accessed_at`, **TIDAK meng-update importance**. Jadi memori yang sering dipakai gak naik ke persistent context sampai lifecycle jalan.
> - **T1.1 plan adaptive-memory (v0.2.15)** menutup ini: re-estimate importance saat recall access. Ini **tidak menambah conf score** — cukup memakai `estimate_importance` yang sudah ada (access + recency + centrality), lossless, dan membuat `top_by_importance` otomatis mengangkat memori yang sering dipakai.

---

## Hubungan dengan PLAN adaptive-memory

Plan ini (core memory integrity) SALING MELENGKAPI dengan `PLAN-v0.2.15-adaptive-memory-intelligence.md`:

| Plan | Fokus | Interaksi |
|------|-------|-----------|
| **Core integrity (ini)** | Sumber core = DB tag `core`; anti-dup; test 100% verified | Core TETAP di-pin (importance ≥ 0.9). Importance adaptif TIDAK menurunkan core — invariant yang sama dikunci |
| **Adaptive memory** | Importance hidup saat recall → yang sering dipakai naik, yang jarang turun → prune efektif | Penting untuk NON-core memori; core di-pin tidak ikut turun |

Keduanya berbagi invariant yang sama: **core memory tidak boleh terpengaruh oleh importance adaptif** (selalu pin, selalu muncul, sumber DB tag `core`).

---

## Prinsip

- **Kebenaran dulu:** setiap claim di-trace ke kode + test yang membuktikannya. Tidak ada test "ikut backend" yang hanya memantulkan implementasi — test harus **memverifikasi invariant** (sumber = DB tag `core`).
- Lossless: tidak mengubah perilaku recall/lifecycle tanpa perlu.
- Urutan WAJIB: **Laporan → ACC user → commit → push.**

---

## Pemahaman yang DIKUCI (invariant)

1. **Sumber core = DB, tag `core`** — `_build_core_memory()` memanggil `backend.by_tag_top(tag, top_n)`. Bukan dari hasil recall, bukan dari `_injected_ids`.
2. **`_injected_ids` = tracker anti-dup** — di-isi UNION dari core + persistent context; recall block SKIP id di dalamnya supaya tidak dobel. Bukan sumber konten.
3. **Core selalu ada di context** — `system_prompt_block()` (session-start) DAN `prefetch()` (setiap turn) memanggil `_build_core_memory()`. Jadi aturan inti tidak hilang di tengah session.
4. **Core di-pin** — `luminary_core_add` set importance ≥ 0.9 → kebal dari prune/consolidate. Importance adaptif (plan lain) TIDAK menurunkan core di bawah 0.9.
5. **Budget & top_n** — `core_budget` (chars), `core_top_n`, `core_tag` (semua env-configurable).
6. **Inject persistent context = f(importance), bukan conf score** — untuk memori sering dipakai naik ke context, `importance` di DB harus up-to-date (re-estimate saat recall access), supaya `top_by_importance` mengangkatnya. Tidak ada "confidence value" terpisah yang dibutuhkan.

---

## Fase 1 — Verifikasi & Fix (jika ada gap)

### T1.1 Audit sumber konten core (trace ke kode)
- [ ] Trace `_build_core_memory` → `by_tag_top(tag, top_n)` → SQL `tags LIKE` → DB.
- [ ] Konfirmasi TIDAK ada jalur di mana `_injected_ids` atau hasil recall menjadi input isi core.
- **Keluaran:** catatan verifikasi di plan (file:line). Jika ditemukan jalur bocor → fix.

### T1.2 Guard defensif (hardening, lossless)
- [ ] Di `_build_core_memory`, pastikan tidak ada kemungkinan core memuat memori yang bukan tag `core` (mis. fallback `list(limit=0)` path sudah memfilter `tag in (m.tags or [])` — verifikasi, jangan ubah).
- [ ] Verifikasi `_injected_ids` reset per turn di `prefetch()` (line 734) — tidak menumpuk antar turn.

---

## Fase 2 — Test 100% Verified (invariant-based)

> Semua test backend asli (SQLiteBackend via provider `_client`), bukan stub. Nama test harus menyatakan **invariant**, bukan implementasi.

### T2.1 Core sumbernya dari DB (bukan recall/injected)
- [ ] **Test:** buat provider, `_seed_core` 2 memori tag `core`. Panggil `_build_core_memory()`. Assert block berisi KEDUA memori tag `core`.
- [ ] **Test (kunci):** buat 1 memori tag `core` + 1 memori tag LAIN (mis. `biasa`) yang **sangat relevan & high-importance**. `_build_core_memory()` harus berisi HANYA yang tag `core`, TIDAK yang tag `biasa` — membuktikan core tidak diisi dari ranking/recall/persistent.
- [ ] **Test:** kosongkan `_injected_ids`, panggil `_build_core_memory()`, assert block tetap berisi memori core — membuktikan isi TIDAK bergantung pada injected ids.

### T2.2 Anti-duplikasi 3 arah (core ↔ persistent ↔ recall)
- [ ] **Test:** core berisi X, persistent context juga punya X (high importance, tag biasa) → `prefetch()` menghasilkan X SEKALI (dihitung kemunculan string di seluruh block).
- [ ] **Test:** recall mengembalikan X juga → `_format_recall_block` skip X → X tetap sekali di context.
- [ ] **Test:** `_injected_ids` berisi UNION core+persistent ids; recall block tidak memuat id yang ada di set itu.

### T2.3 Core budget & top_n (boundary)
- [ ] **Test:** `core_budget=100`, 1 memori core 150 chars → block kosong ATAU terpotong ≤ budget (verifikasi behavior yang benar: break sebelum over-budget).
- [ ] **Test:** `core_top_n=3`, 5 memori core → tepat 3 muncul.
- [ ] **Test:** env `LUMINARY_CORE_BUDGET=100` mengubah settings (Settings unit test).

### T2.4 Tools core (add/remove/list) — integrity
- [ ] **Test:** `luminary_core_add` → store + tag `core` + importance ≥ 0.9 (pinned) → masuk `_injected_ids` saat `_build_core_memory`.
- [ ] **Test:** `luminary_core_remove` → tag `core` dihapus, memori TETAP di store → tidak muncul lagi di core block.
- [ ] **Test:** `luminary_core_list` → hanya memori tag `core`.

### T2.5 Lifecycle safety core
- [ ] **Test:** core memory (importance ≥ 0.9) TIDAK di-prune oleh `run_lifecycle()` walau `min_importance` rendah.
- [ ] **Test:** core TIDAK di-consolidate (dihapus sebagai duplikat) — pinned safe.

---

## Fase 3 — Regression & Verifikasi

- [ ] T3.1 Full suite (`pytest tests/`) — semua pass.
- [ ] T3.2 `ruff check src tests` — clean.
- [ ] T3.3 `hermes/test.sh` — smoke OK (core add/list/remove, prefetch, anti-dup, system prompt).
- [ ] T3.4 Live verifikasi: provider initialize + `system_prompt_block()` berisi core block; `prefetch()` memuat core.

---

## Fase 4 — Docs & Release

- [ ] T4.1 `docs/hermes-integration.md` — bagian Core memory: pertegas "sumber = DB tag `core`", `_injected_ids` = anti-dup tracker (bukan sumber), injected di system prompt + prefetch.
- [ ] T4.2 `PLAN-core-memory.md` — update status + invariant yang dikunci.
- [ ] T4.3 `CHANGELOG.md` + `ROADMAP.md` — v0.2.15.
- [ ] T4.4 Version bump `__init__.py` + `pyproject.toml` → 0.2.15.
- [ ] T4.5 `PLAN-v0.2.15-core-memory-integrity.md` status.

---

## Definition of Done

| Check | Target |
|-------|--------|
| Sumber core | DB tag `core` saja — dibuktikan test (T2.1) |
| `_injected_ids` | tracker anti-dup saja — bukan sumber (test T2.1-3) |
| Anti-duplikasi | core/persistent/recall → sekali di context (test T2.2) |
| Budget/top_n/tag | boundary test (T2.3) |
| Tools core | add/remove/list integrity (T2.4) |
| Lifecycle | core pinned aman (T2.5) |
| Full suite | 100% pass, coverage ≥ 93%, ruff clean |
| Hermes runtime | smoke OK |
| Docs | hermes-integration + PLAN-core-memory konsisten |
| Proses | Laporan → ACC → commit → push |

---

## Task prioritization

| Priority | Task | Alasan |
|----------|------|--------|
| 🔴 P1 | T2.1 Core sumber DB (bukan recall/injected) | Invariant inti yang dikunci |
| 🔴 P1 | T2.2 Anti-duplikasi 3 arah | Jamin tidak dobel di context |
| 🔴 P1 | T2.4 Tools core integrity | Add/remove/list tidak merusak invariant |
| 🟡 P2 | T2.3 Budget/top_n boundary | Safety context window |
| 🟡 P2 | T2.5 Lifecycle safety | Pinned core tidak hilang |
| 🟡 P2 | T3.x Regression + verifikasi | Jaring pengaman |
| 🟢 P3 | T4.x Docs & release | Konsistensi |

---

## Referensi

- `src/luminary_memory/hermes/provider.py`:
  - `_build_core_memory()` (line ~597) — sumber `by_tag_top(tag)`.
  - `prefetch()` (line ~709) — reset `_injected_ids` per turn, merge core+ctx+recall.
  - `_format_recall_block()` (line ~650) — skip injected ids.
  - `_handle_core_add/remove/list` (line ~944-996).
- `src/luminary_memory/backends/sqlite.py` — `by_tag_top` (tag LIKE filter, lean scan).
- `tests/hermes/test_core_memory.py` — 12 test existing.
