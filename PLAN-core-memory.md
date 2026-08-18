# PLAN — Core Memory (DB-backed, auto-loaded every session)

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0
**Target:** v0.2.13 (bagian dari maturation pass)
**Konsep:** Luminary equivalent of Hermes' native `MEMORY.md` / `USER.md` — tapi di **database** (luminary store), bukan file `.md`. Aturan inti selalu auto-load ke system prompt setiap session, sebelum persistent context & recall.

---

## Masalah yang dipecahkan

Di session baru, prompt pertama user bisa gak nyebut aturan format (misal "tolong riset x,y,z"), tapi agent tetap harus TAU aturan "WAJIB markdown table" dari awal. Kalau cuma recall (query-driven), aturan yang gak ke-match gak masuk context → agent ngasih tabel berantakan lagi.

**Solusi:** memory ber-tag `core` (default, configurable) **selalu di-inject ke system prompt setiap session** — kayak MEMORY.md native hermes — dari DB, bukan file. Jadi gak perlu recall match, gak perlu nunggu query.

---

## Desain

### Data
- Memory dengan tag `core` (default) = core memory.
- Store di **luminary SQLite** — bisa di-manage via tools, backup, export/import, tanpa file `.md` terpisah.

### Injection alur (system prompt, setiap session):
```
system prompt
├── # Luminary Memory
│   ├── Core memory (auto-loaded every session):   ← NEW, dari tag "core"
│   │   - <rule 1> (importance tinggi dulu)
│   │   - <rule 2>
│   │   ...
│   ├── Key memories (persistent, top-N by importance):
│   │   - <top penting lain, gak di-tag core>
│   └── Use the luminary_recall / luminary_ingest tools...
```

### Konfigurasi (config provider + env var Settings):
| Setting | Env | Default | Arti |
|---------|-----|---------|------|
| `core_tag` | `LUMINARY_CORE_TAG` | `core` | Tag penanda core memory |
| `core_top_n` | `LUMINARY_CORE_TOP_N` | `12` | Maks memory core yang di-inject |
| `core_budget` | `LUMINARY_CORE_BUDGET` | `8000` | **Maks karakter** core block (lu minta chars configurable) |

### Tools baru (agent bisa patch core sendiri):
| Tool | Fungsi |
|------|--------|
| `luminary_core_add` | Simpan rule/fakta sebagai core (tag `core`, importance di-pin ≥ 0.9) |
| `luminary_core_remove` | Hapus dari core (keep di store, cuma un-pin) |
| `luminary_core_list` | List core memory saat ini |

### Anti-duplikasi
- Core block & persistent context & recall block saling dedup via `_injected_ids` (memory yang udah di core gak muncul lagi di persistent/recall).

### Prune/lifecycle
- Core memories di-pin importance ≥ 0.9 → exempt dari prune & consolidate (rule pinning yang sudah ada).

---

## Fase Implementasi

| Task | Detail | Status |
|------|--------|--------|
| T1 | Config: `core_tag` / `core_top_n` / `core_budget` (Settings + env + provider config) | ✅ done |
| T2 | Backend: `by_tag_top(tag, top_n)` lean query | ✅ done |
| T3 | Provider: `_build_core_memory()` + inject di `system_prompt_block()` sebelum persistent context | ✅ done |
| T4 | Tools: `luminary_core_add` / `luminary_core_remove` / `luminary_core_list` + dispatch | ✅ done |
| T5 | **Testing komprehensif** (core block, tools, dedup, chars budget, env override) | ✅ done — 324 passed, 3 skipped, ruff clean, coverage 93% |
| T6 | Docs + CHANGELOG + ROADMAP + website update | ✅ done |
| T7 | Verify runtime hermes live (system prompt berisi core block) | ✅ done — `hermes/test.sh` smoke pass |
| T8 | Script testing `hermes/test.sh` (jalankan sekali: pytest + ruff + hermes smoke) | ✅ done |
| T9 | Commit + laporan + push | ⏳ |

---

## Testing plan (T5)

### Unit — backend
- [ ] `by_tag_top` hanya return memory ber-tag `core`, urut importance desc
- [ ] `by_tag_top` gak return yang tags-nya mirip (misal "core-x" harus beda dari "core")

### Unit — provider
- [ ] `_build_core_memory()` return block "Core memory (auto-loaded...)" dengan konten memory ber-tag `core`
- [ ] Memory ber-tag `core` masuk `_injected_ids` (anti-dup dengan recall)
- [ ] `core_budget` chars di-respect (total ≤ budget)
- [ ] `core_top_n` di-respect (jumlah ≤ top_n)
- [ ] `system_prompt_block()` include core block SEBELUM persistent context

### Unit — tools
- [ ] `luminary_core_add` → memory baru tag `core`, importance dipin ≥ 0.9
- [ ] `luminary_core_remove` → tag core dihapus, memory tetap di store
- [ ] `luminary_core_remove` id gak ada → error
- [ ] `luminary_core_list` → list core memory
- [ ] get_tool_schemas include 3 tool core

### Integration — hermes runtime
- [ ] Provider initialize → `system_prompt_block()` berisi "Core memory (auto-loaded every session)"
- [ ] Env `LUMINARY_CORE_BUDGET=100` → core block dipotong ke 100 chars
- [ ] Env `LUMINARY_CORE_TAG=identitas` → memory tag `identitas` yang ke-load

### Regression
- [ ] Full test suite 311+ pass (tak ada yang pecah)
- [ ] `ruff check` clean
- [ ] Benchmark quality tidak turun (MRR 1.0)

---

## Definition of Done

| Check | Target |
|-------|--------|
| Core block di system prompt | ✅ selalu, setiap session, gak perlu query |
| Chars budget | ✅ configurable (`core_budget`) |
| Tools patch core | ✅ add/remove/list |
| Anti-duplikat | ✅ core ↔ persistent ↔ recall |
| Test | ✅ semua pass, coverage ≥ 93% |
| Ruff | ✅ clean |
| Runtime hermes | ✅ system prompt berisi core block live |
| Docs | ✅ CHANGELOG + ROADMAP + hermes-integration + SKILL + website |
| Laporan pre-push | ✅ test penuh + verifikasi hermes dilaporkan |

---

## Referensi
- Native Hermes: `MEMORY.md` (auto-loaded, up to `memory_char_limit`), `USER.md`.
- Luminary: persistent context (`context_*`), rule pinning (`rule_importance`).
