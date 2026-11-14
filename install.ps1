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

# 3. Everything that touches host config and the shared bridge record.
$arguments = @("--agents", $Agents, "--version", $Version)
if ($NoConfig) { $arguments += "--no-config" }
if ($Project) { $arguments += "--project" }
if ($Prune) { $arguments += "--prune" }
if ($DryRun) { $arguments += "--dry-run" }
if ($Check) { $arguments += "--check" }
if ($Upgrade) { $arguments += "--upgrade" }
if ($Uninstall) { $arguments += "--uninstall" }

if ($Verbose) { Write-Host "+ $python -m luminary_memory.integrations setup $($arguments -join ' ')" }
& $python -m luminary_memory.integrations setup @arguments
exit $LASTEXITCODE
