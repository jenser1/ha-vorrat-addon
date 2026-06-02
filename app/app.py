from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta
import os, re, pdfplumber, tempfile, json, requests, sqlite3, threading, time
from bs4 import BeautifulSoup
from translations import TRANSLATIONS, CURRENCIES, LANGUAGES, get_translation, format_currency

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vorrat-geheim")

DB_PATH = os.environ.get("DB_PATH", "/tmp/vorrat.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ── Modelle ────────────────────────────────────────────────────────────────────

class Produkt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    menge = db.Column(db.Float, default=1)
    einheit = db.Column(db.String(20), default="Stück")
    mindestmenge = db.Column(db.Float, default=1)
    lagerort = db.Column(db.String(50), default="")
    kategorie = db.Column(db.String(50), default="Sonstiges")
    mhd = db.Column(db.Date, nullable=True)
    erstellt = db.Column(db.DateTime, default=datetime.utcnow)

class EinkaufsListe(db.Model):
    """Eine benannte Einkaufsliste (z.B. 'Edeka', 'Aldi')."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    erstellt = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship("Einkaufsliste", backref="liste", lazy=True, cascade="all, delete-orphan")

class Einkaufsliste(db.Model):
    """Ein Artikel in einer Einkaufsliste."""
    id = db.Column(db.Integer, primary_key=True)
    liste_id = db.Column(db.Integer, db.ForeignKey("einkaufs_liste.id"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    menge = db.Column(db.Float, default=1)
    einheit = db.Column(db.String(20), default="Stück")
    einzelpreis = db.Column(db.Float, nullable=True)  # Preis pro Einheit
    erledigt = db.Column(db.Boolean, default=False)
    in_bestand = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)
    hinzugefuegt = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def gesamtpreis(self):
        """Einzelpreis × Menge."""
        if self.einzelpreis is not None:
            return round(self.einzelpreis * self.menge, 2)
        return None


class Rezept(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    beschreibung = db.Column(db.Text, default="")
    anleitung = db.Column(db.Text, default="")
    portionen = db.Column(db.Integer, default=4)
    kategorie = db.Column(db.String(50), default="Sonstiges")
    quell_url = db.Column(db.String(500), default="")
    erstellt = db.Column(db.DateTime, default=datetime.utcnow)
    zutaten = db.relationship("RezeptZutat", backref="rezept", lazy=True, cascade="all, delete-orphan")

class RezeptZutat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rezept_id = db.Column(db.Integer, db.ForeignKey("rezept.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    menge = db.Column(db.Float, default=1)
    einheit = db.Column(db.String(20), default="Stueck")

class Einstellungen(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sprache = db.Column(db.String(5), default="de")
    waehrung = db.Column(db.String(5), default="EUR")
    theme = db.Column(db.String(20), default="light")
    farbe = db.Column(db.String(20), default="blau")

# ── PDF Extraktion ────────────────────────────────────────────────────────────

def pdf_text_bereinigen(text):
    if not text:
        return ""
    text = re.sub(r"-\n([a-zäöüß])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(z.strip() for z in text.splitlines()).strip()

def pdf_spalten_extrahieren(seite):
    """Trennt zweispaltige PDFs anhand von Wort-Koordinaten."""
    woerter = seite.extract_words(x_tolerance=3, y_tolerance=3)
    if not woerter:
        return seite.extract_text() or "", ""

    breite = seite.width
    mitte = breite * 0.5

    # Prüfe ob wirklich zwei Spalten vorhanden (Wörter auf beiden Seiten)
    links_woerter = [w for w in woerter if w["x0"] < mitte - 20]
    rechts_woerter = [w for w in woerter if w["x0"] > mitte + 20]

    if not rechts_woerter or len(rechts_woerter) < 5:
        # Einspaltig
        return seite.extract_text() or "", ""

    # Spalten nach Y-Koordinate gruppieren (Zeilen rekonstruieren)
    def woerter_zu_text(wlist):
        if not wlist:
            return ""
        wlist = sorted(wlist, key=lambda w: (round(w["top"] / 5) * 5, w["x0"]))
        zeilen = []
        aktuelle_y = None
        aktuelle_zeile = []
        for w in wlist:
            y = round(w["top"] / 5) * 5
            if aktuelle_y is None or abs(y - aktuelle_y) > 8:
                if aktuelle_zeile:
                    zeilen.append(" ".join(aktuelle_zeile))
                aktuelle_zeile = [w["text"]]
                aktuelle_y = y
            else:
                aktuelle_zeile.append(w["text"])
        if aktuelle_zeile:
            zeilen.append(" ".join(aktuelle_zeile))
        return "\n".join(zeilen)

    return woerter_zu_text(links_woerter), woerter_zu_text(rechts_woerter)

def pdf_abschnitte_erkennen(links_text, rechts_text, gesamt_text):
    """Erkennt Titel, Zutaten und Anleitung aus getrennten Spalten."""
    abschnitte = {"titel": "", "zutaten": "", "anleitung": ""}

    zutaten_keys = ["zutaten", "zutaten:", "ingredients", "zutaten ("]
    anleitung_keys = ["zubereitung", "zubereitung:", "anleitung", "preparation", "so wird", "zubereiten"]

    def abschnitt_aus_text(text):
        """Extrahiert Zutaten und Anleitung aus einem Textblock."""
        zutaten_z = []
        anleitung_z = []
        modus = None
        for zeile in text.splitlines():
            zl = zeile.lower().strip()
            if any(k in zl for k in zutaten_keys):
                modus = "zutaten"
                continue
            elif any(k in zl for k in anleitung_keys):
                modus = "anleitung"
                continue
            if zeile.strip():
                if modus == "zutaten":
                    zutaten_z.append(zeile.strip())
                elif modus == "anleitung":
                    anleitung_z.append(zeile.strip())
        return zutaten_z, anleitung_z

    # Titel aus erstem kurzen nicht-leeren Text
    for text in [links_text, rechts_text, gesamt_text]:
        for z in text.splitlines():
            if z.strip() and len(z.strip()) < 100 and not re.match(r"^\d+$", z.strip()):
                # Kein URL, kein "von X", kein Datum
                if "http" not in z and "/" not in z:
                    abschnitte["titel"] = z.strip()
                    break
        if abschnitte["titel"]:
            break

    # Bei zweispaltigem Layout: linke Spalte = Zutaten, rechte = Anleitung
    if links_text and rechts_text:
        # Linke Spalte auf Zutaten prüfen
        if any(k in links_text.lower() for k in zutaten_keys):
            z, a = abschnitt_aus_text(links_text)
            abschnitte["zutaten"] = "\n".join(z)
        if any(k in rechts_text.lower() for k in anleitung_keys):
            z, a = abschnitt_aus_text(rechts_text)
            abschnitte["anleitung"] = "\n".join(a)
        # Manchmal auch andersrum
        if not abschnitte["zutaten"] and any(k in rechts_text.lower() for k in zutaten_keys):
            z, a = abschnitt_aus_text(rechts_text)
            abschnitte["zutaten"] = "\n".join(z)
        if not abschnitte["anleitung"] and any(k in links_text.lower() for k in anleitung_keys):
            z, a = abschnitt_aus_text(links_text)
            abschnitte["anleitung"] = "\n".join(a)

    # Fallback: einspaltig
    if not abschnitte["zutaten"] and not abschnitte["anleitung"]:
        z, a = abschnitt_aus_text(gesamt_text)
        abschnitte["zutaten"] = "\n".join(z)
        abschnitte["anleitung"] = "\n".join(a)

    MUELL_PATTERN = re.compile(
        r"kcal|kJ|Eiweiß|Kohlenhydrate|Nährwert|http|www\.|"
        r"Rezepte$|Rezeptkategor|Zurück zu|filiale\.|kaufland\.|"
        r"QR-Code|Einkaufsliste\.$|Smartphone|Tablet|"
        r"\d{2}\.\d{2}\.\d{4}|Rezept \|| - Rezept|^\d+ von \d+",
        re.I)

    def zeilen_bereinigen(text):
        return "\n".join(z for z in text.splitlines() if z.strip() and not MUELL_PATTERN.search(z)).strip()

    abschnitte["zutaten"] = zeilen_bereinigen(abschnitte["zutaten"])
    abschnitte["anleitung"] = zeilen_bereinigen(abschnitte["anleitung"])

    # Zutaten aus allen Seiten zusammenführen:
    # Manche PDFs (z.B. Kaufland) haben letzte Zutaten auf Seite 2 links
    if links_text and rechts_text:
        extra_zutaten = []
        for z in links_text.splitlines():
            if MUELL_PATTERN.search(z):
                continue
            if re.match(r"^\d+\s*(g|kg|ml|l|EL|TL|Bund|Prise|Stück|Dose|Tasse|Pkg\.?|Packung)?\s+\S", z, re.I):
                extra_zutaten.append(z.strip())
            elif re.match(r"^(Salz|Pfeffer|Öl|Butter|Wasser|Zucker|Mehl)$", z.strip(), re.I):
                extra_zutaten.append(z.strip())
        # Nur hinzufügen was nicht schon drin ist
        if abschnitte["zutaten"] and extra_zutaten:
            vorhandene = abschnitte["zutaten"].lower()
            neue = [z for z in extra_zutaten if z.lower() not in vorhandene]
            if neue:
                abschnitte["zutaten"] = abschnitte["zutaten"] + "\n" + "\n".join(neue)

    # Titel aufräumen: " - Rezept | Supermarkt" entfernen
    if abschnitte["titel"]:
        abschnitte["titel"] = re.sub(r"\s*-\s*Rezept.*$", "", abschnitte["titel"], flags=re.I).strip()
        abschnitte["titel"] = re.sub(r"\s*\|.*$", "", abschnitte["titel"]).strip()

    return abschnitte

def pdf_text_extrahieren(pfad):
    """Extrahiert Text aus einer PDF mit Spalten-Unterstützung."""
    links_gesamt = []
    rechts_gesamt = []
    alle_texte = []

    with pdfplumber.open(pfad) as doc:
        for i, seite in enumerate(doc.pages):
            links, rechts = pdf_spalten_extrahieren(seite)
            if rechts:
                links_gesamt.append(pdf_text_bereinigen(links))
                rechts_gesamt.append(pdf_text_bereinigen(rechts))
                alle_texte.append(pdf_text_bereinigen(links + "\n" + rechts))
            else:
                text = pdf_text_bereinigen(links or seite.extract_text() or "")
                alle_texte.append(text)
                links_gesamt.append(text)

    links_text = "\n\n".join(t for t in links_gesamt if t)
    rechts_text = "\n\n".join(t for t in rechts_gesamt if t)
    gesamt = "\n\n".join(t for t in alle_texte if t)

    abschnitte = pdf_abschnitte_erkennen(links_text, rechts_text, gesamt)
    return gesamt, abschnitte

# ── Ingress Middleware ─────────────────────────────────────────────────────────

class ReverseProxied:
    """Middleware für HA Ingress – setzt SCRIPT_NAME aus X-Ingress-Path Header."""
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get("HTTP_X_INGRESS_PATH", "")
        if script_name:
            environ["SCRIPT_NAME"] = script_name
            path = environ.get("PATH_INFO", "")
            if path.startswith(script_name):
                environ["PATH_INFO"] = path[len(script_name):]
        return self.app(environ, start_response)

app.wsgi_app = ReverseProxied(app.wsgi_app)

# ── Einstellungen Helfer ─────────────────────────────────────────────────────────

@app.before_request
def load_settings():
    try:
        s = Einstellungen.query.first()
        g.lang = s.sprache if s else "de"
        g.waehrung = s.waehrung if s else "EUR"
    except:
        g.lang = "de"
        g.waehrung = "EUR"

@app.context_processor
def inject_globals():
    lang = getattr(g, 'lang', 'de')
    waehrung = getattr(g, 'waehrung', 'EUR')
    trans = TRANSLATIONS.get(lang, TRANSLATIONS['de'])
    try:
        s = Einstellungen.query.first()
        theme = s.theme if s and s.theme else "light"
        farbe = s.farbe if s and s.farbe else "blau"
    except:
        theme = "light"
        farbe = "blau"
    return {
        't': trans,
        'lang': lang,
        'waehrung': waehrung,
        'waehrung_symbol': CURRENCIES.get(waehrung, CURRENCIES['EUR'])['symbol'],
        'fmt_currency': fmt_currency,
        'alle_sprachen': LANGUAGES,
        'alle_waehrungen': CURRENCIES,
        'theme': theme,
        'farbe': farbe,
    }

def get_settings():
    """Gibt aktuelle Einstellungen zurück (oder Defaults)."""
    s = Einstellungen.query.first()
    if not s:
        s = Einstellungen(sprache="de", waehrung="EUR", theme="light", farbe="blau")
        db.session.add(s)
        db.session.commit()
    return s

def t(key):
    """Übersetzung für aktuellen Request."""
    lang = getattr(g, 'lang', 'de')
    return TRANSLATIONS.get(lang, TRANSLATIONS['de']).get(key, key)

def fmt_currency(amount):
    """Formatiert Betrag mit aktueller Währung."""
    currency = getattr(g, 'waehrung', 'EUR')
    return format_currency(amount, currency)

# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def mhd_status(mhd):
    if not mhd:
        return "ok"
    heute = date.today()
    diff = (mhd - heute).days
    if diff < 0:
        return "abgelaufen"
    elif diff <= 3:
        return "kritisch"
    elif diff <= 7:
        return "warnung"
    return "ok"

# ── Routen: Übersicht ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    heute = date.today()
    in_7_tagen = heute + timedelta(days=7)
    produkte = Produkt.query.order_by(Produkt.kategorie, Produkt.name).all()
    # Nullbestände ans Ende sortieren
    produkte = sorted(produkte, key=lambda p: (p.menge <= 0, p.kategorie, p.name))
    
    abgelaufen = [p for p in produkte if p.mhd and p.mhd < heute]
    bald_ablaufend = [p for p in produkte if p.mhd and heute <= p.mhd <= in_7_tagen]
    unter_mindest = [p for p in produkte if p.menge < p.mindestmenge]
    
    # Kategorien und Lagerorte aus allen Produkten (vor Filter)
    kategorien = sorted(set(p.kategorie for p in produkte))
    lagerorte = sorted(set(p.lagerort for p in produkte if p.lagerort))

    kat_filter = request.args.get("kategorie", "")
    ort_filter = request.args.get("lagerort", "")

    if kat_filter:
        produkte = [p for p in produkte if p.kategorie == kat_filter]
    if ort_filter:
        produkte = [p for p in produkte if p.lagerort == ort_filter]

    # angebrochen und gebinde direkt per SQL laden
    try:
        _conn = sqlite3.connect(DB_PATH)
        _rows = _conn.execute("SELECT id, angebrochen, gebinde FROM produkt").fetchall()
        _conn.close()
        _angebrochen_ids = set(r[0] for r in _rows if r[1])
        _gebinde_map = {r[0]: int(r[2] or 0) for r in _rows}
    except:
        _angebrochen_ids = set()
        _gebinde_map = {}

    for p in produkte:
        p.mhd_status = mhd_status(p.mhd)
        p.ist_angebrochen = p.id in _angebrochen_ids
        p.gebinde_wert = _gebinde_map.get(p.id, 0)

    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    alle_listen = EinkaufsListe.query.order_by(EinkaufsListe.erstellt.desc()).all()

    return render_template("index.html",
        produkte=produkte,
        abgelaufen=abgelaufen,
        bald_ablaufend=bald_ablaufend,
        unter_mindest=unter_mindest,
        kategorien=kategorien,
        lagerorte=lagerorte,
        kat_filter=kat_filter,
        ort_filter=ort_filter,
        einkauf_count=einkauf_count,
        alle_listen=alle_listen,
        heute=heute
    )

# ── Routen: Produkte ───────────────────────────────────────────────────────────

@app.route("/produkt/neu", methods=["GET", "POST"])
def produkt_neu():
    if request.method == "POST":
        mhd_str = request.form.get("mhd")
        mhd = datetime.strptime(mhd_str, "%Y-%m-%d").date() if mhd_str else None
        p = Produkt(
            name=request.form["name"],
            menge=float(request.form.get("menge", 1)),
            einheit=request.form.get("einheit", "Stück"),
            mindestmenge=float(request.form.get("mindestmenge", 1)),
            lagerort=request.form.get("lagerort", ""),
            kategorie=request.form.get("kategorie", "Sonstiges"),
            mhd=mhd
        )
        db.session.add(p)
        db.session.commit()
        # Gebinde direkt per SQL speichern
        gebinde_val = int(request.form.get("gebinde", 0) or 0)
        if gebinde_val > 0:
            with db.engine.connect() as conn:
                conn.execute(db.text("UPDATE produkt SET gebinde=:g WHERE id=:id"), {"g": gebinde_val, "id": p.id})
                conn.commit()
        flash(f"'{p.name}' wurde hinzugefügt.", "success")
        return redirect(url_for("index"))
    return render_template("produkt_form.html", produkt=None)

@app.route("/produkt/<int:id>/bearbeiten", methods=["GET", "POST"])
def produkt_bearbeiten(id):
    p = Produkt.query.get_or_404(id)
    if request.method == "POST":
        p.name = request.form["name"]
        p.menge = float(request.form.get("menge", 1))
        p.einheit = request.form.get("einheit", "Stück")
        p.mindestmenge = float(request.form.get("mindestmenge", 1))
        p.lagerort = request.form.get("lagerort", "")
        p.kategorie = request.form.get("kategorie", "Sonstiges")
        mhd_str = request.form.get("mhd")
        p.mhd = datetime.strptime(mhd_str, "%Y-%m-%d").date() if mhd_str else None
        db.session.commit()
        # Gebinde direkt per SQL speichern
        gebinde_val = int(request.form.get("gebinde", 0) or 0)
        with db.engine.connect() as conn:
            conn.execute(db.text("UPDATE produkt SET gebinde=:g WHERE id=:id"), {"g": gebinde_val, "id": id})
            conn.commit()
        flash(f"'{p.name}' wurde gespeichert.", "success")
        # Zurück zum gleichen Filter
        zurueck_kat = request.form.get("zurueck_kat", "") or None
        zurueck_ort = request.form.get("zurueck_ort", "") or None
        return redirect(url_for("index", kategorie=zurueck_kat, lagerort=zurueck_ort))
    # GET – Filter für Rücksprung merken
    zurueck_kat = request.args.get("zurueck_kat", "")
    zurueck_ort = request.args.get("zurueck_ort", "")
    # Gebinde-Wert direkt per SQL laden
    try:
        with db.engine.connect() as conn:
            row = conn.execute(db.text("SELECT gebinde FROM produkt WHERE id=:id"), {"id": id}).fetchone()
            p.gebinde_wert = int(row[0] or 0) if row else 0
    except:
        p.gebinde_wert = 0
    return render_template("produkt_form.html", produkt=p,
                           zurueck_kat=zurueck_kat, zurueck_ort=zurueck_ort)

@app.route("/produkt/<int:id>/angebrochen", methods=["POST"])
def produkt_angebrochen(id):
    with db.engine.connect() as conn:
        row = conn.execute(db.text("SELECT angebrochen FROM produkt WHERE id=:id"), {"id": id}).fetchone()
        if row:
            neu = 0 if row[0] else 1
            conn.execute(db.text("UPDATE produkt SET angebrochen=:val WHERE id=:id"), {"val": neu, "id": id})
            conn.commit()
    kat = request.args.get("kategorie") or None
    ort = request.args.get("lagerort") or None
    return redirect(url_for("index", kategorie=kat, lagerort=ort))

@app.route("/produkt/<int:id>/loeschen", methods=["POST"])
def produkt_loeschen(id):
    p = Produkt.query.get_or_404(id)
    name = p.name
    db.session.delete(p)
    db.session.commit()
    flash(f"'{name}' wurde gelöscht.", "info")
    kat = request.args.get("kategorie") or None
    ort = request.args.get("lagerort") or None
    return redirect(url_for("index", kategorie=kat, lagerort=ort))

@app.route("/produkt/<int:id>/menge", methods=["POST"])
def menge_anpassen(id):
    p = Produkt.query.get_or_404(id)
    aktion = request.form.get("aktion")
    wert = float(request.form.get("wert", 1))
    if aktion == "erhoehen":
        p.menge += wert
    elif aktion == "verringern":
        p.menge = max(0, p.menge - wert)
    db.session.commit()
    kat = request.args.get("kategorie") or None
    ort = request.args.get("lagerort") or None
    return redirect(url_for("index", kategorie=kat, lagerort=ort))

@app.route("/produkt/<int:id>/umlagern", methods=["POST"])
def produkt_umlagern(id):
    p = Produkt.query.get_or_404(id)
    alter_ort = p.lagerort or "–"
    neuer_ort = request.form.get("lagerort", "").strip()
    try:
        menge = float(request.form.get("menge", p.menge) or p.menge)
    except ValueError:
        menge = p.menge
    menge = min(max(0, menge), p.menge)  # 0 … Gesamtmenge

    if menge <= 0:
        flash("Menge muss größer als 0 sein.", "danger")
        return redirect(url_for("index"))

    if menge >= p.menge:
        # Vollständige Umlagerung – nur Lagerort ändern
        p.lagerort = neuer_ort
        db.session.commit()
        flash(f"'{p.name}' ({int(menge) if menge == int(menge) else menge} {p.einheit}) komplett von '{alter_ort}' nach '{neuer_ort or '–'}' umgelagert.", "success")
    else:
        # Teilumlagerung – Menge abziehen, am Zielort hinzufügen
        p.menge -= menge
        vorhandener = Produkt.query.filter(
            Produkt.name == p.name,
            Produkt.lagerort == neuer_ort
        ).first()
        if vorhandener:
            vorhandener.menge += menge
        else:
            neu = Produkt(
                name=p.name,
                menge=menge,
                einheit=p.einheit,
                mindestmenge=0,
                lagerort=neuer_ort,
                kategorie=p.kategorie,
                mhd=p.mhd
            )
            db.session.add(neu)
        db.session.commit()
        menge_str = int(menge) if menge == int(menge) else menge
        flash(f"'{p.name}': {menge_str} {p.einheit} von '{alter_ort}' nach '{neuer_ort or '–'}' umgelagert.", "success")

    kat = request.args.get("kategorie") or None
    ort = request.args.get("lagerort") or None
    return redirect(url_for("index", kategorie=kat, lagerort=ort))

# ── Routen: Einkaufsliste ──────────────────────────────────────────────────────

# ── Routen: Einkaufslisten ────────────────────────────────────────────────────

@app.route("/einkauf")
def einkauf():
    listen = EinkaufsListe.query.order_by(EinkaufsListe.erstellt.desc()).all()
    unter_mindest = Produkt.query.filter(Produkt.menge < Produkt.mindestmenge).all()
    nicht_zugeordnet = Produkt.query.filter_by(kategorie="Nicht zugeordnet").all()
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    return render_template("einkauf_uebersicht.html",
        listen=listen, unter_mindest=unter_mindest,
        nicht_zugeordnet=nicht_zugeordnet, einkauf_count=einkauf_count)

@app.route("/einkauf/neu", methods=["POST"])
def einkauf_liste_neu():
    name = request.form.get("name", "").strip()
    if name:
        l = EinkaufsListe(name=name)
        db.session.add(l)
        db.session.commit()
        flash(f"Liste '{name}' erstellt.", "success")
        return redirect(url_for("einkauf_liste", liste_id=l.id))
    return redirect(url_for("einkauf"))

@app.route("/einkauf/liste/<int:liste_id>")
def einkauf_liste(liste_id):
    liste = EinkaufsListe.query.get_or_404(liste_id)
    alle_listen = EinkaufsListe.query.order_by(EinkaufsListe.erstellt.desc()).all()
    unter_mindest = Produkt.query.filter(Produkt.menge < Produkt.mindestmenge).all()
    offene = Einkaufsliste.query.filter_by(liste_id=liste_id, erledigt=False).order_by(Einkaufsliste.position, Einkaufsliste.hinzugefuegt).all()
    erledigte = Einkaufsliste.query.filter_by(liste_id=liste_id, erledigt=True).all()
    gesamtpreis = sum(i.gesamtpreis or 0 for i in offene + erledigte)
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    return render_template("einkauf.html",
        liste=liste, alle_listen=alle_listen,
        offene=offene, erledigte=erledigte,
        unter_mindest=unter_mindest,
        gesamtpreis=gesamtpreis,
        einkauf_count=einkauf_count)

@app.route("/einkauf/liste/<int:liste_id>/loeschen", methods=["POST"])
def einkauf_liste_loeschen(liste_id):
    l = EinkaufsListe.query.get_or_404(liste_id)
    name = l.name
    db.session.delete(l)
    db.session.commit()
    flash(f"Liste '{name}' wurde gelöscht.", "info")
    return redirect(url_for("einkauf"))

@app.route("/einkauf/liste/<int:liste_id>/hinzufuegen", methods=["POST"])
def einkauf_hinzufuegen(liste_id):
    name = request.form.get("name", "").strip()
    if name:
        preis_str = request.form.get("einzelpreis", "").strip()
        einzelpreis = float(preis_str.replace(",", ".")) if preis_str else None
        e = Einkaufsliste(
            liste_id=liste_id,
            name=name,
            menge=float(request.form.get("menge", 1)),
            einheit=request.form.get("einheit", "Stück"),
            einzelpreis=einzelpreis
        )
        db.session.add(e)
        db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/liste/<int:liste_id>/auto", methods=["POST"])
def einkauf_auto(liste_id):
    unter_mindest = Produkt.query.filter(Produkt.menge < Produkt.mindestmenge).all()
    hinzugefuegt = 0
    for p in unter_mindest:
        existiert = Einkaufsliste.query.filter_by(liste_id=liste_id, name=p.name, erledigt=False).first()
        if not existiert:
            fehlend = p.mindestmenge - p.menge
            e = Einkaufsliste(liste_id=liste_id, name=p.name, menge=fehlend, einheit=p.einheit)
            db.session.add(e)
            hinzugefuegt += 1
    db.session.commit()
    flash(f"{hinzugefuegt} Artikel hinzugefügt.", "success")
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/item/<int:id>/erledigt", methods=["POST"])
def einkauf_erledigt(id):
    e = Einkaufsliste.query.get_or_404(id)
    e.erledigt = True
    liste_id = e.liste_id
    # Preis aktualisieren falls angegeben
    preis_str = request.form.get("einzelpreis", "").strip()
    if preis_str:
        try:
            e.einzelpreis = float(preis_str.replace(",", "."))
        except: pass
    # Optional: in Bestand buchen
    if request.form.get("in_bestand"):
        p = Produkt.query.filter(Produkt.name.ilike(f"%{e.name}%")).first()
        if p:
            p.menge += e.menge
            e.in_bestand = True
            flash(f"'{e.name}' erledigt – Bestand um {e.menge} {e.einheit} erhöht.", "success")
        else:
            # Neu anlegen als "Nicht zugeordnet"
            neu = Produkt(
                name=e.name,
                menge=e.menge,
                einheit=e.einheit,
                mindestmenge=e.menge,
                kategorie="Nicht zugeordnet",
                lagerort=""
            )
            db.session.add(neu)
            e.in_bestand = True
            flash(f"'{e.name}' neu im Vorrat angelegt (Nicht zugeordnet) – bitte Kategorie ergänzen.", "info")
    db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/item/<int:id>/rueckgaengig", methods=["POST"])
def einkauf_rueckgaengig(id):
    e = Einkaufsliste.query.get_or_404(id)
    e.erledigt = False
    e.in_bestand = False
    db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=e.liste_id))

@app.route("/einkauf/item/<int:id>/bestand_nachbuchen", methods=["POST"])
def einkauf_bestand_nachbuchen(id):
    e = Einkaufsliste.query.get_or_404(id)
    if not e.in_bestand:
        p = Produkt.query.filter(Produkt.name.ilike(f"%{e.name}%")).first()
        if p:
            p.menge += e.menge
            e.in_bestand = True
            flash(f"'{e.name}' nachgebucht – Bestand um {e.menge} {e.einheit} erhöht.", "success")
        else:
            neu = Produkt(
                name=e.name, menge=e.menge, einheit=e.einheit,
                mindestmenge=e.menge, kategorie="Nicht zugeordnet", lagerort=""
            )
            db.session.add(neu)
            e.in_bestand = True
            flash(f"'{e.name}' neu im Vorrat angelegt (Nicht zugeordnet).", "info")
        db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=e.liste_id))

@app.route("/einkauf/liste/<int:liste_id>/sortieren", methods=["POST"])
def einkauf_sortieren(liste_id):
    """Speichert neue Reihenfolge per Drag & Drop (JSON-Liste von IDs)."""
    import json as _json
    reihenfolge = json.loads(request.data or "[]")
    for pos, item_id in enumerate(reihenfolge):
        e = Einkaufsliste.query.get(item_id)
        if e and e.liste_id == liste_id:
            e.position = pos
    db.session.commit()
    return "", 204

@app.route("/einkauf/item/<int:id>/loeschen", methods=["POST"])
def einkauf_loeschen(id):
    e = Einkaufsliste.query.get_or_404(id)
    liste_id = e.liste_id
    db.session.delete(e)
    db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/liste/<int:liste_id>/alle_buchen", methods=["POST"])
def einkauf_alle_buchen(liste_id):
    """Alle erledigten Artikel auf einmal in Bestand buchen."""
    erledigte = Einkaufsliste.query.filter_by(liste_id=liste_id, erledigt=True, in_bestand=False).all()
    gebucht = 0
    neu_angelegt = 0
    for e in erledigte:
        p = Produkt.query.filter(Produkt.name.ilike(f"%{e.name}%")).first()
        if p:
            p.menge += e.menge
            e.in_bestand = True
            gebucht += 1
        else:
            neu = Produkt(name=e.name, menge=e.menge, einheit=e.einheit,
                         mindestmenge=e.menge, kategorie="Nicht zugeordnet", lagerort="")
            db.session.add(neu)
            e.in_bestand = True
            neu_angelegt += 1
    db.session.commit()
    flash(f"{gebucht} Artikel gebucht, {neu_angelegt} neu angelegt.", "success")
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/liste/<int:liste_id>/leeren", methods=["POST"])
def einkauf_leeren(liste_id):
    Einkaufsliste.query.filter_by(liste_id=liste_id, erledigt=True).delete()
    db.session.commit()
    flash("Erledigte Artikel gelöscht.", "info")
    return redirect(url_for("einkauf_liste", liste_id=liste_id))

@app.route("/einkauf/item/<int:id>/preis", methods=["POST"])
def einkauf_preis(id):
    e = Einkaufsliste.query.get_or_404(id)
    preis_str = request.form.get("einzelpreis", "").strip()
    try:
        e.einzelpreis = float(preis_str.replace(",", ".")) if preis_str else None
    except: pass
    db.session.commit()
    return redirect(url_for("einkauf_liste", liste_id=e.liste_id))


# ── Routen: Rezepte ────────────────────────────────────────────────────────────

EINHEITEN = ['Stück', 'g', 'kg', 'ml', 'l', 'EL', 'TL', 'Prise', 'Packung', 'Dose', 'Tasse']

@app.route("/rezepte")
def rezepte():
    alle = Rezept.query.all()
    kat_filter = request.args.get("kategorie", "")
    sort = request.args.get("sort", "neu")

    # Sortierung
    if sort == "name":
        alle = sorted(alle, key=lambda r: r.name.lower())
    elif sort == "kategorie":
        alle = sorted(alle, key=lambda r: (r.kategorie.lower(), r.name.lower()))
    else:  # neueste
        alle = sorted(alle, key=lambda r: r.erstellt, reverse=True)

    # Filter
    gefiltert = [r for r in alle if not kat_filter or r.kategorie == kat_filter]

    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    return render_template("rezepte.html",
        rezepte=alle, gefiltert=gefiltert,
        kat_filter=kat_filter, sort=sort,
        einkauf_count=einkauf_count)

@app.route("/rezept/neu", methods=["GET", "POST"])
def rezept_neu():
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    if request.method == "POST":
        quell_url = request.form.get("quell_url", "").strip()
        r = Rezept(
            name=request.form["name"],
            beschreibung=request.form.get("beschreibung", ""),
            anleitung=request.form.get("anleitung", ""),
            portionen=int(request.form.get("portionen", 4)),
            kategorie=request.form.get("kategorie", "Sonstiges"),
            quell_url=quell_url,
        )
        db.session.add(r)
        db.session.flush()
        # Zutaten speichern
        namen = request.form.getlist("zutat_name")
        mengen = request.form.getlist("zutat_menge")
        einheiten = request.form.getlist("zutat_einheit")
        for n, m, e in zip(namen, mengen, einheiten):
            if n.strip():
                z = RezeptZutat(rezept_id=r.id, name=n.strip(),
                    menge=float(m) if m else 1, einheit=e or "Stück")
                db.session.add(z)
        db.session.commit()
        flash(f"Rezept \'{r.name}\' wurde gespeichert.", "success")
        return redirect(url_for("rezept_detail", id=r.id))
    return render_template("rezept_form.html", rezept=None, einheiten=EINHEITEN, einkauf_count=einkauf_count)

@app.route("/rezept/<int:id>")
def rezept_detail(id):
    r = Rezept.query.get_or_404(id)
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    listen = EinkaufsListe.query.order_by(EinkaufsListe.erstellt.desc()).all()
    # Vorrat-Abgleich
    abgleich = []
    for z in r.zutaten:
        p = Produkt.query.filter(Produkt.name.ilike(f"%{z.name}%")).first()
        abgleich.append({
            "zutat": z,
            "vorrat": p,
            "vorhanden": p is not None and p.menge >= z.menge
        })
    return render_template("rezept_detail.html", rezept=r, abgleich=abgleich,
        einkauf_count=einkauf_count, listen=listen)

@app.route("/rezept/<int:id>/bearbeiten", methods=["GET", "POST"])
def rezept_bearbeiten(id):
    r = Rezept.query.get_or_404(id)
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    if request.method == "POST":
        r.name = request.form["name"]
        r.beschreibung = request.form.get("beschreibung", "")
        r.anleitung = request.form.get("anleitung", "")
        r.portionen = int(request.form.get("portionen", 4))
        r.kategorie = request.form.get("kategorie", "Sonstiges")
        # Zutaten neu setzen
        RezeptZutat.query.filter_by(rezept_id=r.id).delete()
        namen = request.form.getlist("zutat_name")
        mengen = request.form.getlist("zutat_menge")
        einheiten = request.form.getlist("zutat_einheit")
        for n, m, e in zip(namen, mengen, einheiten):
            if n.strip():
                z = RezeptZutat(rezept_id=r.id, name=n.strip(),
                    menge=float(m) if m else 1, einheit=e or "Stück")
                db.session.add(z)
        db.session.commit()
        flash(f"Rezept \'{r.name}\' wurde aktualisiert.", "success")
        return redirect(url_for("rezept_detail", id=r.id))
    return render_template("rezept_form.html", rezept=r, einheiten=EINHEITEN, einkauf_count=einkauf_count)

@app.route("/rezept/<int:id>/loeschen", methods=["POST"])
def rezept_loeschen(id):
    r = Rezept.query.get_or_404(id)
    name = r.name
    db.session.delete(r)
    db.session.commit()
    flash(f"Rezept \'{name}\' wurde gelöscht.", "info")
    return redirect(url_for("rezepte"))

@app.route("/rezept/<int:id>/einkaufen", methods=["POST"])
def rezept_einkaufen(id):
    r = Rezept.query.get_or_404(id)
    # Erste vorhandene Liste nehmen oder neue anlegen
    liste_id = request.form.get("liste_id")
    if liste_id:
        liste = EinkaufsListe.query.get(int(liste_id))
    else:
        liste = EinkaufsListe.query.order_by(EinkaufsListe.erstellt).first()
    if not liste:
        liste = EinkaufsListe(name="Einkauf")
        db.session.add(liste)
        db.session.flush()
    hinzugefuegt = 0
    for z in r.zutaten:
        p = Produkt.query.filter(Produkt.name.ilike(f"%{z.name}%")).first()
        if not p or p.menge < z.menge:
            existiert = Einkaufsliste.query.filter_by(liste_id=liste.id, name=z.name, erledigt=False).first()
            if not existiert:
                fehlend = z.menge - (p.menge if p else 0)
                e = Einkaufsliste(liste_id=liste.id, name=z.name, menge=max(0, fehlend), einheit=z.einheit)
                db.session.add(e)
                hinzugefuegt += 1
    db.session.commit()
    flash(f"{hinzugefuegt} fehlende Zutaten zur Liste '{liste.name}' hinzugefügt.", "success")
    return redirect(url_for("rezept_detail", id=id))

@app.route("/rezept/pdf-import", methods=["GET", "POST"])
def rezept_pdf_import():
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    extrahierter_text = ""
    abschnitte = {}
    if request.method == "POST":
        pdf = request.files.get("pdf")
        if pdf and pdf.filename.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf.save(tmp.name)
                try:
                    extrahierter_text, abschnitte = pdf_text_extrahieren(tmp.name)
                except Exception as ex:
                    flash(f"PDF konnte nicht gelesen werden: {ex}", "danger")
                finally:
                    os.unlink(tmp.name)
        else:
            flash("Bitte eine gültige PDF-Datei hochladen.", "danger")
    return render_template("rezept_pdf_import.html",
        extrahierter_text=extrahierter_text,
        abschnitte=abschnitte,
        einheiten=EINHEITEN,
        einkauf_count=einkauf_count)


# ── Web-Import ─────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

def html_bereinigen(text):
    """Entfernt HTML-Tags und normalisiert Whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def menge_parsen(wert):
    """Konvertiert Mengenangaben wie '1/2', '½' in Float."""
    if not wert:
        return 1.0
    wert = str(wert).strip()
    brueche = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 0.33, "⅔": 0.67}
    for b, f in brueche.items():
        wert = wert.replace(b, str(f))
    try:
        if "/" in wert:
            z, n = wert.split("/", 1)
            return float(z.strip()) / float(n.strip())
        return float(re.search(r"[\d\.]+", wert).group())
    except:
        return 1.0

