# Install and remove Luminary Memory

This guide covers the one-command installer, manual installation for each
supported host, verification, updates, and complete removal.

## Requirements

| Path | Needs |
| --- | --- |
| One-command install | nothing beyond the host; `uv` provisions Python |
| Manual install | Python 3.11+; Node 22+ only for the npm packages |

The bridge is a Python process. The npm packages are thin adapters that spawn
it; they do not contain the memory engine.

## One-command install

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
```

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.sh | sh
```

The installer is non-interactive and idempotent. It:

1. installs `uv` under `~/.luminary/bin` when needed;
2. creates `~/.luminary/venvs/<version>` with Python 3.12;
3. installs the version-matched `luminary-memory` bridge;
4. writes `~/.luminary/bridge.json` (interpreter per agent);
5. configures every detected agent;
6. writes `~/.luminary/luminary.env` with a stable `LUMINARY_MODEL_CACHE`;
7. verifies the bridge with `action:"version"` and a `core` load.

It never modifies `PATH` or a shell profile.

### Options

| Option | Meaning |
| --- | --- |
| `--agents opencode,pi,omp` | configure only these agents |
| `--all` | configure every supported agent |
| `--check` | report versions and drift, change nothing |
| `--upgrade` | move plugin pins to the target version |
| `--uninstall` | remove Luminary entries |
| `--prune` | remove unreferenced bridge venvs |
| `--version X` | pin the bridge version |
| `--no-config` | install the bridge only |
| `--project` | target project-local config |
| `--dry-run` | show actions without writing |
| `--verbose` | print every command |

The same logic is available from the Python CLI:

```bash
luminary-memory setup --agents auto
luminary-memory setup --check
luminary-memory setup --list
luminary-memory setup --agents pi --version 0.3.4
```

`setup` reads each agent's plugin pin and installs the matching bridge, so a
plugin and its bridge cannot drift apart.

## Manual install

### OpenCode V2

```bash
python -m pip install --upgrade "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
```

Add the plugin to `~/.config/opencode/opencode.jsonc`:

```json
{
  "plugins": ["luminary-memory-opencode@0.3.4"]
}
```

Restart OpenCode. On Windows, set the interpreter in the OpenCode server's
environment:

```powershell
$env:LUMINARY_PYTHON = 'C:\absolute\path\to\venv\Scripts\python.exe'
```

### pi

```bash
python -m pip install --upgrade "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
pi install npm:luminary-memory-pi@0.3.4
```

Restart pi. `pi list` shows the configured package.

### omp

```bash
python -m pip install --upgrade "luminary-memory==0.3.4"
export LUMINARY_PYTHON=/absolute/path/to/venv/bin/python
omp plugin install luminary-memory-omp@0.3.4
```

Restart omp. `omp plugin list` shows the configured plugin.

### Copy install (no npm)

The Python package can install the compiled adapter directly:

```bash
luminary-memory hook install opencode --global   # or pi / omp
```

This writes the adapter under the host's config directory and embeds the
current interpreter. Choose the npm package **or** the copied adapter, never
both.

## Verify

```bash
luminary-memory setup --check
```

Expected output:

```
opencode  ok        bridge=0.3.4    pin=0.3.4
pi        ok        bridge=0.3.4    pin=0.3.4
```

Probe the bridge directly:

```bash
printf '{"agent":"opencode","action":"version"}' |
  "$LUMINARY_PYTHON" -m luminary_memory.integrations bridge
```

A healthy bridge returns `{"ok": true, "version": "0.3.4", ...}`.

## Update

Run the installer again, or:

```bash
luminary-memory setup --upgrade
```

`--upgrade` moves each agent's plugin pin to the target version and installs
the matching bridge. To pin a specific version, add `--version X`.

## Remove Luminary

Removal is deliberately separate from the memory store. The steps below remove
the plugin, the bridge, and the interpreter. `~/.luminary/memory.db` is only
deleted if you delete it yourself.

### 1. Remove the host plugin

OpenCode:

```bash
opencode plugin remove luminary-memory-opencode@0.3.4
```

Or remove the `luminary-memory-opencode@...` entry from `plugins` in
`~/.config/opencode/opencode.jsonc`.

pi:

```bash
pi remove npm:luminary-memory-pi
```

omp:

```bash
omp plugin uninstall luminary-memory-omp
```

### 2. Remove copied adapters

Only if you used `luminary-memory hook install` instead of the npm package:

```bash
rm -rf ~/.config/opencode/plugins/luminary-memory
rm -rf ~/.pi/agent/extensions/luminary-memory
rm -rf ~/.omp/agent/extensions/luminary-memory
```

### 3. Remove the bridge and config entries

```bash
luminary-memory setup --uninstall --agents all
luminary-memory setup --prune
```

`--uninstall` removes the Luminary entries from each host config and from
`~/.luminary/bridge.json`. `--prune` deletes bridge venvs that are no longer
referenced.

### 4. Remove the interpreter and cache

```bash
rm -rf ~/.luminary/venvs
rm -rf ~/.luminary/bin
rm -rf ~/.luminary/models
rm -f  ~/.luminary/bridge.json
rm -f  ~/.luminary/luminary.env
```

### 5. Remove the environment variable

If you set `LUMINARY_PYTHON` manually, remove it from the OpenCode/pi/omp
launch environment.

Windows (user environment):

```powershell
[Environment]::SetEnvironmentVariable('LUMINARY_PYTHON', $null, 'User')
```

Linux / macOS: remove the `export LUMINARY_PYTHON=...` line from your shell
profile.

### 6. Keep or delete memories

The memory store is `~/.luminary/memory.db`. Back it up before deleting:

```bash
cp ~/.luminary/memory.db ~/luminary-memory-backup.db
```

To remove everything, including memories:

```bash
rm -rf ~/.luminary
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Luminary memory is unavailable` in a turn | bridge missing or version mismatch | run the installer, then restart the host |
| `unsupported memory action` | plugin newer than the bridge | `luminary-memory setup --upgrade` |
| `bridge_exit` in `--check` | interpreter cannot import the bridge | reinstall the bridge for that version |
| Model downloads on every run | `LUMINARY_MODEL_CACHE` unset | run `luminary-memory setup` again |
| `pin X != bridge Y` | plugin and bridge versions differ | `luminary-memory setup --upgrade` |
