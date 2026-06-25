# 🥫 Vorratsverwaltung – Home Assistant Add-on

[![PayPal](https://img.shields.io/badge/Sponsor-PayPal-blue?logo=paypal)](https://paypal.me/jenser1)
[![GitHub stars](https://img.shields.io/github/stars/jenser1/ha-vorrat-addon?style=social)](https://github.com/jenser1/ha-vorrat-addon)
[![GitHub release](https://img.shields.io/github/v/release/jenser1/ha-vorrat-addon)](https://github.com/jenser1/ha-vorrat-addon/releases)

Vollständige Haushalts-Vorratsverwaltung direkt in Home Assistant – mit Rezepten, Einkaufslisten, Web-Import und Dashboard-Sensoren.

---

## ✨ Features

### 📦 Vorratsverwaltung
- Produkte mit Menge, Einheit, Lagerort und Kategorie verwalten
- **MHD-Warnungen** – farbcodiert (grün/gelb/rot/grau)
- **Mindestmengen** – automatische Warnung bei Unterschreitung
- Menge direkt per +/- Stepper anpassen

### 🛒 Einkaufslisten
- **Mehrere Listen** – z.B. Edeka, Aldi, Drogerie
- **Einzelpreis × Menge** = automatischer Gesamtpreis
- **Drag & Drop** Sortierung
- Erledigte Artikel automatisch in den Vorrat buchen
- Auto-Befüllung aus Produkten unter Mindestmenge

### 📖 Rezepte
- Vorrat-Abgleich: welche Zutaten sind vorhanden?
- **PDF-Import** mit automatischer Spalten-Erkennung
- **Web-Import** von Chefkoch, Kaufland, Lidl und hunderten weiteren Seiten
- Filter und Sortierung nach Kategorie

### 📅 Essensplaner
- Wochenansicht mit **Frühstück / Mittag / Abend**
- Pro Mahlzeit: vorhandenes Rezept **oder** eigener Freitext
- **Personenzahl** pro Mahlzeit + fehlende Zutaten direkt zur Einkaufsliste
- **„Zum Essensplan"** direkt von jeder Rezeptseite
- **Anbindung an den Home-Assistant-Kalender** (Zwei-Wege-Sync)
- Im HA-Kalender gelöschte Mahlzeiten verschwinden auch aus dem Planer

### 📊 Dashboard-Sensoren
Automatisch verfügbare HA-Sensoren:
| Sensor | Beschreibung |
|--------|-------------|
| `sensor.vorrat_abgelaufen` | Anzahl abgelaufener Produkte |
| `sensor.vorrat_bald_ablaufend` | Ablaufend in ≤7 Tagen |
| `sensor.vorrat_kritisch` | Ablaufend in ≤3 Tagen |
| `sensor.vorrat_unter_mindestmenge` | Unter Mindestmenge |
| `sensor.vorrat_gesamt` | Gesamtanzahl Produkte |
| `sensor.vorrat_einkaufsliste` | Offene Artikel in Einkaufslisten |

### 🌍 Mehrsprachig & Mehrere Währungen
- Sprachen: Deutsch, Englisch, Französisch, Spanisch
- Währungen: € Euro, CHF Franken, £ Pfund, $ Dollar

### 📱 Mobil-optimiert
- Bottom-Navigation für einfache Bedienung auf dem Handy
- Als PWA installierbar (Vollbild ohne Browser)
- Große Touch-Flächen, kein versehentlicher Zoom

---

## 🔧 Installation

### Über Add-on Store (empfohlen)
1. **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories**
2. URL hinzufügen: `https://github.com/jenser1/ha-vorrat-addon`
3. **Vorratsverwaltung** installieren & starten
4. Über die HA-Sidebar öffnen



---

## 📊 Dashboard einbinden

```yaml
type: entities
title: 🥫 Vorratsverwaltung
entities:
  - sensor.vorrat_abgelaufen
  - sensor.vorrat_bald_ablaufend
  - sensor.vorrat_kritisch
  - sensor.vorrat_unter_mindestmenge
  - sensor.vorrat_gesamt
  - sensor.vorrat_einkaufsliste
```

---

## 📱 Als App installieren

Im Browser auf **„Zum Startbildschirm hinzufügen"** tippen – öffnet dann wie eine native App im Vollbild.

---

## 🤝 Mitmachen & Feedback

Hast du einen Fehler gefunden oder eine Idee für ein neues Feature?

👉 **[Issue erstellen](https://github.com/jenser1/ha-vorrat-addon/issues/new)** – ich freue mich über jedes Feedback!

**Bitte beschreibe bei Bugs:**
- Was hast du gemacht?
- Was ist passiert?
- Was hast du erwartet?
- Home Assistant Version & Hardware (z.B. Raspberry Pi 4)

**Ideen & Feature-Wünsche** sind ebenfalls willkommen – einfach als Issue mit dem Label `enhancement` eintragen.

---

## 📝 Changelog

### 1.5.8
- 🩹 Stabilität: Server verarbeitet mehrere Anfragen gleichzeitig (`threaded`)
  – ein langsamer Kalender-Aufruf legt nicht mehr das ganze Add-on lahm (503-Fix)
- 🩹 SIGTERM wird sauber abgefangen → sauberer Stop/Neustart (kein Exit-Code 143)
- ⚡ Essensplaner lädt deutlich schneller: Kalender-Abgleich nur noch, wenn nötig
- ⏱️ Kürzere Timeouts für HA-Kalender-Aufrufe (schnelles Scheitern bei Netzproblemen)

### 1.5.7
- 👥 **Personenzahl** pro geplanter Mahlzeit (automatisch aus den Rezept-Portionen)
- 🛒 Im Essensplaner direkt **fehlende Zutaten zur Einkaufsliste** hinzufügen
  – Menge auf die Personenzahl umgerechnet, Auswahl welche Liste
- 📅 **„Zum Essensplan"-Button** auf jeder Rezeptseite (Datum/Mahlzeit/Personen)

### 1.5.6
- 📅 **Essensplaner** – Wochenansicht mit Frühstück / Mittag / Abend
- 🔗 Pro Mahlzeit: vorhandenes Rezept **oder** eigener Freitext
- 🗓️ **HA-Kalender-Anbindung** (Zwei-Wege): geplante Mahlzeiten landen automatisch
  im gewählten Home-Assistant-Kalender
- ↩️ Im HA-Kalender gelöschte Mahlzeiten verschwinden auch aus dem Planer
- 🛡️ Schutz vor Fehllöschungen (nur >90 s synchronisierte Einträge werden abgeglichen)
- ⚙️ Einstellungen: Ziel-Kalender auswählen (automatische Erkennung)
- 📊 Dashboard-Beispiel: `sensor.vorrat_einkaufsliste` ergänzt

### 1.5.5
- ✅ **Lidl-Import funktioniert jetzt vollständig** – Zutaten UND Anleitung werden geladen
  (Schema.org-JSON mit Steuerzeichen wird jetzt korrekt geparst, `strict=False`)
- ✅ **Kaufland-Zubereitung wird jetzt geladen** – Schritt-Text aus Microdata (`content`-Attribut)
  und `cooking-description` ausgelesen
- 🌐 Kaufland-Zutaten: korrekte Mengen/Einheiten aus der Zutaten-Tabelle
- 🧺 Zutaten-Parser erkennt nachgestellte Mengen (`Frühlingszwiebeln 3 St.`, `Salz Prise`)
- 🔤 Einheiten-Normalisierung: `St`/`Stk` → `Stück`, `Pkg` → `Packung`
- 🌐 Schema.org Parser unterstützt `HowToSection`, verschachtelte Anleitungen und `@graph`-Format
- 🐛 Fix: `fallback_extrahieren()` wird jetzt korrekt aufgerufen wenn Schema.org leer zurückgibt

### 1.5.4
- 🔍 Lagerort-Filter in der Übersicht (kombinierbar mit Kategorie-Filter)
- 🔒 Filter bleibt erhalten bei: +/- Menge, Bearbeiten, Löschen, Angebrochen, Umlagern
- 📍 Umlagerung: Mengenfeld ergänzt (Teilumlagerung möglich)
- 🐛 Fix: Chip-onclick im Umlagern-Modal (Apostroph-Sicherheit)
- 🐛 Fix: Mobile Aktionen-Buttons umbrechen statt zu überlaufen

### 1.5.3
- 📱 Mobile Optimierung: Karten-Layout für Handy/Tablet (HA Companion App)
- 📍 Umlagerung: Produkte zwischen Lagerorten verschieben (z.B. Keller → Küche)
- 📍 Teilumlagerung: nur einen Teil der Menge umlagern
- 🐛 Fix: Zur-Einkaufsliste-Button funktioniert wieder korrekt

### 1.5.2
- 🐛 Doppelte Funktionsdefinitionen entfernt (get_settings, t, fmt_currency)
- 🐛 Rezept-Einkauf: fehlende Menge wurde falsch berechnet
- 🐛 Web-Import: Internal Server Error behoben (fehlende Parser-Logik)
- 🔒 XSS-Fix: Produktnamen in JavaScript korrekt escaped
- 🔒 Sicherheitsupdate: requests 2.32.3 → 2.33.0 (CVE: .netrc credentials leak)

### 1.5.1
- 🔒 Sicherheitsupdate: requests 2.32.3, flask 3.1.1
- 📋 SECURITY.md hinzugefügt

### 1.5.0
- 📦 Gebinde-Funktion (Kisten, Pakete, etc.)
- Zwei Stepper pro Produkt: Kiste und Einzelstück
- Gebinde-Auswahl beim Zur-Einkaufsliste-Hinzufügen
- 🔧 Code-Review und Bereinigung

### 1.4.0
- 🎨 Hell/Dunkel-Modus & 6 Farbthemen in den Einstellungen
- 📦 Angebrochen-Status mit orangem Rahmen
- 🟠 Farbränder für MHD-Warnung, abgelaufen und Mindestmenge
- 🛒 Produkte direkt aus Übersicht zur Einkaufsliste hinzufügen
- ↓ Nullbestände automatisch ans Ende sortiert
- 🌐 Quell-URL beim Web-Import gespeichert

### 1.3.0
- 🛒 Produkte direkt aus der Übersicht zur Einkaufsliste hinzufügen
- ↓ Nullbestände automatisch ans Ende sortiert
- ✅ Kompatibilität mit HACS Add-on Store
- 🌐 Quell-URL wird beim Web-Import gespeichert (Link zum Originalrezept)

### 1.2.2
- Quell-URL wird beim Web-Import gespeichert
- 🌐 Originalrezept öffnen Link im Rezept-Detail

### 1.2.1
- Drag & Drop Sortierung in Einkaufslisten repariert

### 1.2.0
- Dashboard-Sensoren für HA (abgelaufen, bald ablaufend, unter Mindestmenge)
- Einzelpreis × Menge Berechnung in Einkaufslisten
- Alle erledigten Artikel auf einmal in Vorrat buchen

### 1.1.0
- Mehrsprachigkeit (DE/EN/FR/ES)
- Mehrere Währungen (€/CHF/£/$)
- Einstellungen-Seite
- Mobil-optimiertes Design mit Bottom-Navigation
- PWA-Unterstützung

### 1.0.0
- Initiale Version
- Vorratsverwaltung mit MHD-Warnungen
- Mehrere Einkaufslisten mit Preisen
- Rezepte mit PDF- und Web-Import
