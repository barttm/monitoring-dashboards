#!/usr/bin/env python3
"""
zetting_dashboard.py
Genereert een standalone HTML-dashboard (zetting_dashboard.html) uit een
Basetime zakbaak-export (Result_of_Settlement_*.xlsx).

Gebruik:
    python zetting_dashboard.py
    python zetting_dashboard.py --bestand Result_of_Settlement_123.xlsx
    python zetting_dashboard.py --bestand data.xlsx --project "Projectnaam" --logo nepocon_logo.png
    python zetting_dashboard.py --export zetting_resultaten.xlsx

Belangrijk (lessen uit eerdere versie):
  - Height Groundplate = echte zetting ondergrond; Height Soil Level = ophoging/maaiveld.
    Altijd apart behandelen en apart togglebaar.
  - Tekenconventie: plaat NAP+2.00 -> NAP+1.90 = -100 mm zetting (zakking NEGATIEF,
    heave positief). Kaartjes, export en grafiek gebruiken hetzelfde teken; zakking gaat naar beneden.
  - Gaten in de data tot MAX_GAT_DAGEN worden in de grafiek overbrugd; langere gaten blijven zichtbaar.
  - Basetime-export is aflopend (nieuwste eerst) -> altijd chronologisch sorteren.
  - Radar >= 2 betekent een ongeldige maaiveldmeting (Soil Level = Groundplate) -> maskeren.
  - In de gegenereerde JS: GEEN backticks/template literals en GEEN inline onclick=.
    Alles via addEventListener en string-concatenatie.
  - Layout is vast (zie HTML_TEMPLATE) zodat elk project er identiek uitziet.
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONFIGURATIE
# ─────────────────────────────────────────────
EXCEL_BESTAND = "Result_of_Settlement_1790161660576.xlsx"
OUTPUT_HTML = "zetting_dashboard.html"
LOGO_PAD = "nepocon_logo.png"
PROJECTNAAM = "Projectnaam"

DATA_STARTRIJ = 5      # eerste datarij (0-based); rijen 0-4 zijn kopregels
BLOK_BREEDTE = 7       # aantal kolommen per zakbaak
# Kolom-offset binnen een zakbaak-blok
COL = {
    "easting": 0,
    "northing": 1,
    "radar": 2,
    "soil": 3,    # Height Soil Level [m+NAP]  -> maaiveld / ophoging
    "plate": 4,   # Height Groundplate [m+NAP] -> echte zetting ondergrond
    "rod": 5,     # Length Settlement Rod [m]
    "temp": 6,    # temperature
}

# Verstoorde zakbaken: data vóór 'herstart' wordt gemaskeerd, zetting herstart op 0.
# Label: '\n' = nieuwe regel in het labelkader in de grafiek.
# Voorbeeld:
# VERSTORINGEN = {
#     "ZB9": {"herstart": "2026-02-24",
#             "label": "ZB9 zakbaak verstoord\nmonitoring hervat na\n24-02-2026"},
# }
VERSTORINGEN = {}

# Ongeldige maaiveldmeting: radar >= RADAR_MAX (Basetime zet Soil Level dan gelijk aan Groundplate)
RADAR_MAX = 2.0

# Grafiek: ontbrekende dagen tot en met dit aantal worden met een lijn overbrugd
MAX_GAT_DAGEN = 3

# None = elke ZB t.o.v. eigen eerste meting; of "YYYY-MM-DD" = gemeenschappelijke referentiedatum
REFERENTIEDATUM = None

NEPOCON_BLAUW = "#004B8D"
KLEUREN = [
    "#004B8D", "#E05A1E", "#2CA02C", "#D62728", "#9467BD", "#8C564B",
    "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF", "#1F77B4", "#FF7F0E",
    "#6B8E23", "#B8860B", "#4682B4", "#C71585",
]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


# ─────────────────────────────────────────────
# INLEZEN
# ─────────────────────────────────────────────
def vind_blokken(df):
    """Zoek ZB-namen in de kopregels; val terug op vaste blokbreedte."""
    blokken, gezien = [], set()
    for c in range(1, df.shape[1]):
        for r in range(min(DATA_STARTRIJ, df.shape[0])):
            v = df.iat[r, c]
            if isinstance(v, str):
                m = re.search(r"ZB\s*-?\s*(\d+)", v, re.I)
                if m:
                    naam = "ZB" + m.group(1)
                    if naam not in gezien:
                        gezien.add(naam)
                        blokken.append((naam, c))
                    break
    if not blokken:
        n = (df.shape[1] - 1) // BLOK_BREEDTE
        blokken = [("ZB%d" % (i + 1), 1 + i * BLOK_BREEDTE) for i in range(n)]
    return blokken


def lees_data(pad):
    # pad = Excel-bestand of een DataFrame in exportlayout (bv. opgehaald via de API)
    df = pad if isinstance(pad, pd.DataFrame) else pd.read_excel(pad, header=None)
    blokken = vind_blokken(df)
    data = df.iloc[DATA_STARTRIJ:]
    datums = pd.to_datetime(data.iloc[:, 0], errors="coerce", format="mixed", dayfirst=True)

    resultaat = {}
    for naam, c0 in blokken:
        def kol(key):
            idx = c0 + COL[key]
            if idx >= df.shape[1]:
                return np.full(len(data), np.nan)
            return pd.to_numeric(data.iloc[:, idx], errors="coerce").values

        d = pd.DataFrame({
            "datum": datums.values,
            "soil": kol("soil"),
            "plate": kol("plate"),
            "rod": kol("rod"),
        })
        # Ongeldige radarmeting -> maaiveld onbekend (grondplaat blijft geldig)
        radar = kol("radar")
        ongeldig = (radar >= RADAR_MAX) | np.isclose(d["soil"].values, d["plate"].values)
        d.loc[ongeldig, "soil"] = np.nan

        d = d.dropna(subset=["datum"]).dropna(subset=["soil", "plate"], how="all")
        if d.empty:
            continue
        # Chronologisch + 1 waarde per dag (daggemiddelde)
        d["dag"] = pd.to_datetime(d["datum"]).dt.strftime("%Y-%m-%d")
        d = d.groupby("dag", as_index=False)[["soil", "plate", "rod"]].mean()
        d = d.sort_values("dag").reset_index(drop=True)

        if naam in VERSTORINGEN:
            d = d[d["dag"] >= VERSTORINGEN[naam]["herstart"]].reset_index(drop=True)
        if not d.empty:
            resultaat[naam] = d
    return resultaat


# ─────────────────────────────────────────────
# BEREKENEN
# ─────────────────────────────────────────────
def referentie_plaat(d):
    geldig = d.dropna(subset=["plate"])
    if geldig.empty:
        return None
    if REFERENTIEDATUM:
        na = geldig[geldig["dag"] >= REFERENTIEDATUM]
        if not na.empty:
            return float(na["plate"].iloc[0])
    return float(geldig["plate"].iloc[0])


def bereken(data):
    for naam, d in data.items():
        ref = referentie_plaat(d)
        # zakking negatief: (huidig - start) * 1000
        d["zet_mm"] = (d["plate"] - ref) * 1000.0 if ref is not None else np.nan
    return data


def stats(naam, d):
    p = d["plate"].dropna()
    s = d["soil"].dropna()
    z = d["zet_mm"].dropna()
    return {
        "zet_totaal_mm": round(float(z.iloc[-1]), 1) if len(z) else None,
        "zet_max_mm": round(float(z.min()), 1) if len(z) else None,   # grootste zakking
        "gplate_start": float(p.iloc[0]) if len(p) else None,
        "gplate_huidig": float(p.iloc[-1]) if len(p) else None,
        "soil_start": float(s.iloc[0]) if len(s) else None,
        "soil_huidig": float(s.iloc[-1]) if len(s) else None,
        "eerste_datum": d["dag"].iloc[0],
        "laatste_datum": d["dag"].iloc[-1],
        "n_metingen": int(len(d)),
    }


def schoon(lijst, decimalen):
    return [None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(float(v), decimalen)
            for v in lijst]


def zb_sort_key(naam):
    m = re.search(r"\d+", naam)
    return int(m.group()) if m else 0


def periode_label(start, eind):
    """'2026-01-17','2026-04-29' -> 'jan – apr 2026'."""
    a, b = pd.Timestamp(start), pd.Timestamp(eind)
    ma, mb = MAANDEN[a.month - 1], MAANDEN[b.month - 1]
    if a.year == b.year:
        return "%s %d" % (ma, a.year) if a.month == b.month else "%s – %s %d" % (ma, mb, a.year)
    return "%s %d – %s %d" % (ma, a.year, mb, b.year)


def bouw_payload(data, project):
    zbs = sorted(data.keys(), key=zb_sort_key)
    alle_st = {z: stats(z, data[z]) for z in zbs}
    start = min(s["eerste_datum"] for s in alle_st.values())
    eind = max(s["laatste_datum"] for s in alle_st.values())
    return {
        "project": project,
        "maxgat": MAX_GAT_DAGEN,
        "periode": periode_label(start, eind),
        "zbs": zbs,
        "colors": {z: KLEUREN[i % len(KLEUREN)] for i, z in enumerate(zbs)},
        "series": {
            z: {
                "dates": list(data[z]["dag"]),
                "soil": schoon(data[z]["soil"].tolist(), 4),
                "plate": schoon(data[z]["plate"].tolist(), 4),
                "zet": schoon(data[z]["zet_mm"].tolist(), 1),
            } for z in zbs
        },
        "stats": alle_st,
        "verstoringen": {z: v for z, v in VERSTORINGEN.items() if z in data},
    }


# ─────────────────────────────────────────────
# HTML  (vaste layout - niet per project aanpassen)
# ─────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zettingsdashboard - __PROJECT__</title>
<meta name="referrer" content="no-referrer">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js" integrity="sha384-bs/nf9FbdNouRbMiFcrcZfLXYPKiPaGVGplVbv7dLGECccEXDW+S3zjqSKR5ZEaD" crossorigin="anonymous"></script>
<style>
:root {
  --blauw: #004B8D; --tekst: #1a2233; --grijs: #6b7686; --lijn: #dfe4ec; --bg: #f5f7fa;
  --oranje: #E07B00; --groen: #2CA02C; --rood: #D62728; --heave: #1f5fbf;
  --sans: "Segoe UI", "IBM Plex Sans", Arial, sans-serif;
  --mono: Consolas, "IBM Plex Mono", "Courier New", monospace;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: var(--sans); background: var(--bg); color: var(--tekst); }

/* Header */
header { display: flex; align-items: center; gap: 20px; padding: 8px 24px; background: #fff;
         border-bottom: 3px solid var(--blauw); }
header img { height: 42px; display: block; }
header .logo-txt { font-weight: 800; font-size: 26px; color: var(--blauw); letter-spacing: 1px; }
header .sep { width: 1px; align-self: stretch; background: var(--lijn); margin: 4px 0; }
header h1 { font-size: 15px; margin: 0 0 3px; font-weight: 700; color: var(--tekst); }
header .sub { font-family: var(--mono); font-size: 12px; color: var(--grijs); }
header .sub .pipe { margin: 0 8px; }

.wrap { display: grid; grid-template-columns: 246px 1fr; min-height: calc(100vh - 62px); }

/* Sidebar */
aside { background: #fff; border-right: 1px solid var(--lijn); }
.sb-sec { padding: 18px 12px 16px; border-bottom: 1px solid var(--lijn); }
.sb-sec h3 { font-size: 10px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase;
             color: var(--blauw); margin: 0 0 12px; }
.layer { display: flex; align-items: center; gap: 10px; padding: 9px 10px; margin-bottom: 6px;
         border: 1px solid var(--lijn); border-radius: 4px; cursor: pointer; user-select: none; background: #fff; }
.layer.on { border-color: var(--blauw); }
.layer .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.layer .lt { flex: 1; min-width: 0; }
.layer .ln { font-size: 12px; font-weight: 600; }
.layer .ls { font-size: 9.5px; color: var(--grijs); margin-top: 1px; }
.layer .sw { position: relative; width: 30px; height: 16px; border-radius: 8px; background: #c9d1dc; flex: none; }
.layer .sw::after { content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px;
                    border-radius: 50%; background: #fff; transition: left .15s; }
.layer.on .sw { background: var(--blauw); }
.layer.on .sw::after { left: 16px; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.actions button { font-family: var(--sans); font-size: 11px; padding: 7px 0; border: 1px solid var(--lijn);
                  background: #f3f5f8; color: var(--grijs); border-radius: 3px; cursor: pointer; }
.actions button:hover { border-color: var(--blauw); color: var(--blauw); }
.zbgrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; }
.zbbtn { padding: 8px 0; text-align: center; font-family: var(--mono); font-size: 11px; font-weight: 700;
         border-radius: 3px; cursor: pointer; user-select: none; border: 1px solid var(--lijn);
         background: #fff; color: #9aa3b0; }
.zbbtn.on { background: var(--blauw); border-color: var(--blauw); color: #fff; }

/* Main */
main { padding: 20px 20px; min-width: 0; }
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 11px; margin-bottom: 16px; }
.stat-card { background: #fff; border: 1px solid var(--lijn); border-radius: 4px; padding: 12px 14px 10px;
             cursor: pointer; user-select: none; font-family: var(--mono); }
.stat-card.on { border-color: var(--blauw); }
.sc-name { font-size: 11px; font-weight: 700; margin-bottom: 4px; }
.sc-val { font-size: 18px; font-weight: 700; margin-bottom: 6px; }
.sc-val .u { font-size: 14px; margin-left: 4px; }
.z-zak { color: var(--rood); } .z-heave { color: var(--heave); } .z-nul { color: var(--grijs); }
.sc-sub { font-family: var(--sans); font-size: 9.5px; color: var(--grijs); margin-bottom: 6px; }
.sc-nap, .sc-per { font-size: 10px; color: #4b5563; line-height: 1.45; }
.sc-per { margin-top: 6px; }
.sc-warn { font-family: var(--sans); font-size: 9.5px; color: var(--oranje); margin-top: 6px; }

.panel { background: #fff; border: 1px solid var(--lijn); border-radius: 4px; padding: 16px 18px 12px; margin-bottom: 16px; }
.ph { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.ph h2 { font-size: 13px; font-weight: 700; margin: 0; }
.ph h2 .sel { font-family: var(--mono); font-weight: 700; color: var(--blauw); }
.ph .psub { font-size: 10.5px; color: var(--grijs); margin-top: 3px; }
.legend { display: flex; gap: 16px; font-size: 10.5px; color: var(--grijs); white-space: nowrap; padding-top: 2px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { display: inline-block; width: 20px; border-top: 2px solid; }
.legend i.dash { border-top-style: dashed; }
.cbox { position: relative; height: 300px; }
.hidden { display: none !important; }

/* Bewerkmodus: teksten en opmerkingen aanpassen in de browser, opslaan in dit HTML-bestand */
.hbtns { margin-left: auto; display: flex; gap: 8px; }
.hbtn { font-family: var(--sans); font-size: 12px; padding: 6px 12px; border: 1px solid var(--blauw);
        background: #fff; color: var(--blauw); border-radius: 3px; cursor: pointer; }
.hbtn.prim { background: var(--blauw); color: #fff; }
.editbar { display: none; background: #fff8ec; border-bottom: 1px solid #f3d9b0; color: #8a4b00;
           font-size: 12px; padding: 7px 24px; }
body.edit .editbar { display: block; }
body.edit [data-edit] { outline: 1px dashed var(--oranje); outline-offset: 2px; background: #fffaf0; cursor: text; user-select: text; }
body.edit [data-edit]:empty::before { content: attr(data-ph); color: #b0b7c3; }
body.edit .stat-card { cursor: default; }
.sc-opm { font-family: var(--sans); font-size: 10.5px; color: var(--tekst); background: #fff8ec;
          border-left: 3px solid var(--oranje); padding: 4px 6px; margin-top: 8px; white-space: pre-wrap; line-height: 1.4; }
.sc-opm:empty { display: none; }
body.edit .sc-opm:empty { display: block; }
.opm-tekst { font-size: 12.5px; white-space: pre-wrap; line-height: 1.5; min-height: 1.5em; }
@media (max-width: 800px) {
  .wrap { grid-template-columns: 1fr; }
  aside { border-right: 0; border-bottom: 1px solid var(--lijn); }
  .ph { flex-direction: column; }
}
</style>
</head>
<body>
<header>
  __LOGO__
  <div class="sep"></div>
  <div>
    <h1 data-edit="titel" data-single="1">Zettingsdashboard &mdash; __PROJECT__</h1>
    <div class="sub" data-edit="sub" data-single="1">Settlement rod metingen | __PERIODE__ | __NZB__ zakbaken</div>
  </div>
  <div class="hbtns">
    <button class="hbtn" id="btn-edit">&#9998; Bewerken</button>
    <button class="hbtn prim hidden" id="btn-save">Opslaan</button>
  </div>
</header>
<div class="editbar">Bewerkmodus &mdash; klik op een tekst met oranje stippellijn om die te wijzigen; onderaan elk kaartje kun je een opmerking per zakbaak typen.
  Klik <b>Opslaan</b> en kies dit HTML-bestand om de wijzigingen te bewaren.</div>
<div class="wrap">
  <aside>
    <div class="sb-sec">
      <h3>Datalaag</h3>
      <div class="layer on" id="tgl-soil"><span class="dot" style="background:#E07B00"></span>
        <div class="lt"><div class="ln">Maaiveld hoogte</div><div class="ls">Height Soil Level [m+NAP]</div></div><span class="sw"></span></div>
      <div class="layer on" id="tgl-plate"><span class="dot" style="background:#2CA02C"></span>
        <div class="lt"><div class="ln">Grondplaat hoogte</div><div class="ls">Height Groundplate [m+NAP]</div></div><span class="sw"></span></div>
      <div class="layer on" id="tgl-zetting"><span class="dot" style="background:#D62728"></span>
        <div class="lt"><div class="ln">Zetting grondplaat</div><div class="ls">t.o.v. beginmeting [mm]</div></div><span class="sw"></span></div>
    </div>
    <div class="sb-sec">
      <h3>Zakbaken</h3>
      <div class="actions">
        <button id="btn-sel-all">Alle aan</button>
        <button id="btn-desel-all">Alle uit</button>
      </div>
      <div class="zbgrid" id="zbgrid"></div>
    </div>
  </aside>
  <main>
    <div class="stats" id="stats"></div>
    <div class="panel" id="panel-opm">
      <div class="ph"><h2>Opmerkingen</h2></div>
      <div class="opm-tekst" data-edit="opmerkingen" data-ph="Algemene opmerkingen of toelichting typen..."></div>
    </div>
    <div class="panel" id="panel-nap">
      <div class="ph">
        <div>
          <h2>Absolute hoogte [m+NAP] &mdash; <span class="sel" id="chart1-title"></span></h2>
          <div class="psub" data-edit="p1-sub">Maaiveld (ophoging) en grondplaat op datum</div>
        </div>
        <div class="legend">
          <span id="lg-soil"><i style="border-color:#E07B00"></i>Maaiveld</span>
          <span id="lg-plate"><i class="dash" style="border-color:#2CA02C"></i>Grondplaat</span>
        </div>
      </div>
      <div class="cbox"><canvas id="cNAP"></canvas></div>
    </div>
    <div class="panel" id="panel-zet">
      <div class="ph">
        <div>
          <h2>Zetting grondplaat [mm] &mdash; <span class="sel" id="chart2-title"></span></h2>
          <div class="psub" data-edit="p2-sub">Zakking gaat naar beneden | heave gaat naar boven</div>
        </div>
        <div class="legend"><span><i style="border-color:#D62728"></i>Zetting (mm)</span></div>
      </div>
      <div class="cbox"><canvas id="cZet"></canvas></div>
    </div>
  </main>
</div>
<script>
// Ongewijzigde pagina bewaren: bij Opslaan wordt alleen het EDITS-blok hierin vervangen
var ORIG = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
var EDITS = __EDITS__;//EDITS-END
var D = __DATA__;
var ZBS = D.zbs;
var activeZBs = {};
ZBS.forEach(function(z){ activeZBs[z] = true; });
var showSoil = true, showPlate = true, showZet = true;
var chartNAP = null, chartZetting = null;
var MONO = 'Consolas, "IBM Plex Mono", monospace';

Chart.defaults.font.family = '"Segoe UI", "IBM Plex Sans", Arial, sans-serif';
Chart.defaults.font.size = 10;
Chart.defaults.color = '#6b7686';

function getAllDates() {
  var s = {};
  ZBS.forEach(function(z){ D.series[z].dates.forEach(function(d){ s[d] = 1; }); });
  return Object.keys(s).sort();
}
var ALL = getAllDates();

function align(z, key, factor) {
  var map = {}, s = D.series[z];
  for (var i = 0; i < s.dates.length; i++) { map[s.dates[i]] = s[key][i]; }
  return ALL.map(function(d){
    var v = map[d];
    if (v === undefined || v === null) return null;
    return factor ? v * factor : v;
  });
}

// Korte gaten (<= MAX_GAT_DAGEN) worden overbrugd, langere gaten blijven een onderbreking
function gapColor(ctx) {
  if (!ctx.p0.skip && !ctx.p1.skip) return undefined;
  var data = ctx.chart.data.datasets[ctx.datasetIndex].data;
  var a = ctx.p0DataIndex, b = ctx.p1DataIndex;
  while (a > 0 && data[a] === null) a--;
  while (b < data.length - 1 && data[b] === null) b++;
  return (b - a - 1 > D.maxgat) ? 'rgba(0,0,0,0)' : undefined;
}

function lineDs(label, data, c, dash) {
  return { label: label, data: data, borderColor: c, backgroundColor: c, borderWidth: 1.5,
           borderDash: dash || [], pointRadius: 1.5, pointHoverRadius: 4, spanGaps: true, tension: 0.3,
           segment: { borderColor: gapColor } };
}

function buildDatasets_NAP() {
  var out = [];
  ZBS.forEach(function(z){
    if (!activeZBs[z]) return;
    var c = D.colors[z];
    if (showSoil) out.push(lineDs(z + ' maaiveld', align(z, 'soil'), c));
    if (showPlate) out.push(lineDs(z + ' grondplaat', align(z, 'plate'), c, [4, 3]));
  });
  return out;
}

function buildDatasets_Zetting() {
  var out = [];
  ZBS.forEach(function(z){
    if (!activeZBs[z]) return;
    out.push(lineDs(z, align(z, 'zet'), D.colors[z]));
  });
  return out;
}

var verstoringPlugin = {
  id: 'verstoring',
  afterDatasetsDraw: function(chart) {
    var xs = chart.scales.x, area = chart.chartArea, ctx = chart.ctx;
    Object.keys(D.verstoringen).forEach(function(z){
      if (!activeZBs[z]) return;
      var v = D.verstoringen[z], idx = -1;
      for (var i = 0; i < ALL.length; i++) { if (ALL[i] >= v.herstart) { idx = i; break; } }
      if (idx < 0) return;
      var x = xs.getPixelForValue(idx);
      ctx.save();
      ctx.strokeStyle = '#E07B00'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = '10px ' + MONO;
      var lines = String(v.label).split('\n'), w = 0, lh = 12;
      lines.forEach(function(l){ w = Math.max(w, ctx.measureText(l).width); });
      var bw = w + 12, bh = lines.length * lh + 8;
      var bx = Math.max(area.left + 2, Math.min(x - bw / 2, area.right - bw - 2));
      var by = area.bottom - bh - 6;
      ctx.fillStyle = '#FFF8EC'; ctx.strokeStyle = '#E07B00'; ctx.lineWidth = 1;
      ctx.fillRect(bx, by, bw, bh); ctx.strokeRect(bx, by, bw, bh);
      ctx.fillStyle = '#8a4b00'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      lines.forEach(function(l, k){ ctx.fillText(l, bx + bw / 2, by + 4 + k * lh); });
      ctx.restore();
    });
  }
};

function baseOptions(yExtra) {
  var y = { grid: { color: '#eef1f5' }, border: { display: false }, ticks: { padding: 6 } };
  for (var k in yExtra) { y[k] = yExtra[k]; }
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { bodyFont: { family: MONO, size: 11 }, titleFont: { family: MONO, size: 11 } }
    },
    scales: {
      x: { ticks: { maxTicksLimit: 13, maxRotation: 0, autoSkip: true }, grid: { color: '#eef1f5' } },
      y: y
    }
  };
}

function initCharts() {
  chartNAP = new Chart(document.getElementById('cNAP'), {
    type: 'line', data: { labels: ALL, datasets: buildDatasets_NAP() },
    options: baseOptions({}), plugins: [verstoringPlugin]
  });
  chartZetting = new Chart(document.getElementById('cZet'), {
    type: 'line', data: { labels: ALL, datasets: buildDatasets_Zetting() },
    options: baseOptions({
      title: { display: true, text: 'heave ↑', font: { size: 10 } },
      ticks: { padding: 6, callback: function(v){ return v + ' mm'; } }
    }),
    plugins: [verstoringPlugin]
  });
  updateCharts();
}

function updateCharts() {
  var activeList = ZBS.filter(function(z){ return activeZBs[z]; });
  var title = activeList.length === ZBS.length ? 'alle zakbaken' :
    (activeList.length === 0 ? 'geen selectie' : activeList.join(', '));
  document.getElementById('chart1-title').textContent = title;
  document.getElementById('chart2-title').textContent = title;
  document.getElementById('panel-nap').classList.toggle('hidden', !showSoil && !showPlate);
  document.getElementById('panel-zet').classList.toggle('hidden', !showZet);
  document.getElementById('lg-soil').classList.toggle('hidden', !showSoil);
  document.getElementById('lg-plate').classList.toggle('hidden', !showPlate);
  chartNAP.data.datasets = buildDatasets_NAP();
  chartNAP.update('none');
  chartZetting.data.datasets = buildDatasets_Zetting();
  chartZetting.update('none');
}

// Knop links en kaartje rechts krijgen dezelfde ZB-kleur als de grafieklijn
function kleurZB(z) {
  var on = activeZBs[z], c = D.colors[z];
  var btn = document.getElementById('zbbtn-' + z), card = document.getElementById('sc-' + z);
  btn.classList.toggle('on', on);
  btn.style.background = on ? c : '#fff';
  btn.style.borderColor = on ? c : '';
  card.classList.toggle('on', on);
  card.style.borderColor = on ? c : '';
  card.style.boxShadow = on ? 'inset 0 3px 0 ' + c : 'none';
}

function toggleZB(z) {
  activeZBs[z] = !activeZBs[z];
  kleurZB(z);
  updateCharts();
}

function setAll(state) {
  ZBS.forEach(function(z){ if (activeZBs[z] !== state) { toggleZB(z); } });
}

function buildZBButtons() {
  var grid = document.getElementById('zbgrid');
  ZBS.forEach(function(z){
    var b = document.createElement('div');
    b.className = 'zbbtn on';
    b.id = 'zbbtn-' + z;
    b.textContent = z;
    b.addEventListener('click', function(){ toggleZB(z); });
    grid.appendChild(b);
  });
}

function fmt(v, n) { return (v === null || v === undefined) ? '--' : v.toFixed(n); }
function nlDatum(iso) { var p = iso.split('-'); return p[2] + '-' + p[1] + '-' + p[0]; }

function buildStats() {
  var row = document.getElementById('stats');
  ZBS.forEach(function(z){
    var d = D.stats[z], color = D.colors[z];
    var v = d.zet_totaal_mm;
    var cls = v === null ? 'z-nul' : (v < 0 ? 'z-zak' : 'z-heave');
    var html =
      '<div class="sc-name" style="color:' + color + '">' + z + '</div>' +
      '<div class="sc-val ' + cls + '">' + fmt(v, 0) + '<span class="u">mm</span></div>' +
      '<div class="sc-sub">zetting grondplaat totaal</div>' +
      '<div class="sc-nap">Plaat: ' + fmt(d.gplate_start, 3) + ' → ' + fmt(d.gplate_huidig, 3) + '<br>m+NAP</div>' +
      '<div class="sc-per">' + d.eerste_datum + ' –<br>' + d.laatste_datum + '</div>' +
      '<div class="sc-opm" data-edit="opm-' + z + '" data-ph="Opmerking toevoegen..."></div>';
    if (D.verstoringen[z]) {
      html += '<div class="sc-warn">⚠ verstoord vóór ' + nlDatum(D.verstoringen[z].herstart) + '</div>';
    }
    var card = document.createElement('div');
    card.className = 'stat-card on';
    card.id = 'sc-' + z;
    card.innerHTML = html;
    card.addEventListener('click', function(){ if (!editMode) { toggleZB(z); } });
    row.appendChild(card);
  });
}

document.getElementById('tgl-soil').addEventListener('click', function() {
  showSoil = !showSoil; this.classList.toggle('on', showSoil); updateCharts();
});
document.getElementById('tgl-plate').addEventListener('click', function() {
  showPlate = !showPlate; this.classList.toggle('on', showPlate); updateCharts();
});
document.getElementById('tgl-zetting').addEventListener('click', function() {
  showZet = !showZet; this.classList.toggle('on', showZet); updateCharts();
});
document.getElementById('btn-sel-all').addEventListener('click', function() { setAll(true); });
document.getElementById('btn-desel-all').addEventListener('click', function() { setAll(false); });

// ── Bewerkmodus ──────────────────────────────
var editMode = false, dirty = false;
var TEKST = {}, DEF = {};

function editEls() { return Array.prototype.slice.call(document.querySelectorAll('[data-edit]')); }

function applyEdits() {
  var t = (EDITS && EDITS.teksten) || {};
  editEls().forEach(function(el){
    var k = el.getAttribute('data-edit');
    DEF[k] = el.textContent;
    if (Object.prototype.hasOwnProperty.call(t, k)) { el.textContent = t[k]; TEKST[k] = t[k]; }
  });
  updateOpmPanel();
}

function updateOpmPanel() {
  var leeg = !document.querySelector('[data-edit="opmerkingen"]').textContent.trim();
  document.getElementById('panel-opm').classList.toggle('hidden', leeg && !editMode);
}

function setEditMode(on) {
  editMode = on;
  document.body.classList.toggle('edit', on);
  editEls().forEach(function(el){
    if (on) { el.setAttribute('contenteditable', 'true'); } else { el.removeAttribute('contenteditable'); }
  });
  document.getElementById('btn-edit').innerHTML = on ? '&#10003; Klaar' : '&#9998; Bewerken';
  document.getElementById('btn-save').classList.toggle('hidden', !on && !dirty);
  updateOpmPanel();
}

function markDirty(d) {
  dirty = d;
  document.getElementById('btn-save').textContent = d ? 'Opslaan •' : 'Opslaan';
  document.getElementById('btn-save').classList.toggle('hidden', !editMode && !d);
}

function onEditInput(e) {
  var el = e.target.closest('[data-edit]');
  if (!el) return;
  var k = el.getAttribute('data-edit');
  var v = el.innerText.replace(/\n+$/, '');
  if (v === DEF[k]) { delete TEKST[k]; } else { TEKST[k] = v; }
  markDirty(true);
}

function escJson(s) {
  return s.replace(/<\//g, '<\\/')
          .replace(new RegExp(String.fromCharCode(96), 'g'), '\\u0060')
          .replace(new RegExp('onclick' + '=', 'gi'), 'onclick\\u003d');
}

function buildHtml() {
  var open = 'var EDITS' + ' = ', close = ';//EDITS' + '-END';
  var a = ORIG.indexOf(open), b = ORIG.indexOf(close, a);
  var ed = { teksten: TEKST, opgeslagen: new Date().toISOString().slice(0, 16).replace('T', ' ') };
  return ORIG.slice(0, a) + open + escJson(JSON.stringify(ed)) + ORIG.slice(b);
}

function downloadHtml(html, name) {
  var blob = new Blob([html], { type: 'text/html' });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(function(){ URL.revokeObjectURL(a.href); }, 2000);
  markDirty(false);
  alert('Opgeslagen als download: ' + name + '\nZet dit bestand over de oude versie in de projectmap.');
}

function saveHtml() {
  var html = buildHtml();
  var name = decodeURIComponent(location.pathname.split('/').pop() || '') || 'zetting_dashboard.html';
  if (window.showSaveFilePicker) {
    window.showSaveFilePicker({ suggestedName: name, types: [{ description: 'HTML', accept: { 'text/html': ['.html'] } }] })
      .then(function(h){ return h.createWritable(); })
      .then(function(w){ return w.write(html).then(function(){ return w.close(); }); })
      .then(function(){ markDirty(false); })
      .catch(function(e){ if (!e || e.name !== 'AbortError') { downloadHtml(html, name); } });
  } else {
    downloadHtml(html, name);
  }
}

document.addEventListener('input', onEditInput);
document.addEventListener('keydown', function(e){
  var el = e.target.closest ? e.target.closest('[data-single]') : null;
  if (el && e.key === 'Enter') { e.preventDefault(); el.blur(); }
});
document.addEventListener('paste', function(e){
  if (!e.target.closest || !e.target.closest('[data-edit]')) return;
  e.preventDefault();
  document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text'));
});
document.getElementById('btn-edit').addEventListener('click', function(){ setEditMode(!editMode); });
document.getElementById('btn-save').addEventListener('click', saveHtml);
window.addEventListener('beforeunload', function(e){ if (dirty) { e.preventDefault(); e.returnValue = ''; } });

buildZBButtons();
buildStats();
ZBS.forEach(kleurZB);
applyEdits();
initCharts();
</script>
</body>
</html>
"""


