# zet-secrets.ps1
# Zet de GitHub Secrets voor de dashboards, zonder dat sleutels of wachtwoorden op het scherm komen.
#   - BASETIME_ACCESS_KEY_ID / BASETIME_SECRET_ACCESS_KEY  uit %USERPROFILE%\.basetime-geheim\NepoConRestFul_accessKeys.csv
#   - DASHBOARD_WACHTWOORDEN  uit %USERPROFILE%\.basetime-geheim\wachtwoorden.online.json
#     (bestaat dat bestand niet, of ontbreekt een project, dan wordt een sterk wachtwoord van 20 tekens gemaakt)
#   - PROJECTEN_JSON  uit projecten.json (projectnamen + linkcodes; staat niet in git)
#
# Gebruik (vanuit deze map):
#   powershell -ExecutionPolicy Bypass -File .\zet-secrets.ps1
#   powershell -ExecutionPolicy Bypass -File .\zet-secrets.ps1 -AlleenWachtwoorden     # na toevoegen project / wisselen
#   powershell -ExecutionPolicy Bypass -File .\zet-secrets.ps1 -Vernieuw <slug>         # nieuw wachtwoord voor één project
#
# Dit script bevat zelf GEEN geheimen en mag in git.

param(
    [string]$Repo = "barttm/monitoring-dashboards",
    [string]$Domein = "argeo.nl",
    [switch]$AlleenWachtwoorden,
    [string[]]$Vernieuw = @()
)
$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$geheim = Join-Path $env:USERPROFILE ".basetime-geheim"
$csvPad = Join-Path $geheim "NepoConRestFul_accessKeys.csv"
$wwPad = Join-Path $geheim "wachtwoorden.online.json"

function Nieuw-Wachtwoord([int]$lengte = 20) {
    $tekens = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"   # geen 0/O/1/l/I
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] 1
    $uit = ""
    while ($uit.Length -lt $lengte) {
        $rng.GetBytes($buf)
        if ($buf[0] -lt (256 - (256 % $tekens.Length))) { $uit += $tekens[$buf[0] % $tekens.Length] }
    }
    return $uit
}

if (-not $AlleenWachtwoorden) {
    if (-not (Test-Path $csvPad)) { throw "Sleutelbestand niet gevonden: $csvPad" }
    $rij = (Import-Csv $csvPad)[0]
    $rij.'Access key ID'.Trim()     | & $gh secret set BASETIME_ACCESS_KEY_ID -R $Repo
    $rij.'Secret access key'.Trim() | & $gh secret set BASETIME_SECRET_ACCESS_KEY -R $Repo
    Write-Host "API-sleutels gezet (BASETIME_ACCESS_KEY_ID, BASETIME_SECRET_ACCESS_KEY)."
}

$slugs = (Get-Content (Join-Path $PSScriptRoot "projecten.json") -Raw | ConvertFrom-Json).projecten | ForEach-Object { $_.slug }
$ww = @{}
if (Test-Path $wwPad) {
    (Get-Content $wwPad -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $ww[$_.Name] = $_.Value }
}
foreach ($s in $slugs) {
    if (-not $ww.ContainsKey($s) -or $Vernieuw -contains $s) { $ww[$s] = Nieuw-Wachtwoord; Write-Host "Nieuw wachtwoord: $s" }
}
New-Item -ItemType Directory -Force $geheim | Out-Null
($ww | ConvertTo-Json -Compress) | Set-Content -Path $wwPad -Encoding ASCII
($ww | ConvertTo-Json -Compress) | & $gh secret set DASHBOARD_WACHTWOORDEN -R $Repo
Write-Host "DASHBOARD_WACHTWOORDEN gezet voor: $($slugs -join ', ')"

# Projectconfiguratie (namen + linkcodes) is vertrouwelijk en staat niet in de openbare repo
$cfg = Get-Content (Join-Path $PSScriptRoot "projecten.json") -Raw
$cfg | & $gh secret set PROJECTEN_JSON -R $Repo
Write-Host "PROJECTEN_JSON gezet."

Write-Host ""
Write-Host "Deelbare links (per opdrachtgever los versturen, wachtwoord apart delen):"
$basis = "https://" + $Domein + "/"
(ConvertFrom-Json $cfg).projecten | ForEach-Object { Write-Host ("  {0,-22} {1}{2}-{3}/" -f $_.slug, $basis, $_.slug, $_.code) }
Write-Host ""
Write-Host "Wachtwoorden staan lokaal in: $wwPad  (niet in SharePoint zetten)"
