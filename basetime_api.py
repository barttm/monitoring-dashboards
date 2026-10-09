"""
basetime_api.py
Client voor de Basetime RESTful API (AWS Signature Version 4, alleen standaardbibliotheek + requests).

Endpoints:  GET /get-projects                       -> {"Projectnaam": ["Punt1", ...], ...}
            GET /get-data  (headers Project, Point_ID, optioneel Start_Date/End_Date) -> JSON per punt

SECURITY
  - Sleutels komen uitsluitend uit omgevingsvariabelen:
        BASETIME_ACCESS_KEY_ID + BASETIME_SECRET_ACCESS_KEY   (GitHub Secrets)
    of lokaal BASETIME_KEYS_CSV = pad naar het CSV-bestand van Basetime (buiten deze repository!).
  - Sleutels worden nooit geprint, gelogd of weggeschreven; foutmeldingen bevatten ze niet.
  - Alleen HTTPS; de geheime sleutel zelf wordt nooit verstuurd (alleen een HMAC-handtekening).

Lokaal testen (toont alleen projectnamen en aantallen punten):
    BASETIME_KEYS_CSV="pad/naar/accessKeys.csv" python basetime_api.py projecten
"""

import csv
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
from urllib.parse import quote, urlparse

import requests

BASIS_URL = os.environ.get("BASETIME_API_URL") or "https://parvamoti-restful.basetime.nl"
REGIO = os.environ.get("BASETIME_API_REGION") or "eu-west-1"
SERVICE = "execute-api"
TIMEOUT = 120


class ApiFout(RuntimeError):
    pass


def _sleutels():
    kid, geheim = os.environ.get("BASETIME_ACCESS_KEY_ID"), os.environ.get("BASETIME_SECRET_ACCESS_KEY")
    if kid and geheim:
        return kid.strip(), geheim.strip()
    pad = os.environ.get("BASETIME_KEYS_CSV")
    if pad and os.path.exists(pad):
        with open(pad, newline="", encoding="utf-8-sig") as f:
            rij = list(csv.DictReader(f))[0]
        return rij["Access key ID"].strip(), rij["Secret access key"].strip()
    raise ApiFout("Geen API-sleutels: zet BASETIME_ACCESS_KEY_ID/BASETIME_SECRET_ACCESS_KEY (GitHub Secrets) "
                  "of lokaal BASETIME_KEYS_CSV.")


def geheime_waarden():
    """Voor de lekcontrole in build.py (nooit printen)."""
    try:
        return [v for v in _sleutels() if v]
    except ApiFout:
        return []


def _hmac(k, msg):
    return hmac.new(k, msg.encode("utf-8"), hashlib.sha256).digest()


def _onderteken(methode, url, regio):
    kid, geheim = _sleutels()
    u = urlparse(url)
    nu = dt.datetime.now(dt.timezone.utc)
    amzdate, datum = nu.strftime("%Y%m%dT%H%M%SZ"), nu.strftime("%Y%m%d")
    canon_uri = quote(u.path or "/", safe="/-_.~")
    canon_headers = "host:" + u.netloc + "\n" + "x-amz-date:" + amzdate + "\n"
    signed = "host;x-amz-date"
    canon_req = "\n".join([methode, canon_uri, u.query, canon_headers, signed, hashlib.sha256(b"").hexdigest()])
    scope = datum + "/" + regio + "/" + SERVICE + "/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope, hashlib.sha256(canon_req.encode("utf-8")).hexdigest()])
    k = _hmac(("AWS4" + geheim).encode("utf-8"), datum)
    for deel in (regio, SERVICE, "aws4_request"):
        k = _hmac(k, deel)
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"x-amz-date": amzdate,
            "Authorization": "AWS4-HMAC-SHA256 Credential=" + kid + "/" + scope + ", SignedHeaders=" + signed +
                             ", Signature=" + sig}


def _get(pad, extra=None, regio=None):
    url = BASIS_URL.rstrip("/") + pad
    if not url.startswith("https://"):
        raise ApiFout("Alleen HTTPS toegestaan.")
    headers = _onderteken("GET", url, regio or REGIO)
    headers.update(extra or {})
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        # Body van de API bevat geen sleutels; headers (met Authorization) worden nooit getoond.
        raise ApiFout("API %s gaf HTTP %d: %s" % (pad, r.status_code, r.text[:300]))
    return r.json()


def projecten():
    return _get("/get-projects")


def data(project, punt, start=None, eind=None):
    """start/eind: 'YYYY-MM-DD HH:MM:SS+00:00' (UTC) of None."""
    h = {"Project": project, "Point_ID": punt}
    if start:
        h["Start_Date"] = start
    if eind:
        h["End_Date"] = eind
    return _get("/get-data", h)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "projecten":
        p = projecten()
        for naam, punten in p.items():
            print("%-50s %3d punten" % (naam, len(punten)))
    elif len(sys.argv) > 3 and sys.argv[1] == "data":
        js = data(sys.argv[2], sys.argv[3])
        m = js.get("Measurements", {})
        print(json.dumps({k: v for k, v in js.items() if k != "Measurements"}, indent=1, ensure_ascii=False))
        print("metingen:", len(m))
        if m:
            k = sorted(m)[-1]
            print("laatste", k, json.dumps(m[k], ensure_ascii=False)[:900])
    else:
        print(__doc__)
