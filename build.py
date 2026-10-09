#!/usr/bin/env python3
"""
build.py
Bouwt per project een LOS, afgeschermd dashboard: eigen deelbare link met onraadbare code, eigen
inlogscherm en eigen wachtwoord. Er is geen gezamenlijk overzicht; opdrachtgevers zien elkaars
projecten niet. Uitvoer: statische site (GitHub Actions publiceert die op GitHub Pages).

Gebruik (lokaal):
    python build.py --maak-codes                 # geeft nieuwe projecten een onraadbare linkcode
    python build.py --maak-testwachtwoorden      # lokale testwachtwoorden (buiten de projectmap)
    python build.py                              # bouwt de site
    python build.py --links                      # toont de deelbare link per project

Configuratie (NIET in de openbare repository; projectnamen en codes zijn vertrouwelijk):
    online : GitHub Secret PROJECTEN_JSON      (inhoud van projecten.json)
    lokaal : projecten.json naast dit script    (staat in .gitignore; voorbeeld: projecten.voorbeeld.json)
Wachtwoorden (JSON {"slug": "wachtwoord", ...}):
    online : GitHub Secret DASHBOARD_WACHTWOORDEN
    lokaal : %USERPROFILE%\.basetime-geheim\wachtwoorden.local.json

Faalt een veiligheidscontrole, dan stopt de build -> niets gepubliceerd, vorige versie blijft online.
Een storing bij één project levert alleen voor dat project een storingspagina op.
"""

import argparse
import base64
import html as htmlmod
import json
import os
import secrets
import shutil
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

BASIS = Path(__file__).resolve().parent
sys.path.insert(0, str(BASIS / "generators"))
sys.path.insert(0, str(BASIS))

import gnss_dashboard as gd      # noqa: E402
import zetting_dashboard as zd   # noqa: E402

import bronnen                   # noqa: E402
import versleutel                # noqa: E402

CI = os.environ.get("GITHUB_ACTIONS") == "true"
# GitHub Actions: site/ in de repo-map. Lokaal: buiten de OneDrive/SharePoint-map (sync vergrendelt bestanden).
if CI:
    SITE = BASIS / "site"
else:
    SITE = Path(os.environ.get("DASHBOARD_SITE_MAP") or
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "nepocon-dashboards" / "site")
LOGO = BASIS / "assets" / "nepocon_logo.png"
CONFIG = BASIS / "projecten.json"
LOKAAL_WW = Path(os.environ.get("DASHBOARD_WACHTWOORDEN_BESTAND") or
                 Path.home() / ".basetime-geheim" / "wachtwoorden.local.json")
BASIS_URL = os.environ.get("DASHBOARD_BASIS_URL") or "https://monitoring.nepocon.nl/"
MIN_WW_LENGTE = 12
CODE_LENGTE = 12


# ── Configuratie ─────────────────────────────
def laad_config():
    if os.environ.get("PROJECTEN_JSON"):
        return json.loads(os.environ["PROJECTEN_JSON"])
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    sys.exit("Geen projectconfiguratie: zet GitHub Secret PROJECTEN_JSON of maak projecten.json "
             "(zie projecten.voorbeeld.json).")


def map_van(p):
    if not p.get("code") or len(p["code"]) < CODE_LENGTE:
        sys.exit("Project %s heeft geen linkcode - draai eerst: python build.py --maak-codes" % p.get("slug"))
    return p["slug"] + "-" + p["code"]


def maak_codes():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    tekens = string.ascii_letters + string.digits
    for p in cfg["projecten"]:
        if not p.get("code"):
            p["code"] = "".join(secrets.choice(tekens) for _ in range(CODE_LENGTE))
            print("Nieuwe linkcode voor %s" % p["slug"])
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def laad_wachtwoorden():
    if os.environ.get("DASHBOARD_WACHTWOORDEN"):
        return json.loads(os.environ["DASHBOARD_WACHTWOORDEN"])
    if LOKAAL_WW.exists():
        return json.loads(LOKAAL_WW.read_text(encoding="utf-8"))
    sys.exit("Geen wachtwoorden: zet GitHub Secret DASHBOARD_WACHTWOORDEN of maak lokale testwachtwoorden "
             "(python build.py --maak-testwachtwoorden).")


