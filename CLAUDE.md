# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projekt

Deutschsprachige **Home-Assistant-App** (bis HA 2026.1 „Add-on") „Vorratsverwaltung": Vorrat, Einkaufslisten,
Rezepte (PDF-/Web-/Text-Import), Essensplaner, Küchen-Timer. Öffentliches Repo – andere Nutzer installieren
es über den App-Store von Home Assistant. Ausführliche Details (alle DB-Spalten, Feature-Liste,
Fehler-Tabelle): **[PROJEKT_KONTEXT.md](PROJEKT_KONTEXT.md)**.

UI-Texte, Kommentare, Doku und Commit-Nachrichten sind **Deutsch**. Python-Bezeichner deutsch, aber
ohne Umlaute (`produkt_bestaende`, `naehrwerte`).

## Befehle

Kein Build-Schritt, kein Linter, keine Test-Suite im Repo. Home Assistant baut das Image aus dem
`Dockerfile` (`python:3.11-alpine`, kopiert nur `app/` und `run.sh`; `run.sh` setzt
`DB_PATH=/share/vorratsverwaltung/vorrat.db`).

Lokal starten (Port 5000; ohne `SUPERVISOR_TOKEN` sind alle Home-Assistant-Funktionen still aus):
```bash
pip install -r app/requirements.txt
DB_PATH=/tmp/vorrat_dev.db python app/app.py
```
`db_migrieren()` läuft nur im `__main__`-Block – wer `app` importiert, muss es selbst aufrufen.
Jinja-Templates werden bei `debug=False` gecacht → nach Template-Änderungen den Server neu starten.

**Testen** = Python-Skript mit dem Flask-Testclient (aus dem Repo-Root starten):
```python
import sys, os, re, types, tempfile
sys.modules.setdefault("pdfplumber", types.ModuleType("pdfplumber"))   # pdfplumber muss nicht installiert sein
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "v.db")        # IMMER eine Wegwerf-DB
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, "app")
import app as A
A.db_migrieren(); c = A.app.test_client()
tok = lambda p: re.search(r'name="_csrf" value="([^"]+)"', c.get(p).get_data(as_text=True)).group(1)
c.post("/produkt/neu", data={"name": "Mehl", "menge": "2", "einheit": "Packung", "_csrf": tok("/produkt/neu")})
```
Jeder POST braucht das `_csrf`-Feld aus einer gerenderten Seite (sonst 400). DB-Zugriffe außerhalb von
Requests nur in `with A.app.app_context():`. Migrationstest: die alte Version per `git show HEAD:app/app.py`
in einem eigenen Prozess eine DB anlegen lassen, danach den neuen Code darauf starten.

## Architektur (das große Bild)

Fast alles steckt in **`app/app.py`** (~3800 Zeilen, Abschnitte mit `# ── Titel ──` markiert);
`translations.py` liefert DE/EN/FR/ES, Templates in `app/templates/` (Jinja, Inline-CSS, Themes über
CSS-Variablen in `base.html`).

- **HA Ingress:** Die App läuft in einem iframe unter einem wechselnden Pfad-Präfix (`ReverseProxied`
  setzt `SCRIPT_NAME` aus `X-Ingress-Path`). Nie absolute Pfade – in Python und Templates immer
  `url_for()`, in JS URLs per `url_for` ins Template rendern; statische Manifest-Pfade relativ.
- **Datenbank ohne Alembic:** `db_migrieren()` = `db.create_all()` (neue Tabellen) + `ALTER TABLE` mit
  `spalte_existiert()`-Prüfung. Neue Spalte = ORM-Feld **und** Eintrag in der Migrationsliste.
  Achtung: Einige `produkt`-Spalten existieren **nur per Raw-SQL** und sind keine ORM-Attribute
  (`angebrochen`, `angebrochen_prozent`, `gebinde`, `eingefroren`, `eingekocht`, `herkunft`, `behaelter`,
  `markierung`, Datumsfelder) – gelesen/geschrieben mit `db.text(...)`/`sqlite3`; Routen setzen daraus
  Hilfsattribute wie `p.ist_angebrochen`, `p.gebinde_wert`.
- **CSRF:** `before_request` prüft jeden POST; `after_request` fügt in **jedes** `<form method="post">`
  automatisch das versteckte `_csrf`-Feld ein. AJAX sendet `X-CSRF-Token` (Meta-Tag in `base.html`).
- **Fremde URLs (SSRF):** Abrufe nur über `_get_sicher()` / `seite_laden()` (nur öffentliche IPs, jeder
  Redirect geprüft, 5-MB-Limit) – nie direkt `requests.get` auf Nutzer- oder Fremd-URLs.
- **Home-Assistant-Anbindung** (`SUPERVISOR_TOKEN`, `_ha_api()` → `http://supervisor/core/api`):
  Sensoren `sensor.vorrat_*` per REST – nicht persistent, darum setzt ein Daemon-Thread
  (`ha_sensoren_aktualisieren`) sie alle 5 Min neu. Kalender per REST + Websocket
  (`ws://supervisor/core/websocket`, Lösch-Fall). Küchen-Timer: Event `vorrat_kochtimer_fertig`,
  `sensor.vorrat_kochtimer`, optional `notify.<dienst>`.
  **Portabilität:** nie Entitäten/Dienste einer bestimmten Installation hartkodieren – Listen
  (notify-Dienste, Kalender) live aus der jeweiligen HA lesen, Doku-Beispiele mit Platzhaltern
  (`notify.mobile_app_DEIN_HANDY`).
- **Mengen & Rezept-Abgleich:** `rezept_abgleich(rezept, faktor)` ist die **einzige** Quelle für
  Rezeptseite, „Fehlende Zutaten hinzufügen" (`rezept_zur_liste`, auch Essensplaner) und „Verwendet in
  Rezepten". Bausteine: `einheit_basis()` (g/ml/Stück), `produkt_bestaende()` (Packung × `inhalt`,
  offene Packung nur mit Rest), `produkt_fuer_zutat()` (gemerkte `ZutatZuordnung` > sicherer
  Namenstreffer > „unsicher"). Neue Ableitungen dort einhängen, nicht parallel nachbauen.
- **Produkt bearbeiten nur an EINEM Platz** (bewusste Designentscheidung): Produktseite
  `/produkt/<id>` mit einem Formular → `POST /produkt/<id>/bearbeiten`. Grundfelder liegen im Include
  `_produkt_felder.html` (gemeinsam mit „Neues Produkt"). Neue Produktfelder dort ergänzen – keine
  zweiten Bearbeiten-Knöpfe oder Extra-Formulare. „Zurück zur Übersicht" über `uebersicht_url(id)`
  (letzter Filter aus `session["filter"]` + Sprung zur Zeile `#p<id>`).
- `base.html` enthält den globalen Küchen-Timer (Knopf unten rechts + Modal); Mobil-Layout über
  `@media`-Breakpoints in den Templates (auf dem Handy läuft die App in der Home-Assistant-App).

## Release-Ablauf

- Commits, Pushes und die Versionsnummer gibt der **Maintainer frei** – nicht eigenmächtig committen,
  taggen oder pushen.
- Laufende Änderungen beim Entwickeln in `CHANGELOG.md` unter `## Nächste Version` sammeln (ganz oben).
- Beim Release: Überschrift → exakt `## X.Y.Z` (kein Datum/„v"/Zusatz – HA schneidet die Update-Hinweise
  per Regex zwischen neuer und installierter Version aus, sonst zeigt es den ganzen Changelog),
  `version` in `config.yaml` gleich setzen, bei neuer Minor-Version die Tabelle in `SECURITY.md`,
  `**Aktuelle Version:**` in `PROJEKT_KONTEXT.md`. Dann Commit, Tag `vX.Y.Z`, Push von `main` + Tag.
- `CHANGELOG.md` muss LF-Zeilenenden behalten (`.gitattributes`); die README enthält keinen Changelog,
  nur einen Verweis.

Persönliche Einstellungen (Git-Identität, Entwicklungs-PC, eigene HA-Installation) gehören in
`CLAUDE.local.md` – per `.gitignore` ausgeschlossen, wird nicht hochgeladen.
