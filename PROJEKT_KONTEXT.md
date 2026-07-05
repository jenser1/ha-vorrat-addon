# 🥫 Vorratsverwaltung – Projekt-Kontext für Claude Code

## Überblick
Home Assistant Add-on für Haushalts-Vorratsverwaltung mit Rezepten, Einkaufslisten und Web-Import.

**GitHub:** https://github.com/jenser1/ha-vorrat-addon
**Aktuelle Version:** 1.6.0

---

## Tech-Stack
- **Backend:** Python 3.11 + Flask + SQLAlchemy
- **Frontend:** Jinja2 Templates + Inline CSS
- **Datenbank:** SQLite unter `/share/vorratsverwaltung/vorrat.db`
- **Container:** Python 3.11 Alpine (kein HA Base Image)
- **PDF:** pdfplumber
- **Web-Scraping:** requests + BeautifulSoup

---

## Verzeichnisstruktur
```
ha-vorrat-addon/
├── config.yaml          # HA Add-on Konfiguration
├── Dockerfile
├── run.sh               # Startskript
├── hacs.json
├── SECURITY.md
├── README.md
└── app/
    ├── app.py           # Flask-App (alle Routen & Logik)
    ├── translations.py  # DE/EN/FR/ES Übersetzungen
    ├── requirements.txt
    └── templates/
        ├── base.html              # Layout, Bottom-Nav, Themes
        ├── index.html             # Produktübersicht mit Stepper
        ├── produkt_form.html      # Produkt anlegen/bearbeiten
        ├── einkauf_uebersicht.html # Einkaufslisten-Übersicht
        ├── einkauf.html           # Einkaufsliste Detail
        ├── rezepte.html           # Rezeptübersicht
        ├── rezept_detail.html     # Rezept mit Vorrat-Abgleich
        ├── rezept_form.html       # Rezept anlegen/bearbeiten
        ├── rezept_pdf_import.html # PDF-Upload & Extraktion
        ├── rezept_web_import.html # Web-Import
        └── einstellungen.html     # Sprache, Währung, Theme
```

---

## Datenbank-Modelle

```python
Produkt: id, name, menge, einheit, mindestmenge, lagerort,
         kategorie, mhd, angebrochen, gebinde, erstellt,
         notiz, bild, barcode, kcal, eiweiss, fett, kohlenhydrate,
         angebrochen_prozent
         (angebrochen/gebinde/angebrochen_prozent: nur per Raw-SQL, nicht im ORM)

EinkaufsListe: id, name, erstellt

Einkaufsliste: id, liste_id, name, menge, einheit,
               einzelpreis, erledigt, in_bestand,
               position, hinzugefuegt

Rezept: id, name, beschreibung, anleitung, portionen,
        kategorie, quell_url, erstellt

RezeptZutat: id, rezept_id, name, menge, einheit

Einstellungen: id, sprache, waehrung, theme, farbe, kalender_entity

Stammdaten: id, typ (lagerort/kategorie/einheit), name
            (UNIQUE: typ + name) – verwaltbare Listen

Essensplan: id, datum, mahlzeit (fruehstueck/mittag/abend),
            rezept_id, freitext, personen, erstellt, cal_synced_at
            (UNIQUE: datum + mahlzeit)
```

---

## Wichtige Besonderheiten

### SQLAlchemy Cache Problem
Neue Spalten (angebrochen, gebinde) werden von SQLAlchemy
nicht automatisch erkannt. Lösung: direkt per sqlite3 lesen:
```python
_conn = sqlite3.connect(DB_PATH)
_rows = _conn.execute("SELECT id, angebrochen, gebinde FROM produkt").fetchall()
_conn.close()
_angebrochen_ids = set(r[0] for r in _rows if r[1])
_gebinde_map = {r[0]: int(r[2] or 0) for r in _rows}
```

### HA Ingress
Die App läuft hinter HA Ingress (Pfad-Prefix).
Lösung: ReverseProxied Middleware + immer url_for() nutzen,
nie hardcodierte Pfade!

### Gebinde-Funktion
Produkte können eine Gebindegröße haben (z.B. 12 für 12er-Kiste).
In der Übersicht: zwei Stepper (Kiste und Einzeln).
Werte werden per direktem SQL gespeichert/geladen (nicht ORM).

---

## Features

