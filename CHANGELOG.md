# Changelog

## 1.8.0

### ⚖️ Packungsinhalt
- Neues Feld **„Inhalt pro Packung/Dose/Stück"** (z. B. 500 g, 1 l) – freiwillig
- Übersicht zeigt z. B. **„3 Packung · à 500 g · 1,5 kg"**, bei angebrochenen Packungen zusätzlich **„1 offen: noch 700 g"**
- Der „Angebrochen"-Regler zeigt den Rest auch in Gramm bzw. ml
- Open Food Facts trägt den Packungsinhalt automatisch ein und zeigt die Packungsgröße schon in den Suchtreffern

### 🍳 Rezept-Abgleich mit echten Mengen
- Rechnet g ↔ kg, ml ↔ l und Packungen (über den Packungsinhalt) um und zählt alle Lagerorte eines Produkts zusammen
- Erkennt Schreibweisen: Zwiebel/Zwiebeln, Hackfleisch/Gehacktes, „Mehl (Type 405)", Weizenmehl → Mehl
- Status je Zutat: ✅ genug da · ⚠️ zu wenig · 🛒 fehlt · ❓ unsicher (nur ähnlicher Name, z. B. Kokosmilch ↔ Milch) · ➖ nicht geprüft (z. B. Leitungswasser)
- **🔗 Zuordnung merken**: eine Zutat einmal einem Vorratsprodukt zuordnen – gilt dann für alle Rezepte (oder „nicht prüfen")
- Braucht ein Rezept dasselbe Produkt mehrmals (z. B. Butter für Teig und Füllung), wird der Bedarf zusammengezählt
- „Fehlende Zutaten hinzufügen" – auch im Essensplaner – schreibt die echte Fehlmenge auf die Einkaufsliste, bei Packungsware als ganze Packungen
- „Verwendet in Rezepten" auf der Produktseite nutzt denselben Abgleich

### ✏️ Bearbeiten an einem Platz
- Klick auf den Produktnamen öffnet die Produktseite – dort stehen **alle Angaben in einem Formular** (Name, Menge, Inhalt, Lagerort, Kategorie, MHD, Gebinde, Einfrieren/Einkochen, Bild, Nährwerte, Notiz) mit einem Speichern-Knopf
- **„Speichern & zur Übersicht"** springt zurück zur Zeile des Produkts – mit dem vorher gewählten Filter
- Rückfrage, bevor ungespeicherte Änderungen verloren gehen
- Der ✏️-Knopf in der Übersicht und die getrennten Formulare (Bild/Nährwerte/Notiz, Tiefkühl-Karte) entfallen

### 📱 Handy & Kleinigkeiten
- Rezeptseite auf Handy/Tablet untereinander – die Zutatenliste wird nicht mehr abgeschnitten
- Kopfleiste der Produktseite am Handy kompakt (nur Symbole)
- Mengen mit mehreren Nachkommastellen (z. B. 2,75) lassen sich speichern; eine frei eingetragene Herkunft bleibt beim Speichern erhalten
- README: Nutzung über die **Home-Assistant-App** genau beschrieben, Menüpfade für Home Assistant 2026.2 („Apps" statt „Add-ons") aktualisiert
- Neu: diese **CHANGELOG.md** – Home Assistant zeigt sie beim Update an
- Security-Policy auf 1.8.x aktualisiert

💾 Die Datenbank wird beim Start automatisch ergänzt (Packungsinhalt und Zutaten-Zuordnungen) – vorhandene Daten bleiben unverändert.

## 1.7.1
- 🔒 **Sicherheit**: Web-Import und Bild-Download prüfen jetzt jede Adresse – auch Weiterleitungen – und verweigern interne Ziele. Home-Assistant-Supervisor, andere Add-ons und Geräte im Heimnetz sind über den Import nicht mehr erreichbar (SSRF-Schutz); Seitenabruf auf 5 MB begrenzt
- 🔒 notify-Dienstname wird streng geprüft, Nachrichtenvorlage ohne Format-String-Auswertung, Session-Cookie mit `SameSite=Lax` + `HttpOnly`, Eingabelängen begrenzt
- 🎨 **Neues Logo**: Add-on-Icon im Store und in der HA-Seitenleiste, Logo auf der Infoseite und in der README, Favicon, Homescreen-Icons für iPhone und Android; PWA-Manifest funktioniert jetzt auch hinter Ingress (relative Pfade)
- 👤 Maintainer-Angaben in `repository.json` und im Container-Image; Security-Policy auf 1.7.x aktualisiert

## 1.7.0
- ⏲️ **Küchen-Timer**: überall startbar (⏲️-Knopf unten rechts) mit Presets oder freien Minuten; im Kochmodus zusätzlich Schnellwahl aus den Rezeptzeiten. Läuft im Add-on – Seitenwechsel oder Tab schließen egal. Piepton/Vibration im Browser, +1 Min, Stopp
- 🏠 **Home-Assistant-Anbindung**: beim Ablauf Event `vorrat_kochtimer_fertig` + neuer Sensor `sensor.vorrat_kochtimer` (idle/läuft/fertig, überlebt HA-Neustarts). Optional direkte Handy-Push – notify-Dienst wird aus der jeweiligen HA-Installation gelistet, Nachrichtentext mit Platzhaltern
- 🔔 **Test-Button** in den Einstellungen (Event + Sensor + Push sofort auslösen) und README-Beispiele für „Handy klingeln lassen" und Sprachansage
- 🩹 HA-Aufrufe prüfen jetzt den HTTP-Status und loggen Fehler; Timer-Start/-Ablauf im Add-on-Log sichtbar

## 1.6.6
- ⏱️ **Zeitangaben** pro Rezept: Vorbereitung, Kochen/Backen und Gesamt (in Minuten). Beim Web-Import automatisch aus der Seite übernommen (schema.org `prepTime`/`cookTime`/`totalTime`, auch ISO-Format), beim Text-Import aus Zeilen wie „Zubereitungszeit: 30 min" erkannt, manuell eintragbar – angezeigt auf der Rezeptseite und im Kochmodus

## 1.6.5
- 📋 **Text-Import**: Rezept aus freiem Text einfügen (Instagram-/Facebook-Caption, WhatsApp, Koch-App) – wird automatisch in Titel, Zutaten und Schritte zerlegt; editierbare Vorschau. Direkt neben dem Web-Import auf der Import-Seite
- 📝 README: Sektion „Speicherbedarf & Datenverbrauch" ergänzt; doppelte Sensor-Liste entfernt

## 1.6.4
- 👨‍🍳 **Kochmodus**: Rezept im Vollbild Schritt für Schritt kochen – große Schrift, Fortschrittsbalken, „◀ Zurück / Weiter ▶", einblendbare Zutaten, Tastatur (← → / Esc); der Bildschirm bleibt an (Wake Lock, bei HTTPS/Nabu Casa)
- 🐛 **Web-Import repariert**: Seiten wie Chefkoch lieferten teils Brotli-komprimierte Antworten, die nicht dekodiert werden konnten → „Kein Rezept gefunden". Brotli wird nicht mehr angefragt; Import funktioniert wieder

## 1.6.3
- 🥫 **Einkochen**: Gegenstück zum Einfrieren – im Produktformular eine Auswahl „Konservierung" (Keine / ❄️ Eingefroren / 🥫 Eingekocht) mit passender Haltbarkeit (Marmelade 2 Jahre, Kompott/Gemüse 1 Jahr …)
- 🏷️ **Behälter & Kennzeichnung**: „Aufbewahrt in" (Gefrierbeutel, Weckglas …) und eine kurze Kennzeichnung (z. B. `A3`) zum Wiedererkennen – als Pille in Übersicht und auf der Produktseite
- 📊 Neuer Sensor `sensor.vorrat_eingekocht`

## 1.6.2
- 🔒 **Sicherheit**: CSRF-Schutz für alle Formulare; zufälliger, persistenter SECRET_KEY (kein fester Default); Open-Food-Facts-Bilddownload auf 5 MB begrenzt (gestreamt)
- 🧊 **Tiefkühl automatisch**: Produkte in einem als ❄️-Gefrierfach markierten Lagerort bekommen das Frost-Symbol automatisch – auch bereits vorhandene
- 🧩 **Ein Formular**: Anlegen, Bearbeiten und Einfrieren zusammengefasst – im Produktformular ein ❄️-Schalter „Eingefroren"; der separate Einfrieren-Dialog entfällt
- 🩹 **Fixes**: ❄️-Markierung bleibt beim Umbenennen eines Lagerorts erhalten; „Verbrauchen bis" lässt sich leeren; keine Server-Fehler mehr bei ungültiger Mengeneingabe

## 1.6.1
- ❄️ **Einfrieren-Dialog**: Reste/Garten-Ernte als Tiefkühl-Produkt anlegen (Portionen, Herkunft, Einfrierdatum)
- ⏱️ **„Verbrauchen bis" automatisch** aus Einfrierdatum + Richtwert (Standard 1 Jahr, je Art anpassbar) – zählt in die MHD-Warnungen
- 🏷️ **Herkunft** (Garten/Reste/Selbstgemacht/Eingekauft) mit Filter in der Übersicht + ❄️-Kennzeichnung
- 📍 **Lagerorte als Gefrierfach** (❄️) markierbar (Einstellungen → Verwaltung); im Einfrieren-Dialog nur diese zur Auswahl
- 🧊 **Tiefkühl-Karte** auf der Produktseite (Einfrierdatum, Verbrauchen bis, Herkunft)
- 📊 Neuer Sensor `sensor.vorrat_tiefkuehl`

## 1.6.0
- 🔎 **Produkt-Detailseite** – öffnet sich per Klick auf den Produktnamen in der Übersicht
- 🖼️ **Produktbild** hochladen (auch direkt per Handy-Kamera) und **Nährwerte** (kcal, Eiweiß, Fett, KH) hinterlegen
- 🌐 **Open Food Facts**: nach dem Produkt suchen (kein Barcode nötig) → Bild und Nährwerte automatisch übernehmen
- 📝 **Notizfeld** pro Produkt + Übersicht „🍳 Verwendet in Rezepten"
- 📦 **Angebrochen-Balken**: farbiger Schieberegler für den Füllstand der offenen Packung
  (orange, unter 15 % rot) – unter 15 % wird automatisch 1 Einheit abgezogen und die Packung geschlossen
- 🔒 Sicherheit: Flask auf 3.1.3 aktualisiert

## 1.5.9
- 🔍 **Live-Suche** in der Übersicht (filtert Produkte sofort beim Tippen)
- ↕️ **Sortierung** nach Name, MHD (Ablaufdatum) oder Menge – bleibt erhalten
- 🗂️ **Verwaltung** in den Einstellungen: Lagerorte, Kategorien & Einheiten
  umbenennen (führt Dubletten zusammen), löschen (nur ungenutzte) und neu anlegen
- 📍 Produktformular schlägt vorhandene Lagerorte/Kategorien/Einheiten vor (keine Tippfehler)
- 🎨 Status als farbiger **Balken links** (statt kompletter Umrandung) – einheitlich mit Rezepten
- 🎨 Gebinde-Stepper sauber ausgerichtet, alle +/- Buttons in gleicher Form
- 🌙 Dark-Mode: Hinweis-Boxen, Kategorie-Tags und Stepper-Symbole überarbeitet (lesbar)
- 📱 Mobile: größere Touch-Flächen, volle Suchfeld-Breite, kompaktere Verwaltung

## 1.5.8
- 🩹 Stabilität: Server verarbeitet mehrere Anfragen gleichzeitig (`threaded`)
  – ein langsamer Kalender-Aufruf legt nicht mehr das ganze Add-on lahm (503-Fix)
- 🩹 SIGTERM wird sauber abgefangen → sauberer Stop/Neustart (kein Exit-Code 143)
- ⚡ Essensplaner lädt deutlich schneller: Kalender-Abgleich nur noch, wenn nötig
- ⏱️ Kürzere Timeouts für HA-Kalender-Aufrufe (schnelles Scheitern bei Netzproblemen)

## 1.5.7
- 👥 **Personenzahl** pro geplanter Mahlzeit (automatisch aus den Rezept-Portionen)
- 🛒 Im Essensplaner direkt **fehlende Zutaten zur Einkaufsliste** hinzufügen
  – Menge auf die Personenzahl umgerechnet, Auswahl welche Liste
- 📅 **„Zum Essensplan"-Button** auf jeder Rezeptseite (Datum/Mahlzeit/Personen)

## 1.5.6
- 📅 **Essensplaner** – Wochenansicht mit Frühstück / Mittag / Abend
- 🔗 Pro Mahlzeit: vorhandenes Rezept **oder** eigener Freitext
- 🗓️ **HA-Kalender-Anbindung** (Zwei-Wege): geplante Mahlzeiten landen automatisch
  im gewählten Home-Assistant-Kalender
- ↩️ Im HA-Kalender gelöschte Mahlzeiten verschwinden auch aus dem Planer
- 🛡️ Schutz vor Fehllöschungen (nur >90 s synchronisierte Einträge werden abgeglichen)
- ⚙️ Einstellungen: Ziel-Kalender auswählen (automatische Erkennung)
- 📊 Dashboard-Beispiel: `sensor.vorrat_einkaufsliste` ergänzt

## 1.5.5
- ✅ **Lidl-Import funktioniert jetzt vollständig** – Zutaten UND Anleitung werden geladen
  (Schema.org-JSON mit Steuerzeichen wird jetzt korrekt geparst, `strict=False`)
- ✅ **Kaufland-Zubereitung wird jetzt geladen** – Schritt-Text aus Microdata (`content`-Attribut)
  und `cooking-description` ausgelesen
- 🌐 Kaufland-Zutaten: korrekte Mengen/Einheiten aus der Zutaten-Tabelle
- 🧺 Zutaten-Parser erkennt nachgestellte Mengen (`Frühlingszwiebeln 3 St.`, `Salz Prise`)
- 🔤 Einheiten-Normalisierung: `St`/`Stk` → `Stück`, `Pkg` → `Packung`
- 🌐 Schema.org Parser unterstützt `HowToSection`, verschachtelte Anleitungen und `@graph`-Format
- 🐛 Fix: `fallback_extrahieren()` wird jetzt korrekt aufgerufen wenn Schema.org leer zurückgibt

## 1.5.4
- 🔍 Lagerort-Filter in der Übersicht (kombinierbar mit Kategorie-Filter)
- 🔒 Filter bleibt erhalten bei: +/- Menge, Bearbeiten, Löschen, Angebrochen, Umlagern
- 📍 Umlagerung: Mengenfeld ergänzt (Teilumlagerung möglich)
- 🐛 Fix: Chip-onclick im Umlagern-Modal (Apostroph-Sicherheit)
- 🐛 Fix: Mobile Aktionen-Buttons umbrechen statt zu überlaufen

## 1.5.3
- 📱 Mobile Optimierung: Karten-Layout für Handy/Tablet (HA Companion App)
- 📍 Umlagerung: Produkte zwischen Lagerorten verschieben (z.B. Keller → Küche)
- 📍 Teilumlagerung: nur einen Teil der Menge umlagern
- 🐛 Fix: Zur-Einkaufsliste-Button funktioniert wieder korrekt

## 1.5.2
- 🐛 Doppelte Funktionsdefinitionen entfernt (get_settings, t, fmt_currency)
- 🐛 Rezept-Einkauf: fehlende Menge wurde falsch berechnet
- 🐛 Web-Import: Internal Server Error behoben (fehlende Parser-Logik)
- 🔒 XSS-Fix: Produktnamen in JavaScript korrekt escaped
- 🔒 Sicherheitsupdate: requests 2.32.3 → 2.33.0 (CVE: .netrc credentials leak)

## 1.5.1
- 🔒 Sicherheitsupdate: requests 2.32.3, flask 3.1.1
- 📋 SECURITY.md hinzugefügt

## 1.5.0
- 📦 Gebinde-Funktion (Kisten, Pakete, etc.)
- Zwei Stepper pro Produkt: Kiste und Einzelstück
- Gebinde-Auswahl beim Zur-Einkaufsliste-Hinzufügen
- 🔧 Code-Review und Bereinigung

## 1.4.0
- 🎨 Hell/Dunkel-Modus & 6 Farbthemen in den Einstellungen
- 📦 Angebrochen-Status mit orangem Rahmen
- 🟠 Farbränder für MHD-Warnung, abgelaufen und Mindestmenge
- 🛒 Produkte direkt aus Übersicht zur Einkaufsliste hinzufügen
- ↓ Nullbestände automatisch ans Ende sortiert
- 🌐 Quell-URL beim Web-Import gespeichert

## 1.3.0
- 🛒 Produkte direkt aus der Übersicht zur Einkaufsliste hinzufügen
- ↓ Nullbestände automatisch ans Ende sortiert
- ✅ Kompatibilität mit HACS Add-on Store
- 🌐 Quell-URL wird beim Web-Import gespeichert (Link zum Originalrezept)

## 1.2.2
- Quell-URL wird beim Web-Import gespeichert
- 🌐 Originalrezept öffnen Link im Rezept-Detail

## 1.2.1
- Drag & Drop Sortierung in Einkaufslisten repariert

## 1.2.0
- Dashboard-Sensoren für HA (abgelaufen, bald ablaufend, unter Mindestmenge)
- Einzelpreis × Menge Berechnung in Einkaufslisten
- Alle erledigten Artikel auf einmal in Vorrat buchen

## 1.1.0
- Mehrsprachigkeit (DE/EN/FR/ES)
- Mehrere Währungen (€/CHF/£/$)
- Einstellungen-Seite
- Mobil-optimiertes Design mit Bottom-Navigation
- PWA-Unterstützung

## 1.0.0
- Initiale Version
- Vorratsverwaltung mit MHD-Warnungen
- Mehrere Einkaufslisten mit Preisen
- Rezepte mit PDF- und Web-Import
