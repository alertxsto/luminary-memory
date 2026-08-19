# PLAN — v0.2.17 Fix Enricher Baca Response Cline Gateway (`data` envelope)

**Status:** Code + test SELESAI, menunggu ACC user untuk bump/push/release
**Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.17 (patch) · **Branches:** fix di `develop` → merge `main` (release-only)

**Nilai:** Enricher LLM gagal mengekstrak summary dari semua response karena gateway Cline
(`api.cline.bot` → `cline-pass/deepseek-v4-flash`) membungkus shape OpenAI-compatible di bawah
kunci `data`, sedangkan `_call_llm` cuma membaca `payload["choices"]` di level akar. Akibat: setiap
turn di-skip (`retain skipped: no curated summary`), memori nyaris tidak pernah tersimpan, dan hook
`luminary-activity` tidak punya apa-apa untuk di-post ke Telegram. Ini bug satu baris yang selama ini
membuat LLM curation mati diam-diam.

---

## Akar Masalah (verified)

| Lapisan | Status |
|---------|--------|
| Endpoint `api.cline.bot/v1/chat/completions` | ✅ HTTP 200, JSON valid |
| Response shape | ❌ dibungkus `{"data": {"choices": [...]}}` |
| `_call_llm` (ingest/llm.py:126) | ❌ baca `payload.get("choices")` level akar → `""` |
| `enrich()` | summary None → `_do_retain` skip → storage mandek |

Live trace singkat saat debugging: `_call_llm` balik `''`, `_parse_enrichment_payload({})` → `{}`,
`worth_saving=True` + `summary=None` → provider log `retain skipped (LLM: no curated summary)`.

---

## Perubahan

### [Code] `src/luminary_memory/ingest/llm.py` — unwrap `data` envelope (SELESAI, teriverifikasi)

Akhir `_call_llm` (`with ... urlopen` blok) diubah: setelah `json.loads`, jika `payload` itu dict dan
memiliki kunci `data` (dict), `payload = payload["data"]` dulu. Baru `choices = payload.get("choices")`.

- Backward compatible: endpoint yang TIDAK bungkus `data` tetap jalan (baca `choices` dari akar).
- Ganti respons untuk unwrap ada di baris komentar singkat biar jelas kenapa reshape.
- Lint: `status ok`.

### [Test] `tests/test_llm_enricher.py` — 2 test regresi (SELESAI, teriverifikasi)

| Test | Menguji |
|------|---------|
| `test_unwrap_data_envelope` | Response berbungkus `{"data": {"choices": [...]}}` → summary/entities terbaca |
| `test_unwrap_data_envelope_plain_shape` | Response akar biasa (tanpa `data`) tetap terbaca (backward compat) |

Keduanya pakai pola mock `urllib.request.urlopen` yang sudah ada di file ini (konsisten).

### [Docs] CHANGELOG + bump versi (PENDING, tunggu ACC)

- `CHANGELOG.md`: entry v0.2.17 (Fixed: enricher tidak baca response gateway yang bungkus `data`).
- Bump 0.2.16 → 0.2.17 via `scripts/bump-version.sh` (konsisten semua file, JANGAN lompat).
- Verify: grep sisa `0.2.16` = cuma referensi historis di CHANGELOG/ROADMAP.

---

## Hasil Pengujian (verified, tool output)

| Check | Hasil |
|-------|-------|
| Live enrich (response cline asli) | summary = "Tim sudah pindah target deploy ke production cluster, tidak lagi staging." |
| Test baru (`test_llm_enricher.py`) | 7 passed (5 lama + 2 baru) |
| Test suite penuh (`tests/`) | 375 passed, 3 skipped, 0 failed |

---

## Verifikasi sebelum klaim selesai

- `python -m pytest tests/` → 375 passed, 3 skipped (bukan ngarang, tool output).
- Live call enricher via config Hermes menghasilkan summary non-kosong dari `api.cline.bot`.
- Tidak ada claim "beres" tanpa bukti tool output.
- WIP hygiene: commit fix + test di `develop` sebelum bump/push.

---

## Deliverables

| # | Output | File | Status |
|---|--------|------|--------|
| 1 | Fix unwrap `data` envelope | `src/luminary_memory/ingest/llm.py` | ✅ selesai |
| 2 | Test regresi (2 test) | `tests/test_llm_enricher.py` | ✅ selesai |
| 3 | Changelog v0.2.17 | `CHANGELOG.md` | ⏳ pending ACC |
| 4 | Bump 0.2.16 → 0.2.17 | `scripts/bump-version.sh` | ⏳ pending ACC |