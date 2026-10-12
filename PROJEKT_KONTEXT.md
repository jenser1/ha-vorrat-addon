# 🥫 Vorratsverwaltung – Projekt-Kontext für Claude Code

## Überblick
Home Assistant Add-on für Haushalts-Vorratsverwaltung mit Rezepten, Einkaufslisten und Web-Import.

**GitHub:** https://github.com/jenser1/ha-vorrat-addon
**Aktuelle Version:** 1.8.0

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
├── CHANGELOG.md         # Änderungen je Version – HA zeigt sie beim Update an (Format: "## X.Y.Z")
├── .gitattributes       # CHANGELOG.md immer mit LF (sonst greift HAs Regex nicht)
├── repository.json      # HA-Repository-Metadaten (name, url, maintainer)
├── icon.png / logo.png  # Add-on-Icon (Store/Seitenleiste) + Logo (Infoseite/README)
└── app/
    ├── app.py           # Flask-App (alle Routen & Logik)
    ├── translations.py  # DE/EN/FR/ES Übersetzungen
    ├── requirements.txt
    └── templates/
        ├── base.html              # Layout, Bottom-Nav, Themes
        ├── index.html             # Produktübersicht mit Stepper
        ├── produkt_form.html      # Neues Produkt anlegen
        ├── produkt_detail.html    # Produktseite: Überblick + EIN Bearbeiten-Formular
        ├── _produkt_felder.html   # Include: Grundfelder (Neu + Produktseite)
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
         angebrochen_prozent, eingefroren, einfrierdatum, herkunft,
         behaelter, markierung, eingekocht, einkochdatum
         (alle Konservierungs-/Zusatzspalten: nur per Raw-SQL, nicht im ORM)
         inhalt (Float, Inhalt je Einheit, z.B. 500), inhalt_einheit (g|kg|ml|l|Stück)
         (normale ORM-Spalten + ALTER-TABLE-Migration; bei g/kg/ml/l immer leer)

ZutatZuordnung: id, begriff (normalisierter Zutatenname, UNIQUE), produkt_name
                ("" = Zutat nicht aus dem Vorrat prüfen) – gemerkte 🔗-Zuordnung, gilt für alle Rezepte

EinkaufsListe: id, name, erstellt

Einkaufsliste: id, liste_id, name, menge, einheit,
               einzelpreis, erledigt, in_bestand,
               position, hinzugefuegt

Rezept: id, name, beschreibung, anleitung, portionen,
        kategorie, quell_url, erstellt,
        vorbereitungszeit, kochzeit, gesamtzeit (Minuten, optional; normale ORM-Spalten + ALTER-TABLE-Migration wie quell_url)

RezeptZutat: id, rezept_id, name, menge, einheit

Einstellungen: id, sprache, waehrung, theme, farbe, kalender_entity,
               timer_notify (notify-Dienst, "" = keiner), timer_text (Vorlage, "" = Standard)

Stammdaten: id, typ (lagerort/kategorie/einheit), name, ist_frost
            (UNIQUE: typ + name) – verwaltbare Listen
            (ist_frost: Lagerort = Gefrierfach ❄️, nur per Raw-SQL)

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
Auf dem Handy läuft sie in der **Home-Assistant-App** (Companion) als Seitenleisten-Eintrag
(„In der Seitenleiste anzeigen“). Panel-Pfad = `/<slug>` (lokal `/local_vorratsverwaltung`,
aus dem Store `/<8-Zeichen-Hash>_vorratsverwaltung` – je Installation anders, in Doku nie fest
eintragen). „Zum Startbildschirm“ im Browser greift nicht (Seite läuft im Ingress-iframe, der
Browser nimmt das HA-Manifest) → README empfiehlt HA-App + Android-Verknüpfung bzw.
iOS-Kurzbefehl `homeassistant://navigate/<pfad>`.

### Benennung in Home Assistant (seit 2026.2)
Add-ons heißen in der HA-Oberfläche „Apps“: **Einstellungen → Apps → App-Store → ⋮ → Repositories**.
Technisch unverändert (config.yaml, repository.json, /addons-API) – nur Menünamen in Doku anpassen.

### CSRF-Schutz
Token pro Session (`csrf_token()`). `before_request` prüft POST/PUT/PATCH/DELETE;
`after_request` injiziert automatisch ein `<input name="_csrf">` in jedes POST-Formular –
kein Template muss es selbst setzen. AJAX/JSON sendet es per `X-CSRF-Token`-Header
(Meta-Tag in base.html). `SECRET_KEY`: ENV oder persistenter Zufallsschlüssel
(`.secret_key` neben der DB), kein hartkodierter Default.
Session-Cookie: `SameSite=Lax` + `HttpOnly`.

