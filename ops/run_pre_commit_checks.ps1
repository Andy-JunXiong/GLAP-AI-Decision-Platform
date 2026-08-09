[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Unable to resolve the Git repository root."
}
Set-Location -LiteralPath $repoRoot

$configuredPython = (& git config --local --get glap.pythonPath 2>$null)
if ($configuredPython) {
    $configuredPython = $configuredPython.Trim()
    if (Test-Path -LiteralPath $configuredPython -PathType Leaf) {
        & $configuredPython "ops/run_pre_commit_checks.py"
        exit $LASTEXITCODE
    }
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source "ops/run_pre_commit_checks.py"
    exit $LASTEXITCODE
}

$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    & $launcher.Source -3 "ops/run_pre_commit_checks.py"
    exit $LASTEXITCODE
}

$pipCommand = Get-Command pip.exe -ErrorAction SilentlyContinue
if ($pipCommand) {
    $scriptsDirectory = Split-Path -Parent $pipCommand.Source
    $runtimeDirectory = Split-Path -Parent $scriptsDirectory
    $pythonCandidate = Join-Path $runtimeDirectory "python.exe"
    if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
        & $pythonCandidate "ops/run_pre_commit_checks.py"
        exit $LASTEXITCODE
    }
}

Write-Error "Python 3 is required for the GLAP pre-commit gate."
exit 1
