#!/usr/bin/env python3
"""
Vollmacht-Finder – nächtliche Linkprüfung (Autohaus Kalla)

Prüft jeden hinterlegten Vollmacht-Link der Zulassungsbehörden:
  * Ist der Link erreichbar?
  * Ist es (noch) eine Datei (PDF/Word/…) bzw. die erwartete Formularseite?
  * Hat sich die Datei geändert (Fingerabdruck SHA-256)?
Geprüfte Dateien werden als Kopie gespeichert, damit die App sie direkt anzeigen kann.
Ist ein Link zwei Nächte in Folge defekt, sucht der Dienst auf der Website der Behörde
nach Ersatz und legt Vorschläge ab – übernommen wird nur nach Bestätigung in der App.

Nur Python-Standardbibliothek, keine Zusatzpakete.
"""
import datetime as dt
import hashlib
import html.parser
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from email.message import EmailMessage

DATA = os.environ.get("DATA_DIR", "/data")
COPY_DIR = os.path.join(DATA, "kopien")
BASE_LINKS = os.environ.get("BASE_LINKS", "/app/web/links.json")  # mitgelieferte Basisliste (nur lesen)
MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = 25
HOST_DELAY = 1.5  # Sekunden Pause zwischen Abrufen derselben Website
CONTACT = os.environ.get("CONTACT", "")
UA = "Vollmacht-Finder/1.0 (Linkpruefung Autohaus Kalla" + (f"; {CONTACT}" if CONTACT else "") + ")"

FILE_EXT = re.compile(r"\.(pdf|docx?|zip|jpe?g|png)(\?|$)", re.I)
KEYWORDS_FOLLOW = re.compile(r"kfz|zulass|fahrzeug|formular|download|vollmacht|verkehr|buergerservice|service|dienstleist", re.I)
EXCLUDE = re.compile(r"gbr|qr|f(ue|ü)hrerschein|reisepass|personalausweis|vorsorge|betreuung|standesamt|meldeamt|ausl(ae|ä)nder", re.I)

import threading
RUN_LOCK = threading.Lock()  # nie zwei Prüfläufe gleichzeitig
_last_hit = {}
_robots = {}


