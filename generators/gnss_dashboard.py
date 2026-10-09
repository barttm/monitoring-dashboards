#!/usr/bin/env python3
"""
gnss_dashboard.py
Genereert een standalone, interactief D3-dashboard (gnss_dashboard.html) uit een
Basetime GNSS-export (Results_of_measureme_*.xlsx): verschil hoogte / easting / northing
per meetpunt + bovenaanzicht (kaart met PDOK-luchtfoto of BRT-kaart en verplaatsingsvectoren).

Gebruik:
    python gnss_dashboard.py
    python gnss_dashboard.py --bestand Results_of_measureme_123.xlsx --vanaf "2026-09-22 13:00"

Belangrijk:
  - Export heeft vóór VANAF een foute offset (hoogte ~ -36 m i.p.v. ~ +6 m, E/N ~48 m / ~7 m verschoven).
    Alleen data vanaf VANAF wordt gebruikt; de 'Difference'-kolommen uit Basetime worden NIET gebruikt
    (die zijn t.o.v. de foute nulmeting) -> verschillen worden zelf berekend t.o.v. de nieuwe nulmeting.
  - Tijden zijn UTC (zoals in de Basetime-export).
  - Verschil = (waarde - nulpunt) * 1000 [mm]; omhoog / oost / noord = positief.
  - In de gegenereerde JS: GEEN backticks/template literals en GEEN inline onclick=.
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
EXCEL_BESTAND = "Results_of_measureme_1790780301533.xlsx"
OUTPUT_HTML = "gnss_dashboard.html"
LOGO_PAD = "nepocon_logo.png"
PROJECTNAAM = "Projectnaam"

VANAF = "2026-09-22 13:00"   # data hiervoor heeft een offset-fout -> weggelaten (UTC)
DATA_STARTRIJ = 6            # eerste datarij (0-based); rij 2 = puntnamen, rij 5 = kolomkoppen
NAAM_RIJ = 2
KOP_RIJ = 5

KLEUREN = ["#004B8D", "#E05A1E", "#2CA02C", "#9467BD", "#8C564B", "#E377C2",
           "#17BECF", "#BCBD22", "#D62728", "#7F7F7F"]


# ─────────────────────────────────────────────
# INLEZEN
# ─────────────────────────────────────────────
def lees_data(pad, vanaf):
    # pad = Excel-bestand of een DataFrame in exportlayout (bv. opgehaald via de API)
    df = pad if isinstance(pad, pd.DataFrame) else pd.read_excel(pad, header=None)
    namen = [(c, str(df.iat[NAAM_RIJ, c]).strip()) for c in range(1, df.shape[1])
             if isinstance(df.iat[NAAM_RIJ, c], str)]
    if not namen:
        sys.exit("Geen meetpuntnamen gevonden in rij %d." % NAAM_RIJ)
    starts = [c for c, _ in namen] + [df.shape[1]]

    data = df.iloc[DATA_STARTRIJ:]
    tijd = pd.to_datetime(data.iloc[:, 0], errors="coerce", format="mixed")
    grens = pd.Timestamp(vanaf)

    punten = []
    for i, (c0, naam) in enumerate(namen):
        kop = {str(df.iat[KOP_RIJ, c]).strip().lower(): c for c in range(c0, starts[i + 1])}

        def kol(k):
            return pd.to_numeric(data.iloc[:, kop[k] - 0], errors="coerce").values if k in kop else \
                np.full(len(data), np.nan)

        d = pd.DataFrame({"t": tijd.values, "E": kol("easting"), "N": kol("northing"), "H": kol("height")})
        d = d.dropna(subset=["t"])
        d = d[d["t"] >= grens].sort_values("t")
        d = d.dropna(subset=["E", "N", "H"], how="all")
        m = re.search(r"([A-Za-z]\d+)$", naam)
        punten.append({"id": naam, "kort": m.group(1) if m else naam, "df": d})
    return punten


def schoon(v, n):
    return [None if pd.isna(x) else round(float(x), n) for x in v]


def bouw_payload(punten, project, vanaf):
    tijden = sorted(set(t for p in punten for t in p["df"]["t"]))
    T = [pd.Timestamp(t).strftime("%Y-%m-%d %H:%M") for t in tijden]
    out = []
    for i, p in enumerate(punten):
        d = p["df"].set_index("t").reindex(tijden)
        out.append({
            "id": p["id"], "kort": p["kort"], "kleur": KLEUREN[i % len(KLEUREN)],
            "E": schoon(d["E"], 4), "N": schoon(d["N"], 4), "H": schoon(d["H"], 4),
        })
    return {"project": project, "vanaf": vanaf, "T": T, "punten": out}


def periode_label(T):
    a, b = pd.Timestamp(T[0]), pd.Timestamp(T[-1])
    return a.strftime("%d-%m-%Y %H:%M") + " – " + b.strftime("%d-%m-%Y %H:%M") + " UTC"


# ─────────────────────────────────────────────
# HTML  (vaste layout, zelfde huisstijl als zettingsdashboard)
# ─────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verplaatsingsdashboard - __PROJECT__</title>
<meta name="referrer" content="no-referrer">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js" integrity="sha384-CjloA8y00+1SDAUkjs099PVfnY2KmDC2BZnws9kh8D/lX1s46w6EPhpXdqMfjK6i" crossorigin="anonymous"></script>
<style>
:root {
  --blauw: #004B8D; --tekst: #1a2233; --grijs: #6b7686; --lijn: #dfe4ec; --bg: #f5f7fa;
  --oranje: #E07B00; --rood: #D62728; --heave: #1f5fbf;
  --sans: "Segoe UI", "IBM Plex Sans", Arial, sans-serif;
  --mono: Consolas, "IBM Plex Mono", "Courier New", monospace;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: var(--sans); background: var(--bg); color: var(--tekst); }
header { display: flex; align-items: center; gap: 20px; padding: 8px 24px; background: #fff; border-bottom: 3px solid var(--blauw); }
header img { height: 42px; display: block; }
header .logo-txt { font-weight: 800; font-size: 26px; color: var(--blauw); letter-spacing: 1px; }
header .sep { width: 1px; align-self: stretch; background: var(--lijn); margin: 4px 0; }
header h1 { font-size: 15px; margin: 0 0 3px; font-weight: 700; }
header .sub { font-family: var(--mono); font-size: 12px; color: var(--grijs); }
.wrap { display: grid; grid-template-columns: 246px 1fr; min-height: calc(100vh - 62px); }

aside { background: #fff; border-right: 1px solid var(--lijn); }
.sb-sec { padding: 18px 12px 16px; border-bottom: 1px solid var(--lijn); }
.sb-sec h3 { font-size: 10px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: var(--blauw); margin: 0 0 12px; }
.layer { display: flex; align-items: center; gap: 10px; padding: 9px 10px; margin-bottom: 6px; border: 1px solid var(--lijn);
         border-radius: 4px; cursor: pointer; user-select: none; background: #fff; }
.layer.on { border-color: var(--blauw); }
.layer .lt { flex: 1; min-width: 0; }
.layer .ln { font-size: 12px; font-weight: 600; }
.layer .ls { font-size: 9.5px; color: var(--grijs); margin-top: 1px; }
.layer .sw { position: relative; width: 30px; height: 16px; border-radius: 8px; background: #c9d1dc; flex: none; }
.layer .sw::after { content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: #fff; transition: left .15s; }
.layer.on .sw { background: var(--blauw); }
.layer.on .sw::after { left: 16px; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.actions button { font-family: var(--sans); font-size: 11px; padding: 7px 0; border: 1px solid var(--lijn); background: #f3f5f8;
                  color: var(--grijs); border-radius: 3px; cursor: pointer; }
.actions button:hover { border-color: var(--blauw); color: var(--blauw); }
.ptgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.ptbtn { padding: 8px 0; text-align: center; font-family: var(--mono); font-size: 11px; font-weight: 700; border-radius: 3px;
         cursor: pointer; user-select: none; border: 1px solid var(--lijn); background: #fff; color: #9aa3b0; }
.fld { font-size: 11px; color: var(--grijs); margin: 10px 0 4px; }
select, input[type=range] { width: 100%; font-family: var(--sans); font-size: 12px; }
select { padding: 6px; border: 1px solid var(--lijn); border-radius: 3px; background: #fff; color: var(--tekst); }
.hint { font-size: 10px; color: var(--grijs); line-height: 1.45; margin-top: 8px; }

main { padding: 20px; min-width: 0; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 11px; margin-bottom: 16px; }
.card { background: #fff; border: 1px solid var(--lijn); border-radius: 4px; padding: 12px 14px 10px; cursor: pointer; user-select: none; font-family: var(--mono); }
.c-name { font-size: 12px; font-weight: 700; }
.c-id { font-size: 9.5px; color: var(--grijs); margin-bottom: 8px; }
.c-row { display: flex; justify-content: space-between; align-items: baseline; font-size: 11px; color: #4b5563; margin: 2px 0; }
.c-row b { font-size: 16px; }
.c-row .u { font-size: 11px; margin-left: 3px; font-weight: 400; }
.pos { color: var(--heave); } .neg { color: var(--rood); } .nul { color: var(--grijs); }
.c-foot { font-size: 9.5px; color: var(--grijs); margin-top: 8px; line-height: 1.5; }
.c-warn { font-family: var(--sans); font-size: 9.5px; color: var(--oranje); margin-top: 4px; }

.grid2 { display: grid; grid-template-columns: minmax(360px, 520px) 1fr; gap: 16px; align-items: start; }
.panel { background: #fff; border: 1px solid var(--lijn); border-radius: 4px; padding: 16px 18px 12px; margin-bottom: 16px; }
.ph { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.ph h2 { font-size: 13px; font-weight: 700; margin: 0; }
.ph .psub { font-size: 10.5px; color: var(--grijs); margin-top: 3px; }
.ph .rt { font-family: var(--mono); font-size: 11px; color: var(--blauw); white-space: nowrap; }
.mapwrap { position: sticky; top: 12px; }
#map { width: 100%; aspect-ratio: 1 / 1; display: block; background: #eef1f5; border-radius: 3px; cursor: grab; }
#map:active { cursor: grabbing; }
.chart svg { display: block; width: 100%; }
.axis text { font-family: var(--sans); font-size: 10px; fill: var(--grijs); }
.axis path, .axis line { stroke: #cfd6e0; }
.gridl line { stroke: #eef1f5; } .gridl path { display: none; }
.zero { stroke: #9aa3b0; stroke-dasharray: 3 3; }
.cross { stroke: #1a2233; stroke-width: 1; stroke-dasharray: 2 3; pointer-events: none; }
#tip { position: fixed; pointer-events: none; background: #fff; border: 1px solid var(--lijn); border-radius: 4px;
       box-shadow: 0 4px 14px rgba(0,0,0,.12); padding: 8px 10px; font-family: var(--mono); font-size: 11px; display: none; z-index: 10; }
#tip table { border-collapse: collapse; } #tip td { padding: 1px 6px; text-align: right; } #tip td:first-child { text-align: left; font-weight: 700; }
#tip .th { color: var(--grijs); font-weight: 400; }
.brush .selection { fill: var(--blauw); fill-opacity: .08; stroke: var(--blauw); }
.maplbl { font-family: var(--mono); font-weight: 700; paint-order: stroke; stroke: #fff; stroke-linejoin: round; }
.hidden { display: none !important; }
@media (max-width: 1200px) { .grid2 { grid-template-columns: 1fr; } .mapwrap { position: static; } }
@media (max-width: 800px) { .wrap { grid-template-columns: 1fr; } aside { border-right: 0; border-bottom: 1px solid var(--lijn); } }
</style>
</head>
<body>
<header>
  __LOGO__
  <div class="sep"></div>
  <div>
    <h1>Verplaatsingsdashboard &mdash; __PROJECT__</h1>
    <div class="sub">GNSS-metingen | __PERIODE__ | __NPT__ meetpunten</div>
  </div>
</header>
<div class="wrap">
  <aside>
    <div class="sb-sec">
      <h3>Meetpunten</h3>
      <div class="actions"><button id="btn-all">Alle aan</button><button id="btn-none">Alle uit</button></div>
      <div class="ptgrid" id="ptgrid"></div>
    </div>
    <div class="sb-sec">
      <h3>Weergave</h3>
      <div class="layer on" id="tgl-raw"><div class="lt"><div class="ln">Ruwe metingen</div><div class="ls">elke meting (2-uurlijks)</div></div><span class="sw"></span></div>
      <div class="layer" id="tgl-avg"><div class="lt"><div class="ln">Voortschrijdend gemiddelde</div><div class="ls">gecentreerd venster</div></div><span class="sw"></span></div>
      <div class="fld">Venster gemiddelde</div>
      <select id="sel-win"><option value="6">6 uur</option><option value="12" selected>12 uur</option><option value="24">24 uur</option></select>
      <div class="fld">Nulpunt</div>
      <select id="sel-ref"><option value="eerste">Eerste meting (__VANAF__)</option><option value="gem24">Gemiddelde eerste 24 uur</option></select>
    </div>
    <div class="sb-sec">
      <h3>Bovenaanzicht</h3>
      <div class="fld">Achtergrond</div>
      <select id="sel-bg"><option value="lucht">Luchtfoto (PDOK)</option><option value="brt">Topografisch (PDOK BRT)</option><option value="geen">Geen</option></select>
      <div class="fld">Vectorvergroting: <b id="vf-lbl"></b></div>
      <input type="range" id="vf" min="100" max="3000" step="100" value="500">
      <div class="hint">Scroll = zoomen, slepen = verschuiven, dubbelklik = reset. Pijl = horizontale verplaatsing (E/N), label = hoogteverschil. Beweeg over een grafiek om de situatie op dat moment te zien.</div>
    </div>
    <div class="sb-sec">
      <div class="hint">Data v&oacute;&oacute;r __VANAF__ UTC is weggelaten (offset-fout in de export). Verschillen zijn opnieuw berekend t.o.v. het gekozen nulpunt. Omhoog / oost / noord = positief.</div>
    </div>
  </aside>
  <main>
    <div class="stats" id="stats"></div>
    <div class="grid2">
      <div class="mapwrap">
        <div class="panel">
          <div class="ph"><div><h2>Bovenaanzicht meetpunten</h2><div class="psub">RD-co&ouml;rdinaten (EPSG:28992)</div></div><div class="rt" id="map-t"></div></div>
          <svg id="map"></svg>
        </div>
      </div>
      <div>
        <div class="panel chart"><div class="ph"><div><h2>Verschil hoogte [mm]</h2><div class="psub">omhoog = positief, zakking = negatief</div></div></div><div id="c-H"></div></div>
        <div class="panel chart"><div class="ph"><div><h2>Verschil easting [mm]</h2><div class="psub">oost = positief</div></div></div><div id="c-E"></div></div>
        <div class="panel chart"><div class="ph"><div><h2>Verschil northing [mm]</h2><div class="psub">noord = positief</div></div></div><div id="c-N"></div></div>
        <div class="panel chart"><div class="ph"><div><h2>Tijdvenster</h2><div class="psub">sleep in deze balk om in te zoomen op een periode; dubbelklik = hele periode</div></div></div><div id="c-brush"></div></div>
      </div>
    </div>
  </main>
</div>
<div id="tip"></div>
<script>
var D = __DATA__;
var parse = d3.utcParse('%Y-%m-%d %H:%M');
var T = D.T.map(parse);
var P = D.punten;
var act = {}; P.forEach(function(p){ act[p.id] = true; });
var showRaw = true, showAvg = false, winH = 12, refMode = 'eerste', vfac = 500, hoverIdx = null;
var COMP = ['H', 'E', 'N'];
var fmtT = d3.utcFormat('%d-%m-%Y %H:%M');

// ── Berekening ──────────────────────────────
function refVal(arr) {
  var i0 = -1;
  for (var i = 0; i < arr.length; i++) { if (arr[i] !== null) { i0 = i; break; } }
  if (i0 < 0) return null;
  if (refMode === 'eerste') return arr[i0];
  var lim = +T[i0] + 24 * 3600e3, s = 0, n = 0;
  for (var j = i0; j < arr.length && +T[j] < lim; j++) { if (arr[j] !== null) { s += arr[j]; n++; } }
  return s / n;
}
function diffs(p, c) {
  var r = refVal(p[c]);
  return p[c].map(function(v){ return (v === null || r === null) ? null : (v - r) * 1000; });
}
function smooth(arr) {
  var half = winH * 3600e3 / 2;
  return arr.map(function(v, i){
    var s = 0, n = 0, t0 = +T[i];
    for (var j = i; j >= 0 && t0 - T[j] <= half; j--) { if (arr[j] !== null) { s += arr[j]; n++; } }
    for (var k = i + 1; k < arr.length && T[k] - t0 <= half; k++) { if (arr[k] !== null) { s += arr[k]; n++; } }
    return (v === null && n === 0) ? null : (n ? s / n : null);
  });
}
var S = {};
function recompute() {
  P.forEach(function(p){
    S[p.id] = {};
    COMP.forEach(function(c){ var r = diffs(p, c); S[p.id][c] = { raw: r, avg: smooth(r) }; });
  });
}
function cur(id, c) { return showAvg ? S[id][c].avg : S[id][c].raw; }
function lastIdx(arr) { for (var i = arr.length - 1; i >= 0; i--) { if (arr[i] !== null) return i; } return -1; }
function std(arr) {
  var v = arr.filter(function(x){ return x !== null; });
  if (v.length < 2) return null;
  var m = d3.mean(v); return Math.sqrt(d3.sum(v, function(x){ return (x - m) * (x - m); }) / (v.length - 1));
}
// Punten verbinden zolang het gat <= 6 uur is
function segs(arr) {
  var out = [], seg = [], prev = null;
  arr.forEach(function(v, i){
    if (v === null) return;
    if (prev !== null && T[i] - T[prev] > 6 * 3600e3) { out.push(seg); seg = []; }
    seg.push([T[i], v]); prev = i;
  });
  if (seg.length) out.push(seg);
  return out;
}

// ── Knoppen en kaarten ──────────────────────
function sgn(v, n) { if (v === null || v === undefined || isNaN(v)) return '--'; return (v > 0 ? '+' : '') + v.toFixed(n); }
function cls(v) { return (v === null || Math.abs(v) < 0.5) ? 'nul' : (v > 0 ? 'pos' : 'neg'); }

function buildButtons() {
  var g = d3.select('#ptgrid');
  P.forEach(function(p){
    g.append('div').attr('class', 'ptbtn').attr('id', 'pb-' + p.kort).text(p.kort)
      .attr('title', p.id).on('click', function(){ togglePt(p.id); });
  });
}
function paintButtons() {
  P.forEach(function(p){
    var on = act[p.id];
    d3.select('#pb-' + p.kort).style('background', on ? p.kleur : '#fff').style('border-color', on ? p.kleur : '')
      .style('color', on ? '#fff' : '#9aa3b0');
    d3.select('#card-' + p.kort).style('border-color', on ? p.kleur : '')
      .style('box-shadow', on ? 'inset 0 3px 0 ' + p.kleur : 'none').style('opacity', on ? 1 : 0.55);
  });
}
function buildCards() {
  var box = d3.select('#stats').html('');
  P.forEach(function(p){
    var li = lastIdx(p.H), rawH = S[p.id].H.raw;
    var sd = std(rawH);
    var html = '<div class="c-name" style="color:' + p.kleur + '">' + p.kort + '</div><div class="c-id">' + p.id + '</div>';
    [['H', 'hoogte'], ['E', 'easting'], ['N', 'northing']].forEach(function(cc){
      var a = cur(p.id, cc[0]), v = a[lastIdx(a)];
      html += '<div class="c-row"><span>&Delta; ' + cc[1] + '</span><b class="' + cls(v) + '">' + sgn(v, 0) + '<span class="u">mm</span></b></div>';
    });
    html += '<div class="c-foot">spreiding hoogte &sigma; ' + (sd === null ? '--' : sd.toFixed(0)) + ' mm<br>laatste: ' +
      (li >= 0 ? fmtT(T[li]) : '--') + '<br>' + p.H.filter(function(x){ return x !== null; }).length + ' metingen' + '</div>';
    if (sd !== null && sd > 20) { html += '<div class="c-warn">⚠ grote spreiding &ndash; gebruik gemiddelde</div>'; }
    box.append('div').attr('class', 'card').attr('id', 'card-' + p.kort).html(html)
      .on('click', function(){ togglePt(p.id); });
  });
  paintButtons();
}
function togglePt(id) { act[id] = !act[id]; paintButtons(); drawCharts(); drawMapData(); }

// ── Grafieken ───────────────────────────────
var X = d3.scaleUtc().domain(d3.extent(T)), X0 = X.copy();
var M = { l: 52, r: 14, t: 8, b: 24 }, CH = 190;
var charts = {};

function chartWidth() { return Math.max(300, document.getElementById('c-H').clientWidth); }

function setupChart(c) {
  var host = d3.select('#c-' + c).html('');
  var svg = host.append('svg').attr('height', CH);
  var clipId = 'clip-' + c;
  svg.append('defs').append('clipPath').attr('id', clipId).append('rect');
  var g = svg.append('g').attr('transform', 'translate(' + M.l + ',' + M.t + ')');
  var o = { svg: svg, g: g, clip: clipId,
    gy: g.append('g').attr('class', 'gridl'), ax: g.append('g').attr('class', 'axis'), ay: g.append('g').attr('class', 'axis'),
    zero: g.append('line').attr('class', 'zero'),
    plot: g.append('g').attr('clip-path', 'url(#' + clipId + ')'),
    cross: g.append('line').attr('class', 'cross').style('display', 'none'),
    ov: g.append('rect').attr('fill', 'transparent') };
  o.ov.on('mousemove', function(ev){ hover(ev, this); }).on('mouseleave', unhover)
      .on('dblclick', function(){ X.domain(X0.domain()); brushG.call(brush.move, null); drawCharts(); });
  charts[c] = o;
}

function yDomain(c) {
  var lo = Infinity, hi = -Infinity, d0 = X.domain();
  P.forEach(function(p){
    if (!act[p.id]) return;
    var arrs = []; if (showRaw) arrs.push(S[p.id][c].raw); if (showAvg) arrs.push(S[p.id][c].avg);
    arrs.forEach(function(a){ a.forEach(function(v, i){
      if (v === null || T[i] < d0[0] || T[i] > d0[1]) return; lo = Math.min(lo, v); hi = Math.max(hi, v); }); });
  });
  if (lo === Infinity) { lo = -10; hi = 10; }
  lo = Math.min(lo, 0); hi = Math.max(hi, 0);
  var pad = Math.max(2, (hi - lo) * 0.08);
  return [lo - pad, hi + pad];
}

function drawChart(c) {
  var o = charts[c], W = chartWidth(), w = W - M.l - M.r, h = CH - M.t - M.b;
  o.svg.attr('width', W);
  d3.select('#' + o.clip + ' rect').attr('width', w).attr('height', h);
  X.range([0, w]);
  var Y = d3.scaleLinear().domain(yDomain(c)).range([h, 0]).nice();
  o.Y = Y; o.w = w; o.h = h;
  o.gy.call(d3.axisLeft(Y).ticks(5).tickSize(-w).tickFormat(''));
  o.ax.attr('transform', 'translate(0,' + h + ')').call(d3.axisBottom(X).ticks(Math.max(3, Math.floor(w / 110))).tickFormat(tfmt));
  o.ay.call(d3.axisLeft(Y).ticks(5).tickFormat(function(v){ return v + ' mm'; }));
  o.zero.attr('x1', 0).attr('x2', w).attr('y1', Y(0)).attr('y2', Y(0));
  o.ov.attr('width', w).attr('height', h);
  var line = d3.line().x(function(d){ return X(d[0]); }).y(function(d){ return Y(d[1]); });
  o.plot.selectAll('*').remove();
  P.forEach(function(p){
    if (!act[p.id]) return;
    if (showRaw) {
      var raw = S[p.id][c].raw;
      segs(raw).forEach(function(s){
        o.plot.append('path').attr('d', line(s)).attr('fill', 'none').attr('stroke', p.kleur)
          .attr('stroke-width', showAvg ? 0.8 : 1.3).attr('stroke-opacity', showAvg ? 0.35 : 0.9);
      });
      o.plot.append('g').selectAll('circle').data(raw.map(function(v, i){ return [T[i], v]; }).filter(function(d){ return d[1] !== null; }))
        .join('circle').attr('cx', function(d){ return X(d[0]); }).attr('cy', function(d){ return Y(d[1]); })
        .attr('r', showAvg ? 1.2 : 1.8).attr('fill', p.kleur).attr('fill-opacity', showAvg ? 0.35 : 0.9);
    }
    if (showAvg) {
      segs(S[p.id][c].avg).forEach(function(s){
        o.plot.append('path').attr('d', line.curve(d3.curveMonotoneX)(s)).attr('fill', 'none').attr('stroke', p.kleur).attr('stroke-width', 2.2);
      });
      line.curve(d3.curveLinear);
    }
  });
}
var tfmt = function(d){ return d3.utcHour(d) < d ? d3.utcFormat('%H:%M')(d) : (d3.utcDay(d) < d ? d3.utcFormat('%H:%M')(d) : d3.utcFormat('%d-%m')(d)); };

function drawCharts() { COMP.forEach(drawChart); drawBrush(); if (hoverIdx !== null) showCross(hoverIdx); }

// Overzicht + brush
var brush, brushG, BX = d3.scaleUtc().domain(X0.domain()), BH = 60;
function drawBrush() {
  var host = d3.select('#c-brush').html(''), W = chartWidth(), w = W - M.l - M.r, h = BH;
  var svg = host.append('svg').attr('width', W).attr('height', h + 22);
  var g = svg.append('g').attr('transform', 'translate(' + M.l + ',4)');
  BX.range([0, w]);
  var lo = Infinity, hi = -Infinity;
  P.forEach(function(p){ if (act[p.id]) S[p.id].H.avg.forEach(function(v){ if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
  if (lo === Infinity) { lo = -1; hi = 1; }
  var Y = d3.scaleLinear().domain([Math.min(lo, 0), Math.max(hi, 0)]).range([h, 0]);
  var line = d3.line().x(function(d){ return BX(d[0]); }).y(function(d){ return Y(d[1]); });
  P.forEach(function(p){ if (act[p.id]) segs(S[p.id].H.avg).forEach(function(s){
    g.append('path').attr('d', line(s)).attr('fill', 'none').attr('stroke', p.kleur).attr('stroke-width', 1.2); }); });
  g.append('g').attr('class', 'axis').attr('transform', 'translate(0,' + h + ')').call(d3.axisBottom(BX).ticks(Math.max(3, Math.floor(w / 110))).tickFormat(tfmt));
  brush = d3.brushX().extent([[0, 0], [w, h]]).on('brush end', function(ev){
    if (!ev.sourceEvent) return;
    X.domain(ev.selection ? ev.selection.map(BX.invert) : X0.domain());
    COMP.forEach(drawChart);
  });
  brushG = g.append('g').attr('class', 'brush').call(brush);
  var d = X.domain();
  if (+d[0] !== +X0.domain()[0] || +d[1] !== +X0.domain()[1]) brushG.call(brush.move, d.map(BX));
  svg.on('dblclick', function(){ X.domain(X0.domain()); brushG.call(brush.move, null); COMP.forEach(drawChart); });
}

// Hover: kruislijn in alle grafieken + tooltip + kaart op dat moment
function nearestIdx(t) { var i = d3.bisector(function(d){ return d; }).center(T, t); return Math.max(0, Math.min(T.length - 1, i)); }
function hover(ev, el) {
  var m = d3.pointer(ev, el), i = nearestIdx(X.invert(m[0]));
  hoverIdx = i; showCross(i); drawMapData();
  var rows = '<tr><td class="th">' + fmtT(T[i]) + '</td><td class="th">&Delta;H</td><td class="th">&Delta;E</td><td class="th">&Delta;N</td></tr>';
  P.forEach(function(p){
    if (!act[p.id]) return;
    rows += '<tr><td style="color:' + p.kleur + '">' + p.kort + '</td>';
    COMP.forEach(function(c){ var v = cur(p.id, c)[i]; rows += '<td class="' + cls(v) + '">' + sgn(v, 0) + '</td>'; });
    rows += '</tr>';
  });
  var tip = document.getElementById('tip');
  tip.innerHTML = '<table>' + rows + '</table><div class="th" style="margin-top:4px;font-size:10px;color:#6b7686">mm, ' + (showAvg ? 'gemiddelde ' + winH + ' u' : 'ruwe meting') + '</div>';
  tip.style.display = 'block';
  var x = ev.clientX + 16, y = ev.clientY + 12;
  if (x + tip.offsetWidth > window.innerWidth - 8) x = ev.clientX - tip.offsetWidth - 16;
  if (y + tip.offsetHeight > window.innerHeight - 8) y = ev.clientY - tip.offsetHeight - 12;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
function showCross(i) {
  COMP.forEach(function(c){ var o = charts[c], x = X(T[i]);
    o.cross.style('display', (x >= 0 && x <= o.w) ? null : 'none').attr('x1', x).attr('x2', x).attr('y1', 0).attr('y2', o.h); });
}
function unhover() {
  hoverIdx = null; document.getElementById('tip').style.display = 'none';
  COMP.forEach(function(c){ charts[c].cross.style('display', 'none'); }); drawMapData();
}

// ── Bovenaanzicht ───────────────────────────
var MS = 600, mapSvg, mapG, bgG, vecG, ptG, scaleG, MX, MY, zoomK = 1, zoom;
var RD = { ox: -285401.92, oy: 903401.92, r0: 3440.64 };
var BG = {
  lucht: { url: 'https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:28992/', ext: '.jpeg', z: 14 },
  brt:   { url: 'https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/standaard/EPSG:28992/', ext: '.png', z: 14 }
};
function basePos(p) {  // eerste geldige absolute positie (voor kaart)
  for (var i = 0; i < p.E.length; i++) { if (p.E[i] !== null && p.N[i] !== null) return [p.E[i], p.N[i]]; }
  return null;
}
function setupMap() {
  mapSvg = d3.select('#map').attr('viewBox', '0 0 ' + MS + ' ' + MS);
  var pos = P.map(basePos).filter(function(x){ return x; });
  var ex = d3.extent(pos, function(d){ return d[0]; }), ny = d3.extent(pos, function(d){ return d[1]; });
  var cx = (ex[0] + ex[1]) / 2, cy = (ny[0] + ny[1]) / 2;
  var half = Math.max(ex[1] - ex[0], ny[1] - ny[0]) / 2 + 30;
  MX = d3.scaleLinear().domain([cx - half, cx + half]).range([0, MS]);
  MY = d3.scaleLinear().domain([cy - half, cy + half]).range([MS, 0]);
  mapG = mapSvg.append('g');
  bgG = mapG.append('g'); vecG = mapG.append('g'); ptG = mapG.append('g');
  scaleG = mapSvg.append('g').attr('transform', 'translate(14,' + (MS - 18) + ')');
  var na = mapSvg.append('g').attr('transform', 'translate(' + (MS - 26) + ',30)');
  na.append('path').attr('d', 'M0,-18 L7,4 L0,0 L-7,4 Z').attr('fill', '#1a2233').attr('stroke', '#fff').attr('stroke-width', 1.5);
  na.append('text').attr('y', 18).attr('text-anchor', 'middle').attr('class', 'maplbl').attr('font-size', 12).attr('stroke-width', 3).text('N');
  zoom = d3.zoom().scaleExtent([0.5, 40]).on('zoom', function(ev){ zoomK = ev.transform.k; mapG.attr('transform', ev.transform); drawMapData(); drawScale(); });
  mapSvg.call(zoom).on('dblclick.zoom', null).on('dblclick', function(){ mapSvg.transition().duration(300).call(zoom.transform, d3.zoomIdentity); });
  drawBg(); drawScale();
}
function drawBg() {
  bgG.selectAll('*').remove();
  var key = document.getElementById('sel-bg').value;
  if (key === 'geen') {
    var gr = MX.domain(), st = 10;
    for (var e = Math.ceil(gr[0] / st) * st; e < gr[1]; e += st) bgG.append('line').attr('x1', MX(e)).attr('x2', MX(e)).attr('y1', 0).attr('y2', MS).attr('stroke', '#dfe4ec');
    var gy = MY.domain();
    for (var n = Math.ceil(gy[0] / st) * st; n < gy[1]; n += st) bgG.append('line').attr('y1', MY(n)).attr('y2', MY(n)).attr('x1', 0).attr('x2', MS).attr('stroke', '#dfe4ec');
    return;
  }
  var L = BG[key], res = RD.r0 / Math.pow(2, L.z), ts = res * 256;
  var e0 = MX.domain()[0] - 150, e1 = MX.domain()[1] + 150, n0 = MY.domain()[0] - 150, n1 = MY.domain()[1] + 150;
  var c0 = Math.floor((e0 - RD.ox) / ts), c1 = Math.floor((e1 - RD.ox) / ts);
  var r0 = Math.floor((RD.oy - n1) / ts), r1 = Math.floor((RD.oy - n0) / ts);
  for (var c = c0; c <= c1; c++) for (var r = r0; r <= r1; r++) {
    var te = RD.ox + c * ts, tn = RD.oy - r * ts;
    bgG.append('image').attr('href', L.url + L.z + '/' + c + '/' + r + L.ext)
      .attr('x', MX(te)).attr('y', MY(tn)).attr('width', MX(te + ts) - MX(te) + 0.5).attr('height', MY(tn - ts) - MY(tn) + 0.5)
      .attr('preserveAspectRatio', 'none');
  }
}
function drawScale() {
  var mpp = (MX.domain()[1] - MX.domain()[0]) / MS / zoomK, target = 110 * mpp;
  var nice = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500].filter(function(v){ return v <= target; }).pop() || 1;
  var px = nice / mpp;
  scaleG.selectAll('*').remove();
  scaleG.append('rect').attr('x', -6).attr('y', -16).attr('width', px + 44).attr('height', 24).attr('fill', '#fff').attr('fill-opacity', 0.85).attr('rx', 3);
  scaleG.append('path').attr('d', 'M0,-4 V0 H' + px + ' V-4').attr('fill', 'none').attr('stroke', '#1a2233').attr('stroke-width', 1.5);
  scaleG.append('text').attr('x', px + 6).attr('y', 1).attr('font-family', 'Consolas, monospace').attr('font-size', 11).text(nice + ' m');
}
function drawMapData() {
  var k = zoomK, i = hoverIdx;
  vecG.selectAll('*').remove(); ptG.selectAll('*').remove();
  var mppx = (MX.domain()[1] - MX.domain()[0]) / MS;
  P.forEach(function(p){
    var b = basePos(p); if (!b) return;
    var on = act[p.id], x = MX(b[0]), y = MY(b[1]);
    var aE = cur(p.id, 'E'), aN = cur(p.id, 'N'), aH = cur(p.id, 'H');
    var j = (i !== null) ? i : lastIdx(aE);
    var dE = j >= 0 ? aE[j] : null, dN = j >= 0 ? aN[j] : null, dH = j >= 0 ? aH[j] : null;
    if (on && dE !== null && dN !== null) {
      var x2 = MX(b[0] + dE / 1000 * vfac), y2 = MY(b[1] + dN / 1000 * vfac);
      vecG.append('line').attr('x1', x).attr('y1', y).attr('x2', x2).attr('y2', y2)
        .attr('stroke', '#fff').attr('stroke-width', 5 / k).attr('stroke-linecap', 'round');
      vecG.append('line').attr('x1', x).attr('y1', y).attr('x2', x2).attr('y2', y2)
        .attr('stroke', p.kleur).attr('stroke-width', 2.6 / k).attr('stroke-linecap', 'round');
      var ang = Math.atan2(y2 - y, x2 - x), al = 9 / k;
      if (Math.hypot(x2 - x, y2 - y) > al) {
        vecG.append('path').attr('d', 'M' + x2 + ',' + y2 + ' L' + (x2 - al * Math.cos(ang - 0.45)) + ',' + (y2 - al * Math.sin(ang - 0.45)) +
          ' L' + (x2 - al * Math.cos(ang + 0.45)) + ',' + (y2 - al * Math.sin(ang + 0.45)) + ' Z').attr('fill', p.kleur).attr('stroke', '#fff').attr('stroke-width', 1 / k);
      }
    }
    var g = ptG.append('g').style('cursor', 'pointer').style('opacity', on ? 1 : 0.45).on('click', function(){ togglePt(p.id); });
    g.append('circle').attr('cx', x).attr('cy', y).attr('r', 6 / k).attr('fill', on ? p.kleur : '#fff').attr('stroke', on ? '#fff' : p.kleur).attr('stroke-width', 2 / k);
    g.append('text').attr('x', x + 9 / k).attr('y', y - 7 / k).attr('class', 'maplbl').attr('font-size', 12 / k).attr('stroke-width', 3 / k)
      .attr('fill', p.kleur).text(p.kort);
    if (on) g.append('text').attr('x', x + 9 / k).attr('y', y + 8 / k).attr('class', 'maplbl').attr('font-size', 10.5 / k).attr('stroke-width', 3 / k)
      .attr('fill', dH === null ? '#6b7686' : (dH < 0 ? '#D62728' : '#1f5fbf')).text('ΔH ' + sgn(dH, 0) + ' mm');
    g.append('title').text(p.id + '\nE ' + b[0].toFixed(3) + '  N ' + b[1].toFixed(3) + '\nΔE ' + sgn(dE, 0) + '  ΔN ' + sgn(dN, 0) + '  ΔH ' + sgn(dH, 0) + ' mm');
  });
  var jt = (i !== null) ? T[i] : T[T.length - 1];
  document.getElementById('map-t').textContent = (i !== null ? '' : 'laatste: ') + fmtT(jt) + ' UTC';
  document.getElementById('vf-lbl').textContent = '×' + vfac + '  (10 mm = ' + (vfac / 100).toFixed(1) + ' m)';
}

// ── Bediening ───────────────────────────────
function setLayer(id, on) { document.getElementById(id).classList.toggle('on', on); }
d3.select('#tgl-raw').on('click', function(){ showRaw = !showRaw; if (!showRaw && !showAvg) { showAvg = true; setLayer('tgl-avg', true); } setLayer('tgl-raw', showRaw); refresh(); });
d3.select('#tgl-avg').on('click', function(){ showAvg = !showAvg; if (!showRaw && !showAvg) { showRaw = true; setLayer('tgl-raw', true); } setLayer('tgl-avg', showAvg); refresh(); });
d3.select('#sel-win').on('change', function(){ winH = +this.value; recompute(); refresh(); });
d3.select('#sel-ref').on('change', function(){ refMode = this.value; recompute(); refresh(); });
d3.select('#sel-bg').on('change', drawBg);
d3.select('#vf').on('input', function(){ vfac = +this.value; drawMapData(); });
d3.select('#btn-all').on('click', function(){ P.forEach(function(p){ act[p.id] = true; }); paintButtons(); drawCharts(); drawMapData(); });
d3.select('#btn-none').on('click', function(){ P.forEach(function(p){ act[p.id] = false; }); paintButtons(); drawCharts(); drawMapData(); });
function refresh() { buildCards(); drawCharts(); drawMapData(); }
var rsz; window.addEventListener('resize', function(){ clearTimeout(rsz); rsz = setTimeout(drawCharts, 120); });

recompute();
buildButtons();
COMP.forEach(setupChart);
setupMap();
refresh();
</script>
</body>
</html>
"""


