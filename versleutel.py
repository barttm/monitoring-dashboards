"""
versleutel.py
Versleutelt een dashboard-HTML met een wachtwoord (zelfde principe als StatiCrypt):
  - sleutel = PBKDF2-HMAC-SHA256(wachtwoord, salt, 600.000 rondes) -> AES-256-GCM
  - de inlogpagina bevat alleen versleutelde bytes; ontsleutelen gebeurt in de browser (WebCrypto)
  - zonder het juiste wachtwoord is de inhoud niet te lezen, ook niet in de paginabron

Salt is vast per project (afgeleid van de slug), zodat 'Onthoud op dit apparaat' blijft werken
na de dagelijkse build. Het IV is elke build nieuw (verplicht voor AES-GCM).
"""

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROUNDS = 600_000


def _salt(slug):
    return hashlib.sha256(("nepocon-dashboards:" + slug).encode("utf-8")).digest()[:16]


def versleutel(html, wachtwoord, slug):
    salt = _salt(slug)
    key = hashlib.pbkdf2_hmac("sha256", wachtwoord.encode("utf-8"), salt, ROUNDS, dklen=32)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
        "rounds": ROUNDS,
    }


def ontsleutel(blob, wachtwoord):
    """Alleen voor tests: controleert dat de versleuteling terug te draaien is."""
    salt, iv, ct = (base64.b64decode(blob[k]) for k in ("salt", "iv", "ct"))
    key = hashlib.pbkdf2_hmac("sha256", wachtwoord.encode("utf-8"), salt, blob["rounds"], dklen=32)
    return AESGCM(key).decrypt(iv, ct, None).decode("utf-8")


LOGIN_TEMPLATE = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>__TITEL__</title>
<style>
:root { --blauw: #004B8D; --tekst: #1a2233; --grijs: #6b7686; --lijn: #dfe4ec; --bg: #f5f7fa; --rood: #D62728; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px;
       font-family: "Segoe UI", Arial, sans-serif; background: var(--bg); color: var(--tekst); }
.box { width: 100%; max-width: 380px; background: #fff; border: 1px solid var(--lijn); border-top: 3px solid var(--blauw);
       border-radius: 4px; padding: 28px 28px 24px; }
.box img { height: 40px; display: block; margin-bottom: 18px; }
h1 { font-size: 16px; margin: 0 0 4px; }
.sub { font-size: 12px; color: var(--grijs); margin-bottom: 20px; }
label { font-size: 12px; font-weight: 600; display: block; margin-bottom: 6px; }
input[type=password] { width: 100%; padding: 10px; font-size: 14px; border: 1px solid var(--lijn); border-radius: 3px; }
input[type=password]:focus { outline: 2px solid var(--blauw); outline-offset: -1px; }
.rem { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--grijs); margin: 12px 0 16px; }
button { width: 100%; padding: 10px; font-size: 14px; font-weight: 600; border: 0; border-radius: 3px; background: var(--blauw); color: #fff; cursor: pointer; }
button:disabled { opacity: .6; cursor: wait; }
.err { color: var(--rood); font-size: 12px; min-height: 16px; margin-top: 10px; }
.foot { font-size: 10.5px; color: var(--grijs); margin-top: 18px; line-height: 1.5; }
.foot a, .terug { color: var(--blauw); }
.terug { display: inline-block; font-size: 12px; text-decoration: none; margin-top: 14px; }
.terug:hover { text-decoration: underline; }
</style>
</head>
<body>
<form class="box" id="f" autocomplete="on">
  __LOGO__
  <h1>__NAAM__</h1>
  <div class="sub">Beveiligd monitoringdashboard</div>
  <input type="text" name="username" value="__SLUG__" autocomplete="username" hidden>
  <label for="pw">Wachtwoord</label>
  <input type="password" id="pw" autocomplete="current-password" required autofocus>
  <label class="rem"><input type="checkbox" id="rem"> Onthoud op dit apparaat</label>
  <button type="submit" id="btn">Openen</button>
  <div class="err" id="err"></div>
  <div class="foot">Wachtwoord vergeten? Neem contact op met
    <a href="mailto:b.termull@nepocon.nl?subject=Wachtwoord%20monitoringdashboard%20__SLUG__">b.termull@nepocon.nl</a>.</div>
</form>
<script>
var B = __BLOB__;
var KEY_ID = 'nd-key-__SLUG__';
function b64(s) { var r = atob(s), u = new Uint8Array(r.length); for (var i = 0; i < r.length; i++) u[i] = r.charCodeAt(i); return u; }
function toB64(buf) { var u = new Uint8Array(buf), s = ''; for (var i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); }
function derive(pw) {
  return crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveBits'])
    .then(function(k){ return crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(B.salt), iterations: B.rounds }, k, 256); });
}
function openWith(bits) {
  return crypto.subtle.importKey('raw', bits, 'AES-GCM', false, ['decrypt'])
    .then(function(k){ return crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(B.iv) }, k, b64(B.ct)); })
    .then(function(pt){
      var html = new TextDecoder().decode(pt);
      document.open(); document.write(html); document.close();
    });
}
function store(bits) { try { localStorage.setItem(KEY_ID, toB64(bits)); } catch (e) {} }
function forget() { try { localStorage.removeItem(KEY_ID); } catch (e) {} }
document.getElementById('f').addEventListener('submit', function(e){
  e.preventDefault();
  var btn = document.getElementById('btn'), err = document.getElementById('err');
  if (!window.crypto || !crypto.subtle) { err.textContent = 'Deze browser ondersteunt geen versleuteling (gebruik https en een moderne browser).'; return; }
  btn.disabled = true; btn.textContent = 'Bezig...'; err.textContent = '';
  var rem = document.getElementById('rem').checked, keyBits;
  derive(document.getElementById('pw').value)
    .then(function(bits){ keyBits = bits; return openWith(bits); })
    .then(function(){ if (rem) store(keyBits); })
    .catch(function(){ btn.disabled = false; btn.textContent = 'Openen'; err.textContent = 'Onjuist wachtwoord.'; });
});
(function(){
  var saved = null;
  try { saved = localStorage.getItem(KEY_ID); } catch (e) {}
  if (saved && window.crypto && crypto.subtle) { openWith(b64(saved).buffer).catch(forget); }
})();
</script>
</body>
</html>
"""


def login_pagina(blob, naam, slug, logo_html):
    html = LOGIN_TEMPLATE
    html = html.replace("__BLOB__", json.dumps(blob))
    html = html.replace("__LOGO__", logo_html)
    html = html.replace("__NAAM__", naam)
    html = html.replace("__TITEL__", naam + " - Nepocon")
    html = html.replace("__SLUG__", slug)
    return html