### SSRF-Schutz & Härtung (seit 1.7.1)
Jeder Abruf einer fremden URL (Web-Import, Open-Food-Facts-Bild) läuft über
`_get_sicher()` → `url_sicher()`: nur http/https zu **öffentlichen** IPs; Loopback, private
Netze, Link-Local, IPv4-in-IPv6 (`::ffff:127.0.0.1`) und HA-interne Hostnamen
(`supervisor`, `*.local`, …) sind gesperrt – **jeder Redirect wird einzeln geprüft**
(`allow_redirects=False`). `seite_laden()` streamt mit 5-MB-Limit (`MAX_SEITE_BYTES`).
Neue Abrufe fremder URLs IMMER über `_get_sicher()`/`seite_laden()`, nie direkt `requests.get`.
Weitere Regeln: notify-Dienstname gegen `NOTIFY_DIENST_RE` (`^[a-z0-9_]+$`, landet im API-Pfad),
Nachrichtenvorlagen per `str.replace` statt `str.format` (Format-String-Injection),
Eingabelängen begrenzt (Text-Import 200 KB, URL 2000 Zeichen).

### Gebinde-Funktion
Produkte können eine Gebindegröße haben (z.B. 12 für 12er-Kiste).
In der Übersicht: zwei Stepper (Kiste und Einzeln).
Werte werden per direktem SQL gespeichert/geladen (nicht ORM).

### Packungsinhalt & Vorrat-Abgleich
- `menge` zählt weiter Packungen/Dosen; `inhalt` sagt, wie viel in **einer** Einheit steckt.
  Eine angebrochene Packung zählt mit ihrem Rest: `menge - 1 + angebrochen_prozent/100`
  (`produkt_bestaende()` liefert je Vergleichs-Einheit, z.B. `{'packung': 2.6, 'g': 1300}`).
- Einheiten: `einheit_basis()` → Masse g, Volumen ml, Anzahl Stück; Behälter (Packung, Dose …)
  nur über `inhalt` umrechenbar. EL/TL/Prise = „kleine Menge“ → vorhanden, sobald etwas da ist.
- `rezept_abgleich(rezept, faktor)` ist die **eine** Quelle für Rezeptseite, „Fehlende Zutaten
  hinzufügen“ (`rezept_zur_liste`, auch Essensplan) und „verwendet in Rezepten“. Gleicher
  Produktname an mehreren Lagerorten = eine Gruppe; Bedarf mehrerer Zutaten fürs selbe
  Produkt wird summiert; Fehlmenge geht in Produkt-Einheit auf die Liste (Packungen aufgerundet).
- Namensvergleich (`produkt_fuer_zutat`): gemerkte Zuordnung > sicherer Treffer (gleiches Wort,
  Synonym `_ZUTAT_SYNONYME`, Grundwort mit neutraler Vorsilbe `_NEUTRALE_VORSILBEN`:
  Weizen|mehl, Schlag|sahne) > **unsicher** (Kokos|milch ↔ Milch, Tomaten → Tomaten|mark).
  Unsicher wird ❓ angezeigt und zur Sicherheit eingekauft, bis per 🔗 bestätigt.
  Wasser/Leitungswasser (`_IMMER_DA`) wird nie als fehlend gemeldet.

---

## Features

### ✅ Implementiert
- Produktverwaltung mit MHD, Mindestmenge, Lagerort, Kategorie
- Farbränder: rot (abgelaufen/unter Minimum), orange (Warnung/angebrochen)
- Angebrochen-Status mit orangem Rahmen
- Produktseite (Klick auf Namen) = EINZIGER Platz zum Bearbeiten (Wunsch des Users):
  oben Überblick + Schnell-Aktionen (+/−, Anbruch-Regler), darunter EIN Formular „✏️ Bearbeiten“
  (alle Grundfelder + Konservierung + Bild + Nährwerte + Notiz, multipart) → POST /produkt/<id>/bearbeiten
  - Grundfelder als Include `_produkt_felder.html` – gemeinsam mit „Neues Produkt“ (produkt_form.html)
  - GET /produkt/<id>/bearbeiten leitet nur noch auf /produkt/<id>#bearbeiten (alte Lesezeichen)
  - Kein ✏️-Knopf mehr in der Übersicht; alte Routen /detail-speichern und /tiefkuehl entfernt
  - „Speichern & zur Übersicht“ → `uebersicht_url(id)`: zuletzt benutzter Filter (session["filter"],
    gesetzt in index()) + Sprung zur Zeile `#p<id>` (scroll-margin + kurze Markierung per :target)
  - Bild/Nährwerte/Notiz nur übernehmen, wenn das Feld im Formular steht (alter Tab löscht nichts)
  - JS-Schutz: ungespeicherte Formular-Änderungen → Rückfrage vor +/−, Anbruch, OFF, Wegnavigieren
  - Route /produkt/<id>, Bild /produkt/<id>/bild
  - Bild-Upload nach BILDER_DIR (/share/vorratsverwaltung/bilder), send_from_directory
  - Open Food Facts: /produkt/<id>/off-suche (Namenssuche) + /off-import (per Barcode/code)
    openfoodfacts_suche() nutzt search.openfoodfacts.org (Fallback /cgi/search.pl)
