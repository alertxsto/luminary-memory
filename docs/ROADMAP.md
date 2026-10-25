# Luminary Interactive UI Roadmap

## Goal

Make Luminary a visible, interactive memory-management system inside supported agent applications—not only hooks and notifications.

The complete product includes compact and full native inspectors, substantial controls organized into tabs, explicit project sharing, and a final Summary tab. One existing memory engine serves every UI. A browser companion and AI explanation are opt-in options, not hidden requirements or substitutes for native functionality.

**Status: planned product work.** This document does not claim the new UI is implemented. Existing tools, provider integration and basic terminal interaction are the starting point, not completion of this goal.

## Product decisions

| Area | Decision |
| --- | --- |
| Coverage | Plan every requested harness through completion, not one integration only. |
| Presentation | Both a compact conversation-side view and a full inspector, adapted to each host. |
| Organization | Related controls live in tabs. Summary is last. |
| Saving | Preserve current configured saving, curation and maintenance. UI installation/navigation changes none of these. |
| Sharing | Explicit project opt-in and configurable per-recipient-agent permissions. Edit/retract access is never implicit. |
| Summary | Deterministic data summary always works; AI explanation is separately requested. |
| Browser | Explicit optional companion, never automatic fallback or completion of a missing native panel. |
| Completion | Packaged working operations and actual host acceptance—not mockups, scaffolding, tool cards or manifest declarations alone. |

## Experience and tabs

### Compact view

Show active project/profile/server/store/agent, effective permissions, owned/shared status, bounded recent activity, actual committed/duplicate/skipped/error outcomes, warnings, and an entry to the full inspector.

The compact view remains useful during conversation. It does not cram every management control into a narrow sidebar.

### Full inspector

| Tab | Complete behavior |
| --- | --- |
| **Memories** | Search/filter/page, inspect ownership/status, create, explicitly correct/version, manage authorized tags/core designation and confirm retraction. Concurrent changes are not silently overwritten. |
| **Activity** | Actual recall, injection, durable save, duplicate, skip and error events with time/source. Distinguish current record snapshots, session episodes and new committed events. |
| **Evidence & History** | Grounding, provenance, validity, claim lineage, conflicts and authorized audit. Raw episodes require explicit expansion, not default bulk exposure. |
| **Relations** | Scoped graph or accessible adjacency view, supporting facts and bounded drill-down. Co-occurrence is not labeled causation or invented reasoning. |
| **Review & Maintenance** | Preview manual correction/conflict/maintenance effects before confirming. No new mandatory queue replaces configured automatic saving. |
| **Sharing & Workspaces** | Explicit project/location bindings, recipients, individual capabilities, revocation and effective access. Context switching clears stale data/actions. |
| **Settings & Diagnostics** | Effective supported values/configuration origin, secret presence, transport/backend/model readiness and separate data-quality diagnostics. No secret values or implicit all-profile changes. |
| **Data Transfer** | Authorized file selection, export coverage, import preview/confirmation, correct ownership/lineage and honest backup limitations. |
| **Summary** | Last tab: deterministic authorized totals, changes and unresolved issues at a visible reference time. Optional AI explanation identifies model, outbound data and available usage information. |

### Interaction requirements

- Every terminal action has a keyboard path; pointer support is verified per host.
- Tabs handle overflow/narrow layouts, resize, theme and Unicode without losing focus or selection.
- Empty, loading, denied, conflict, unavailable, unsupported, cancelled and unknown outcomes remain distinct.
- Closing restores conversation focus. Disable/reload/shutdown disposes listeners, timers, requests and registrations.
- An animation or optimistic card is not proof of a durable commit.
- Stored content, evidence and explanations remain untrusted data; they cannot activate controls or grant permissions.

## Target support matrix

Documented capability is not proof that Luminary's new implementation works on a particular installed release.

