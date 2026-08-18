# PLAN — Luminary Memory Optimalization

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0

---

## Ringkasan

Luminary memory optimal: aturan kritis selalu muncul di context, recall
akurat, store bersih anti-kontradiksi. Dua plan spesifik:

| Plan | Fokus | Status |
|---|---|---|
| [PLAN-persistent-context.md](./PLAN-persistent-context.md) | Persistent memory injection (anti-lupa, LongMemEval-ready) | **Fase 1 done** (persistent context + hook recall), Fase 2-4 pending |
| [PLAN-memory-optimal.md](./PLAN-memory-optimal.md) | Recall quality + store hygiene (rule pinning, auto-replace, multi-lingual) | T1-T3 done, sisanya pending |

---

## Roadmap

| Release | Isi |
|---|---|
| **v0.2.11** | Persistent context (Fase 1) + rule pinning + auto-replace + thread-safe sqlite + max_tokens fix |
| **v0.2.12** | Multi-lingual embedding + query expansion + benchmark LongMemEval + docs |

### Sudah rilis
| Versi | Isi |
|---|---|
| v0.2.10 | Smarter recall, max_memories cap, memory fixes |
| v0.2.11 (WIP) | Adaptive cliff, temporal fallback, importance boost, persistent context, hook recall |

---

## Status Task (agregat)

| Task | Detail | Status |
|---|---|---|
| T1 | Persistent context (system prompt inject top-N) | ✅ done (5440c66) |
| T2 | Anti-duplikat inject vs recall | ✅ done (5440c66) |
| T3 | Hook recall notification Telegram | ✅ done (5440c66) |
| T4 | Rule pinning (importance >= 0.9 gak ke-prune) | ⏳ pending |
| T5 | Auto-replace aturan lama | ⏳ pending |
| T6 | Multi-lingual embedding | ⏳ pending |
| T7 | Benchmark LongMemEval + docs | ⏳ pending |

---

*Detail lengkap di [PLAN-persistent-context.md](./PLAN-persistent-context.md) dan [PLAN-memory-optimal.md](./PLAN-memory-optimal.md).*