def logo_html(pad):
    p = Path(pad)
    if p.exists():
        mime = "image/svg+xml" if p.suffix.lower() == ".svg" else "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return '<img src="data:' + mime + ';base64,' + b64 + '" alt="Nepocon">'
    return '<span class="logo-txt">nepocon</span>'


EDITS_START = "var EDITS = "
EDITS_EIND = ";//EDITS-END"


def lees_edits(pad):
    """Haal teksten/opmerkingen (bewerkmodus) uit een eerder opgeslagen dashboard-HTML."""
    p = Path(pad) if pad else None
    if not p or not p.exists():
        return {"teksten": {}}
    try:
        t = p.read_text(encoding="utf-8")
        a = t.index(EDITS_START) + len(EDITS_START)
        b = t.index(EDITS_EIND, a)
        ed = json.loads(t[a:b])
        ed.setdefault("teksten", {})
        return ed
    except (ValueError, json.JSONDecodeError):
        return {"teksten": {}}


def js_json(obj):
    """JSON veilig in een <script> zetten (en de backtick/onclick-guard niet laten struikelen)."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("</", "<\\/").replace("`", "\\u0060").replace("onclick=", "onclick\\u003d"))


def bouw_html(payload, logo_pad, edits=None):
    html = HTML_TEMPLATE
    html = html.replace("__EDITS__", js_json(edits or {"teksten": {}}))
    html = html.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    html = html.replace("__LOGO__", logo_html(logo_pad))
    html = html.replace("__PROJECT__", payload["project"])
    html = html.replace("__PERIODE__", payload["periode"])
    html = html.replace("__NZB__", str(len(payload["zbs"])))
    return html


def exporteer(data, pad):
    with pd.ExcelWriter(pad) as xw:
        samenvatting = pd.DataFrame({z: stats(z, d) for z, d in data.items()}).T
        samenvatting.to_excel(xw, sheet_name="Samenvatting")
        for z in sorted(data.keys(), key=zb_sort_key):
            data[z].to_excel(xw, sheet_name=z, index=False)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Zakbaak zettingsdashboard generator")
    ap.add_argument("--bestand", default=EXCEL_BESTAND)
    ap.add_argument("--output", default=OUTPUT_HTML)
    ap.add_argument("--project", default=PROJECTNAAM)
    ap.add_argument("--logo", default=LOGO_PAD)
    ap.add_argument("--zakbaken", nargs="*", help="Alleen deze zakbaken, bv. ZB1 ZB3")
    ap.add_argument("--export", help="Optioneel: resultaten naar .xlsx")
    ap.add_argument("--opmerkingen", help="HTML waaruit teksten/opmerkingen worden overgenomen "
                                          "(standaard: de bestaande --output)")
    args = ap.parse_args()

    if not Path(args.bestand).exists():
        sys.exit("Bestand niet gevonden: " + args.bestand)

    data = bereken(lees_data(args.bestand))
    if args.zakbaken:
        keuze = {z.upper() for z in args.zakbaken}
        data = {z: d for z, d in data.items() if z.upper() in keuze}
    if not data:
        sys.exit("Geen zakbaakdata gevonden - controleer DATA_STARTRIJ / BLOK_BREEDTE / COL.")

    # Teksten/opmerkingen uit de bewerkmodus blijven behouden bij een nieuwe data-export
    edits = lees_edits(args.opmerkingen or args.output)
    html = bouw_html(bouw_payload(data, args.project), args.logo, edits)
    # Guard: geen backticks of inline onclick in de output
    assert "`" not in html, "Backtick in HTML gevonden"
    assert "onclick=" not in html, "Inline onclick gevonden"
    Path(args.output).write_text(html, encoding="utf-8")

    print("Dashboard: %s (%s bytes)" % (args.output, format(len(html), ",")))
    if edits["teksten"]:
        print("  %d aangepaste tekst(en)/opmerking(en) overgenomen" % len(edits["teksten"]))
    for z in sorted(data.keys(), key=zb_sort_key):
        s = stats(z, data[z])
        print("  %-5s  zetting %7s mm  | %s t/m %s | %d metingen" % (
            z, s["zet_totaal_mm"], s["eerste_datum"], s["laatste_datum"], s["n_metingen"]))

    if args.export:
        exporteer(data, args.export)
        print("Export:", args.export)


if __name__ == "__main__":
    main()