| Target | Native end state | Contract and completion gate |
| --- | --- | --- |
| **OpenCode CLI** | Compact session panel, full panel/page, shortcuts and all tabs/actions. | Documented TUI and typed server RPC. Verify actual package exports, host version, remote context and rendering. |
| **OpenCode Desktop** | In-application compact/full inspector. | Arbitrary frontend contribution API remains unverified. Needs supported loader/contributions/context/lifecycle and actual Desktop acceptance. Browser/tool cards do not close this target. |
| **OpenCode Web** | Host-native inspector using authorized connected-server data. | Separately gated on supported frontend API and real acceptance; CLI/Desktop support is not proof. |
| **Hermes Desktop** | Dockable pane, full page, sidebar/settings and native controls. | Documented Desktop SDK; typed provider schema, explicit discovery, profile routing and real installation must pass. |
| **Hermes web dashboard** | Host-native tab plus compact slots. | Separate dashboard SDK and manifest/backend mount, not the Desktop SDK or standalone companion. |
| **Hermes CLI/TUI** | In-host compact/full terminal inspector. | Commands/prompts exist; a general rich rendering contribution seam is not verified. Needs native API/enabler before completion. |
| **pi** | Compact widget/in-chat rendering and full custom TUI. | Documented custom UI. RPC forwards supported interactions, not custom TUI components. Verify exact host/mode behavior. |
| **omp** | Compact widget and custom overlay/full inspector. | Versioned UI declarations support these primitives. Verify lifecycle, parent/child isolation and input separately from pi. |
| **Browser companion** | Complete inspector when explicitly launched. | Optional authenticated local transport/frontend. It is not Hermes dashboard or a substitute for native targets. |

Server plugins, terminal plugins, providers, Hermes Desktop/dashboard and ordinary agent plugins have different entrypoints. A generic single export does not establish all surfaces.

## Architecture and authority

### One engine, multiple native renderers

Reuse `MemoryClient`, existing retrieval/ingestion, SQLite/pgvector and provider/bridge integrations. Add one inspector service for authorized projections and explicit operations. Frontends never open databases or implement another memory engine.

Share operation meanings and state/error contracts, not an incompatible universal widget tree or duplicate host renderer/React runtime.

### Trusted native context

- Resolve user/profile/project/agent/session/host/store on the server from trusted native context.
- Frontend fields and recalled text cannot authorize another user, DB, scope or grant.
- Remote UI uses the remote host's configured backend; failure never silently switches to a local/unbound store.
- Missing identity fails closed. Global/legacy read compatibility is not project sharing.
- Initially support one trusted owner per backend deployment. Arbitrary multi-user hosting needs independently verified principal binding.
- Extensions with owner-level OS access are not sandboxed by memory permissions; do not claim otherwise.

### Explicit project sharing

Stable owner-approved project identity and location bindings are required. Matching folder names, Git URLs or usernames across machines is insufficient. Separate stores are not magically shared: require an explicitly configured common backend/context, not SQLite over unverified network/SSHFS locking.

| Capability | Meaning |
| --- | --- |
| Read | Inspect explicitly authorized resources and their permitted projections. |
| Contribute | Add under the contributing agent's own identity; does not imply read/edit/retract rights or transfer ownership. |
| Edit | Explicit permission to correct/version selected shared resources. |
| Retract | Explicit permission to retract selected shared resources. |

Only verified owner interaction administers grants. Preserve original record IDs/ownership; do not copy facts or remove agent predicates. Recheck rights per operation and inside writes. Policy changes invalidate cursors, cached authorization and pending work.

Revocation blocks subsequent reads, exports, explanations and changes and clears usable inspector content where feasible. It cannot retroactively remove information already delivered.

### Truthful data and mutations

- Browse/refresh/deterministic Summary do not ingest, maintain, call models or mutate access bookkeeping.
- Scope filters precede ranking, aggregation and limits for cards, evidence, history, graphs, counts, audit, transfer and AI payloads.
- Bound page/expansion/graph work and serialized payloads. Context/filter/policy-bound cursors cannot be reused across selections.
- Changes use content revisions and explicit preview/confirmation where appropriate. Stale changes produce conflict, not last-write-wins.
- Successful inspector changes commit memory/claims/index state and durable audit together. Self-committing helpers require genuine transaction-aware integration.
- Audit retains scope after a record disappears. Unverifiable legacy history is not exposed globally.
- Event cursors/replay distinguish durable outcomes from running/cancelled/unknown operations and do not count snapshots as new writes.

