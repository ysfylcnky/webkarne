# Monthly scan round (PLAN.md K-09, run by hand per K-14) — run on the LOCAL
# machine in the first week of each month, from the repo root:
#
#   powershell -ExecutionPolicy Bypass -File scripts\monthly_round.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\monthly_round.ps1 -RunLabel 2026-11
#
# Steps: plan (dry run) -> batch scan (resumable: re-running continues a broken
# round) -> rescore email + transport -> consistent DB snapshot. A transcript is
# written to data/logs/ so the round's date and duration are on record.
param(
    [string]$RunLabel = (Get-Date).ToUniversalTime().ToString("yyyy-MM")
)

$ErrorActionPreference = "Stop"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
New-Item -ItemType Directory -Force "data/logs" | Out-Null
Start-Transcript -Path "data/logs/round-$RunLabel-$stamp.log" | Out-Null

function Invoke-Step([string]$Name, [string[]]$Arguments) {
    Write-Host "`n=== $Name ($((Get-Date).ToUniversalTime().ToString('u'))) ==="
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-Transcript | Out-Null
        throw "Step '$Name' failed with exit code $LASTEXITCODE. Fix and re-run; batch resumes."
    }
}

try {
    Invoke-Step "plan" @("run", "karne", "batch", "--run-label", $RunLabel, "--dry-run")
    Invoke-Step "batch" @("run", "karne", "batch", "--run-label", $RunLabel)
    Invoke-Step "rescore email" @("run", "karne", "rescore", "--run-label", $RunLabel, "--dimension", "email")
    Invoke-Step "rescore transport" @("run", "karne", "rescore", "--run-label", $RunLabel, "--dimension", "transport")
    Invoke-Step "snapshot" @("run", "python", "scripts/db_snapshot.py", "data/karne.db", "data/snapshots/karne-$RunLabel-$stamp.db")
    Write-Host "`nRound $RunLabel complete. Record it in docs/PROGRESS.md."
}
finally {
    Stop-Transcript | Out-Null
}
