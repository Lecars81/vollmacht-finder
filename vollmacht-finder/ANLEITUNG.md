# Vollmacht-Finder auf GitHub Pages

**So funktioniert es**
- Die App läuft unter `https://lecars81.github.io/vollmacht-finder/`. Die Kollegen öffnen sie ohne Anmeldung.
- Fehlt ein Formular oder stimmt ein Link nicht, tippen sie auf **„Per Mail melden“**. Du bekommst eine fertige Mail mit Kreis, PLZ und Link.
- Jede Nacht prüft GitHub alle Links. Findet die Prüfung für einen defekten Link Ersatz, legt sie einen **Pull Request** an. Du tippst in der GitHub-App auf **Merge**, wenige Minuten später gilt der neue Link für alle.
- Ändern kann nur, wer Schreibzugriff auf dein Repository hat.

**Kosten:** 0 €. Kein Google- oder Firebase-Konto nötig.
**Hinweis:** Das Repository ist öffentlich. Es enthält nur öffentliche Behörden-Links und den Programmcode, keine Passwörter und keine Kundendaten.

---

## Einrichten (ca. 10 Minuten, am PC)

1. **Öffentliches Repository anlegen**
   https://github.com/new → Repository name `vollmacht-finder` → **Public** → **ohne** README → **Create repository**.

2. **Dateien hochladen**
   Entweder **mir Bescheid geben**, dann lade ich alles hoch. Oder selbst: „uploading an existing file“ → den **Inhalt** des Ordners `vollmacht-finder` hineinziehen, inklusive des versteckten Ordners `.github` (Mac: im Finder ⌘ + ⇧ + . drücken, um ihn zu sehen) → **Commit changes**.

3. **Aktionen Schreibrechte geben**
   **Settings → Actions → General** → ganz unten bei *Workflow permissions*: **Read and write permissions** wählen und **Allow GitHub Actions to create and approve pull requests** anhaken → **Save**.

4. **GitHub Pages einschalten**
   **Settings → Pages** → bei *Build and deployment* unter **Source** „**GitHub Actions**“ wählen. (Speichern ist nicht nötig.)

5. **Kontakt hinterlegen**
   **Settings → Secrets and variables → Actions** → Reiter **Variables** → **New repository variable**: Name `KONTAKT_MAIL`, Wert `mhantsche@toyota-kalla.de` → **Add variable**. Die Adresse wird beim Abruf der Behörden-Websites als Kontakt mitgeschickt.

6. **App veröffentlichen**
   Reiter **Actions** → links **App veröffentlichen** → **Run workflow** → grünes **Run workflow**. Nach ca. 1 Minute erscheint ein grüner Haken. Die App ist dann unter `https://lecars81.github.io/vollmacht-finder/` erreichbar.

7. **Erste Prüfung starten**
   **Actions** → **Nächtliche Linkprüfung** → **Run workflow**. Dauert ca. 20–30 Minuten. Danach steht in der App bei jedem Kreis „Geprüft am …“. Ab jetzt läuft das jede Nacht automatisch.

8. **Mitteilungen aufs Handy**
   App „GitHub“ installieren und anmelden. Am PC im Repository oben rechts **Watch → All Activity**. Dann kommen Vorschläge und Prüfberichte als Mitteilung aufs Handy und per Mail.

Auf Handy und Tablet die App-Adresse im Browser öffnen → Teilen → **Zum Home-Bildschirm**.

---

## Im Alltag

**Ein Ersatzvorschlag ist da (Pull Request)**
Mitteilung öffnen → im Text den **Vorschlag** antippen und kurz prüfen, ob es die Vollmacht ist → **Merge pull request** → **Confirm merge**. Passt er nicht: **Close pull request**.

**Ein Prüfbericht ist da (Issue)**
Er listet Formulare, die eine Behörde ausgetauscht hat, und Links ohne gefundenen Ersatz. Nach dem Lesen **Close issue**.

**Ein Kollege meldet einen Link per Mail**
Am einfachsten die Mail an mich weiterleiten, dann trage ich den Link ein. Selbst geht es so: im Repository `web/links.json` öffnen → Stift-Symbol → den Kreis suchen (5-stellige Nummer aus der Mail) und die Adresse hinter `"url":` ersetzen. Fehlt der Kreis noch, so ergänzen:
```
 "12052": {
  "url": "https://…/vollmacht.pdf"
 },
```
→ **Commit changes**. Kurz danach ist der Link online.

**Empfänger der Meldungen ändern:** Datei `web/config.js` → Adresse bei `meldenAn`.

**Optional Mail-Bericht über euren Mailserver:** Unter Settings → Secrets → Actions die Secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM`, `MAIL_TO` anlegen. Nicht nötig, GitHub benachrichtigt ohnehin.

## Gut zu wissen

- Die Prüfung läuft auf Servern von GitHub (USA). Einzelne Behörden-Websites sperren Abrufe aus dem Ausland, dort steht dann „Website nicht erreichbar“. Automatisch ersetzt wird nie etwas, jeder neue Link geht über deine Freigabe.
- Zieht die App später aufs NAS um, kommt `web/links.json` einfach mit.