### Configuration, secrets and optional AI

Never return raw Settings/config objects, API keys, credential-bearing DSNs or other profiles' secrets. Show presence/status through host-managed secret facilities.

Installing/enabling/opening UI must not select a provider, edit other profiles or change current save enablement, grounding, cadence and session continuity.

Deterministic Summary uses actual authorized data and a visible reference time. AI explanation is read-only, explicitly requested and disclosed: provider/model/destination/outbound fields and known usage/cost availability. Disabled/offline/failed AI does not break normal Summary. It cannot authorize tools, writes or permissions.

## Delivery sequence

Supported integrations may ship incrementally, but partial shipment is not whole-product completion. Missing native SDK targets stay visible and open.

```mermaid
flowchart TD
  M0[M0 Baseline and host contracts] --> M1[M1 Inspector service and reads]
  M1 --> M2[M2 Project permissions]
  M2 --> M3[M3 Atomic changes and audit]
  M3 --> M4[M4 Complete inspector features]
  M4 --> M5[M5 OpenCode CLI, pi and omp]
  M4 --> M6[M6 Hermes Desktop and dashboard]
  M0 --> G[Native Desktop-Web and Hermes terminal enablers]
  G --> M7[M7 Remaining native surfaces]
  M4 --> M7
  M4 --> M8[M8 Optional browser companion]
  M5 --> M9[M9 Whole-product acceptance and release]
  M6 --> M9
  M7 --> M9
  M8 --> M9
```

### M0 — Reconciled baseline and verified host contracts

**State:** planned; prerequisite to implementation.

Main/develop were found diverged and the inspected develop tree lacks the released native npm/integration tooling. Reconcile separately through a reviewed implementation change, preserving both sides. Roadmap publication does not merge branches or application code.

Deliver:
- Reviewed execution baseline and passing existing safety/backend/package gates.
- Exact tested host releases, entrypoints, install/input/headless/remote contracts.
- Bounded upstream-enabler work for native OpenCode Desktop/Web and rich Hermes terminal, started alongside independent supported work.

**Exit:** required APIs verified; missing seams have evidence, ownership and completion conditions. No invented SDK or assumed version range.

### M1 — Shared inspector service and bounded reads

Deliver canonical requests/results, trusted context/store/project binding, filtered/paged non-mutating browse/detail/evidence/history, safe projections, explicit expansion, bounded payloads and context-bound cursors.

**Exit:** SQLite and real pgvector return exactly authorized records across users/projects/agents. Refresh changes neither memory/access bookkeeping nor saving. Missing/forged identity and stale cross-context cursors fail closed; backend failure is not an empty healthy result.

### M2 — Opt-in sharing and permission administration

Deliver explicit per-project recipient rights, effective-permission data, policy revision, scoped grant audit and revocation covering pending requests/caches/events/exports/explanations. Keep IDs and ownership unchanged.

**Exit:** each capability is tested independently. Contribute cannot mutate another agent's record. Foreign IDs/labels/counts/audit/evidence do not leak; revoked queued work cannot deliver stale authorized-looking output.

### M3 — Safe changes, history and actual activity

Deliver confirmed create/correction/tag/core/conflict-resolution/retraction, content revision checks, atomic domain/index/audit transitions, scope-retaining event history and snapshot/live reconnect semantics.

**Exit:** two editors cannot silently overwrite each other; a new conflicting claim also invalidates an older resolution preview. Failed audit leaves no acknowledged partial change. Cancellation/timeout do not become fabricated success or destructive replay. Snapshot rows never count as new saves.

### M4 — Complete feature projections and shared view state

Deliver:
- Real service operations for every semantic tab, with honest availability.
- Bounded graph drill-down/supporting facts and actual recorded recall/injection evidence.
- Manual review/maintenance previews without new automatic-save rules.
- Safe effective configuration, secret presence and separately labeled readiness/data quality.
- File-handle-based export/import preview, confirmed transfer, accurate format coverage and tested lineage mapping.
- Deterministic final Summary and optional read-only AI explanation with disclosure/consent.
- Shared controller with context epochs, stale-result rejection, permissions and cancellation; separate native renderers.

