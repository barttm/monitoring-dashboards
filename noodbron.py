#!/usr/bin/env python3
"""
noodbron.py
Versleutelde reservebron per project: een handmatige Basetime Excel-export die wordt gebruikt als de
API voor dat project faalt (bv. HTTP 502). Zodra de API weer werkt, wordt automatisch live data gebruikt.

  - Bestand in de repo: noodbron/<neutrale naam>.enc  (AES-256-GCM; naam verraadt het project niet)
  - Sleutel: GitHub Secret DATA_SLEUTEL / lokaal %USERPROFILE%\.basetime-geheim\data_sleutel.txt

Gebruik:
    python noodbron.py <slug> <pad\naar\export.xlsx>      # versleutelen en klaarzetten
    python noodbron.py <slug> --wis                        # noodbron van project verwijderen
Daarna committen en pushen (zet-secrets.ps1 zet DATA_SLEUTEL online).
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
SLEUTEL_PAD = Path.home() / ".basetime-geheim" / "data_sleutel.txt"


def sleutel(maak=False):
    if os.environ.get("DATA_SLEUTEL"):
        return base64.b64decode(os.environ["DATA_SLEUTEL"].strip())
    if SLEUTEL_PAD.exists():
        return base64.b64decode(SLEUTEL_PAD.read_text().strip())
    if not maak:
        raise RuntimeError("Geen DATA_SLEUTEL beschikbaar")
    SLEUTEL_PAD.parent.mkdir(parents=True, exist_ok=True)
    k = AESGCM.generate_key(bit_length=256)
    SLEUTEL_PAD.write_text(base64.b64encode(k).decode("ascii"))
    print("Nieuwe datasleutel aangemaakt in %s" % SLEUTEL_PAD)
    return k


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