### ✅ Implementiert
- Produktverwaltung mit MHD, Mindestmenge, Lagerort, Kategorie
- Farbränder: rot (abgelaufen/unter Minimum), orange (Warnung/angebrochen)
- Angebrochen-Status mit orangem Rahmen
- Produkt-Detailseite (Klick auf Namen): Bild, Nährwerte, Notiz, "verwendet in Rezepten"
  - Route /produkt/<id>, Speichern /produkt/<id>/detail-speichern, Bild /produkt/<id>/bild
  - Bild-Upload nach BILDER_DIR (/share/vorratsverwaltung/bilder), send_from_directory
  - Open Food Facts: /produkt/<id>/off-suche (Namenssuche) + /off-import (per Barcode/code)
    openfoodfacts_suche() nutzt search.openfoodfacts.org (Fallback /cgi/search.pl)
- Angebrochen-Balken auf der Detailseite: Füllstand-Schieberegler (angebrochen_prozent)
  - Route /produkt/<id>/anbruch (aktion=start/stop/set); unter 15 % → menge-1, angebrochen=0
  - farbige Füll-Div (orange, <15 % rot), Slider transparent darüber (WebKit-tauglich)
- Gebinde-Funktion (Kisten, Pakete) mit zwei Steppern
- Nullbestände automatisch ans Ende sortiert
- Mehrere Einkaufslisten mit Drag & Drop
- Einzelpreis × Menge Berechnung
- Alle erledigten in Vorrat buchen (einzeln oder alle auf einmal)
- Rezeptverwaltung mit Vorrat-Abgleich
- PDF-Import mit Spalten-Erkennung (Kaufland-Format)
- Web-Import via Schema.org (Chefkoch, Kaufland, etc.)
- Kaufland-spezifischer Parser
- Quell-URL beim Web-Import gespeichert
- 4 Sprachen: DE, EN, FR, ES
- 4 Währungen: €, CHF, £, $
- Hell/Dunkel-Modus + 6 Farbthemen
- PWA-fähig (als App installierbar)
- Bottom-Navigation (mobil) + Sidebar (Desktop)
- HA Dashboard-Sensoren (abgelaufen, bald, unter Minimum)
- 🛒 Button: Produkte direkt zur Einkaufsliste
- Produkte direkt zur Einkaufsliste hinzufügen (Modal)
- 📅 Essensplaner (Wochenansicht, Frühstück/Mittag/Abend, Rezept/Freitext)
- 📅 HA-Kalender-Anbindung (Zwei-Wege-Sync über Lokaler Kalender)
  - REST calendar.create_event zum Erstellen, GET /calendars zum Lesen
  - WebSocket calendar/event/delete zum Löschen (websocket-client)
  - Marker [essensplan:ID] in der Event-Beschreibung; cal_synced_at + 90s-Schutz

### 🔧 Bekannte Einschränkungen
- Lidl-Kochen: Zutaten werden per JavaScript geladen
  (nicht scrappbar), Anleitung funktioniert
- HA Sensoren aktualisieren sich alle 5 Minuten

---

## Deployment

### Lokal testen
```bash
cd ha-vorrat-addon/app
pip install -r requirements.txt
DB_PATH=/tmp/vorrat.db python app.py
```

### HA Add-on
1. Ordner nach `/addons/ha-vorrat-addon/` kopieren
2. HA: Add-on Store → Lokale Add-ons neu einlesen
3. Installieren & starten

### GitHub Update
1. Version in `config.yaml` erhöhen
2. Dateien auf GitHub ersetzen
3. Release erstellen (z.B. v1.5.0)

---

## Häufige Fehler & Lösungen

| Fehler | Ursache | Lösung |
|--------|---------|--------|
| 404 überall | Ingress-Pfad fehlt | ReverseProxied Middleware prüfen |
| AttributeError neue Spalte | SQLAlchemy Cache | Direkt per sqlite3 lesen |
| Kein Log bei Button-Klick | JS-Fehler | Kein `const` in Funktionen, `var` nutzen |
| Internal Server Error | Jinja-Block fehlt | {% endblock %} prüfen |
| Build-Fehler | config.yaml doppelt | Duplikate entfernen |

---

## Nächste geplante Features
- Übersetzungen: Niederländisch, Polnisch
- Pull Requests von Community willkommen
- HACS Default Repository (wenn genug Stars)
