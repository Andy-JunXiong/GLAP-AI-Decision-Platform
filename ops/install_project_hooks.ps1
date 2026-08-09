[CmdletBinding()]
param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Unable to resolve the Git repository root."
}
Set-Location -LiteralPath $repoRoot

$hookPath = Join-Path $repoRoot ".githooks/pre-commit"
if (-not (Test-Path -LiteralPath $hookPath -PathType Leaf)) {
    throw "Versioned pre-commit hook is missing: $hookPath"
}

function Resolve-PythonExecutable {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = (& $launcher.Source -3 -c "import sys; print(sys.executable)").Trim()
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            return $resolved
        }
    }
    $pipCommand = Get-Command pip.exe -ErrorAction SilentlyContinue
    if ($pipCommand) {
        $scriptsDirectory = Split-Path -Parent $pipCommand.Source
        $runtimeDirectory = Split-Path -Parent $scriptsDirectory
        $candidate = Join-Path $runtimeDirectory "python.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "Python 3 is required for the GLAP pre-commit gate."
}

$pythonPath = Resolve-PythonExecutable

$current = (& git config --local --get core.hooksPath 2>$null)
if (-not $Apply) {
    Write-Output "Plan only: configure core.hooksPath=.githooks"
    Write-Output "Plan only: record the resolved Python executable in local Git config."
    Write-Output "Current local value: $current"
    Write-Output "Run again with -Apply to activate the versioned hook."
    exit 0
}

& git config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw "Failed to configure the local Git hooks path."
}
& git config --local glap.pythonPath $pythonPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to record the repository-local Python path."
}

$verified = (& git config --local --get core.hooksPath).Trim()
if ($verified -ne ".githooks") {
    throw "Git hooks path verification failed."
}
Write-Output "Configured core.hooksPath=.githooks for this repository."
Write-Output "Recorded the repository-local Python executable for the hook."