def maak_testwachtwoorden(projecten):
    LOKAAL_WW.parent.mkdir(parents=True, exist_ok=True)
    bestaand = json.loads(LOKAAL_WW.read_text(encoding="utf-8")) if LOKAAL_WW.exists() else {}
    for p in projecten:
        bestaand.setdefault(p["slug"], secrets.token_urlsafe(18))
    LOKAAL_WW.write_text(json.dumps(bestaand, indent=2), encoding="utf-8")
    print("Testwachtwoorden staan in %s" % LOKAAL_WW)


def maskeer_in_ci_logs(projecten):
    """Openbare repo = openbare Actions-logs: projectnamen, slugs en codes maskeren."""
    if not CI:
        return
    for p in projecten:
        for v in (p.get("naam"), p.get("slug"), p.get("code"), p.get("bron", {}).get("project")):
            if v:
                print("::add-mask::" + v)


def log(i, n, p, tekst):
    wie = ("project %d/%d" % (i, n)) if CI else p["slug"]
    print("[%s] %s: %s" % (p["type"], wie, tekst), flush=True)


# ── Dashboards ───────────────────────────────
def laad_edits(slug):
    j, h = BASIS / "opmerkingen" / (slug + ".json"), BASIS / "opmerkingen" / (slug + ".html")
    if j.exists():
        ed = json.loads(j.read_text(encoding="utf-8"))
        ed.setdefault("teksten", {})
        return ed
    return zd.lees_edits(h)


def bouw_zetting(p, ruw):
    for k, v in p.get("opties", {}).items():      # bv. VERSTORINGEN, REFERENTIEDATUM, MAX_GAT_DAGEN
        setattr(zd, k.upper(), v)
    data = zd.bereken(zd.lees_data(ruw))
    if not data:
        raise RuntimeError("geen zakbaakdata gevonden")
    return zd.bouw_html(zd.bouw_payload(data, p["naam"]), LOGO, laad_edits(p["slug"]))


def bouw_gnss(p, ruw):
    vanaf = p.get("opties", {}).get("vanaf", "1900-01-01 00:00")
    punten = gd.lees_data(ruw, vanaf)
    return gd.bouw_html(gd.bouw_payload(punten, p["naam"], vanaf), LOGO)


BOUWERS = {"zetting": bouw_zetting, "gnss": bouw_gnss}


def logo_html():
    return '<img src="data:image/png;base64,' + base64.b64encode(LOGO.read_bytes()).decode("ascii") + '" alt="Nepocon">'


# ── Neutrale pagina's (geen projectnamen!) ───
NEUTRAAL = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>Monitoringdashboard - Nepocon</title>
<style>
/* Zelfde stijl als het inlogscherm (versleutel.py) */
:root { --blauw: #004B8D; --tekst: #1a2233; --grijs: #6b7686; --lijn: #dfe4ec; --bg: #f5f7fa; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px;
       font-family: "Segoe UI", Arial, sans-serif; background: var(--bg); color: var(--tekst); }
.box { width: 100%; max-width: 380px; background: #fff; border: 1px solid var(--lijn); border-top: 3px solid var(--blauw);
       border-radius: 4px; padding: 28px 28px 24px; }
.box img { height: 40px; display: block; margin-bottom: 18px; }
h1 { font-size: 16px; margin: 0 0 8px; }
p { font-size: 13px; color: var(--grijs); line-height: 1.55; margin: 0 0 10px; }
a { color: var(--blauw); }
</style>
</head>
<body>
<main class="box">
  __LOGO__
  <h1>__TITEL__</h1>
  <p>__TEKST__</p>
  <p>Vragen of geen toegang? Neem contact op met
    <a href="mailto:b.termull@nepocon.nl?subject=Toegang%20monitoringdashboard">b.termull@nepocon.nl</a>.</p>
