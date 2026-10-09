# Nepocon monitoringdashboards

Per project een **los, afgeschermd dashboard** (zakbaken/zetting of GNSS-verplaatsing) met data uit de Basetime
REST API, dagelijks bijgewerkt en gehost op GitHub Pages. Elke opdrachtgever krijgt een eigen deelbare link met
eigen wachtwoord en ziet alleen zijn eigen project.

```
GitHub Actions (dagelijks 04:00 UTC)
  └─ build.py
       ├─ basetime_api.py   Basetime REST API (AWS SigV4, regio eu-west-1)
       ├─ bronnen.py        API-JSON -> exportlayout
       ├─ generators/       zetting_dashboard.py / gnss_dashboard.py -> dashboard-HTML
       └─ versleutel.py     AES-256-GCM met projectwachtwoord -> inlogpagina
  └─ GitHub Pages
       /                         neutrale Nepocon-pagina (géén projectenlijst)
       /<slug>-<linkcode>/       inlogscherm + dashboard van één project (link per opdrachtgever)
```

## Beveiliging
| Wat | Waar | Nooit |
|---|---|---|
| Basetime Access key ID + Secret access key | Secrets `BASETIME_ACCESS_KEY_ID`, `BASETIME_SECRET_ACCESS_KEY` | in code, HTML, chat, git of SharePoint |
| Projectwachtwoorden | Secret `DASHBOARD_WACHTWOORDEN` + lokaal `%USERPROFILE%\.basetime-geheim\` | in git of SharePoint |
| Projectnamen + linkcodes | Secret `PROJECTEN_JSON` + lokaal `projecten.json` (in `.gitignore`) | in de openbare repo |
| Meetdata | alleen versleuteld in de gepubliceerde pagina | in git |

Maatregelen:
- **Losse dashboards**: elk project op een eigen adres met een onraadbare code (12 tekens). Geen overzicht,
  geen links tussen projecten; de hoofdpagina en 404 tonen geen projectnamen (wordt bij elke build gecontroleerd).
- **Versleuteling**: AES-256-GCM, sleutel = PBKDF2-SHA256 (600.000 rondes) van het projectwachtwoord. Zonder
  wachtwoord geen data, ook niet in de paginabron. "Onthoud op dit apparaat" geldt per project.
- **API-sleutels** alleen tijdens de build (SigV4-handtekening; geheime sleutel gaat niet over de lijn). Alleen HTTPS.
- **Lekcontrole**: staat er een sleutel, wachtwoord, onversleutelde data of projectverwijzing op een algemene
  pagina, dan stopt de build -> niets gepubliceerd, vorige versie blijft online.
- **Openbare Actions-logs**: projectnamen, slugs en codes worden gemaskeerd; logs tonen alleen "project 2/4".
- **Storing bij één project** -> alleen dat project toont "tijdelijk niet beschikbaar".
- Externe scripts met SRI-hash, `no-referrer`, zoekmachines geweerd (`robots.txt`, `noindex`).
- Workflow alleen via `schedule` en handmatig; minimale rechten.

Beheer:
- Deel link en wachtwoord **apart** (bv. link per mail, wachtwoord per telefoon/sms).
- Opdrachtgever weg of link gelekt? `python build.py --maak-codes` na het wissen van de `code` van dat project
  (nieuwe link) en/of `zet-secrets.ps1 -Vernieuw <slug>` (nieuw wachtwoord), daarna workflow draaien.
- Vraag Basetime of de API-sleutel **alleen-lezen** is; laat hem roteren als hij ooit is rondgestuurd.

## Locatie
- Project: `Water - Documenten Nieuwe structuur\05_Monitoring\04_Basetime\nepocon-dashboards` (SharePoint/OneDrive).
- Geheimen: `%USERPROFILE%\.basetime-geheim\` (alleen lokaal, niet gesynchroniseerd).
- Lokale testsite: `%LOCALAPPDATA%\nepocon-dashboards\site` (bij Python uit de Microsoft Store onder
  `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation...\LocalCache\Local\`).

## Online (eenmalig ingericht)
Repository `barttm/monitoring-dashboards`, Pages via GitHub Actions, eigen domein **https://argeo.nl** (TransIP).
DNS: `@` A 185.199.108.153 / .109.153 / .110.153 / .111.153 en `www` CNAME `barttm.github.io.`;
in de links staat geen GitHub-naam. Secrets zetten / bijwerken:
```powershell
powershell -ExecutionPolicy Bypass -File .\zet-secrets.ps1
```
Dit zet de API-sleutels (uit de lokale CSV), de wachtwoorden en `PROJECTEN_JSON`, en toont de deelbare links.
Daarna: **Actions → Dashboards bouwen en publiceren → Run workflow** (of wacht op de dagelijkse run).

## Project toevoegen
1. `python basetime_api.py projecten` (met `BASETIME_KEYS_CSV` gezet) -> exacte projectnaam in Basetime.
2. Blok toevoegen in `projecten.json` (zie `projecten.voorbeeld.json`).
3. `python build.py --maak-codes`
4. `powershell -ExecutionPolicy Bypass -File .\zet-secrets.ps1 -AlleenWachtwoorden` -> nieuwe link + wachtwoord.
5. Workflow draaien.

## Lokaal testen
```bash
pip install -r requirements.txt
set BASETIME_KEYS_CSV=%USERPROFILE%\.basetime-geheim\NepoConRestFul_accessKeys.csv
python build.py --maak-testwachtwoorden
python build.py
python build.py --links
```

## Bekende punten
- Eén project gaf op 09-10-2026 HTTP 502 vanuit de API (`get-data`, alle punten) -> melden bij support@basetime.nl.
- Zakbaken: grondplaat = `Coordinates Soil -> Height groundplate` (zelfde als de Excel-export), staaflengte = `Vertical offset`.