def zutat_parsen(text):
    """Zerlegt einen Zutaten-String in Menge, Einheit und Name."""
    text = html_bereinigen(text).strip()
    einheiten = ["g", "kg", "ml", "l", "EL", "TL", "Prise", "Bund", "Stück",
                 "Dose", "Packung", "Pkg", "Tasse", "Becher", "Scheibe",
                 "Scheiben", "Zehe", "Zehen", "cm", "tbsp", "tsp", "cup",
                 "oz", "lb", "handful", "bunch"]

    # Kaufland-Format: "300 g | grüner Spargel" oder "4 | TK-Lachsfilets"
    if "|" in text:
        teile = [t.strip() for t in text.split("|", 1)]
        menge_teil = teile[0].strip()
        name_teil  = teile[1].strip() if len(teile) > 1 else ""
        if name_teil:
            # Menge + Einheit im linken Teil parsen
            m = re.match(
                r"^([\d\s\/½¼¾⅓⅔,\.]+)\s*("
                + "|".join(re.escape(e) for e in einheiten)
                + r")\.?\s*$", menge_teil, re.I)
            if m:
                return menge_parsen(m.group(1)), m.group(2), name_teil
            # Nur Zahl links
            m2 = re.match(r"^([\d½¼¾⅓⅔][,\.\d\s\/]*)\s*$", menge_teil)
            if m2:
                return menge_parsen(m2.group(1)), "Stück", name_teil
            # Linker Teil ist kein Zahlenwert → ganzer Text als Name
            if not re.search(r"\d", menge_teil):
                return 1.0, "Stück", f"{menge_teil} {name_teil}".strip()

    m = re.match(
        r"^([\d\s\/½¼¾⅓⅔,\.]+)\s*("
        + "|".join(re.escape(e) for e in einheiten)
        + r")\.?\s+(.+)$", text, re.I)
    if m:
        return menge_parsen(m.group(1)), m.group(2), m.group(3).strip()
    # Nur Zahl am Anfang
    m2 = re.match(r"^([\d½¼¾⅓⅔][\d\s\/,\.]*?)\s+(.+)$", text)
    if m2:
        return menge_parsen(m2.group(1)), "Stück", m2.group(2).strip()
    return 1.0, "Stück", text

