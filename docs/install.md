# Install and remove Luminary Memory

## Release status

**Current registry release: 0.3.4. Managed native setup: UNRELEASED source.**
The proposed 0.3.5 bump is deferred; source versions remain 0.3.4.
The managed native setup described below is the unreleased source contract, not a
claim of completed platform acceptance, registry-download proof, or release
readiness. The published 0.3.4 wheel predates `setup`; its native packages alone
do not provide managed Python setup. Use the advanced 0.3.4 instructions below
for the currently published artifacts.

## Recommended installer (OpenCode, pi, omp)

Install a supported host first. Luminary does not install or replace the host.
The following are the public installer entry points; `main` may differ from
this unreleased checkout. The next registry release requires an audit and a
separately authorized publication; these commands are not evidence it is available.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
```

Linux / macOS (POSIX shell):

```sh
curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
```

The **installer**, not `npm install` or a native package install, provisions a
uv-managed Python 3.12 bridge. No manual Python, pip, venv activation, or
`LUMINARY_PYTHON` export is needed for managed setup. The installed host must
supply its supported runtime; no separate Node installation is needed when it
already does so.

Mutating setup provisions/reuses the selected bridge, validates its version and
capabilities, installs one matching native adapter per selected host, and
records the verified interpreter. Native installation is user-wide by default:

| Host | Native registration for release `X` |
| --- | --- |
| pi | `pi install npm:luminary-memory-pi@X` |
| omp | `omp plugin install luminary-memory-omp@X` |
| OpenCode V2 | `"plugins": ["luminary-memory-opencode@X"]` in user config |

`X` is a coordinated, available Python/npm release, not a literal argument.
OpenCode uses plural **`plugins`**. Native package installation alone never
downloads Python or installs the Python memory engine. A failed native install
is an error, not a reason to silently switch to copied adapters.

### Options and scope

For a downloaded local wrapper, POSIX uses `sh ./install.sh --agents pi`;
PowerShell uses `.\install.ps1 -Agents pi`. Do not append arguments to `iex`.

| POSIX / Python CLI | PowerShell wrapper | Meaning |
| --- | --- | --- |
| `--agents opencode,pi,omp` | `-Agents opencode,pi,omp` | Select hosts; default `auto` detects installed hosts |
| `--all` | `-All` | Select all three supported native hosts |
| `--check` | `-Check` | Report actual bridge health/version and pin drift; no provisioning |
| `--dry-run` | `-DryRun` | Show planned actions; no provisioning or writes |
| `--upgrade` | `-Upgrade` | Explicitly migrate native pins to the target release |
| `--version X` | `-Version X` | Select a supported bridge/plugin release |
| `--uninstall` | `-Uninstall` | Remove selected hosts' Luminary registration and bridge records |
| `--prune` | `-Prune` | Separately remove unreferenced managed bridge environments |
| `--no-config` | `-NoConfig` | Provision bridge without registering host plugins |
| `--project` | `-Project` | Register for the current project, not user-wide |
| `--verbose` | `-Verbose` | Show commands |

The candidate Python CLI also supports `setup --list` for detection only and
`--json` for structured reports. **Check, dry-run, and list never bootstrap uv,
Python, packages, or models, and never change host config, bridge records, or
memory stores.** An absent bridge is reported rather than installed by a check.
The unreleased CLI can be invoked through its interpreter without changing PATH.
For an installed release `X`, use
`~/.luminary/venvs/X/bin/python -m luminary_memory.integrations setup --check`;
on Windows use
`& "$HOME\.luminary\venvs\X\Scripts\python.exe" -m luminary_memory.integrations setup --check`.
Replace `X` with the actual installed version; this is not a claim that a next
release is installed or published.

Native project registration supports pi's `pi install --local` (project trust
required) and an OpenCode project `opencode.json`/`opencode.jsonc` with plural
`plugins`. Run setup from the intended project.

**omp native project installation is unsupported.** Installed 18.20 help
advertises `--scope`, but the upstream plugin-manager contract says npm/git/link
CLI installation remains user-scoped and warns then ignores that option.
Setup therefore refuses native omp `--project` before changes; it must not
silently install user-wide. Use explicit `luminary-memory hook install omp`
for the advanced project-local copied alternative. See the
[upstream scope contract](https://github.com/can1357/oh-my-pi/blob/main/docs/plugin-manager-installer-plumbing.md).
Project registration does not create a second memory authority or
project-owned Python runtime.

### Managed paths and interpreter selection

| Path under the user home | Purpose |
| --- | --- |
| `~/.luminary/bin` | Installer-managed uv tooling |
| `~/.luminary/venvs/<version>` | Isolated versioned bridge environment |
| `~/.luminary/bridge.json` | Schema-1 per-agent `python`, `version`, and `mode` records |
| `~/.luminary/luminary.env` | Existing shared settings, including stable `LUMINARY_MODEL_CACHE` |
| `~/.luminary/models` | Default managed model cache |
| `~/.luminary/memory.db` | Default native memory store; not deleted by uninstall |

Memory tools and the native inspector use the same local interpreter discovery:
explicit **`LUMINARY_PYTHON` > the selected agent's bridge.json record > embedded
interpreter > PATH fallback**. An invalid explicit interpreter fails visibly;
it does not silently select the managed record or PATH. Remove a stale override
from the host/server launch environment if you intend to use managed discovery.
Interpreter discovery and ordinary user turns never install runtimes or packages.

Setup does not pip-install into a discovered system/project environment, edit
persistent PATH or shell profiles, or change memory ownership, saving settings,
or API keys. Existing configuration takes precedence over default cache settings.

## Repeat setup, repair, and upgrade

A normal repeat reuses/repairs the selected compatible release; it is not an
implicit upgrade of existing pins. A present Python executable with a missing,
broken, or wrong-version bridge is not a healthy install.

For migration from 0.3.4, use the **new installer** with explicit upgrade and a
target available release: `sh ./install.sh --agents pi --upgrade --version X`,
or `.\install.ps1 -Agents pi -Upgrade -Version X`. The old 0.3.4 bridge has no
`setup` command. A next release has not been selected or staged.
Migration must update the matching native registration, not just bridge.json.
Installer-owned copied adapters are cut over so they do not double-register;
modified/unrecognized copies are preserved and reported as conflicts.
Unrelated plugins, settings, and memories stay intact. Restart the host.

An explicitly selected older bridge lacking `setup` fails with a diagnostic;
the new installer does not fall back to a copy-adapter compatibility path.

## Advanced: manual current-release installation

These commands use **published 0.3.4**, not unreleased source. Install the Python
bridge into an environment you manage, then set the interpreter in the process
launching the host (the **server** environment for remote OpenCode clients):

```sh
python -m pip install "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
```

PowerShell: `$env:LUMINARY_PYTHON = 'C:\absolute\venv\Scripts\python.exe'`.
The bridge requires Python 3.11+. The native host supplies its supported runtime.

Choose exactly one host registration:

```sh
pi install npm:luminary-memory-pi@0.3.4
omp plugin install luminary-memory-omp@0.3.4
```

For OpenCode V2, merge into existing `~/.config/opencode/opencode.jsonc`:

```json
{"plugins": ["luminary-memory-opencode@0.3.4"]}
```

Restart the host. `pi list` and `omp plugin list` show their registrations.
Keep Python and native package versions matched when upgrading manually.

### Advanced alternative: explicit copied adapter

Instead of native package registration, use the Python package's existing
file-copy installer:

```sh
luminary-memory hook install pi --global
# Or: luminary-memory hook install omp --global
# Or: luminary-memory hook install opencode --global
```

Omit `--global` for its project-local form. This embeds the installing
interpreter. Choose native **or** copied installation, never both. This is an
explicit advanced alternative, not the recommended installer default or a
silent fallback after native failure. Preserve unrelated extensions; inspect
modified Luminary files before any ownership-aware cutover.

## Verify and offline operation

Use the candidate wrapper's `--check` / `-Check`, or its managed interpreter's
`setup --check`, to report version, capability failures, and pin drift without
opening a memory store. No sample output here constitutes acceptance evidence.
Then use a real host session to remember a fact, recall it in the same ownership
scope, open the inspector, restart the host, and confirm persistence.

An already healthy cached runtime can run offline without setup downloads.
Semantic operations still need the configured embedding model in cache; a
missing model may require network access. Do not promise cold offline setup or
offline semantic recall with an uncached model. Optional remote LLM curation is
separate and needs its configured endpoint.

## Uninstall without deleting memory

Use the new wrapper with selected agents: `sh ./install.sh --uninstall --agents pi`
or `.\install.ps1 -Uninstall -Agents pi`. This removes only pi's Luminary host
registration and per-agent bridge record. Other agents, unrelated settings,
still-referenced environments, and memories remain.

Pruning is separate: `sh ./install.sh --prune` or `.\install.ps1 -Prune`
removes only unreferenced managed bridge environments. It does not delete the
memory store or model cache.

For manual 0.3.4 native removal, use `pi remove npm:luminary-memory-pi`,
`omp plugin uninstall luminary-memory-omp`, or remove only Luminary's entry from
OpenCode's `plugins`. Match project scope when removing a project registration.
Remove a manual `LUMINARY_PYTHON` override only if you no longer need it.

Back up `~/.luminary/memory.db` (or your configured store) before any deliberate
memory deletion. Do not recursively delete `~/.luminary` merely to uninstall a
plugin: it contains your memories.

## Hermes is separate

Hermes keeps its existing provider/catalog installation path; see
[Hermes integration](hermes-integration.md) and the [install kit](../hermes/README.md).
It is not one of the Node bridge installer's three hosts and is not routed into
their managed venv. A catalog submission is not a claim that its upstream PR
has merged or deployed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Invalid explicit `LUMINARY_PYTHON` | Fix/remove the override in the host/server environment; no silent fallback occurs |
| Missing/broken bridge or wrong version | Run mutating setup for the selected release; check alone does not repair |
| Plugin pin differs from bridge | Use explicit `--upgrade --version X` for a supported available target |
| Native package install fails | Fix the host package-manager error; no automatic copied-adapter fallback |
| Modified copied adapter conflict | Inspect/preserve changes before explicitly resolving the cutover |
| Older bridge has no `setup` | Use the new installer for migration, or manual 0.3.4 installation |
| Offline model unavailable | Populate the configured model cache online before semantic operations |
