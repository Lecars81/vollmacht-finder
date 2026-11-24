#!/usr/bin/env python3
"""
Vollmacht-Finder – nächtliche Prüfung in GitHub Actions (Variante „Pflege über GitHub“)

1. Prüft alle Links aus web/links.json mit derselben Logik wie auf dem NAS (check.py).
2. Schreibt das Ergebnis nach web/status.json (die App zeigt daraus „Geprüft am …“ und defekte Links).
3. Für jeden neu defekten Link mit gefundenem Ersatz: eigener Pull Request mit dem neuen Link.
   Freigabe = in GitHub auf „Merge“ tippen.
4. Gab es Änderungen oder Defekte: ein Issue „Prüfbericht“ (GitHub benachrichtigt per App/Mail).
   Optional zusätzlich Mail über SMTP_* (siehe check.py).

Benötigt im Workflow: git, gh (GitHub CLI) und GH_TOKEN.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKS = os.path.join(ROOT, "web", "links.json")
STATUS = os.path.join(ROOT, "web", "status.json")
TMP = tempfile.mkdtemp(prefix="vf-")
os.environ["DATA_DIR"] = TMP
os.environ["BASE_LINKS"] = LINKS

import check  # noqa: E402

KEEP = ("url", "state", "checked", "changed", "error", "candidates", "hash", "fails", "kind", "seite_links")
DRY = os.environ.get("VF_DRY_RUN") == "1"   # zum Testen: nichts pushen


def sh(*cmd, check_=True):
    print("$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode and check_:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(r.returncode)
    return r


def write_links(links):
    with open(LINKS, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(links.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")


def main():
    with open(os.path.join(ROOT, "web", "plz.json"), encoding="utf-8") as f:
        names = json.load(f)["d"]
    check.save("kreise.json", names)
    try:
        with open(STATUS, encoding="utf-8") as f:
            prev = json.load(f).get("kreise", {})
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}
    check.save("status.json", prev)
    check.save("overrides.json", {})

    before = {k: v.get("state") for k, v in prev.items()}
    summary = check.run(sys.argv[1:] or None)
    status = check.load("status.json", {})

    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump({"lauf": summary.get("lauf"),
                   "kreise": {k: {x: v[x] for x in KEEP if x in v} for k, v in sorted(status.items())}},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")

    # 1) Status auf main sichern
    sh("git", "config", "user.name", "Vollmacht-Prüfung")
    sh("git", "config", "user.email", "actions@users.noreply.github.com")
    sh("git", "add", "web/status.json")
    if sh("git", "diff", "--cached", "--quiet", check_=False).returncode:
        sh("git", "commit", "-m", f"Prüfung {summary.get('lauf')}")
        if not DRY:
            sh("git", "push", "origin", "HEAD:main")

    # 2) Pull Request je neu defektem Link mit Vorschlag
    with open(LINKS, encoding="utf-8") as f:
        links = json.load(f)
    created = []
    for key, st in sorted(status.items()):
        if st.get("state") != "defekt" or before.get(key) == "defekt" or not st.get("candidates"):
            continue
        best = st["candidates"][0]
        name = names.get(key, key)
        branch = f"vorschlag-{key}-{hashlib.sha1(best['url'].encode()).hexdigest()[:8]}"
        if sh("git", "ls-remote", "--exit-code", "--heads", "origin", branch, check_=False).returncode == 0:
            continue  # Vorschlag existiert schon
        sh("git", "checkout", "-q", "-b", branch, "main" if not DRY else "HEAD")
        new = dict(links)
        new[key] = {"url": best["url"], "note": "Von der nächtlichen Prüfung gefunden und freigegeben"}
        write_links(new)
        sh("git", "commit", "-q", "-am", f"Neuer Vollmacht-Link: {name} ({key})")
        others = "\n".join(f"- [{c.get('text') or 'Link'}]({c['url']})" for c in st["candidates"][1:])
        body = (f"Der bisherige Vollmacht-Link für **{name}** ({key}) funktioniert seit zwei Nächten nicht mehr "
                f"({st.get('error')}).\n\nBisher: {st.get('url')}\n\n**Vorschlag:** [{best.get('text') or 'Link'}]({best['url']})\n\n"
                "Bitte den Vorschlag kurz öffnen und prüfen. Passt er, unten auf **Merge pull request** tippen – "
                "zwei Minuten später gilt der neue Link für alle.\n" + (f"\nWeitere Funde auf der Website:\n{others}\n" if others else ""))
        if not DRY:
            sh("git", "push", "-q", "origin", branch)
            sh("gh", "pr", "create", "--base", "main", "--head", branch,
               "--title", f"Neuer Vollmacht-Link: {name}", "--body", body)
        created.append(branch)
        sh("git", "checkout", "-q", "-")

    # 3) Prüfbericht als Issue, wenn es etwas zu tun gibt
    ev = summary.get("ereignisse", [])
    if ev and not DRY:
        with open(os.path.join(TMP, "bericht.txt"), encoding="utf-8") as f:
            text = f.read()
        if created:
            text += "\nFür gefundene Ersatz-Links wurden Pull Requests angelegt (Reiter „Pull requests“)."
        sh("gh", "issue", "create", "--title", f"Prüfbericht {summary.get('lauf', '')[:10]}: {len(ev)} Änderung(en)",
           "--body", "```\n" + text + "\n```")

    out = os.environ.get("GITHUB_STEP_SUMMARY")
    rep = os.path.join(TMP, "bericht.txt")
    if out and os.path.exists(rep):
        with open(rep, encoding="utf-8") as f, open(out, "a", encoding="utf-8") as g:
            g.write("```\n" + f.read() + "\n```\n")
    print(json.dumps({"zusammenfassung": summary, "pull_requests": created}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
