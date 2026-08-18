# PLAN — v0.2.16 Config Reference & Dashboard Schema Gap

**Status:** Draft (menunggu review user) · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.16 · **Fokus:** dokumentasi setiap variabel config + menutup gap antara `_DEFAULTS` (26 key) dengan dashboard schema (21 field) yang bikin field `context_*` dan `core_*` gak muncul di UI padahal aktif di runtime.

**Nilai:** Barang bagus tanpa dokumentasi = gak kepake. User (dan dev lain) harus tau fungsi tiap variabel config supaya bisa tuning dengan benar. Selain itu ada bottleneck nyata: 7 field yang jalan di runtime tapi **tidak bisa di-set dari dashboard** (cuma bisa lewat edit `config.json` manual), plus 1 mismatch docs-vs-code (`importance_recall_boost` disebut di docs tapi tidak ada di `_DEFAULTS`, cuma env var).

---

## Prinsip

- **Satu sumber kebenaran**: `_DEFAULTS` (di `hermes/config.py`) = daftar config lengkap; `CONFIG_SCHEMA` (di `hermes/config_schema.py`) harus merefleksikan SEMUA key itu, bukan subset.
- **Docs = berasal dari code asli, bukan ngarang**: setiap angka default ditarik dari source (config.py / config_schema.py), diverifikasi, baru ditulis. ANTI-HALU.
- **Jangan lompat versi**: fitur tambahan (expose field baru + docs) = patch bump 0.2.15 → 0.2.16.
- **Laporan → ACC user → commit → push** (urutan WAJIB). Plan ini di-review user di GitHub dulu sebelum eksekusi.

---

## Fase 1 — Dokumentasi config lengkap

> **Akar masalah:** hasil bedah source nemu 3 lapis yang belum nyambung: (1) `Settings` dataclass = 37 env var library-level, (2) `_DEFAULTS` = 26 key provider config, (3) docs hermes-integration.md cuma cover 21 key dan nyebut `importance_recall_boost` yang gak ada di `_DEFAULTS`. User bingung tiap variabel buat apa.

### T1.1 [Docs] Buat `docs/config-reference.md` (SELESAI, teriverifikasi)
- **Apa:** file baru yang mendokumentasikan SETIAP variabel config dari dua sumber otoritatif:
  - Library `Settings` (37 field + env var `LUMINARY_*`, default, arti) — dari `src/luminary_memory/config.py`.
  - Provider `_DEFAULTS` (26 key config.json, default, arti, status in-dashboard) — dari `src/luminary_memory/hermes/config.py`.
- **Status:** ✅ sudah dibuat & diverifikasi, belum di-commit.
- **Catatan:** file mikul `docs/config-reference.md`, belum di-link dari index docs.

### T1.2 [Docs] Tandai gap dashboard di config-reference
- Section "Known gap" udah ada di file: 7 field (`context_*` 3, `core_*` 3, `extract_on_session_end`) tidak tampil di `CONFIG_SCHEMA`. Ini jadi jembatan ke Fase 2.
- Juga catat mismatch `importance_recall_boost` (docs nyebut config key, padahal cuma env var `LUMINARY_IMPORTANCE_RECALL_BOOST`).

---

## Fase 2 — Tutup gap dashboard schema

> **Akar masalah:** `CONFIG_SCHEMA.fields` (config_schema.py, 21 field) tidak mencakup key yang ada di `_DEFAULTS`. Karena `get_config_schema()` di provider.py di-loop dari `CONFIG_SCHEMA`, field yang gak ada di schema otomatis gak muncul di dashboard. User cuma bisa set via edit manual config.json.

### T2.1 [Code] Tambah 7 field gap ke `CONFIG_SCHEMA.fields`
- **Apa:** tambahkan entries baru ke list `fields` di `src/luminary_memory/hermes/config_schema.py`:
  - `context_top_n` (number, "Persistent context: top N")
  - `context_budget` (number, "Persistent context: token budget")
  - `context_min_importance` (number, "Persistent context: min importance")
  - `core_tag` (text, "Core memory tag")
  - `core_top_n` (number, "Core memory: max top N")
  - `core_budget` (number, "Core memory: max chars")
  - `extract_on_session_end` (boolean)
- **Kenapa aman:** `get_config_schema()` di provider.py udah loop `for f in CONFIG_SCHEMA.fields`, jadi tinggal tambah di schema → otomatis ke-expose. `_DEFAULTS` udah punya default buat semua key ini (gak ada key baru yang nyasar ke `save_config` drop-unknown).
- **Test:** `test_api_extended.py` / test provider config round-trip; pastikan `get_config_schema()` return ≥ 28 fields (21 + 7) dan cakupan `_DEFAULTS.keys() - schema.keys()` kosong.

### T2.2 [Code, opsional] Konsistenkan `importance_recall_boost`
- **Opsi A (rekomendasi):** biarkan sebagai env-var only (default 1.0), HAPUS barisnya dari tabel config hermes-integration.md (hindari ngaku key yang gak ada), sisakan di config-reference sebagai env var.
- **Opsi B:** tambah `importance_recall_boost` ke `_DEFAULTS` (config.json key) supaya bisa di-set dashboard, default 1.0.
- **Keputusan:** minta ACC user pilih A atau B.

---

## Fase 3 — Rapiin masuk akun & docs

- Link `config-reference.md` dari `docs/index.md` dan `docs/hermes-integration.md` (section Configuration nunjuk ke config-reference sebagai referensi penuh).
- Update `CHANGELOG.md` entry 0.2.16 (Added: config reference docs + dashboard schema gap closure).
- Bump versi 0.2.15 → 0.2.16 via `scripts/bump-version.sh` (konsisten semua file) — HANYA setelah plan di-ACC.
- Verify: grep sisa `0.2.15` = cuma referensi historis di CHANGELOG/ROADMAP (bukan versi aktif).

---

## Deliverables

| # | Output | File | Status |
|---|--------|------|--------|
| 1 | Config reference lengkap | `docs/config-reference.md` | ✅ dibuat, belum commit |
| 2 | Dashboard schema menutup 7 gap | `config_schema.py` | ⏳ pending ACC |
| 3 | Konsistensi `importance_recall_boost` | `hermes-integration.md` / `_DEFAULTS` | ⏳ pending keputusan A/B |
| 4 | Link docs + CHANGELOG + bump 0.2.16 | index/hermes-integration/CHANGELOG | ⏳ pending ACC |

---

## Verifikasi sebelum klaim selesai

- `python -c "from luminary_memory.hermes.config_schema import CONFIG_SCHEMA; print(len(CONFIG_SCHEMA.fields))"` → 28+ (setelah T2.1).
- `git status` bersih & hanya memuat perubahan yang direncanakan.
- Tidak ada claim "beres" tanpa bukti tool output.