</main>
</body>
</html>
"""


def neutrale_pagina(titel, tekst):
    return NEUTRAAL.replace("__LOGO__", logo_html()).replace("__TITEL__", titel).replace("__TEKST__", tekst)


STORING_TEKST = ("Dit dashboard is tijdelijk niet beschikbaar door een storing bij de databron (controle __TIJD__ UTC). "
                 "Bij de volgende dagelijkse update wordt het opnieuw geprobeerd.")


# ── Controle ─────────────────────────────────
def controleer_site(geheimen, projecten):
    """Geen geheimen, geen onversleutelde data, en geen projectnamen/links op de algemene pagina's."""
    fouten = []
    for f in SITE.rglob("*"):
        if not f.is_file():
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        for g in geheimen:
            if g in t:
                fouten.append("%s bevat een geheime waarde (API-sleutel of wachtwoord)" % f.name)
        if "var D = " in t:
            fouten.append("%s bevat onversleutelde dashboarddata" % f.name)
    algemeen = "".join((SITE / n).read_text(encoding="utf-8") for n in ("index.html", "404.html"))
    for p in projecten:
        for v in (p["naam"], p["slug"], p["code"], p["bron"].get("project", "")):
            if v and v in algemeen:
                fouten.append("algemene pagina verwijst naar een project")
        if not (SITE / map_van(p) / "index.html").exists():
            fouten.append("dashboard ontbreekt (project %s)" % ("?" if CI else p["slug"]))
    if fouten:
        sys.exit("VEILIGHEIDSCONTROLE MISLUKT - niets gepubliceerd:\n  " + "\n  ".join(sorted(set(fouten))))


# ── Main ─────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Bouw losse, versleutelde monitoringdashboards per project")
    ap.add_argument("--maak-codes", action="store_true")
    ap.add_argument("--maak-testwachtwoorden", action="store_true")
    ap.add_argument("--links", action="store_true", help="toon de deelbare link per project")
    ap.add_argument("--alleen", nargs="*", help="alleen deze slugs bouwen (test)")
    args = ap.parse_args()

    if args.maak_codes:
        maak_codes()
        return
    projecten = laad_config()["projecten"]
    maskeer_in_ci_logs(projecten)
    if args.alleen:
        projecten = [p for p in projecten if p["slug"] in args.alleen]
    if args.maak_testwachtwoorden:
        maak_testwachtwoorden(projecten)
        return
    if args.links:
        for p in projecten:
            print("%-28s %s%s/" % (p["slug"], BASIS_URL, map_van(p)))
        return

    ww = laad_wachtwoorden()
    for p in projecten:
        map_van(p)
        if len(ww.get(p["slug"], "")) < MIN_WW_LENGTE:
            sys.exit("Geen of te kort wachtwoord (min. %d tekens) voor project %s." % (
                MIN_WW_LENGTE, "?" if CI else p["slug"]))

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    tijd = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M")

    geheimen = bronnen.geheime_waarden() + [w for w in ww.values() if w]
    mislukt = 0
    for i, p in enumerate(projecten, 1):
        doel = SITE / map_van(p)
        doel.mkdir()
        try:
            ruw = bronnen.haal_ruwe_data(p, BASIS)
            dashboard = BOUWERS[p["type"]](p, ruw)
        except Exception as e:   # storing bij één project mag de rest niet blokkeren
            fout = str(e)
            for g in geheimen + [p["naam"], p["bron"].get("project", "")]:
                if g:
                    fout = fout.replace(g, "***")
            mislukt += 1
            pagina = neutrale_pagina(htmlmod.escape(p["naam"]), STORING_TEKST.replace("__TIJD__", tijd))
            (doel / "index.html").write_text(pagina, encoding="utf-8")
            log(i, len(projecten), p, "STORING - " + fout[:200])
            continue
        blob = versleutel.versleutel(dashboard, ww[p["slug"]], p["slug"])
        assert versleutel.ontsleutel(blob, ww[p["slug"]]) == dashboard
        pagina = versleutel.login_pagina(blob, htmlmod.escape(p["naam"]), p["slug"], logo_html())
        (doel / "index.html").write_text(pagina, encoding="utf-8")
        log(i, len(projecten), p, "ok (%s kB)" % format(len(pagina) // 1024, ","))

    if mislukt == len(projecten):
        sys.exit("Alle projecten mislukt - niets gepubliceerd.")
    tekst = "Gebruik de persoonlijke link naar uw projectdashboard die u van Nepocon heeft ontvangen."
    (SITE / "index.html").write_text(neutrale_pagina("Monitoringdashboard", tekst), encoding="utf-8")
    (SITE / "404.html").write_text(neutrale_pagina("Pagina niet gevonden", "Controleer de link. " + tekst),
                                   encoding="utf-8")
    (SITE / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    controleer_site(geheimen, projecten)
    print("Site klaar - %d dashboard(s), %d storing(en), veiligheidscontrole ok." % (
        len(projecten) - mislukt, mislukt))


if __name__ == "__main__":
    main()