def schema_org_extrahieren(soup):
    """Extrahiert Rezept aus Schema.org JSON-LD – funktioniert für ~80% aller Rezeptseiten."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")

            # Alle Kandidaten sammeln: Array, @graph oder einzelnes Objekt
            kandidaten = []
            if isinstance(data, list):
                kandidaten = data
            elif isinstance(data, dict):
                kandidaten = data.get("@graph", [data])

            # Rezept-Objekt finden (@type kann String ODER Liste sein)
            rezept = None
            for d in kandidaten:
                if not isinstance(d, dict):
                    continue
                typ = d.get("@type", "")
                typen = typ if isinstance(typ, list) else [typ]
                if "Recipe" in typen:
                    rezept = d
                    break
            if not rezept:
                continue

            # Zutaten extrahieren
            zutaten_roh = rezept.get("recipeIngredient", [])
            zutaten = []
            for z in zutaten_roh:
                menge, einheit, name = zutat_parsen(str(z))
                zutaten.append({"name": name, "menge": menge, "einheit": einheit})

            # Anleitung – auch HowToSection und HowToStep behandeln
            anleitung_roh = rezept.get("recipeInstructions", [])
            anleitung_zeilen = []

            def schritt_texte(schritt):
                """Gibt Textzeilen aus einem HowToStep/HowToSection/String zurück."""
                if isinstance(schritt, str):
                    t = html_bereinigen(schritt)
                    return [t] if t else []
                if isinstance(schritt, dict):
                    if schritt.get("@type") == "HowToSection":
                        result = []
                        if schritt.get("name"):
                            result.append(f"── {schritt['name']} ──")
                        for sub in schritt.get("itemListElement", []):
                            result.extend(schritt_texte(sub))
                        return result
                    t = html_bereinigen(schritt.get("text") or schritt.get("name") or "")
                    return [t] if t else []
                return []

            if isinstance(anleitung_roh, str):
                anleitung_zeilen = [html_bereinigen(anleitung_roh)]
            elif isinstance(anleitung_roh, list):
                nr = 1
                for schritt in anleitung_roh:
                    for zeile in schritt_texte(schritt):
                        if zeile.startswith("──"):
                            anleitung_zeilen.append(zeile)
                        else:
                            anleitung_zeilen.append(f"{nr}. {zeile}")
                            nr += 1

            # Portionen
            portionen = 4
            port_val = rezept.get("recipeYield", "4")
            port_str = str(port_val[0] if isinstance(port_val, list) else port_val)
            m = re.search(r"\d+", port_str)
            if m:
                portionen = int(m.group())

            # Titel bereinigen (z.B. "Spaghetti – Rezept | Chefkoch" → "Spaghetti")
            titel = html_bereinigen(str(rezept.get("name", "")))
            titel = re.sub(r"\s*[-–|]\s*(Rezept|Recipe).*$", "", titel, flags=re.I).strip()

            beschreibung = html_bereinigen(str(rezept.get("description", "")))[:300]

            return {
                "titel": titel,
                "beschreibung": beschreibung,
                "portionen": portionen,
                "zutaten": zutaten,
                "anleitung": "\n".join(anleitung_zeilen),
                "quelle": "schema.org",
            }
        except Exception:
            continue
    return None

def fallback_extrahieren(soup, url):
    """Fallback-Extraktion für Seiten ohne Schema.org über HTML-Heuristiken."""
    ergebnis = {"titel": "", "beschreibung": "", "portionen": 4,
                "zutaten": [], "anleitung": "", "quelle": "fallback"}

    # Titel – og:title als erste Wahl
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        ergebnis["titel"] = og_title["content"].strip()
        ergebnis["titel"] = re.sub(r"\s*[-–|]\s*(Rezept|Recipe).*$", "", ergebnis["titel"], flags=re.I).strip()
    if not ergebnis["titel"]:
        for sel in ["h1.recipe-title", "h1.o-headline", "h1[class*=recipe]",
                    "h1[class*=title]", "h1", "h2"]:
            el = soup.select_one(sel)
            if el:
                ergebnis["titel"] = el.get_text(strip=True)
                break

    # Zutaten: erweiterte Selektoren
    zutaten_container = None
    for sel in [
        "[class*=ingredient-list]", "[class*=ingredients-list]",
        "[class*=IngredientList]", "[class*=ingredientList]",
        ".ingredients", ".recipe-ingredients", "#ingredients",
        "[class*=ingredient]", "[itemprop=recipeIngredient]",
        "[class*=zutat]", "[class*=Zutat]",
    ]:
        zutaten_container = soup.select_one(sel)
        if zutaten_container:
            break

    if zutaten_container:
        for li in zutaten_container.find_all(["li", "p", "span", "div"]):
            # Nur direkte Kinder-Texte, keine Duplikate durch Verschachtelung
            if li.find(["li", "ul"]):
                continue
            text = li.get_text(strip=True)
            if text and 2 < len(text) < 150:
                menge, einheit, name = zutat_parsen(text)
                ergebnis["zutaten"].append({"name": name, "menge": menge, "einheit": einheit})

    # Anleitung: erweiterte Selektoren
    anleitung_container = None
    for sel in [
        "[class*=preparation-steps]", "[class*=recipe-steps]",
        "[class*=InstructionList]", "[class*=instructionList]",
        "[class*=step-list]", "[class*=stepList]",
        ".instructions", ".recipe-instructions", "#instructions",
        ".preparation", "[class*=instruction]", "[class*=direction]",
        "[itemprop=recipeInstructions]", "[class*=zubereitung]",
    ]:
        anleitung_container = soup.select_one(sel)
        if anleitung_container:
            break

    if anleitung_container:
        schritte = []
        for li in anleitung_container.find_all(["li", "p"]):
            text = li.get_text(strip=True)
            if text and len(text) > 15:
                schritte.append(text)
        if schritte:
            ergebnis["anleitung"] = "\n".join(f"{i}. {s}" for i, s in enumerate(schritte, 1))

    return ergebnis

def kaufland_extrahieren(soup):
    """Parser für filiale.kaufland.de – Schema.org zuerst, dann HTML-Fallback."""

    # 1. Schema.org versuchen (Kaufland hat oft valides JSON-LD)
    schema = schema_org_extrahieren(soup)
    if schema and schema.get("titel") and (schema.get("zutaten") or schema.get("anleitung")):
        schema["quelle"] = "kaufland+schema"
        return schema

    ergebnis = schema or {"titel": "", "beschreibung": "", "portionen": 4,
                          "zutaten": [], "anleitung": "", "quelle": "kaufland"}
    ergebnis["quelle"] = "kaufland"

    # Titel
    if not ergebnis.get("titel"):
        for sel in ["h1", ".recipe-hero__title", "[class*=recipe-title]", "[class*=recipe-name]"]:
            el = soup.select_one(sel)
            if el:
                ergebnis["titel"] = el.get_text(strip=True)
                break

    # Beschreibung
    if not ergebnis.get("beschreibung"):
        for attr in [{"name": "description"}, {"property": "og:description"}]:
            meta = soup.find("meta", attrs=attr)
            if meta and meta.get("content"):
                ergebnis["beschreibung"] = meta["content"][:300].strip()
                break

    # Portionen
    if ergebnis.get("portionen", 4) == 4:
        for el in soup.select("[class*=portion], [class*=serving], [class*=yield], [class*=personen]"):
            m = re.search(r"(\d+)", el.get_text())
            if m:
                ergebnis["portionen"] = int(m.group(1))
                break

    # Zutaten (wenn Schema.org keine hatte)
    if not ergebnis.get("zutaten"):
        # Tabelle Menge | Zutat
        for row in soup.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                menge_text = cells[0].get_text(strip=True)
                name_text  = cells[1].get_text(strip=True)
                if name_text and len(name_text) > 1 and not re.match(r"^(Menge|Zutat|Ingredient)", name_text, re.I):
                    menge, einheit, name = zutat_parsen(f"{menge_text} {name_text}")
                    ergebnis["zutaten"].append({"name": name, "menge": menge, "einheit": einheit})

    if not ergebnis.get("zutaten"):
        for sel in ["[class*=ingredient]", "[class*=zutat]", "[class*=recipe-ingredient]"]:
            items = soup.select(f"{sel} li, {sel}")
            for li in items:
                if li.find(["li", "ul"]):
                    continue
                text = li.get_text(strip=True)
                if text and 2 < len(text) < 120:
                    menge, einheit, name = zutat_parsen(text)
                    ergebnis["zutaten"].append({"name": name, "menge": menge, "einheit": einheit})
            if ergebnis.get("zutaten"):
                break

    # Zutaten: Pipe-Format "300 g | grüner Spargel" (typisch Kaufland)
    if not ergebnis.get("zutaten"):
        zutaten_pipe = []
        for el in soup.find_all(string=re.compile(r"\|")):
            zeile = el.strip()
            if "|" in zeile and 2 < len(zeile) < 150:
                menge, einheit, name = zutat_parsen(zeile)
                if name and name not in [z["name"] for z in zutaten_pipe]:
                    zutaten_pipe.append({"name": name, "menge": menge, "einheit": einheit})
        if zutaten_pipe:
            ergebnis["zutaten"] = zutaten_pipe

    # Zutaten: generische ul li als letzter Fallback
    if not ergebnis.get("zutaten"):
        for li in soup.select("ul li"):
            text = li.get_text(strip=True)
            if text and re.match(r"^[\d½¼¾]|^\d+\s*(g|kg|ml|l|EL|TL|Bund|Stück)", text, re.I):
                menge, einheit, name = zutat_parsen(text)
                ergebnis["zutaten"].append({"name": name, "menge": menge, "einheit": einheit})

    # Zubereitung (wenn Schema.org keine hatte)
    if not ergebnis.get("anleitung"):
        schritte = []
        # Spezifische CSS-Selektoren
        for sel in [
            "[class*=preparation-step] p", "[class*=preparation-step]",
            "[class*=recipe-step] p",       "[class*=recipe-step]",
            "[class*=cooking-step]",         "[class*=step-description]",
            "ol[class*=preparation] li",     "ol[class*=instruction] li",
            "ol[class*=step] li",            "ol[class*=zubereitung] li",
            "[class*=zubereitung] li",       "[class*=zubereitung] p",
        ]:
            els = soup.select(sel)
            gefunden = [el.get_text(strip=True) for el in els
                        if len(el.get_text(strip=True)) > 20]
            if gefunden:
                schritte = gefunden
                break

        # Fallback: nummerierte <ol> suchen
        if not schritte:
            SPAM = re.compile(r"cookie|impressum|datenschutz|newsletter|©|agb|anmeld", re.I)
            for ol in soup.find_all("ol"):
                items = [li.get_text(strip=True) for li in ol.find_all("li")
                         if len(li.get_text(strip=True)) > 20 and not SPAM.search(li.get_text())]
                if len(items) >= 2:
                    schritte = items
                    break

        # Fallback: Absätze die mit einer Zahl beginnen (Kaufland-Nummerierungsformat)
        if not schritte:
            SPAM = re.compile(r"cookie|impressum|datenschutz|newsletter|©|agb|anmeld|javascript", re.I)
            kandidaten = []
            for el in soup.find_all(["p", "div", "li"]):
                # Kein Kinder-Block-Element
                if el.find(["p", "div", "ol", "ul"]):
                    continue
                text = el.get_text(strip=True)
                if re.match(r"^\d+[\.\)]\s+\S", text) and len(text) > 30 and not SPAM.search(text):
                    kandidaten.append(text)
            if len(kandidaten) >= 2:
                schritte = [re.sub(r"^\d+[\.\)]\s+", "", s) for s in kandidaten]

        if schritte:
            ergebnis["anleitung"] = "\n".join(f"{i}. {s}" for i, s in enumerate(schritte, 1))

    return ergebnis

def lidl_api_abrufen(url):
    """Ruft Lidl Rezept direkt über die API ab."""
    alle_ids = re.findall(r"(\d{4,8})", url)
    if not alle_ids:
        return None
    recipe_id = alle_ids[-1]
    # Slug aus URL extrahieren (für neuere API)
    slug_match = re.search(r"/rezeptwelt/([^/?#]+)", url)
    slug = slug_match.group(1) if slug_match else recipe_id

    api_pfade = [
        f"https://www.lidl-kochen.de/api/v2/recipes/{recipe_id}",
        f"https://www.lidl-kochen.de/api/recipes/{recipe_id}",
        f"https://www.lidl-kochen.de/api/recipe/{recipe_id}",
        f"https://www.lidl-kochen.de/api/v3/recipes/{recipe_id}",
        f"https://www.lidl-kochen.de/rezeptwelt/{slug}.json",
    ]
    headers_api = {**HEADERS, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    for api_url in api_pfade:
        try:
            resp = requests.get(api_url, headers=headers_api, timeout=8)
            if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
                return resp.json()
        except Exception:
            pass
    return None

def ist_js_gerendert(soup):
    """Erkennt ob eine Seite JavaScript-Rendering benötigt (leere Templates)."""
    text = soup.get_text()
    # Vue/Angular Template-Syntax ohne gerenderte Inhalte
    if soup.find(string=re.compile(r"\[\[\s*\w+")) and len(text.strip()) < 5000:
        return True
    # Sehr wenig Text trotz vorhandener Body-Elemente
    body = soup.find("body")
    if body and len(body.get_text(strip=True)) < 500:
        return True
    return False

def lidl_extrahieren(soup, url=""):
    """Parser für lidl-kochen.de / lidl.de – Schema.org → API → HTML."""

    # 1. Schema.org versuchen
    schema = schema_org_extrahieren(soup)
    if schema and schema.get("titel") and schema.get("zutaten"):
        schema["quelle"] = "lidl+schema"
        return schema

    ergebnis = schema or {"titel": "", "beschreibung": "", "portionen": 4,
                          "zutaten": [], "anleitung": "", "quelle": "lidl"}
    ergebnis["quelle"] = "lidl"

    # Titel und Beschreibung immer aus Meta-Tags
    for attr in [{"property": "og:title"}]:
        meta = soup.find("meta", attrs=attr)
        if meta and meta.get("content") and not ergebnis.get("titel"):
            titel = meta["content"].strip()
            ergebnis["titel"] = re.sub(r"\s*[-–|]\s*(Rezept|Lidl).*$", "", titel, flags=re.I).strip()
    if not ergebnis.get("titel"):
        for sel in ["h1", "[class*=recipe-title]", "[class*=RecipeTitle]"]:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if t and not re.search(r"\[\[", t):
                    ergebnis["titel"] = t
                    break
    for attr in [{"property": "og:description"}, {"name": "description"}]:
        meta = soup.find("meta", attrs=attr)
        if meta and meta.get("content") and not ergebnis.get("beschreibung"):
            ergebnis["beschreibung"] = meta["content"][:300].strip()
            break

    # 2. API für Zutaten und Portionen
    api_data = lidl_api_abrufen(url) if url else None
    if api_data and isinstance(api_data, dict):
        for key in ["portions", "servings", "portionen", "persons"]:
            if key in api_data:
                try:
                    ergebnis["portionen"] = int(api_data[key])
                except: pass
                break
        zutaten_roh = api_data.get("ingredients", api_data.get("ingredientGroups", []))
        if isinstance(zutaten_roh, list):
            for z in zutaten_roh:
                if isinstance(z, dict):
                    name    = z.get("name", z.get("ingredientName", ""))
                    menge   = z.get("quantity", z.get("amount", 1)) or 1
                    einheit = z.get("unit", z.get("unitName", "Stück")) or "Stück"
                    if name:
                        ergebnis["zutaten"].append({"name": name, "menge": float(menge), "einheit": einheit})
                    for sub in z.get("ingredients", []):
                        if isinstance(sub, dict):
                            n = sub.get("name", sub.get("ingredientName", ""))
                            m = sub.get("quantity", sub.get("amount", 1)) or 1
                            e = sub.get("unit", sub.get("unitName", "Stück")) or "Stück"
                            if n:
                                ergebnis["zutaten"].append({"name": n, "menge": float(m), "einheit": e})
        if api_data.get("title") and not ergebnis.get("titel"):
            ergebnis["titel"] = api_data["title"]

    # 3. HTML-Fallback Zutaten (funktioniert nur bei SSR)
    if not ergebnis.get("zutaten"):
        for sel in [
            "[class*=ingredient-description]", "[class*=IngredientDescription]",
            "[class*=ingredient-item]",         "[class*=IngredientItem]",
            "[class*=ingredient-list] li",      "[class*=IngredientList] li",
            "[class*=ingredient] li",           "[data-testid*=ingredient]",
        ]:
            items = soup.select(sel)
            gefunden = []
            for item in items:
                if item.find(["li", "ul"]):
                    continue
                text = item.get_text(strip=True)
                # Vue-Template-Syntax überspringen
                if text and 2 < len(text) < 150 and "[[" not in text:
                    menge, einheit, name = zutat_parsen(text)
                    gefunden.append({"name": name, "menge": menge, "einheit": einheit})
            if gefunden:
                ergebnis["zutaten"] = gefunden
                break

    # 4. HTML-Fallback Anleitung
    if not ergebnis.get("anleitung"):
        schritte = []
        for sel in [
            ".preparation__step-content-text",
            "[class*=preparation-step]", "[class*=PreparationStep]",
            "[class*=step-description]", "[class*=recipe-step]",
            "ol[class*=step] li",        "ol[class*=instruction] li",
        ]:
            els = soup.select(sel)
            gefunden = [el.get_text(strip=True) for el in els
                        if len(el.get_text(strip=True)) > 10 and "[[" not in el.get_text()]
            if gefunden:
                schritte = gefunden
                break
        if schritte:
            ergebnis["anleitung"] = "\n".join(f"{i}. {s}" for i, s in enumerate(schritte, 1))

    # 5. Wenn Seite JS-gerendert ist und Zutaten fehlen: Hinweis setzen
    if not ergebnis.get("zutaten") and ist_js_gerendert(soup):
        ergebnis["_warnung"] = "js_rendered"

    return ergebnis

def rezept_von_url(url):
    """Hauptfunktion: Lädt URL und extrahiert Rezept."""
    if not url.startswith("http"):
        url = "https://" + url

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
    except requests.RequestException as e:
        return None, f"Seite konnte nicht geladen werden: {e}"

    soup = BeautifulSoup(resp.text, "html.parser")
    domain = url.lower()

    def beschreibung_ergaenzen(ergebnis, soup):
        """Ergänzt leere Beschreibung aus Meta-Tags."""
        if not ergebnis or not isinstance(ergebnis, dict):
            return ergebnis
        if not ergebnis.get("beschreibung"):
            for attr in [{"name": "description"}, {"property": "og:description"}]:
                meta = soup.find("meta", attrs=attr)
                if meta and meta.get("content"):
                    ergebnis["beschreibung"] = meta["content"][:300].strip()
                    break
        return ergebnis

    # 1. Seiten-spezifische Parser
    if "kaufland" in domain:
        ergebnis = kaufland_extrahieren(soup)
    elif "lidl" in domain:
        ergebnis = lidl_extrahieren(soup, url)
    else:
        # 2. Schema.org (funktioniert für ~80% aller Rezeptseiten)
        ergebnis = schema_org_extrahieren(soup)
        # 3. Fallback: HTML-Heuristiken (wenn Schema.org fehlt oder kein Titel)
        if not ergebnis or not ergebnis.get("titel"):
            print(f"Web-Import: Schema.org fehlgeschlagen für {domain}, versuche Fallback...", flush=True)
            ergebnis = fallback_extrahieren(soup, url)

    ergebnis = beschreibung_ergaenzen(ergebnis, soup)

    if not ergebnis or not ergebnis.get("titel"):
        return None, "Kein Rezept auf dieser Seite gefunden. Bitte prüfe ob die URL direkt zu einem Rezept führt."

    # Warnung wenn Seite JS-gerendert ist und Zutaten fehlen
    warnung = ergebnis.pop("_warnung", None)
    if warnung == "js_rendered" and not ergebnis.get("zutaten"):
        ergebnis["_hinweis"] = ("⚠️ Diese Seite lädt Inhalte per JavaScript – Zutaten konnten nicht "
                                "automatisch importiert werden. Bitte Zutaten manuell ergänzen.")

    return ergebnis, None

# ── Web Import Route ──────────────────────────────────────────────────────────

@app.route("/rezept/web-import", methods=["GET", "POST"])
def rezept_web_import():
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    ergebnis = None
    url = ""
    fehler = None
    debug = None
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if url:
            ergebnis, fehler = rezept_von_url(url)
            if fehler:
                flash(fehler, "danger")
            if ergebnis:
                debug = {
                    "quelle": ergebnis.get("quelle", "?"),
                    "titel": "✅" if ergebnis.get("titel") else "❌",
                    "beschreibung": "✅" if ergebnis.get("beschreibung") else "❌",
                    "zutaten": f"✅ {len(ergebnis.get('zutaten', []))} Stück" if ergebnis.get("zutaten") else "❌",
                    "anleitung": f"✅ {len(ergebnis.get('anleitung',''))} Zeichen" if ergebnis.get("anleitung") else "❌",
                }
        else:
            flash("Bitte eine URL eingeben.", "danger")
    return render_template("rezept_web_import.html",
        ergebnis=ergebnis, url=url, fehler=fehler,
        debug=debug, einheiten=EINHEITEN, einkauf_count=einkauf_count)

# ── Einstellungen Route ────────────────────────────────────────────────────────

@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    s = get_settings()
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    if request.method == "POST":
        s.sprache = request.form.get("sprache", "de")
        s.waehrung = request.form.get("waehrung", "EUR")
        s.theme = request.form.get("theme", "light")
        s.farbe = request.form.get("farbe", "blau")
        db.session.commit()
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("einstellungen"))
    return render_template("einstellungen.html",
        settings=s, einkauf_count=einkauf_count)

# ── HA Sensor Integration ─────────────────────────────────────────────────────

def ha_sensoren_aktualisieren():
    """Schreibt Vorrats-Statistiken als Sensoren in Home Assistant."""
    import threading, time

    SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
    HA_URL = "http://supervisor/core/api"

    if not SUPERVISOR_TOKEN:
        return  # Nicht in HA-Umgebung

    def sensor_setzen(entity_id, state, attributes=None):
        try:
            resp = requests.post(
                f"{HA_URL}/states/{entity_id}",
                headers={
                    "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"state": str(state), "attributes": attributes or {}},
                timeout=5
            )
            resp.raise_for_status()  # Wirft Exception bei HTTP 4xx/5xx
        except requests.HTTPError as e:
            print(f"HA Sensor HTTP-Fehler ({entity_id}): {e.response.status_code} {e.response.text[:200]}", flush=True)
        except Exception as e:
            print(f"HA Sensor Fehler ({entity_id}): {e}", flush=True)

    def update_loop():
        time.sleep(10)  # Warten bis Flask gestartet ist
        while True:
            try:
                with app.app_context():
                    heute = date.today()
                    in_7_tagen = heute + timedelta(days=7)
                    in_3_tagen = heute + timedelta(days=3)

                    alle = Produkt.query.all()

                    # Abgelaufen
                    abgelaufen = [p for p in alle if p.mhd and p.mhd < heute]
                    # Bald ablaufend (≤7 Tage)
                    bald = [p for p in alle if p.mhd and heute <= p.mhd <= in_7_tagen]
                    # Kritisch (≤3 Tage)
                    kritisch = [p for p in alle if p.mhd and heute <= p.mhd <= in_3_tagen]
                    # Unter Mindestmenge
                    unter_min = [p for p in alle if p.menge < p.mindestmenge]

                    # Einkaufsliste (offene Artikel)
                    einkauf_offen = Einkaufsliste.query.filter_by(erledigt=False).count()

                    # Sensor: Abgelaufen
                    sensor_setzen("sensor.vorrat_abgelaufen", len(abgelaufen), {
                        "friendly_name": "Vorrat: Abgelaufen",
                        "unit_of_measurement": "Produkte",
                        "state_class": "measurement",
                        "icon": "mdi:food-off",
                        "produkte": [{"name": p.name, "mhd": str(p.mhd)} for p in abgelaufen[:10]]
                    })

                    # Sensor: Bald ablaufend
                    sensor_setzen("sensor.vorrat_bald_ablaufend", len(bald), {
                        "friendly_name": "Vorrat: Bald ablaufend",
                        "unit_of_measurement": "Produkte",
                        "state_class": "measurement",
                        "icon": "mdi:food-clock",
                        "produkte": [{"name": p.name, "mhd": str(p.mhd), "tage": (p.mhd - heute).days} for p in bald[:10]]
                    })

                    # Sensor: Kritisch (≤3 Tage)
                    sensor_setzen("sensor.vorrat_kritisch", len(kritisch), {
                        "friendly_name": "Vorrat: Kritisch (≤3 Tage)",
                        "unit_of_measurement": "Produkte",
                        "state_class": "measurement",
                        "icon": "mdi:food-alert",
                        "produkte": [{"name": p.name, "mhd": str(p.mhd), "tage": (p.mhd - heute).days} for p in kritisch[:10]]
                    })

                    # Sensor: Unter Mindestmenge
                    sensor_setzen("sensor.vorrat_unter_mindestmenge", len(unter_min), {
                        "friendly_name": "Vorrat: Unter Mindestmenge",
                        "unit_of_measurement": "Produkte",
                        "state_class": "measurement",
                        "icon": "mdi:package-down",
                        "produkte": [{"name": p.name, "menge": p.menge, "mindestmenge": p.mindestmenge, "einheit": p.einheit} for p in unter_min[:10]]
                    })

                    # Sensor: Gesamt Produkte
                    sensor_setzen("sensor.vorrat_gesamt", len(alle), {
                        "friendly_name": "Vorrat: Gesamt",
                        "unit_of_measurement": "Produkte",
                        "state_class": "measurement",
                        "icon": "mdi:food-apple",
                    })

                    # Sensor: Einkaufsliste (offene Artikel)
                    sensor_setzen("sensor.vorrat_einkaufsliste", einkauf_offen, {
                        "friendly_name": "Vorrat: Einkaufsliste offen",
                        "unit_of_measurement": "Artikel",
                        "state_class": "measurement",
                        "icon": "mdi:cart",
                    })

                    print(f"HA Sensoren aktualisiert: {len(abgelaufen)} abgelaufen, {len(bald)} bald, {len(unter_min)} unter Min., {einkauf_offen} Einkauf offen.", flush=True)

            except Exception as e:
                print(f"HA Update Fehler: {e}", flush=True)

            time.sleep(300)  # alle 5 Minuten aktualisieren

    t = threading.Thread(target=update_loop, daemon=True)
    t.start()

def db_migrieren():
    """Erstellt fehlende Tabellen und Spalten ohne Datenverlust."""
    with app.app_context():
        db.create_all()
        import sqlite3 as _sq
        conn = _sq.connect(DB_PATH)
        cur = conn.cursor()

        def spalte_existiert(tabelle, spalte):
            cur.execute(f"PRAGMA table_info({tabelle})")
            return any(row[1] == spalte for row in cur.fetchall())

        def tabelle_existiert(tabelle):
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabelle,))
            return cur.fetchone() is not None

        # einkaufs_liste
        if not tabelle_existiert("einkaufs_liste"):
            cur.execute("""CREATE TABLE einkaufs_liste (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                erstellt DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            cur.execute("INSERT INTO einkaufs_liste (name) VALUES ('Einkauf')")
            conn.commit()

        # einkaufsliste neue Spalten
        if tabelle_existiert("einkaufsliste"):
            for spalte, typ in [
                ("liste_id", "INTEGER"),
                ("einzelpreis", "FLOAT"),
                ("in_bestand", "BOOLEAN DEFAULT 0"),
                ("position", "INTEGER DEFAULT 0"),
            ]:
                if not spalte_existiert("einkaufsliste", spalte):
                    cur.execute(f"ALTER TABLE einkaufsliste ADD COLUMN {spalte} {typ}")
                    if spalte == "liste_id":
                        cur.execute("UPDATE einkaufsliste SET liste_id = (SELECT id FROM einkaufs_liste LIMIT 1)")
                    conn.commit()

        # einstellungen
        if not tabelle_existiert("einstellungen"):
            cur.execute("""CREATE TABLE einstellungen (
                id INTEGER PRIMARY KEY,
                sprache VARCHAR(5) DEFAULT 'de',
                waehrung VARCHAR(5) DEFAULT 'EUR',
                theme VARCHAR(20) DEFAULT 'light',
                farbe VARCHAR(20) DEFAULT 'blau'
            )""")
            cur.execute("INSERT INTO einstellungen (sprache, waehrung, theme, farbe) VALUES ('de','EUR','light','blau')")
            conn.commit()

        for spalte, typ in [
            ("theme", "VARCHAR(20) DEFAULT 'light'"),
            ("farbe", "VARCHAR(20) DEFAULT 'blau'"),
        ]:
            if tabelle_existiert("einstellungen") and not spalte_existiert("einstellungen", spalte):
                cur.execute(f"ALTER TABLE einstellungen ADD COLUMN {spalte} {typ}")
                conn.commit()

        # produkt neue Spalten
        if tabelle_existiert("produkt") and not spalte_existiert("produkt", "angebrochen"):
            cur.execute("ALTER TABLE produkt ADD COLUMN angebrochen BOOLEAN DEFAULT 0")
            conn.commit()
        if tabelle_existiert("produkt") and not spalte_existiert("produkt", "gebinde"):
            cur.execute("ALTER TABLE produkt ADD COLUMN gebinde INTEGER DEFAULT 0")
            conn.commit()

        # rezept neue Spalten
        if tabelle_existiert("rezept") and not spalte_existiert("rezept", "quell_url"):
            cur.execute("ALTER TABLE rezept ADD COLUMN quell_url VARCHAR(500) DEFAULT ''")
            conn.commit()

        conn.close()

if __name__ == "__main__":
    db_migrieren()
    with app.app_context():
        db.engine.dispose()
    ha_sensoren_aktualisieren()
    app.run(host="0.0.0.0", port=5000, debug=False)
