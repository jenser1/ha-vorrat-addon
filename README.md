[README.md](https://github.com/user-attachments/files/26455894/README.md)
# 🥫 Vorratsverwaltung – Home Assistant Add-on

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

### 📊 Dashboard-Sensoren
Automatisch verfügbare HA-Sensoren:
| Sensor | Beschreibung |
|--------|-------------|
| `sensor.vorrat_abgelaufen` | Anzahl abgelaufener Produkte |
| `sensor.vorrat_bald_ablaufend` | Ablaufend in ≤7 Tagen |
| `sensor.vorrat_kritisch` | Ablaufend in ≤3 Tagen |
| `sensor.vorrat_unter_mindestmenge` | Unter Mindestmenge |
| `sensor.vorrat_gesamt` | Gesamtanzahl Produkte |

### 🌍 Mehrsprachig & Mehrere Währungen
- Sprachen: Deutsch, Englisch, Französisch, Spanisch
- Währungen: € Euro, CHF Franken, £ Pfund, $ Dollar

### 📱 Mobil-optimiert
- Bottom-Navigation für einfache Bedienung auf dem Handy
- Als PWA installierbar (Vollbild ohne Browser)
- Große Touch-Flächen, kein versehentlicher Zoom

---

## 🔧 Installation

### Über HACS (empfohlen)
1. HACS → ⋮ → **Custom repositories**
2. URL: `https://github.com/jenser1/ha-vorrat-addon`
3. Typ: **Add-on**
4. **Vorratsverwaltung** installieren & starten

### Manuell
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
```

---

## 📱 Als App installieren

Im Browser auf **„Zum Startbildschirm hinzufügen"** tippen – öffnet dann wie eine native App im Vollbild.

---

## 📝 Changelog

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
