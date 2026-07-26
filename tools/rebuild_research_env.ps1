param(
    [string]$BootstrapPython = "D:\Programs\anaconda3\python.exe",
    [string]$EnvDir = "D:\code\_open-source\_venvs\quant-research-py312",
    [string]$VerificationReport = "D:\code\_open-source\_data\quant-research\environment\verification.json"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockFile = Join-Path $RepoRoot "requirements\research-win-py312.lock"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "External command failed with exit code ${LASTEXITCODE}: $Command $Arguments"
    }
}

if (-not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
    throw "Bootstrap Python does not exist: $BootstrapPython"
}

$BootstrapVersion = & $BootstrapPython -c "import platform; print(platform.python_version())"
if ($BootstrapVersion -ne "3.12.9") {
    throw "Bootstrap Python must be 3.12.9, got $BootstrapVersion"
}

if (Test-Path -LiteralPath $EnvDir) {
    throw "Environment directory already exists; use a new empty path: $EnvDir"
}

if (-not (Test-Path -LiteralPath $LockFile -PathType Leaf)) {
    throw "Lock file does not exist: $LockFile"
}

Invoke-Checked $BootstrapPython "-m" "venv" $EnvDir
$EnvPython = Join-Path $EnvDir "Scripts\python.exe"
Invoke-Checked $EnvPython "-m" "pip" "install" "--disable-pip-version-check" `
    "pip==25.1.1" "setuptools==83.0.0" "wheel==0.47.0"
Invoke-Checked $EnvPython "-m" "pip" "install" "--disable-pip-version-check" `
    "--no-build-isolation" "-r" $LockFile

Push-Location $RepoRoot
try {
    Invoke-Checked $EnvPython "tools\verify_research_environment.py" `
        "--output" $VerificationReport
    Invoke-Checked $EnvPython "-m" "pip" "check"
    Invoke-Checked $EnvPython "-m" "pytest" "-q"
    Invoke-Checked $EnvPython "tools\validate_repo.py"
    Invoke-Checked $EnvPython "-m" "ruff" "check" "src" "tools" "tests" "studies"
}
finally {
    Pop-Location
}
