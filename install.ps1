# Luminary Memory one-command installer for OpenCode, pi, and omp.
#
#   irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
#
# Provisions a private Python runtime with uv, installs the version-matched
# bridge, writes ~/.luminary/bridge.json, configures every detected agent, and
# verifies the bridge. No Python, Node, or venv setup is required.
param(
  [string]$Agents = "auto",
  [string]$Version = $env:LUMINARY_VERSION,
  [switch]$All,
  [switch]$Check,
  [switch]$Upgrade,
  [switch]$Uninstall,
  [switch]$Prune,
  [switch]$NoConfig,
  [switch]$Project,
  [switch]$DryRun,
  [switch]$Verbose
)

$ErrorActionPreference = "Stop"
if (-not $Version) { $Version = "0.3.4" }
if ($All) { $Agents = "all" }

function Write-Log([string]$Message) {
  Write-Host "[luminary] $Message" -ForegroundColor Cyan
}

$homeDir = $env:USERPROFILE
$binDir = Join-Path $homeDir ".luminary\bin"
$venv = Join-Path $homeDir ".luminary\venvs\$Version"
$python = Join-Path $venv "Scripts\python.exe"

function Select-Agents {
  if ($Agents -eq "all") { return @("opencode", "pi", "omp") }
  if ($Agents -ne "auto") { return $Agents.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
  $found = @()
  if (Test-Path (Join-Path $homeDir ".config\opencode")) { $found += "opencode" }
  if ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "Programs\ai.opencode.desktop"))) { $found += "opencode" }
  if (Test-Path (Join-Path $homeDir ".pi")) { $found += "pi" }
  if (Test-Path (Join-Path $homeDir ".omp")) { $found += "omp" }
  return $found | Select-Object -Unique
}

# 1. A bridge interpreter. Status-only modes reuse an existing venv.
if (($Check -or $Uninstall) -and -not (Test-Path $python)) {
  $candidate = Get-ChildItem (Join-Path $homeDir ".luminary\venvs\*\Scripts\python.exe") -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($candidate) { $python = $candidate.FullName }
  if (-not (Test-Path $python)) {
    throw "No Luminary bridge found; run the installer without -Check/-Uninstall first."
  }
}

# 2. uv: a single static binary that can provision Python itself. Only needed
#    when the target interpreter does not exist yet.
if (-not (Test-Path $python)) {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uv = Join-Path $binDir "uv.exe"
    if (-not (Test-Path $uv)) {
      Write-Log "installing uv"
      New-Item -ItemType Directory -Force -Path $binDir | Out-Null
      $env:UV_INSTALL_DIR = $binDir
      $env:UV_NO_MODIFY_PATH = "1"
      Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    $env:Path = "$binDir;$env:Path"
  }
  Write-Log "python 3.12 -> $venv"
  if ($Verbose) { Write-Host "+ uv venv $venv --python 3.12" }
  & uv venv $venv --python 3.12
  if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
  Write-Log "bridge $Version"
  if ($Verbose) { Write-Host "+ uv pip install --python $python luminary-memory==$Version" }
  & uv pip install --python $python "luminary-memory==$Version"
  if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }
}

# 3. Preferred path: the bridge ships the setup command.
$arguments = @("--agents", $Agents, "--version", $Version)
if ($NoConfig) { $arguments += "--no-config" }
if ($Project) { $arguments += "--project" }
if ($Prune) { $arguments += "--prune" }
if ($DryRun) { $arguments += "--dry-run" }
if ($Check) { $arguments += "--check" }
if ($Upgrade) { $arguments += "--upgrade" }
if ($Uninstall) { $arguments += "--uninstall" }

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m luminary_memory.integrations setup --list *> $null
$hasSetup = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previous
if ($hasSetup) {
  & $python -m luminary_memory.integrations setup @arguments
  exit $LASTEXITCODE
}

# ------------------------------------------------------------------------
# Compatibility path for a published bridge that predates `setup`.
#
# It uses only commands and actions the older bridge already has:
#   - `luminary_memory.integrations install <agent> --global` writes a copy
#     adapter that embeds this interpreter, so no env var is required;
#   - the `core` action proves the bridge can read its store.
# Nothing is downloaded, so a stale remote copy cannot masquerade as success.
# ------------------------------------------------------------------------
$selected = @(Select-Agents | Where-Object { $_ })
if (-not $selected) {
  throw "No supported agent detected; use -Agents opencode,pi,omp or -All."
}

if ($Uninstall) {
  Remove-Item -Recurse -Force (Join-Path $homeDir ".config\opencode\plugins\luminary-memory") -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force (Join-Path $homeDir ".pi\agent\extensions\luminary-memory") -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force (Join-Path $homeDir ".omp\agent\extensions\luminary-memory") -ErrorAction SilentlyContinue
  Remove-Item -Force (Join-Path $homeDir ".luminary\bridge.json") -ErrorAction SilentlyContinue
  Write-Log "removed Luminary adapters and bridge record"
  exit 0
}

if ($Check) {
  $bridge = Join-Path $homeDir ".luminary\bridge.json"
  if (-not (Test-Path $bridge)) { Write-Host "no bridge record; run the installer first"; exit 1 }
  $data = Get-Content -Raw $bridge | ConvertFrom-Json
  $ok = $true
  foreach ($entry in $data.agents.PSObject.Properties) {
    $alive = Test-Path $entry.Value.python
    if (-not $alive) { $ok = $false }
    $state = if ($alive) { "ok" } else { "missing" }
    Write-Host ("{0,-9} {1,-9} bridge={2}  python={3}" -f $entry.Name, $state, $entry.Value.version, $entry.Value.python)
  }
  if (-not $ok) { exit 1 }
  exit 0
}

if ($DryRun) { Write-Log "would install: $($selected -join ' ')"; exit 0 }

foreach ($agent in $selected) {
  if ($Verbose) { Write-Host "+ install $agent --global" }
  & $python -m luminary_memory.integrations install $agent --global
  if ($LASTEXITCODE -ne 0) { throw "installing the $agent adapter failed" }
}

$record = @{ schema = 1; agents = @{} }
foreach ($agent in $selected) {
  $record.agents[$agent] = @{ python = $python; version = $Version; mode = "copy" }
}
$path = Join-Path $homeDir ".luminary\bridge.json"
New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
$json = $record | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))

$failed = $false
foreach ($agent in $selected) {
  $request = @{ agent = $agent; workspace = (Get-Location).Path; session_id = "setup-check"; action = "core" } | ConvertTo-Json -Compress
  $reply = $request | & $python -m luminary_memory.integrations bridge 2>$null
  try { $parsed = $reply | ConvertFrom-Json } catch { $parsed = $null }
  $ok = $parsed -and $parsed.ok -eq $true
  if (-not $ok) { $failed = $true }
  $state = if ($ok) { "ok" } else { "error" }
  $detail = if ($ok) { "" } elseif ($parsed.message) { "  " + $parsed.message } elseif ($parsed.reason) { "  " + $parsed.reason } else { "  bridge error" }
  Write-Host ("{0,-9} {1,-9} bridge={2}{3}" -f $agent, $state, $Version, $detail)
}
if ($failed) { exit 1 }
exit 0
