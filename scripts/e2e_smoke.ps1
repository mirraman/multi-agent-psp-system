# Full-stack smoke: requires docker compose (api, postgres, redis, xmpp, agents, celery) running.
# Usage:  powershell -File backend/scripts/e2e_smoke.ps1
#         powershell -File backend/scripts/e2e_smoke.ps1 -BaseUrl "http://localhost:8000" -Accession "P01308"

param(
    [string] $BaseUrl = "http://localhost:8000",
    [string] $Accession = "P01308",
    [int] $TimeoutSeconds = 900,
    [int] $PollSeconds = 5
)

$ErrorActionPreference = "Stop"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

Write-Host "Waiting for API at $BaseUrl ..."
do {
    try {
        Invoke-RestMethod -Uri "$BaseUrl/openapi.json" -Method Get -TimeoutSec 5 | Out-Null
        break
    } catch {
        if ((Get-Date) -gt $deadline) { throw "API not reachable at $BaseUrl" }
        Start-Sleep -Seconds 2
    }
} while ($true)

$body = @{
    type        = "protein_analysis"
    accession   = $Accession
} | ConvertTo-Json

Write-Host "POST /jobs (accession=$Accession) ..."
$created = Invoke-RestMethod -Uri "$BaseUrl/jobs" -Method Post -Body $body -ContentType "application/json; charset=utf-8"
$jobId = $created.job_id
Write-Host "Job id: $jobId"

while ((Get-Date) -lt $deadline) {
    $job = Invoke-RestMethod -Uri "$BaseUrl/jobs/$jobId" -Method Get
    $st = $job.status
    Write-Host "  status: $st"
    if ($st -eq "completed") {
        $result = Invoke-RestMethod -Uri "$BaseUrl/jobs/$jobId/result" -Method Get
        $pockets = $result.pockets
        if ($null -ne $pockets) {
            Write-Host "Result includes pockets key. Pipeline finished OK."
        } else {
            Write-Host "Warning: result has no 'pockets' field (check JSON shape)."
        }
        exit 0
    }
    if ($st -eq "failed") {
        Write-Host "Job failed."
        try {
            $logs = Invoke-RestMethod -Uri "$BaseUrl/jobs/$jobId/logs" -Method Get
            $logs.logs | ForEach-Object { Write-Host "  LOG: $($_.message)" }
        } catch {}
        exit 1
    }
    Start-Sleep -Seconds $PollSeconds
}

Write-Host "Timeout after ${TimeoutSeconds}s"
exit 1
