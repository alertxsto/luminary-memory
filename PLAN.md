# PLAN — Luminary Memory Optimalization

**Status:** Active · **Repo:** alertxsto/luminary-memory · **License:** Apache-2.0

---

## Ringkasan

Luminary memory optimal: aturan kritis selalu muncul di context, recall
akurat, store bersih anti-kontradiksi. Dua plan spesifik:

| Plan | Fokus | Status |
|---|---|---|
| [PLAN-persistent-context.md](./PLAN-persistent-context.md) | Persistent memory injection (anti-lupa, LongMemEval-ready) | **Fase 1 done** (persistent context + hook recall), Fase 2 done, Fase 3-4 pending |
| [PLAN-memory-optimal.md](./PLAN-memory-optimal.md) | Recall quality + store hygiene (rule pinning, auto-replace, multi-lingual) | T1-T4, T7-T8, T10-T11 done, sisanya pending |

---

## Roadmap

| Release | Isi |
|---|---|
| **v0.2.11** | Persistent context (Fase 1) + rule pinning + auto-replace + thread-safe sqlite + max_tokens fix |
| **v0.2.12** | Performance: vectorized auto-replace, lean persistent-context scan, batched lifecycle/access/temporal + docs update |
| **v0.2.13+** | Multi-lingual embedding + query expansion + benchmark LongMemEval |

### Sudah rilis
| Versi | Isi |
|---|---|
| v0.2.10 | Smarter recall, max_memories cap, memory fixes |
| v0.2.11 | Persistent context, rule pinning + auto-replace, store hygiene, thread-safe sqlite |
| v0.2.12 | Performance optimizations + docs update |

---

## Status Task (agregat)

| Task | Detail | Status |
|---|---|---|
| T1 | Persistent context (system prompt inject top-N) | ✅ done (5440c66) |
| T2 | Anti-duplikat inject vs recall | ✅ done (5440c66) |
| T3 | Hook recall notification Telegram | ✅ done (5440c66) |
| T4 | Rule pinning (importance >= 0.9 gak ke-prune) | ✅ done (07ad344) |
| T5 | Auto-replace aturan lama (anti-kontradiksi) | ✅ done (07ad344) |
| T6 | Multi-lingual embedding | ⏳ pending |
| T7 | Perf: vectorized auto-replace, lean persistent scan, batched ops | ✅ done (v0.2.12) |
| T8 | Benchmark + docs update | ⏳ pending |

---

*Detail lengkap di [PLAN-persistent-context.md](./PLAN-persistent-context.md) dan [PLAN-memory-optimal.md](./PLAN-memory-optimal.md).*
