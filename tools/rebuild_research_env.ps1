param(
    [string]$EnvDir,
    [string]$VerificationReport
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Arguments = @("run", "--no-project", "--python", "3.12.9", (Join-Path $RepoRoot "tools/rebuild_research_env.py"))
if ($EnvDir) { $Arguments += @("--env-dir", $EnvDir) }
if ($VerificationReport) { $Arguments += @("--output", $VerificationReport) }
& uv @Arguments
if ($LASTEXITCODE -ne 0) { throw "Research environment setup failed: $LASTEXITCODE" }
