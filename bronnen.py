"""
bronnen.py
Haalt de ruwe meetdata op en levert een DataFrame in dezelfde layout als de Basetime Excel-export
(header=None), zodat de generators in generators/ ongewijzigd kunnen blijven.

Bron-typen (in projecten.json -> "bron"):
  {"type": "api",   "project": "Naam in Basetime"}           productie (Basetime REST API)
  {"type": "excel", "pad": "data/export.xlsx"}                 lokaal testen (data/ staat NIET in git)

SECURITY: sleutels alleen via omgevingsvariabelen (zie basetime_api.py); nooit printen of opslaan.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd

import basetime_api as api

OVERSLAAN = ("base",)          # referentie-/basisstations niet als meetpunt tonen
POGINGEN = 3


def haal_ruwe_data(project, basis):
    bron = project["bron"]
    if bron["type"] == "excel":
        pad = Path(basis) / bron["pad"]
        if not pad.exists():
            raise FileNotFoundError("Excel-bron niet gevonden: %s" % bron["pad"])
        return pd.read_excel(pad, header=None)
    if bron["type"] == "api":
        metingen = haal_api(bron["project"], bron.get("punten"))
        return naar_zetting_df(metingen) if project["type"] == "zetting" else naar_gnss_df(metingen)
    raise ValueError("Onbekend brontype: %r" % bron["type"])


def _met_herhaling(f, *a):
    for i in range(POGINGEN):
        try:
            return f(*a)
        except api.ApiFout as e:
            if "HTTP 5" not in str(e) or i == POGINGEN - 1:
                raise
            time.sleep(3 * (i + 1))


def haal_api(projectnaam, punten=None):
    """{puntnaam: {tijdstip: meting-dict}} voor alle meetpunten van een project."""
    if punten is None:
        alle = _met_herhaling(api.projecten)
        if projectnaam not in alle:
            raise api.ApiFout("Project '%s' niet beschikbaar voor deze API-sleutel." % projectnaam)
        punten = alle[projectnaam]
    punten = [p for p in dict.fromkeys(punten) if not p.lower().startswith(OVERSLAAN)]
    uit = {}
    for p in punten:
        js = _met_herhaling(api.data, projectnaam, p)
        uit[p] = js.get("Measurements") or {}
    if not any(uit.values()):
        raise api.ApiFout("Geen metingen ontvangen voor '%s'." % projectnaam)
    return uit


def _f(d, *pad):
    for k in pad:
        if not isinstance(d, dict):
            return np.nan
        d = d.get(k)
    try:
        return float(d) if d is not None else np.nan
    except (TypeError, ValueError):
        return np.nan


def _tijden(metingen):
    return sorted({t for m in metingen.values() for t in m}, reverse=True)   # nieuwste eerst, zoals de export


def naar_zetting_df(metingen):
    """Exportlayout zakbaken: rij 2 = puntnaam, data vanaf rij 5, blokken van 7 kolommen
    (Easting, Northing, radar, Height Soil, Height groundplate, Length Settlement Rod, temperature)."""
    T = _tijden(metingen)
    namen = list(metingen)
    kop = [[None] * (1 + 7 * len(namen)) for _ in range(5)]
    rijen = []
    for t in T:
        r = [pd.Timestamp(t)]
        for n in namen:
            m = metingen[n].get(t, {})
            r += [_f(m, "Coordinates Local", "Easting"), _f(m, "Coordinates Local", "Northing"),
                  _f(m, "Coordinates Soil", "Radar distance"), _f(m, "Coordinates Soil", "Height Soil"),
                  _f(m, "Coordinates Soil", "Height groundplate"), _f(m, "Vertical offset (meters)"),
                  _f(m, "Temperature (Celsius)")]
        rijen.append(r)
    for i, n in enumerate(namen):
        kop[2][1 + 7 * i] = n
    return pd.DataFrame(kop + rijen)


def naar_gnss_df(metingen):
    """Exportlayout GNSS: rij 2 = puntnaam, rij 5 = kolomkoppen, data vanaf rij 6, blokken van 3 kolommen."""
    T = _tijden(metingen)
    namen = list(metingen)
    kop = [[None] * (1 + 3 * len(namen)) for _ in range(6)]
    for i, n in enumerate(namen):
        kop[2][1 + 3 * i] = n
        kop[5][1 + 3 * i:4 + 3 * i] = ["Easting", "Northing", "Height"]
    rijen = []
    for t in T:
        r = [pd.Timestamp(t)]
        for n in namen:
            m = metingen[n].get(t, {})
            r += [_f(m, "Coordinates Local", "Easting"), _f(m, "Coordinates Local", "Northing"),
                  _f(m, "Coordinates Local", "Height")]
        rijen.append(r)
    return pd.DataFrame(kop + rijen)


def geheime_waarden():
    """Waarden die nooit in de gepubliceerde site mogen staan (voor de controle in build.py)."""
    return [v for v in api.geheime_waarden() if v and len(v) >= 6]