**Exit:** all tab operations use actual authorized data. Failures are not disguised as empty/healthy views. AI-off Summary works offline; no hidden model call, invented reasoning or credential enters a response.

### M5 — OpenCode CLI, pi and omp native inspectors

Deliver:
- OpenCode server typed RPC and separate packaged TUI entrypoint; compact session panel and full inspector.
- Pi compact widget/in-chat view and full custom TUI, honoring its own mode/focus lifecycle.
- Omp widget/overlay/full inspector with session-local state and its own input/mode contracts.
- Commands/shortcuts, all tabs/actions, narrow layouts, themes and keyboard paths.
- Complete wheel/package/copy-install resource graphs without repo-only imports or duplicate obsolete adapters.

**Exit:** installed native hosts demonstrate every tab, confirmed changes, sharing restrictions, Summary, resize, restored focus, reload/removal and session switching. Remote OpenCode uses remote memory. Headless/RPC/JSON/print do not attempt custom terminal UI and retain supported nonvisual operations.

### M6 — Hermes contracts, Desktop and dashboard

Deliver typed provider config and CLI consumer, scoped secrets/context workers, actual storage roundtrip, separate provider/backend/frontend enablement, native Desktop pane/page/sidebar/settings, and independent host dashboard tab/slots/API mounting.

Account for app-level local Desktop installation versus profile-scoped remote backend installation. REST refresh remains sufficient where plugin sockets are unavailable; backend restart requirements are explicit.

**Exit:** real host/SDK tests—not only stubs—prove controls, secrets, profile storage and unchanged saving. Desktop and dashboard both demonstrate all tabs, delayed profile/remote switching, confirmed changes, settings persistence, disabled-backend behavior and teardown.

### M7 — Remaining native extension surfaces

**State:** blocked on verified public rendering seams; enabler work begins at M0.

Deliver:
- Supported native OpenCode Desktop and Web loader/contribution/context/input/lifecycle/package contracts.
- Supported rich Hermes CLI/TUI rendering contract.
- Complete Luminary renderers through those actual released/documented seams.
- Upstream-compatible enabler contributions where needed, not private forks or runtime core/DOM patches.

**Exit:** Desktop, OpenCode Web and Hermes terminal each demonstrate compact/full native operation and equivalent data/action semantics. Commands, server tool cards, another host or a companion browser do not close these rows.

If upstream support is unavailable, keep the exact dependency and target incomplete. Do not silently weaken the goal or promise dates controlled by another project.

### M8 — Explicit optional browser companion

Deliver the complete inspector over the same service/permissions, packaged local frontend, optional dependencies, explicit launch/context selection and authenticated loopback transport with short-lived session setup, same-origin/CSRF checks and safe file handles.

No server/browser starts on import, install, ordinary agent startup or native UI failure. No permissive CORS or browser-selected DB/user identity.

**Exit:** real browser/service/storage prove full operations, expiry/revocation, unauthenticated/cross-origin denial, context isolation, safe stop and unchanged native/retention behavior. Optional means opt-in at runtime, not an unfinished stub or native-support claim.

### M9 — Whole-product acceptance and release

Deliver:
- SQLite/real-pgvector inspection, sharing, concurrency, audit, graph, transfer, settings and Summary coverage.
- Existing Python/native-package safety suites and unchanged real default-embedding-model release gate.
- Actual packed-package/wheel install/update/remove acceptance without source-only imports.
- Exact supported-host/input/remote/headless matrix and secret-free visual/operation evidence.
- Measured large-store responsiveness: bounded work, cancelled stale searches and explicit expensive-diagnostic state; no whole-store scan per keystroke or invented performance claim.
- Accurate registry/catalog metadata, actual publication proof, generic structured release notes and usage/permission documentation.

**Exit:** every required native row and cross-cutting gate passes. Useful incremental releases do not erase unfinished native targets.

## Acceptance matrix