# ---------------------------------------------------------------- Hilfsfunktionen
def now():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def load(name, default):
    p = os.path.join(DATA, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name, obj):
    p = os.path.join(DATA, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def effective_links():
    """Basisliste + gespeicherte Änderungen aus der App (overrides gewinnen)."""
    try:
        with open(BASE_LINKS, encoding="utf-8") as f:
            base = json.load(f)
    except FileNotFoundError:
        base = {}
    over = load("overrides.json", {})
    out = dict(base)
    for k, v in over.items():
        if v.get("url"):
            out[k] = v
        else:
            out.pop(k, None)
    return out


def robots_ok(url):
    p = urllib.parse.urlsplit(url)
    root = f"{p.scheme}://{p.netloc}"
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
                rp.parse(r.read(200_000).decode("utf-8", "replace").splitlines())
        except Exception:
            rp = None  # keine robots.txt lesbar -> erlaubt
        _robots[root] = rp
    rp = _robots[root]
    return True if rp is None else rp.can_fetch(UA, url)


def fetch(url):
    """Lädt eine URL höflich (Pause je Website). Gibt dict mit status, ctype, body, final_url zurück."""
    host = urllib.parse.urlsplit(url).netloc
    wait = HOST_DELAY - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            body = r.read(MAX_BYTES + 1)
            return {"status": r.status, "ctype": r.headers.get("Content-Type", ""), "body": body[:MAX_BYTES],
                    "final_url": r.geturl(), "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ctype": "", "body": b"", "final_url": url, "error": f"HTTP {e.code}"}
    except Exception as e:  # Timeout, DNS, Zertifikat …
        return {"status": 0, "ctype": "", "body": b"", "final_url": url, "error": type(e).__name__ + ": " + str(e)[:120]}


def sniff(body, ctype, url):
    """Erkennt den Dateityp am Inhalt (nicht nur am Header)."""
    b = body[:8]
    if b.startswith(b"%PDF"):
        return "pdf"
    if b.startswith(b"PK"):
        return "docx" if re.search(r"\.docx", url, re.I) else "zip"
    if b.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    if b.startswith(b"\xff\xd8"):
        return "jpg"
    if b.startswith(b"\x89PNG"):
        return "png"
    if "html" in ctype.lower() or body[:400].lstrip().lower().startswith((b"<!doctype", b"<html")):
        return "html"
    return "unbekannt"


class LinkParser(html.parser.HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links, self._href, self._text = base, [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                self._href, self._text = urllib.parse.urljoin(self.base, href), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href.split("#")[0], " ".join("".join(self._text).split())))
            self._href = None


def links_of(body, base):
    p = LinkParser(base)
    try:
        p.feed(body.decode("utf-8", "replace"))
    except Exception:
        pass
    return p.links


def same_site(a, b):
    ha, hb = urllib.parse.urlsplit(a).netloc.lower(), urllib.parse.urlsplit(b).netloc.lower()
    da, db = ".".join(ha.split(".")[-2:]), ".".join(hb.split(".")[-2:])
    return da == db


def vollmacht_candidates(links):
    out = []
    for href, text in links:
        t = f"{text} {href}"
        if "vollmacht" not in t.lower() or EXCLUDE.search(t):
            continue
        score = 1 + (2 if re.search(r"zulass|kfz|fahrzeug", t, re.I) else 0) + (1 if FILE_EXT.search(href) else 0)
        out.append({"url": href, "text": text[:120], "score": score})
    return out


def find_replacement(dead_url, extra_start=None, max_pages=30):
    """Durchsucht die Website der Behörde nach einem neuen Vollmacht-Link."""
    p = urllib.parse.urlsplit(dead_url)
    starts = [u for u in [extra_start, f"{p.scheme}://{p.netloc}/"] if u]
    # Elternverzeichnisse des toten Links (oft die Formularseite)
    path = p.path
    while "/" in path.strip("/"):
        path = path.rsplit("/", 1)[0]
        starts.append(f"{p.scheme}://{p.netloc}{path}/")
    seen, queue, found = set(), list(dict.fromkeys(starts)), {}
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen or not robots_ok(url):
            continue
        seen.add(url)
        r = fetch(url)
        if r["status"] != 200 or sniff(r["body"], r["ctype"], url) != "html":
            continue
        lks = links_of(r["body"], r["final_url"])
        for c in vollmacht_candidates(lks):
            if c["url"] != dead_url:
                found[c["url"]] = max(c, found.get(c["url"], c), key=lambda x: x["score"])
        for href, text in lks:
            if href not in seen and same_site(href, dead_url) and KEYWORDS_FOLLOW.search(href + " " + text) \
                    and not FILE_EXT.search(href) and len(queue) < 200:
                queue.append(href)
    return sorted(found.values(), key=lambda c: -c["score"])[:5]


# ---------------------------------------------------------------- Prüflauf
def check_one(key, entry, old):
    url = entry["url"]
    st = dict(old)
    st["checked"] = now()
    st["url"] = url
    if not robots_ok(url):
        st.update(state="nicht_pruefbar", error="Website erlaubt keinen automatischen Abruf (robots.txt)")
        return st, None
    r = fetch(url)
    kind = sniff(r["body"], r["ctype"], url) if r["status"] == 200 else None
    expects_file = bool(FILE_EXT.search(url)) and not entry.get("seite")
    broken = r["status"] != 200 or (expects_file and kind == "html")
    if broken:
        st["fails"] = old.get("fails", 0) + 1
        st["error"] = r["error"] or ("Statt einer Datei kam eine Webseite zurück" if kind == "html" else "Fehler")
        st["state"] = "defekt" if st["fails"] >= 2 else "stoerung"
        event = None
        if st["state"] == "defekt" and old.get("state") != "defekt":
            st["candidates"] = find_replacement(url)
            event = ("defekt", st["candidates"])
        return st, event
    st["fails"] = 0
    st.pop("error", None)
    st["kind"] = kind
    event = None
    if kind != "html":
        h = hashlib.sha256(r["body"]).hexdigest()
        if old.get("hash") and old["hash"] != h and old.get("url") == url:
            st["changed"] = now()
            event = ("geaendert", None)
        st["hash"] = h
        os.makedirs(COPY_DIR, exist_ok=True)
        ext = {"pdf": "pdf", "doc": "doc", "docx": "docx", "zip": "zip", "jpg": "jpg", "png": "png"}.get(kind, "bin")
        name = f"{key}.{ext}"
        with open(os.path.join(COPY_DIR, name), "wb") as f:
            f.write(r["body"])
        st["copy"] = name
        st["size"] = len(r["body"])
    elif entry.get("seite"):
        # Formularseite: zählen, ob dort (noch) ein Vollmacht-Link steht
        st["seite_links"] = len(vollmacht_candidates(links_of(r["body"], r["final_url"])))
    st["state"] = "geaendert" if event else "ok"
    if old.get("state") in ("defekt", "stoerung"):
        st.pop("candidates", None)
    return st, event


def run(only=None):
    with RUN_LOCK:
        return _run(only)


def _run(only=None):
    links = effective_links()
    status = load("status.json", {})
    events = []
    keys = sorted(links) if not only else [k for k in only if k in links]
    started = time.time()
    for i, key in enumerate(keys, 1):
        try:
            st, ev = check_one(key, links[key], status.get(key, {}))
        except Exception as e:
            st, ev = dict(status.get(key, {}), state="stoerung", error=f"Prüffehler: {e}", checked=now()), None
        status[key] = st
        if ev:
            events.append((key, ev))
        if i % 25 == 0:
            save("status.json", status)
            print(f"[{now()}] {i}/{len(keys)} geprüft", flush=True)
    # Einträge entfernen, die nicht mehr in der Liste stehen
    for k in list(status):
        if k not in links:
            status.pop(k)
    save("status.json", status)
    summary = {"lauf": now(), "dauer_min": round((time.time() - started) / 60, 1), "geprueft": len(keys),
               "ok": sum(1 for k in keys if status[k].get("state") in ("ok", "geaendert")),
               "defekt": [k for k in keys if status[k].get("state") == "defekt"],
               "stoerung": [k for k in keys if status[k].get("state") == "stoerung"],
               "nicht_pruefbar": [k for k in keys if status[k].get("state") == "nicht_pruefbar"],
               "ereignisse": [{"kreis": k, "art": e[0]} for k, e in events]}
    if only:  # Einzelprüfung nach dem Speichern in der App: kein Gesamtbericht
        return summary
    save("letzter_lauf.json", summary)
    report(events, status, summary)
    return summary


def report(events, status, summary):
    names = load("kreise.json", {})
    lines = [f"Vollmacht-Finder – Prüflauf {summary['lauf']}",
             f"Geprüft: {summary['geprueft']}  ·  in Ordnung: {summary['ok']}  ·  defekt: {len(summary['defekt'])}"
             f"  ·  vorübergehend gestört: {len(summary['stoerung'])}", ""]
    for key, (art, cands) in events:
        n = names.get(key, key)
        if art == "geaendert":
            lines.append(f"GEÄNDERT  {n} ({key}): Die Behörde hat ein neues Formular hinterlegt – bitte kurz prüfen.")
            lines.append(f"          {status[key]['url']}")
        elif art == "defekt":
            lines.append(f"DEFEKT    {n} ({key}): {status[key].get('error')}")
            if cands:
                lines.append("          Vorschläge (in der App unter dem Kreis bestätigen):")
                lines += [f"          – {c['text'] or 'Link'}: {c['url']}" for c in cands]
            else:
                lines.append("          Kein Ersatz gefunden – bitte Link in der App neu speichern.")
        lines.append("")
    text = "\n".join(lines)
    with open(os.path.join(DATA, "bericht.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text, flush=True)
    if events:
        send_mail(f"Vollmacht-Finder: {len(events)} Änderung(en) bei Zulassungsstellen", text)


def send_mail(subject, text):
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("MAIL_TO")
    if not host or not to:
        print("Kein Mailversand konfiguriert (SMTP_HOST/MAIL_TO fehlen).", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", to)), to
    msg.set_content(text)
    port = int(os.environ.get("SMTP_PORT") or 587)
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(host, port, timeout=30)
            s.starttls(context=ssl.create_default_context())
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
        s.send_message(msg)
        s.quit()
        print("Bericht per Mail gesendet an", to, flush=True)
    except Exception as e:
        print("Mailversand fehlgeschlagen:", e, flush=True)


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1:] or None), ensure_ascii=False, indent=1))
