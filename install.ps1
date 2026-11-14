# Luminary Memory one-command installer for OpenCode, pi, and omp.
#
#   irm https://raw.githubusercontent.com/alertxsto/luminary-memory/main/install.ps1 | iex
#
# Provision only the bridge; Python setup owns host installation and records.
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
  [switch]$List,
  [switch]$Verbose
)
$ErrorActionPreference = "Stop"
$explicitVersion = [bool]$Version
if (-not $Version) { $Version = "0.3.4" }
if ($All) { $Agents = "all" }
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "Version must have the form X.Y.Z" }
if (@($Check, $Upgrade, $Uninstall | Where-Object { $_ }).Count -gt 1) {
  throw "Choose only one of -Check, -Upgrade, or -Uninstall"
}
if ($Agents -notin @("auto", "all")) {
  foreach ($agent in $Agents.Split(",")) {
    if ($agent -notin @("opencode", "pi", "omp")) { throw "Unknown agent: $agent" }
  }
}
$homeDir = $env:USERPROFILE
$binDir = Join-Path $homeDir ".luminary\bin"
$venv = Join-Path $homeDir ".luminary\venvs\$Version"
$python = Join-Path $venv "Scripts\python.exe"
$lockDir = Join-Path $homeDir ".luminary\locks\bootstrap.lock.d"
function Enter-BootstrapLock {
  New-Item -ItemType Directory -Force (Split-Path $lockDir) | Out-Null
  $deadline = (Get-Date).AddSeconds(120)
  while ($true) {
    try { New-Item -ItemType Directory -Path $lockDir -ErrorAction Stop | Out-Null; break }
    catch {
      $owner = Get-Content (Join-Path $lockDir "pid") -ErrorAction SilentlyContinue
      if ($owner -and -not (Get-Process -Id $owner -ErrorAction SilentlyContinue)) {
        Remove-Item -Recurse -Force $lockDir -ErrorAction SilentlyContinue
        continue
      }
      if ((Get-Date) -gt $deadline) { throw "Another Luminary bootstrap is running; retry after it finishes." }
      Start-Sleep -Milliseconds 100
    }
  }
  Set-Content -Path (Join-Path $lockDir "pid") -Value $PID
}
function Exit-BootstrapLock { Remove-Item -Recurse -Force $lockDir -ErrorAction SilentlyContinue }
$selected = @($Agents.Split(","))
if ($Agents -eq "auto") {
  $selected = @()
  foreach ($agent in @("opencode", "pi", "omp")) {
    $root = Join-Path $homeDir ".$agent\agent"
    if ($Project) { $root = Join-Path (Get-Location) ".$agent" }
    elseif ($agent -eq "opencode") {
      $base = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $homeDir ".config" }
      $root = Join-Path $base "opencode"
    }
    if ((Test-Path $root) -or (Get-Command $agent -ErrorAction SilentlyContinue)) { $selected += $agent }
  }
}
if ($List) { Write-Host "Detected agents: $($selected -join ' ')"; exit 0 }
if (-not $selected) { throw "No supported agent detected; use -Agents opencode,pi,omp." }
if ($Project -and -not $NoConfig -and -not ($Check -or $Uninstall -or $DryRun) -and ($selected -contains "omp" -or $Agents -eq "all")) {
  throw "omp native packages are user-wide; use explicit project copy installation instead."
}
$arguments = @("--agents", $Agents)
if ($explicitVersion) { $arguments += @("--version", $Version) }
if ($NoConfig) { $arguments += "--no-config" }
if ($Project) { $arguments += "--project" }
if ($Prune) { $arguments += "--prune" }
if ($DryRun) { $arguments += "--dry-run" }
if ($Check) { $arguments += "--check" }
if ($Upgrade) { $arguments += "--upgrade" }
if ($Uninstall) { $arguments += "--uninstall" }

function Test-Bridge([string]$Executable, [switch]$MatchVersion) {
  if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
  $probe = "from luminary_memory.integrations.setup import run_setup"
  if ($MatchVersion) { $probe += "; import importlib.metadata as m; assert m.version('luminary-memory') == '$Version'" }
  $previous = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $Executable -I -c $probe *> $null; return $LASTEXITCODE -eq 0 }
  finally { $ErrorActionPreference = $previous }
}

if ($env:LUMINARY_PYTHON) {
  $python = $env:LUMINARY_PYTHON
  if (-not (Test-Bridge $python)) { throw "Invalid LUMINARY_PYTHON; fix or unset the explicit override." }
} elseif ($Check -or $Uninstall -or $DryRun) {
  if (-not (Test-Bridge $python)) {
    $candidates = Get-ChildItem (Join-Path $homeDir ".luminary\venvs\*\Scripts\python.exe") -ErrorAction SilentlyContinue
    foreach ($candidate in $candidates) {
      if (Test-Bridge $candidate.FullName) { $python = $candidate.FullName; break }
    }
  }
  if (-not (Test-Bridge $python)) {
    if ($DryRun) { Write-Host "Planned bridge $Version for $($selected -join ',') (no provisioning)"; exit 0 }
    throw "No healthy Luminary setup bridge found; run setup with a supported release first."
  }
} else {
  $env:PYTHONPATH = $null
  $env:PYTHONHOME = $null
  $env:VIRTUAL_ENV = $null
  $env:CONDA_PREFIX = $null
  Enter-BootstrapLock
  try {
    # Recheck readiness under the lock: a concurrent bootstrap may have finished.
    if (-not (Test-Bridge $python -MatchVersion)) {
      $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
      $uv = if ($uvCommand) { $uvCommand.Source } else { Join-Path $binDir "uv.exe" }
      if (-not (Test-Path $uv)) {
        New-Item -ItemType Directory -Force $binDir | Out-Null
        $env:UV_INSTALL_DIR = $binDir
        $env:UV_NO_MODIFY_PATH = "1"
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        if (-not (Test-Path $uv)) { throw "uv provisioning failed" }
      }
      if (-not (Test-Path $python)) {
        & $uv venv $venv --python 3.12
        if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
      }
      & $uv pip install --python $python --reinstall "luminary-memory==$Version"
      if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }
    }
    if (-not (Test-Bridge $python)) {
      throw "Release $Version predates managed setup; choose a setup-capable release. Host configuration was not changed."
    }
    & $python -I -m luminary_memory.integrations setup @arguments
    exit $LASTEXITCODE
  } finally { Exit-BootstrapLock }
}
if (-not (Test-Bridge $python)) {
  throw "Release $Version predates managed setup; choose a setup-capable release. Host configuration was not changed."
}
& $python -I -m luminary_memory.integrations setup @arguments
exit $LASTEXITCODE
