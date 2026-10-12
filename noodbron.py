#!/usr/bin/env python3
"""
noodbron.py
Versleutelde reservebron per project: een handmatige Basetime Excel-export die wordt gebruikt als de
API voor dat project faalt (bv. HTTP 502). Zodra de API weer werkt, wordt automatisch live data gebruikt.

  - Bestand in de repo: noodbron/<neutrale naam>.enc  (AES-256-GCM; naam verraadt het project niet)
  - Sleutel: afgeleid van de Basetime secret access key (geen extra geheim nodig)

Gebruik:
    python noodbron.py <slug> <pad\naar\export.xlsx>      # versleutelen en klaarzetten
    python noodbron.py <slug> --wis                        # noodbron van project verwijderen
Daarna committen en pushen.
"""

import base64
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASIS = Path(__file__).resolve().parent
MAP = BASIS / "noodbron"
sys.path.insert(0, str(BASIS))


def sleutel(maak=False):
    """AES-sleutel voor de noodbron: afgeleid van de Basetime secret access key (staat al als GitHub Secret
    en lokaal in de geheime map), zodat er geen extra geheim beheerd hoeft te worden."""
    import basetime_api
    _, geheim = basetime_api._sleutels()
    return hashlib.sha256(("nepocon-noodbron:" + geheim).encode("utf-8")).digest()


def bestandsnaam(project):
    """Neutrale, niet-terug te herleiden naam (hash van slug + linkcode)."""
    return hashlib.sha256((project["slug"] + ":" + project.get("code", "")).encode()).hexdigest()[:20] + ".enc"


def lees(project):
    """DataFrame (header=None) uit de noodbron, of None als er geen noodbron is."""
    import pandas as pd
    pad = MAP / bestandsnaam(project)
    if not pad.exists():
        return None
    blob = pad.read_bytes()
    xlsx = AESGCM(sleutel()).decrypt(blob[:12], blob[12:], project["slug"].encode())
    return pd.read_excel(io.BytesIO(xlsx), header=None)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    slug, arg = sys.argv[1], sys.argv[2]
    cfg = json.loads((BASIS / "projecten.json").read_text(encoding="utf-8"))
    project = next((p for p in cfg["projecten"] if p["slug"] == slug), None)
    if not project:
        sys.exit("Onbekende slug: %s" % slug)
    pad = MAP / bestandsnaam(project)
    if arg == "--wis":
        pad.unlink(missing_ok=True)
        print("Noodbron verwijderd voor %s" % slug)
        return
    data = Path(arg).read_bytes()
    MAP.mkdir(exist_ok=True)
    iv = os.urandom(12)
    pad.write_bytes(iv + AESGCM(sleutel(maak=True)).encrypt(iv, data, slug.encode()))
    print("Noodbron klaar: noodbron/%s (%d kB, versleuteld)" % (pad.name, pad.stat().st_size // 1024))


if __name__ == "__main__":
    main()