| Scenario | Required outcome |
| --- | --- |
| Two users/projects/agents plus global/partial rows | Authorized records/aggregates only; guessed IDs and forged scope denied. |
| Share/contribute/edit/retract/revoke | Independent rights, unchanged ownership and revoked pending work denied. |
| Concurrent writes or audit/index failure | No silent overwrite, broken lineage or acknowledged partial commit. |
| Context switch during requests | No old content/actions enter a new profile/project/server. |
| Refresh/reconnect/replay | No extra writes/AI calls, duplicate activity counts or hidden gaps. |
| Empty/backend failure/timeout/cancel | Distinct honest states, no false saved status or destructive replay. |
| Saving on or off | UI leaves configured behavior and unrelated profiles untouched. |
| AI off/offline/revoked snapshot | Deterministic Summary works; no automatic/unauthorized outbound call. |
| Transfer with foreign IDs/version chains | Authorized preview/confirmation, correct or explicitly rejected lineage, no fake full-backup claim. |
| Install/update/remove/reload | Complete resources, no duplicate hooks or leaked listeners/dependencies. |
| Keyboard/supported pointer/narrow/theme | Complete usable workflows and restored conversation focus per actual host. |

## Dependencies and risks

| Dependency/risk | Required response |
| --- | --- |
| Main/develop divergence | Reconcile separately before implementation; roadmap-only publication preserves existing code. |
| Missing native SDK | Named upstream enabler and evidence; no invented API/browser substitution. |
| Hermes discovery differences | Verify every entrypoint, enablement and API mount with the real host. |
| Scope-less old audit/incomplete export lineage | Never infer authority; label limitations and test verifiable migration/roundtrip. |
| Secrets, remote context and principal binding | Use trusted host authority/secret routes; no unproved multi-user safety claim. |
| Self-committing helpers/concurrent writers | Genuine transactional revision/audit handling, not a cosmetic wrapper. |
| Large graphs/stores or noisy feeds | Bound/page/cancel work and measure actual performance. |
| Registry/catalog/release authorization | Verify independently of builds; no hardcoded future version/date or false website visibility. |

## Progress and final definition of done

Use **planned**, **in progress**, **blocked**, **verified** and **released** distinctly. Verified requires observable behavior; released additionally requires an installable artifact and truthful support documentation.

Complete means:
- Every semantic tab backed by real authorized operations.
- Compact/full native acceptance on every requested surface.
- OpenCode Desktop/Web and Hermes terminal native gates genuinely closed, not hidden by fallback.
- Browser and AI options usable when chosen and inert otherwise.
- Existing saving preserved.
- Sharing, safe changes, scoped history, secrets and honest failures proved on both backends.
- Packaging, lifecycle, input/accessibility and publication checks complete.

## References

- [Released native integration baseline](https://github.com/alertxsto/luminary-memory/blob/main/docs/agent-integrations.md)
- [API](api.md), [architecture](architecture.md), [backends](backends.md), [configuration](config-reference.md)
- [OpenCode CLI UI](https://opencode.ai/v2/docs/build/plugins/cli/) and [typed RPC](https://opencode.ai/v2/docs/build/plugins/rpc/)
- [Inspected published OpenCode SDK](https://unpkg.com/@opencode/plugin@2.1.4/package.json)
- [Hermes Desktop SDK](https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk), [dashboard SDK](https://hermes-agent.nousresearch.com/docs/user-guide/features/extending-the-dashboard), [memory-provider contract](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin)
- [pi extensions](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md) and [terminal UI](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/tui.md)
- [Inspected versioned omp contract](https://github.com/can1357/oh-my-pi/blob/v18.12.6/packages/coding-agent/src/extensibility/extensions/types.ts)

Versioned links are evidence references, not permanent compatibility floors or future release numbers. Revalidate actual supported releases before implementation/publication.

## Conclusion

Deliver one trustworthy memory-management experience with native visual integrations, explicit user control and consistent semantics. Browser and AI enrich it only when requested. The goal is complete when native targets, real operations, permissions and packaged lifecycle work—not when hooks merely display more text.