- Angebrochen-Balken auf der Detailseite: Füllstand-Schieberegler (angebrochen_prozent)
  - Route /produkt/<id>/anbruch (aktion=start/stop/set); unter 15 % → menge-1, angebrochen=0
  - farbige Füll-Div (orange, <15 % rot), Slider transparent darüber (WebKit-tauglich)
- Konservierung (❄️ Einfrieren / 🥫 Einkochen): Reste/Garten-Ernte haltbar machen
  - Im Produktformular (Neu + Produktseite): Auswahl "Konservierung" (Keine/eingefroren/eingekocht)
    blendet Herkunft/Behälter/Kennzeichnung/Art/Datum/Verbrauchen-bis ein
    (konserv_effektives_mhd, konservierung_felder_speichern); Buttons → /produkt/neu?konserv=…
    „Verbrauchen bis“ geleert → kein Datum (mhd = None)
  - mhd = "Verbrauchen bis" = Datum + Richtwert (monate_addieren; EINFRIER_RICHTWERT bzw. EINKOCH_RICHTWERT)
  - Spalten eingefroren/einfrierdatum/eingekocht/einkochdatum/herkunft/behaelter/markierung
  - Kennzeichnung als Pille + ❄️/🥫-Badge in der Übersicht; Herkunft-Filter
  - eingefroren = Flag ODER Lagerort ist Gefrierfach (abgeleitet), aber nicht wenn eingekocht
  - Produktseite zeigt Tiefkühl/Eingekocht, Datum, Kennzeichnung, Behälter im Kopf; bearbeitet wird im Formular
  - Lagerorte als Gefrierfach markierbar (Stammdaten.ist_frost, Route /stammdaten/frost)
  - Sensoren sensor.vorrat_tiefkuehl + sensor.vorrat_eingekocht
- Gebinde-Funktion (Kisten, Pakete) mit zwei Steppern
- Nullbestände automatisch ans Ende sortiert
- Mehrere Einkaufslisten mit Drag & Drop
- Einzelpreis × Menge Berechnung
- Alle erledigten in Vorrat buchen (einzeln oder alle auf einmal)
- Rezeptverwaltung mit Vorrat-Abgleich
- Zeitangaben (vorbereitungszeit/kochzeit/gesamtzeit, Minuten): Web-Import übernimmt
  schema.org prepTime/cookTime/totalTime (zeit_zu_minuten, ISO-8601 -> Min), Text-Import
  erkennt "Zubereitungszeit: 30 min" (zeit_label_erkennen). Anzeige via Jinja-Filter |dauer
  (minuten_formatiert) auf Rezeptseite + Kochmodus-Zeitleiste. Formular-Parsing: form_minuten()
- Kochmodus: Vollbild-Overlay auf der Rezeptseite (rezept_detail.html), Schritt für Schritt
  (Anleitung wird clientseitig in Schritte geparst), Fortschritt, einblendbare Zutaten,
  Wake Lock (Bildschirm an), Tastatur ← → / Esc – reines JS/CSS, kein Server-Code
- Küchen-Timer: EINE Implementierung global in base.html (FAB unten rechts + Modal + JS);
  Kochmodus nutzt denselben Dialog via timerModalOeffnen(KOCH_PRESETS) + Chip im Header,
  FAB wird bei offenem Kochmodus ausgeblendet (timerFabSync). Backend: /kochtimer/start|stop|
  status|test, threading.Timer, _kochtimer-State mit Lock. Ablauf -> _kochtimer_melden():
  HA-Event vorrat_kochtimer_fertig + sensor.vorrat_kochtimer + optionale Notify
  (Einstellungen.timer_notify/timer_text). kochtimer_sensor_aktualisieren() läuft auch in der
  5-Min-Schleife -> Sensor überlebt HA-Neustarts (REST-States sind sonst flüchtig).
  HA-Helfer _ha_post() mit raise_for_status + Logging. Portabel: notify-Liste live per
  ha_notify_dienste() (/api/services), nichts hartkodiert.
- PDF-Import mit Spalten-Erkennung (Kaufland-Format)
- Web-Import via Schema.org (Chefkoch, Kaufland, etc.)
  - HEADERS ohne "br" (Brotli): requests dekodiert nur gzip/deflate ohne Zusatzpaket,
    sonst kommt Binärmüll zurück und der Import scheitert ("Kein Rezept gefunden")