def logo_html(pad):
    p = Path(pad)
    if p.exists():
        mime = "image/svg+xml" if p.suffix.lower() == ".svg" else "image/png"
        return '<img src="data:' + mime + ';base64,' + base64.b64encode(p.read_bytes()).decode("ascii") + '" alt="Nepocon">'
    return '<span class="logo-txt">nepocon</span>'


def bouw_html(payload, logo_pad):
    html = HTML_TEMPLATE
    html = html.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace("__LOGO__", logo_html(logo_pad))
    html = html.replace("__PROJECT__", payload["project"])
    html = html.replace("__PERIODE__", periode_label(payload["T"]))
    html = html.replace("__NPT__", str(len(payload["punten"])))
    html = html.replace("__VANAF__", pd.Timestamp(payload["vanaf"]).strftime("%d-%m-%Y %H:%M"))
    return html


def main():
    ap = argparse.ArgumentParser(description="GNSS verplaatsingsdashboard (D3)")
    ap.add_argument("--bestand", default=EXCEL_BESTAND)
    ap.add_argument("--output", default=OUTPUT_HTML)
    ap.add_argument("--project", default=PROJECTNAAM)
    ap.add_argument("--logo", default=LOGO_PAD)
    ap.add_argument("--vanaf", default=VANAF, help='eerste bruikbare meting, UTC, bv. "2026-09-22 13:00"')
    args = ap.parse_args()

    if not Path(args.bestand).exists():
        sys.exit("Bestand niet gevonden: " + args.bestand)
    punten = lees_data(args.bestand, args.vanaf)
    payload = bouw_payload(punten, args.project, args.vanaf)
    html = bouw_html(payload, args.logo)
    assert "`" not in html, "Backtick in HTML gevonden"
    assert "onclick=" not in html, "Inline onclick gevonden"
    Path(args.output).write_text(html, encoding="utf-8")

    print("Dashboard: %s (%s bytes) | %s" % (args.output, format(len(html), ","), periode_label(payload["T"])))
    for p in punten:
        d = p["df"].dropna(subset=["H"])
        if d.empty:
            print("  %-16s geen data" % p["id"]); continue
        dh = (d["H"].iloc[-1] - d["H"].iloc[0]) * 1000
        de = (d["E"].iloc[-1] - d["E"].iloc[0]) * 1000
        dn = (d["N"].iloc[-1] - d["N"].iloc[0]) * 1000
        print("  %-16s dH %+6.0f  dE %+6.0f  dN %+6.0f mm | sigma H %4.0f mm | %d metingen" % (
            p["id"], dh, de, dn, d["H"].std() * 1000, len(d)))


if __name__ == "__main__":
    main()
