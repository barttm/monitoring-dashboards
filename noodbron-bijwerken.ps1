# noodbron-bijwerken.ps1
# Zet de nieuwste Basetime-export (uit Downloads) online voor een project waarvan de API niet werkt.
# Stappen: export zoeken -> versleutelen -> naar GitHub -> build starten -> wachten tot het online staat.
#
# Gebruik:  powershell -ExecutionPolicy Bypass -File .\noodbron-bijwerken.ps1 -Slug <slug>
# Bevat zelf geen geheimen.

param([Parameter(Mandatory = $true)][string]$Slug, [string]$Repo = "barttm/monitoring-dashboards")
$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
Set-Location $PSScriptRoot
$env:BASETIME_KEYS_CSV = Join-Path $env:USERPROFILE ".basetime-geheim\NepoConRestFul_accessKeys.csv"

Write-Host "1/4  Nieuwste export zoeken en versleutelen..." -ForegroundColor Cyan
python noodbron.py $Slug --nieuwste
if ($LASTEXITCODE -ne 0) { throw "Geen export gevonden of versleutelen mislukt." }

Write-Host "2/4  Naar GitHub sturen..." -ForegroundColor Cyan
git add noodbron
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "     Geen wijziging: deze export stond al online." -ForegroundColor Yellow
} else {
    git commit -q -m "Noodbron bijgewerkt"
    git push -q
}

Write-Host "3/4  Build starten..." -ForegroundColor Cyan
& $gh workflow run dashboards.yml -R $Repo | Out-Null
Start-Sleep -Seconds 8
$id = & $gh run list -R $Repo -L 1 --json databaseId --jq ".[0].databaseId"

Write-Host "4/4  Wachten tot het online staat (ca. 1-2 minuten)..." -ForegroundColor Cyan
& $gh run watch $id -R $Repo --exit-status --interval 10 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "Klaar: het dashboard is bijgewerkt." -ForegroundColor Green }
else { Write-Host "De build is mislukt - bekijk: https://github.com/$Repo/actions" -ForegroundColor Red }