- Text-Import (rezept_aus_text): freier Text/Caption -> Titel/Zutaten/Schritte
  (Überschriften Zutaten:/Zubereitung:, Bullets, Nummerierung, Komma-Listen, Portionen,
  Hashtags werden ignoriert). Route rezept_web_import nimmt "url" ODER "text",
  gleiche editierbare Vorschau (rezept_web_import.html), speichert an rezept_neu
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
2. HA: Einstellungen → Apps → App-Store (früher „Add-on Store") → ⋮ → lokale Apps neu einlesen
3. Installieren & starten

### CHANGELOG.md (zeigt HA beim Update an)
- Liegt im Repo-Root **neben `config.yaml`** (= App-Ordner). HA-Core (`hassio/update.py`,
  `async_release_notes`) schneidet per Regex `^#* <neue Version>\n … bis ^#* <installierte Version>`
  den passenden Teil aus → Überschriften **exakt `## X.Y.Z`** (kein Datum, kein „v", kein Zusatz),
  neueste oben, **LF-Zeilenenden** (`.gitattributes`: `CHANGELOG.md text eol=lf`).
  Passt die Überschrift nicht, zeigt HA den kompletten Changelog.
- Laufende Arbeit sammelt sich unter `## Nächste Version`; die Nummer wählt der User beim Release.
- README enthält nur noch einen Verweis auf die CHANGELOG.md (nicht doppelt pflegen).
- Prüfskript-Idee: Regex aus HA nachbauen und 1.7.1 → X.Y.Z simulieren (zeigt nur die neuen Einträge?).

### GitHub Update (Release – nur nach Release-OK des Users)
1. `CHANGELOG.md`: `## Nächste Version` → `## X.Y.Z` (vom User gewählte Nummer)
2. Version in `config.yaml` auf dieselbe Nummer setzen
3. Commit, Tag `vX.Y.Z`, push
4. Release auf GitHub aus dem Tag erstellen

Persönliche Einstellungen des Maintainers (Git-Identität, Entwicklungs-PC, eigene HA-Installation)
stehen in `CLAUDE.local.md` – per `.gitignore` vom Upload ausgeschlossen.

---

## Häufige Fehler & Lösungen

| Fehler | Ursache | Lösung |
|--------|---------|--------|
| 404 überall | Ingress-Pfad fehlt | ReverseProxied Middleware prüfen |
| AttributeError neue Spalte | SQLAlchemy Cache | Direkt per sqlite3 lesen |
| Kein Log bei Button-Klick | JS-Fehler | Kein `const` in Funktionen, `var` nutzen |
| Internal Server Error | Jinja-Block fehlt | {% endblock %} prüfen |
| Build-Fehler | config.yaml doppelt | Duplikate entfernen |
| Web-Import „Kein Rezept gefunden" | Brotli-Antwort (br) nicht dekodierbar | Kein `br` in Accept-Encoding (nur gzip/deflate) |
| Event `vorrat_kochtimer_fertig` „nicht da" | HA listet Custom-Events nirgends | Entwicklerwerkzeuge → Ereignisse lauschen, oder Sensor-Trigger `sensor.vorrat_kochtimer` → `fertig` |
| REST-Sensor nach HA-Neustart weg | `POST /api/states` ist nicht persistent | Sensor regelmäßig neu setzen (5-Min-Schleife) |
| Web-Import „URL abgelehnt (interne Adresse gesperrt)" | SSRF-Schutz (`url_sicher`) – gewollt | Nur öffentliche Rezeptseiten importierbar; LAN/HA-intern ist gesperrt |
| Rezept: Zutat „❓ vielleicht …?" | Nur ähnlicher Name (zusammengesetztes Wort) – gewollt vorsichtig | Per 🔗 bestätigen/zuordnen; ggf. Vorsilbe in `_NEUTRALE_VORSILBEN` ergänzen |
| Rezept: „Tipp: Inhalt pro Dose eintragen" | Rezept in g/ml, Produkt als Dose/Packung ohne Inhalt | Beim Produkt „Inhalt pro …" setzen, dann rechnet der Abgleich |

---

## Nächste geplante Features
- „Gekocht → Zutaten abziehen“: Dialog im Rezept + am Ende des Kochmodus (Portionen,
  Haken je Zutat, offene Packung zuerst, dann frühestes MHD, Rückgängig) – baut auf
  `rezept_abgleich()`/`produkt_bestaende()` auf
- Übersicht aufräumen: Filter als 3 Auswahllisten, Kacheln anklickbar, „A“-Knopf als Symbol
- Doppelte Lagerorte (z.B. „Küche“ + „Küche “ mit Leerzeichen) zusammenführen + beim Speichern strippen
- Übersetzungen: Niederländisch, Polnisch
- Pull Requests von Community willkommen
- HACS Default Repository (wenn genug Stars)
