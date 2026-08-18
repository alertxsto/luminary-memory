# PLAN — Persistent Memory Context (Anti-Lupa, LongMemEval-Ready)

**Status:** Active · **Target release:** v0.2.11 (Fase 1-2), v0.2.12 (Fase 3-4)
**Repo:** alertxsto/luminary-memory · **License:** Apache-2.0

---

## 1. Problem (dibuktikan, bukan tebakan)

Agent (Asep) lupa aturan format tabel **3x berturut-turut** dalam satu sesi,
padahal aturan sudah ada di store. Ini bukan kelalaian sesaat, ini **bug
fundamental di arsitektur memory injection**.

### Bukti
| Kejadian | Aturan yang dilanggar | Kenapa bisa lupa |
|---|---|---|
| Kirim plan pakai tabel acak | "WAJIB markdown table" | Recall query "laporan status" gak match aturan |
| Kirim laporan tanpa tabel | "WAJIB markdown table" | Aturan tenggelam di RANK 15/18 recall |
| Kirim tabel lagi | "WAJIB markdown table" | System prompt statis, aturan gak pernah di context |

### Root cause (analisa kode, bukan asumsi)
1. `system_prompt_block()` cuma nulis teks statis: "Relevant memories are
   automatically injected into context". **TANPA isi memory apa pun.**
2. Memory cuma masuk context lewat `prefetch()` yang **dependen query**.
   Query "laporan status perubahan fitur" semantic-nya cocok ke 20 memory
   kerjaan lain, aturan format tabel tenggelam.
3. Tidak ada mekanisme "memory penting selalu di context". Memory yang gak
   ke-recall = memory yang gak pernah dilihat agent.
4. Kontradiksi aturan di store ([135] "JANGAN tabel" vs [168] "WAJIB table")
   bikin agent bingung dua arah.

### Konteks window (kenapa ini layak)
| Item | Nilai |
|---|---|
| Model | deepseek-v4-flash |
| Window | 1,000,000 token |
| In use | ~445K (45%) |
| Memory saat ini | ~3K token (0.3%) |
| Headroom | ~554K (55%) |

Inject top-8 memories (~2K token) = **0.2% dari window**. Aman.

---

## 2. Solusi: Persistent Memory Context (Hybrid)

Memory relevan harus **selalu di context window**, bukan cuma pas query match.

```
┌─────────────────────────── SYSTEM PROMPT ───────────────────────────┐
│  # Luminary Memory                                                   │
│  Key memories (top-N by importance, anti-duplikat):                 │
│  - [aturan format tabel]         ← SELALU ada, gak perlu query      │
│  - [aturan em dash]                                                 │
│  - [fakta kritis penting]                                           │
└──────────────────────────────────────────────────────────────────────┘
┌─────────────────────────── PER TURN ────────────────────────────────┐
│  prefetch(query) → recall spesifik → SKIP yang udah di system prompt│
│  (anti-duplikat: memory gak muncul 2x di context)                    │
└──────────────────────────────────────────────────────────────────────┘
```

### Kenapa hybrid (bukan cuma satu)
| Opsi | Cara | Verdict |
|---|---|---|
| A. Persistent only | System prompt inject top-N by importance | Aturan selalu ada, tapi konteks spesifik query hilang |
| B. **Hybrid (dipilih)** | System prompt top-N + prefetch query recall (dedup) | Aturan selalu ada + konteks spesifik tetap jalan |
| C. Window buffer | Rolling window memory terakhir | Complex, gak perlu |

---

## 3. Fase Implementasi

### Fase 1: Persistent Rule Injection (PRIORITAS)

| Task | Detail | Status |
|---|---|---|
| T1.1 | `system_prompt_block()` inject top-N memories by importance | ✅ done |
| T1.2 | Rules (importance >= 0.9) selalu included | ✅ done |
| T1.3 | Config: `context_top_n` (8), `context_budget` (2000), `context_min_importance` (0.0) | ✅ done |
| T1.4 | Token cap per budget | ✅ done |
| T1.5 | Anti-duplikat: `_injected_ids` di-track, prefetch skip | ✅ done |
| T1.6 | Test: inject + recall gak ada konten dobel | ⏳ test |

### Fase 2: Rule Pinning & Anti-Kontradiksi

| Task | Detail | Status |
|---|---|---|
| T2.1 | Rule pinning: memory importance >= 0.9 di-pin (gak ke-prune/consolidate) | ⏳ |
| T2.2 | Auto-replace: aturan baru semantic-similar (>= 0.85) REPLACE yang lama | ⏳ |
| T2.3 | Enricher deteksi aturan (configurable keywords) -> importance 0.9 | ✅ done |

### Fase 3: Recall Quality

| Task | Detail | Status |
|---|---|---|
| T3.1 | Multi-lingual embedding (opsional, `LUMINARY_EMBEDDING_MODEL`) | ⏳ |
| T3.2 | Query expansion: topik yang ada aturannya -> inject aturan duluan | ⏳ |

### Fase 4: Verification & Benchmark

| Task | Detail | Status |
|---|---|---|
| T4.1 | Test suite lengkap, coverage >= 90% | ⏳ |
| T4.2 | Simulasi LongMemEval: fakta lama tetap ke-recall setelah N turn | ⏳ |
| T4.3 | Benchmark: context overhead vs recall accuracy | ⏳ |
| T4.4 | Docs + skill + CHANGELOG + ROADMAP update | ⏳ |

---

## 4. Roadmap

| Release | Isi | DoD |
|---|---|---|
| **v0.2.11** | Fase 1 (T1.1-T1.6) + Fase 2 (T2.1-T2.3) | Aturan selalu di context, lifecycle gak hapus pinned, anti-kontradiksi |
| **v0.2.12** | Fase 3 (T3.1-T3.2) + Fase 4 (T4.1-T4.4) | Recall Indo-English lebih akurat, benchmark LongMemEval |

### Sudah dirilis (sebelum plan ini)
| Versi | Isi |
|---|---|
| v0.2.10 | Smarter recall (weighted fusion, query expansion), max_memories cap, memory fixes |
| v0.2.11 (WIP) | Adaptive cliff, temporal fallback, importance boost, rule auto-importance, thread-safe sqlite, max_tokens fix |

---

## 5. Definition of Done

| Check | Target |
|---|---|
| System prompt berisi aturan kritis | top-8 by importance, selalu |
| Anti-duplikat inject vs recall | 0 konten dobel di context |
| Lifecycle gak hapus pinned rules | ✅ |
| Aturan baru replace yang lama | anti-kontradiksi |
| Context overhead | <= 2000 token (0.2% dari 1M) |
| Test + coverage | 100% pass, >= 90% |
| CI | hijau |
| Docs | konsisten versi |

---

## 6. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Context overhead nambah | Budget cap 2000 token, tunable |
| System prompt makin panjang | Top-N 8, cache per session |
| Pinned rules numpuk | max_memories cap tetap jalan |
| Multi-lingual embedding lebih berat | Opsional, `LUMINARY_EMBEDDING_MODEL` |

---

*Changelog: [CHANGELOG.md](./CHANGELOG.md) · Roadmap: [ROADMAP.md](./ROADMAP.md) · Plan multi-user: [docs/PLAN-multi-user.md](./docs/PLAN-multi-user.md)*
