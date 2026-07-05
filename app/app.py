from flask import Flask, render_template, request, redirect, url_for, flash, g, session, send_from_directory
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime, timedelta
import os, re, pdfplumber, tempfile, json, requests, sqlite3, threading, time, sys, signal
from bs4 import BeautifulSoup
from translations import TRANSLATIONS, CURRENCIES, LANGUAGES, get_translation, format_currency

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vorrat-geheim")

DB_PATH = os.environ.get("DB_PATH", "/tmp/vorrat.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB Upload-Limit

# Produktbilder neben der DB ablegen (im Add-on /share/vorratsverwaltung/bilder)
BILDER_DIR = os.path.join(os.path.dirname(DB_PATH) or ".", "bilder")
os.makedirs(BILDER_DIR, exist_ok=True)
ERLAUBTE_BILD_EXT = {"jpg", "jpeg", "png", "gif", "webp"}

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
    notiz = db.Column(db.Text, default="")
    bild = db.Column(db.String(200), default="")          # Dateiname in /share/.../bilder
    barcode = db.Column(db.String(50), default="")        # EAN für Open Food Facts
    kcal = db.Column(db.Float, nullable=True)              # Nährwerte je 100 g/ml
    eiweiss = db.Column(db.Float, nullable=True)
    fett = db.Column(db.Float, nullable=True)
    kohlenhydrate = db.Column(db.Float, nullable=True)

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
    kalender_entity = db.Column(db.String(100), default="")

class Stammdaten(db.Model):
    """Verwaltbare Listen: Lagerorte, Kategorien, Einheiten (typ + name)."""
    id = db.Column(db.Integer, primary_key=True)
    typ = db.Column(db.String(20), nullable=False)   # lagerort | kategorie | einheit
    name = db.Column(db.String(100), nullable=False)
    __table_args__ = (db.UniqueConstraint("typ", "name", name="uq_stammdaten"),)

class Essensplan(db.Model):
    """Geplante Mahlzeit an einem Tag (Frühstück/Mittag/Abend)."""
    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, nullable=False)
    mahlzeit = db.Column(db.String(20), nullable=False)  # fruehstueck, mittag, abend
    rezept_id = db.Column(db.Integer, db.ForeignKey("rezept.id", ondelete="SET NULL"), nullable=True)
    freitext = db.Column(db.String(200), default="")
    personen = db.Column(db.Integer, nullable=True)  # geplante Personenzahl
    erstellt = db.Column(db.DateTime, default=datetime.utcnow)
    cal_synced_at = db.Column(db.DateTime, nullable=True)  # zuletzt in HA-Kalender geschrieben
    rezept = db.relationship("Rezept", lazy=True)
    __table_args__ = (db.UniqueConstraint("datum", "mahlzeit", name="uq_essensplan_slot"),)

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
    # Sortierung – per Session merken, damit sie bei +/-, Filter etc. erhalten bleibt
    sort = request.args.get("sort")
    if sort in ("standard", "name", "menge", "mhd"):
        session["sort"] = sort
    else:
        sort = session.get("sort", "standard")
    if sort == "name":
        produkte = sorted(produkte, key=lambda p: (p.menge <= 0, p.name.lower()))
    elif sort == "menge":
        produkte = sorted(produkte, key=lambda p: p.menge)
    elif sort == "mhd":
        produkte = sorted(produkte, key=lambda p: (p.mhd is None, p.mhd or date.max, p.name.lower()))
    else:  # standard: nach Kategorie, Nullbestände ans Ende
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
        sort=sort,
        einkauf_count=einkauf_count,
        alle_listen=alle_listen,
        heute=heute
    )

# ── Routen: Produkte ───────────────────────────────────────────────────────────

def vorhandene_lagerorte():
    """Liste aller bereits verwendeten Lagerorte (für Auswahlvorschläge)."""
    return sorted({p.lagerort for p in Produkt.query.all() if p.lagerort})

# ── Stammdaten (Lagerorte / Kategorien / Einheiten) ─────────────────────────────

STAMM_FELD = {"lagerort": Produkt.lagerort, "kategorie": Produkt.kategorie, "einheit": Produkt.einheit}

def stammdaten_liste(typ):
    """Sortierte Namensliste eines Typs (für Dropdowns/Datalists)."""
    return [s.name for s in Stammdaten.query.filter_by(typ=typ).order_by(Stammdaten.name).all()]

def stammdaten_sicherstellen(typ, name):
    """Legt einen Wert an, falls er noch nicht existiert (z.B. neuer Lagerort beim Speichern)."""
    name = (name or "").strip()
    if name and typ in STAMM_FELD and not Stammdaten.query.filter_by(typ=typ, name=name).first():
        db.session.add(Stammdaten(typ=typ, name=name))

def stammdaten_mit_anzahl(typ):
    """Liste {name, anzahl} – anzahl = wie viele Produkte den Wert nutzen."""
    feld = STAMM_FELD[typ]
    out = []
    for s in Stammdaten.query.filter_by(typ=typ).order_by(Stammdaten.name).all():
        out.append({"name": s.name, "anzahl": Produkt.query.filter(feld == s.name).count()})
    return out

@app.route("/stammdaten/neu", methods=["POST"])
def stammdaten_neu():
    typ = request.form.get("typ", "")
    name = request.form.get("name", "").strip()
    if typ in STAMM_FELD and name:
        if Stammdaten.query.filter_by(typ=typ, name=name).first():
            flash(f"'{name}' existiert bereits.", "info")
        else:
            db.session.add(Stammdaten(typ=typ, name=name))
            db.session.commit()
            flash(f"'{name}' hinzugefügt.", "success")
    return redirect(url_for("einstellungen") + "#verwaltung")

@app.route("/stammdaten/umbenennen", methods=["POST"])
def stammdaten_umbenennen():
    typ = request.form.get("typ", "")
    alt = request.form.get("alt", "").strip()
    neu = request.form.get("neu", "").strip()
    if typ not in STAMM_FELD or not alt or not neu or alt == neu:
        return redirect(url_for("einstellungen") + "#verwaltung")
    feld = STAMM_FELD[typ]
    # Produkte umstellen (führt Dubletten zusammen)
    anzahl = Produkt.query.filter(feld == alt).update({feld.key: neu}, synchronize_session=False)
    # Stammdaten: alten Eintrag entfernen, neuen sicherstellen
    alt_row = Stammdaten.query.filter_by(typ=typ, name=alt).first()
    if alt_row:
        db.session.delete(alt_row)
    stammdaten_sicherstellen(typ, neu)
    db.session.commit()
    flash(f"'{alt}' → '{neu}' ({anzahl} Produkt(e) umgestellt).", "success")
    return redirect(url_for("einstellungen") + "#verwaltung")

@app.route("/stammdaten/loeschen", methods=["POST"])
def stammdaten_loeschen():
    typ = request.form.get("typ", "")
    name = request.form.get("name", "").strip()
    if typ not in STAMM_FELD or not name:
        return redirect(url_for("einstellungen") + "#verwaltung")
    anzahl = Produkt.query.filter(STAMM_FELD[typ] == name).count()
    if anzahl > 0:
        flash(f"'{name}' wird noch von {anzahl} Produkt(en) genutzt – nicht gelöscht.", "danger")
    else:
        row = Stammdaten.query.filter_by(typ=typ, name=name).first()
        if row:
            db.session.delete(row)
            db.session.commit()
        flash(f"'{name}' gelöscht.", "success")
    return redirect(url_for("einstellungen") + "#verwaltung")

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
        # Neue Werte als Stammdaten sichern (damit sie verwaltbar sind)
        stammdaten_sicherstellen("lagerort", p.lagerort)
        stammdaten_sicherstellen("kategorie", p.kategorie)
        stammdaten_sicherstellen("einheit", p.einheit)
        db.session.commit()
        # Gebinde direkt per SQL speichern
        gebinde_val = int(request.form.get("gebinde", 0) or 0)
        if gebinde_val > 0:
            with db.engine.connect() as conn:
                conn.execute(db.text("UPDATE produkt SET gebinde=:g WHERE id=:id"), {"g": gebinde_val, "id": p.id})
                conn.commit()
        flash(f"'{p.name}' wurde hinzugefügt.", "success")
        return redirect(url_for("index"))
    return render_template("produkt_form.html", produkt=None,
                           lagerorte=stammdaten_liste("lagerort"),
                           kategorien=stammdaten_liste("kategorie"),
                           einheiten=stammdaten_liste("einheit"))

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
        # Neue Werte als Stammdaten sichern
        stammdaten_sicherstellen("lagerort", p.lagerort)
        stammdaten_sicherstellen("kategorie", p.kategorie)
        stammdaten_sicherstellen("einheit", p.einheit)
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
                           zurueck_kat=zurueck_kat, zurueck_ort=zurueck_ort,
                           lagerorte=stammdaten_liste("lagerort"),
                           kategorien=stammdaten_liste("kategorie"),
                           einheiten=stammdaten_liste("einheit"))

@app.route("/produkt/<int:id>/angebrochen", methods=["POST"])
def produkt_angebrochen(id):
    with db.engine.connect() as conn:
        row = conn.execute(db.text("SELECT angebrochen FROM produkt WHERE id=:id"), {"id": id}).fetchone()
        if row:
            if row[0]:
                conn.execute(db.text("UPDATE produkt SET angebrochen=0 WHERE id=:id"), {"id": id})
            else:
                # Beim Anbrechen Füllstand auf 100 % setzen
                conn.execute(db.text("UPDATE produkt SET angebrochen=1, angebrochen_prozent=100 WHERE id=:id"), {"id": id})
            conn.commit()
    kat = request.args.get("kategorie") or None
    ort = request.args.get("lagerort") or None
    return redirect(url_for("index", kategorie=kat, lagerort=ort))

@app.route("/produkt/<int:id>/anbruch", methods=["POST"])
def produkt_anbruch(id):
    """Angebrochen-Balken: anbrechen (start), schließen (stop) oder Füllstand setzen (set).
    Rutscht der Füllstand unter 15 %, gilt die Packung als aufgebraucht:
    1 Einheit wird abgezogen und der Anbruch geschlossen (leuchtet nicht mehr)."""
    p = Produkt.query.get_or_404(id)
    aktion = request.form.get("aktion", "set")
    with db.engine.connect() as conn:
        if aktion == "start":
            conn.execute(db.text("UPDATE produkt SET angebrochen=1, angebrochen_prozent=100 WHERE id=:id"), {"id": id})
        elif aktion == "stop":
            conn.execute(db.text("UPDATE produkt SET angebrochen=0 WHERE id=:id"), {"id": id})
        else:  # set (Schieberegler)
            try:
                proz = int(round(float(request.form.get("prozent", 100))))
            except (TypeError, ValueError):
                proz = 100
            proz = max(0, min(100, proz))
            if proz < 15:
                neue_menge = max(0, (p.menge or 0) - 1)
                conn.execute(db.text(
                    "UPDATE produkt SET menge=:m, angebrochen=0, angebrochen_prozent=100 WHERE id=:id"),
                    {"m": neue_menge, "id": id})
                flash(f"Angebrochene Packung aufgebraucht – 1 {p.einheit or 'Stück'} abgezogen.", "info")
            else:
                conn.execute(db.text(
                    "UPDATE produkt SET angebrochen=1, angebrochen_prozent=:p WHERE id=:id"),
                    {"p": proz, "id": id})
        conn.commit()
    return redirect(url_for("produkt_detail", id=id))

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

def render_produkt_detail(id, **extra):
    """Baut die Produkt-Detailseite (auch für OFF-Suchergebnisse wiederverwendet)."""
    p = Produkt.query.get_or_404(id)
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    # angebrochen/gebinde/anbruch-% direkt per SQL (wie in der Übersicht)
    try:
        with db.engine.connect() as conn:
            row = conn.execute(db.text("SELECT angebrochen, gebinde, angebrochen_prozent FROM produkt WHERE id=:id"), {"id": id}).fetchone()
        p.ist_angebrochen = bool(row[0]) if row else False
        p.gebinde_wert = int(row[1] or 0) if row else 0
        p.anbruch_prozent = int(row[2]) if (row and row[2] is not None) else 100
    except Exception:
        p.ist_angebrochen = False
        p.gebinde_wert = 0
        p.anbruch_prozent = 100
    p.status = mhd_status(p.mhd)
    p.tage_bis_mhd = (p.mhd - date.today()).days if p.mhd else None
    # Verwendet in Rezepten (Namens-Abgleich)
    rezepte_mit = []
    for r in Rezept.query.order_by(Rezept.name).all():
        for z in r.zutaten:
            zn = (z.name or "").lower()
            pn = p.name.lower()
            if zn and (zn in pn or pn in zn):
                rezepte_mit.append(r)
                break
    listen = EinkaufsListe.query.order_by(EinkaufsListe.erstellt.desc()).all()
    return render_template("produkt_detail.html", p=p, einkauf_count=einkauf_count,
                           rezepte_mit=rezepte_mit, listen=listen, **extra)

@app.route("/produkt/<int:id>")
def produkt_detail(id):
    return render_produkt_detail(id)

@app.route("/produkt/<int:id>/detail-speichern", methods=["POST"])
def produkt_detail_speichern(id):
    p = Produkt.query.get_or_404(id)
    p.notiz = request.form.get("notiz", "").strip()

    def _zahl(name):
        v = request.form.get(name, "").strip().replace(",", ".")
        try:
            return float(v) if v else None
        except ValueError:
            return None
    p.kcal = _zahl("kcal")
    p.eiweiss = _zahl("eiweiss")
    p.fett = _zahl("fett")
    p.kohlenhydrate = _zahl("kohlenhydrate")

    # Bild entfernen
    if request.form.get("bild_entfernen") and p.bild:
        try:
            os.remove(os.path.join(BILDER_DIR, p.bild))
        except OSError:
            pass
        p.bild = ""

    # Bild-Upload
    datei = request.files.get("bild")
    if datei and datei.filename:
        ext = datei.filename.rsplit(".", 1)[-1].lower() if "." in datei.filename else ""
        if ext in ERLAUBTE_BILD_EXT:
            dateiname = f"produkt_{id}.{ext}"
            datei.save(os.path.join(BILDER_DIR, dateiname))
            # vorhandene Bilder mit anderer Endung aufräumen
            for e in ERLAUBTE_BILD_EXT:
                if e != ext:
                    alt = os.path.join(BILDER_DIR, f"produkt_{id}.{e}")
                    if os.path.exists(alt):
                        try: os.remove(alt)
                        except OSError: pass
            p.bild = dateiname
        else:
            flash("Bildformat nicht unterstützt (erlaubt: jpg, png, gif, webp).", "danger")

    db.session.commit()
    flash("Produkt-Details gespeichert.", "success")
    return redirect(url_for("produkt_detail", id=id))

@app.route("/produkt/<int:id>/bild")
def produkt_bild(id):
    p = Produkt.query.get_or_404(id)
    if p.bild and os.path.exists(os.path.join(BILDER_DIR, p.bild)):
        return send_from_directory(BILDER_DIR, p.bild)
    from flask import abort
    abort(404)

def openfoodfacts_abrufen(barcode):
    """Holt Name, Bild-URL und Nährwerte (je 100 g) von Open Food Facts."""
    barcode = re.sub(r"\D", "", barcode or "")
    if not barcode:
        return None, "Bitte einen gültigen Barcode (nur Ziffern) eingeben."
    try:
        r = requests.get(
            f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
            headers={"User-Agent": "HA-Vorratsverwaltung (github.com/jenser1/ha-vorrat-addon)"},
            timeout=(4, 10))
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, f"Open Food Facts nicht erreichbar: {e}"
    if data.get("status") != 1 or not data.get("product"):
        return None, f"Barcode {barcode} nicht in Open Food Facts gefunden."
    prod = data["product"]
    nutr = prod.get("nutriments", {})

    def _n(key):
        v = nutr.get(key)
        try:
            return round(float(v), 1) if v not in (None, "") else None
        except (ValueError, TypeError):
            return None
    return {
        "barcode": barcode,
        "name": prod.get("product_name_de") or prod.get("product_name") or "",
        "marke": (prod.get("brands") or "").split(",")[0].strip(),
        "bild_url": prod.get("image_front_url") or prod.get("image_url") or "",
        "kcal": _n("energy-kcal_100g"),
        "eiweiss": _n("proteins_100g"),
        "fett": _n("fat_100g"),
        "kohlenhydrate": _n("carbohydrates_100g"),
    }, None

def openfoodfacts_suche(begriff):
    """Sucht Produkte per Name in Open Food Facts; gibt Trefferliste zurück.
    Nutzt den stabilen Such-Dienst (search.openfoodfacts.org), Legacy als Fallback."""
    begriff = (begriff or "").strip()
    if not begriff:
        return [], "Bitte einen Suchbegriff eingeben."
    UA = {"User-Agent": "HA-Vorratsverwaltung (github.com/jenser1/ha-vorrat-addon)"}
    felder = "code,product_name,product_name_de,brands,image_front_url,image_front_thumb_url,image_url,nutriments"

    produkte = None
    letzter_fehler = ""
    # 1. Neuer, stabiler Such-Dienst
    try:
        r = requests.get("https://search.openfoodfacts.org/search",
                         params={"q": begriff, "page_size": 8, "fields": felder},
                         headers=UA, timeout=(4, 12))
        r.raise_for_status()
        produkte = r.json().get("hits", [])
    except Exception as e:
        letzter_fehler = str(e)
    # 2. Fallback: Legacy-Suche
    if produkte is None:
        try:
            r = requests.get("https://world.openfoodfacts.org/cgi/search.pl",
                             params={"search_terms": begriff, "search_simple": 1, "action": "process",
                                     "json": 1, "page_size": 8, "fields": felder},
                             headers=UA, timeout=(4, 12))
            r.raise_for_status()
            produkte = r.json().get("products", [])
        except Exception as e:
            return [], f"Open Food Facts nicht erreichbar: {letzter_fehler or e}"

    treffer = []
    for prod in produkte:
        code = prod.get("code")
        name = prod.get("product_name_de") or prod.get("product_name") or ""
        if not code or not name:
            continue
        kcal = (prod.get("nutriments") or {}).get("energy-kcal_100g")
        marke_roh = prod.get("brands") or ""
        if isinstance(marke_roh, list):
            marke = marke_roh[0].strip() if marke_roh else ""
        else:
            marke = marke_roh.split(",")[0].strip()
        treffer.append({
            "code": code,
            "name": name,
            "marke": marke,
            "bild": prod.get("image_front_thumb_url") or prod.get("image_front_url") or prod.get("image_url") or "",
            "kcal": kcal,
        })
        if len(treffer) >= 6:
            break
    if not treffer:
        return [], f"Keine Treffer für '{begriff}'."
    return treffer, None

@app.route("/produkt/<int:id>/off-suche", methods=["POST"])
def produkt_off_suche(id):
    Produkt.query.get_or_404(id)
    begriff = request.form.get("suche", "").strip()
    treffer, fehler = openfoodfacts_suche(begriff)
    if fehler:
        flash(fehler, "danger")
        return redirect(url_for("produkt_detail", id=id))
    return render_produkt_detail(id, off_treffer=treffer, off_begriff=begriff)

@app.route("/produkt/<int:id>/off-import", methods=["POST"])
def produkt_off_import(id):
    p = Produkt.query.get_or_404(id)
    daten, fehler = openfoodfacts_abrufen(request.form.get("barcode", ""))
    if fehler:
        flash(fehler, "danger")
        return redirect(url_for("produkt_detail", id=id))

    p.barcode = daten["barcode"]
    for feld in ("kcal", "eiweiss", "fett", "kohlenhydrate"):
        if daten[feld] is not None:
            setattr(p, feld, daten[feld])

    bild_ok = True
    if daten["bild_url"]:
        try:
            ir = requests.get(daten["bild_url"], headers=HEADERS, timeout=(4, 12))
            ir.raise_for_status()
            m = re.search(r"\.(jpg|jpeg|png|gif|webp)(?:\.|\?|$)", daten["bild_url"], re.I)
            ext = (m.group(1).lower() if m else "jpg")
            dateiname = f"produkt_{id}.{ext}"
            with open(os.path.join(BILDER_DIR, dateiname), "wb") as f:
                f.write(ir.content)
            for e in ERLAUBTE_BILD_EXT:
                if e != ext:
                    alt = os.path.join(BILDER_DIR, f"produkt_{id}.{e}")
                    if os.path.exists(alt):
                        try: os.remove(alt)
                        except OSError: pass
            p.bild = dateiname
        except Exception:
            bild_ok = False

    db.session.commit()
    marke = f" ({daten['marke']})" if daten["marke"] else ""
    if bild_ok:
        flash(f"✅ Nährwerte & Bild von Open Food Facts übernommen{marke}.", "success")
    else:
        flash(f"Nährwerte übernommen{marke} – Bild konnte nicht geladen werden.", "warning")
    return redirect(url_for("produkt_detail", id=id))

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
    # Aus der Detailseite aufgerufen → dorthin zurück
    if request.args.get("von") == "detail" or request.form.get("von") == "detail":
        return redirect(url_for("produkt_detail", id=id))
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
        einkauf_count=einkauf_count, listen=listen,
        mahlzeiten=MAHLZEITEN, heute=date.today())

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

def rezept_zur_liste(rezept, liste_id=None, faktor=1.0):
    """Fügt fehlende (nach faktor skalierte) Zutaten eines Rezepts zu einer Liste hinzu.
    Gibt (anzahl_hinzugefügt, liste) zurück."""
    if liste_id:
        liste = EinkaufsListe.query.get(int(liste_id))
    else:
        liste = EinkaufsListe.query.order_by(EinkaufsListe.erstellt).first()
    if not liste:
        liste = EinkaufsListe(name="Einkauf")
        db.session.add(liste)
        db.session.flush()
    hinzugefuegt = 0
    for z in rezept.zutaten:
        benoetigt = (z.menge or 0) * faktor
        p = Produkt.query.filter(Produkt.name.ilike(f"%{z.name}%")).first()
        if not p or p.menge < benoetigt:
            existiert = Einkaufsliste.query.filter_by(liste_id=liste.id, name=z.name, erledigt=False).first()
            if not existiert:
                fehlend = benoetigt - (p.menge if p else 0)
                e = Einkaufsliste(liste_id=liste.id, name=z.name,
                    menge=round(max(0, fehlend), 2), einheit=z.einheit)
                db.session.add(e)
                hinzugefuegt += 1
    return hinzugefuegt, liste

@app.route("/rezept/<int:id>/einkaufen", methods=["POST"])
def rezept_einkaufen(id):
    r = Rezept.query.get_or_404(id)
    hinzugefuegt, liste = rezept_zur_liste(r, request.form.get("liste_id"))
    db.session.commit()
    flash(f"{hinzugefuegt} fehlende Zutaten zur Liste '{liste.name}' hinzugefügt.", "success")
    return redirect(url_for("rezept_detail", id=id))

@app.route("/rezept/<int:id>/zum-essensplan", methods=["POST"])
def rezept_zum_essensplan(id):
    r = Rezept.query.get_or_404(id)
    try:
        datum = datetime.strptime(request.form.get("datum", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Ungültiges Datum.", "danger")
        return redirect(url_for("rezept_detail", id=id))
    mahlzeit = request.form.get("mahlzeit", "")
    if mahlzeit not in dict(MAHLZEITEN):
        flash("Ungültige Mahlzeit.", "danger")
        return redirect(url_for("rezept_detail", id=id))
    try:
        personen = int(request.form.get("personen", "") or 0) or None
    except ValueError:
        personen = None

    eintrag = Essensplan.query.filter_by(datum=datum, mahlzeit=mahlzeit).first()
    if eintrag:
        eintrag.rezept_id = r.id
        eintrag.freitext = ""
        eintrag.personen = personen
    else:
        eintrag = Essensplan(datum=datum, mahlzeit=mahlzeit, rezept_id=r.id, personen=personen)
        db.session.add(eintrag)
    db.session.commit()

    # Auto-Sync in den HA-Kalender
    ent = (get_settings().kalender_entity or "").strip()
    if ent and kalender_eintrag_schreiben(ent, eintrag):
        eintrag.cal_synced_at = datetime.utcnow()
        db.session.commit()

    label = dict(MAHLZEITEN).get(mahlzeit, mahlzeit)
    flash(f"'{r.name}' für {datum.strftime('%d.%m.%Y')} ({label}) eingeplant.", "success")
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

def _einheit_norm(e):
    """Normalisiert Einheiten-Schreibweisen auf die Dropdown-Werte."""
    e = (e or "").strip().rstrip(".")
    mapping = {"st": "Stück", "stk": "Stück", "stück": "Stück", "pkg": "Packung"}
    return mapping.get(e.lower(), e)

def zutat_parsen(text):
    """Zerlegt einen Zutaten-String in Menge, Einheit und Name."""
    text = html_bereinigen(text).strip()
    einheiten = ["g", "kg", "ml", "l", "EL", "TL", "Prise", "Bund", "Stück",
                 "Dose", "Packung", "Pkg", "Tasse", "Becher", "Scheibe",
                 "Scheiben", "Zehe", "Zehen", "cm", "tbsp", "tsp", "cup",
                 "oz", "lb", "handful", "bunch", "St", "St.", "Stk", "Stk."]

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
                return menge_parsen(m.group(1)), _einheit_norm(m.group(2)), name_teil
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
        return menge_parsen(m.group(1)), _einheit_norm(m.group(2)), m.group(3).strip()
    # Nur Zahl am Anfang
    m2 = re.match(r"^([\d½¼¾⅓⅔][\d\s\/,\.]*?)\s+(.+)$", text)
    if m2:
        return menge_parsen(m2.group(1)), "Stück", m2.group(2).strip()

    # Nachgestellte Menge (Lidl-Format): "Frühlingszwiebeln 3 St." / "Cherrytomaten 300 g"
    m3 = re.match(
        r"^(.+?)\s+([\d½¼¾⅓⅔][\d\s\/,\.]*)\s*("
        + "|".join(re.escape(e) for e in einheiten)
        + r")\.?\s*$", text, re.I)
    if m3:
        return menge_parsen(m3.group(2)), _einheit_norm(m3.group(3)), m3.group(1).strip()

    # Nachgestellte einheit-ohne-Zahl: "Salz Prise" / "Chiliflocken Prise"
    m4 = re.match(r"^(.+?)\s+(Prise|Bund|Handvoll|etwas|nach Geschmack)\.?\s*$", text, re.I)
    if m4:
        return 1.0, m4.group(2), m4.group(1).strip()

    return 1.0, "Stück", text

def schema_org_extrahieren(soup):
    """Extrahiert Rezept aus Schema.org JSON-LD – funktioniert für ~80% aller Rezeptseiten."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            roh = tag.string or tag.get_text() or ""
            # strict=False erlaubt Steuerzeichen (\r\n) im JSON – z.B. Lidl
            # hat unescaped Zeilenumbrüche in recipeInstructions, was sonst crasht
            data = json.loads(roh, strict=False)

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

        # Kaufland-Microdata: <span itemprop="recipeInstructions" content="...">
        # Der Schritt-Text steht im content-Attribut, nicht im Element-Text
        microdata = soup.select("[itemprop=recipeInstructions][content]")
        md_texte = []
        for sp in microdata:
            txt = (sp.get("content") or "").strip()
            txt = re.sub(r"^\d+[\.\)]\s*", "", txt)  # führende "1. " entfernen
            if len(txt) > 20:
                md_texte.append(txt)
        if md_texte:
            schritte = md_texte

        # Spezifische CSS-Selektoren (Kaufland: cooking-description enthält den Text)
        if not schritte:
            for sel in [
                "[class*=cooking-description]",
                "[class*=preparation-step] p", "[class*=preparation-step]",
                "[class*=recipe-step] p",       "[class*=recipe-step]",
                "[class*=cooking-step] p",       "[class*=step-description]",
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

# ── Essensplaner Routen ────────────────────────────────────────────────────────

MAHLZEITEN = [
    ("fruehstueck", "🌅 Frühstück"),
    ("mittag",      "☀️ Mittag"),
    ("abend",       "🌙 Abend"),
]

@app.route("/essensplan")
def essensplan():
    # Wochen-Offset (0 = aktuelle Woche)
    try:
        woche = int(request.args.get("woche", 0))
    except ValueError:
        woche = 0

    heute = date.today()
    # Montag der Zielwoche
    montag = heute - timedelta(days=heute.weekday()) + timedelta(weeks=woche)
    tage = [montag + timedelta(days=i) for i in range(7)]

    # Zwei-Wege-Sync: im Kalender gelöschte Mahlzeiten aus dem Plan entfernen
    ent = (get_settings().kalender_entity or "").strip()
    if ent:
        try:
            kalender_reconcile(ent, tage[0], tage[-1])
        except Exception as ex:
            print(f"Reconcile Fehler: {ex}", flush=True)

    # Geplante Einträge der Woche laden → dict[(datum, mahlzeit)] = Eintrag
    eintraege = Essensplan.query.filter(
        Essensplan.datum >= tage[0],
        Essensplan.datum <= tage[-1]
    ).all()
    plan = {f"{e.datum.isoformat()}|{e.mahlzeit}": e for e in eintraege}

    rezepte_liste = Rezept.query.order_by(Rezept.name).all()
    einkaufslisten = EinkaufsListe.query.order_by(EinkaufsListe.erstellt).all()
    rezept_portionen = {r.id: (r.portionen or 1) for r in rezepte_liste}
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    kalender_aktiv = bool(ent)

    return render_template("essensplan.html",
        tage=tage, mahlzeiten=MAHLZEITEN, plan=plan,
        rezepte=rezepte_liste, woche=woche, heute=heute,
        montag=montag, sonntag=tage[-1],
        kalender_aktiv=kalender_aktiv,
        einkaufslisten=einkaufslisten, rezept_portionen=rezept_portionen,
        einkauf_count=einkauf_count)

@app.route("/essensplan/setzen", methods=["POST"])
def essensplan_setzen():
    woche = request.form.get("woche", "0")
    try:
        datum = datetime.strptime(request.form.get("datum", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Ungültiges Datum.", "danger")
        return redirect(url_for("essensplan", woche=woche))

    mahlzeit = request.form.get("mahlzeit", "")
    if mahlzeit not in dict(MAHLZEITEN):
        flash("Ungültige Mahlzeit.", "danger")
        return redirect(url_for("essensplan", woche=woche))

    rezept_id = request.form.get("rezept_id") or None
    freitext = request.form.get("freitext", "").strip()
    if rezept_id:
        try:
            rezept_id = int(rezept_id)
        except ValueError:
            rezept_id = None

    try:
        personen = int(request.form.get("personen", "") or 0) or None
    except ValueError:
        personen = None

    eintrag = Essensplan.query.filter_by(datum=datum, mahlzeit=mahlzeit).first()
    ent = (get_settings().kalender_entity or "").strip()

    # Leer → vorhandenen Eintrag löschen (auch im Kalender)
    if not rezept_id and not freitext:
        if eintrag:
            if ent:
                kalender_eintrag_loeschen(ent, eintrag.datum, eintrag.id)
            db.session.delete(eintrag)
            db.session.commit()
        return redirect(url_for("essensplan", woche=woche))

    if eintrag:
        eintrag.rezept_id = rezept_id
        eintrag.freitext = freitext if not rezept_id else ""
        eintrag.personen = personen
    else:
        eintrag = Essensplan(datum=datum, mahlzeit=mahlzeit,
            rezept_id=rezept_id, freitext=freitext if not rezept_id else "",
            personen=personen)
        db.session.add(eintrag)
    db.session.commit()

    # Optional: Zutaten zur Einkaufsliste (nur bei Rezept)
    if request.form.get("zur_einkaufsliste") and rezept_id:
        rezept = Rezept.query.get(rezept_id)
        if rezept:
            basis = rezept.portionen or 1
            faktor = (personen / basis) if (personen and basis) else 1.0
            anzahl, liste = rezept_zur_liste(rezept, request.form.get("einkauf_liste_id"), faktor)
            db.session.commit()
            flash(f"{anzahl} fehlende Zutaten von '{rezept.name}' zur Liste '{liste.name}' hinzugefügt.", "success")

    # Auto-Sync in den HA-Kalender (sofort)
    if ent:
        if kalender_eintrag_schreiben(ent, eintrag):
            eintrag.cal_synced_at = datetime.utcnow()
            db.session.commit()
    return redirect(url_for("essensplan", woche=woche))

@app.route("/essensplan/<int:id>/loeschen", methods=["POST"])
def essensplan_loeschen(id):
    woche = request.form.get("woche", "0")
    eintrag = Essensplan.query.get_or_404(id)
    ent = (get_settings().kalender_entity or "").strip()
    if ent:
        kalender_eintrag_loeschen(ent, eintrag.datum, eintrag.id)
    db.session.delete(eintrag)
    db.session.commit()
    return redirect(url_for("essensplan", woche=woche))

@app.route("/essensplan/sync", methods=["POST"])
def essensplan_sync():
    """Überträgt die Mahlzeiten einer Woche in den gewählten HA-Kalender.
    Vorgehen: alte vom Add-on erstellte Einträge der Woche löschen, dann neu schreiben."""
    woche = request.form.get("woche", "0")
    try:
        woche_i = int(woche)
    except ValueError:
        woche_i = 0

    s = get_settings()
    ent = (s.kalender_entity or "").strip()
    if not ent:
        flash("Bitte zuerst in den Einstellungen einen HA-Kalender auswählen.", "danger")
        return redirect(url_for("einstellungen"))

    if not os.environ.get("SUPERVISOR_TOKEN", ""):
        flash("HA-Kalender nur innerhalb von Home Assistant verfügbar.", "danger")
        return redirect(url_for("essensplan", woche=woche))

    heute = date.today()
    montag = heute - timedelta(days=heute.weekday()) + timedelta(weeks=woche_i)
    sonntag = montag + timedelta(days=6)

    # 1. Alle vom Add-on erstellten Einträge der Woche löschen (auch Waisen)
    try:
        events = ha_kalender_events_holen(
            ent, montag.isoformat() + "T00:00:00",
            (sonntag + timedelta(days=1)).isoformat() + "T00:00:00")
        for e in events:
            if KAL_MARKER in (e.get("description") or ""):
                ha_kalender_event_loeschen(ent, e.get("uid"))
    except Exception as ex:
        print(f"HA Kalender Lesen/Löschen Fehler: {ex}", flush=True)

    # 2. Aktuelle Wochen-Mahlzeiten neu schreiben (mit Eintrag-Marker)
    eintraege = Essensplan.query.filter(
        Essensplan.datum >= montag, Essensplan.datum <= sonntag).all()
    erstellt = 0
    fehler = 0
    for ev in eintraege:
        if not (ev.rezept or ev.freitext):
            continue
        if kalender_eintrag_schreiben(ent, ev):
            ev.cal_synced_at = datetime.utcnow()
            erstellt += 1
        else:
            fehler += 1
    db.session.commit()

    if fehler:
        flash(f"HA-Kalender: {erstellt} übertragen, {fehler} fehlgeschlagen – siehe Add-on-Log.", "danger")
    else:
        flash(f"✅ HA-Kalender aktualisiert: {erstellt} Mahlzeiten übertragen.", "success")
    return redirect(url_for("essensplan", woche=woche))

# ── Einstellungen Route ────────────────────────────────────────────────────────

@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    s = get_settings()
    einkauf_count = Einkaufsliste.query.filter_by(erledigt=False).count()
    if request.method == "POST":
        # Bestehende Werte als Default → Teil-Formulare setzen nichts zurück
        s.sprache = request.form.get("sprache", s.sprache)
        s.waehrung = request.form.get("waehrung", s.waehrung)
        s.theme = request.form.get("theme", s.theme)
        s.farbe = request.form.get("farbe", s.farbe)
        if "kalender_entity" in request.form:
            s.kalender_entity = request.form.get("kalender_entity", "").strip()
        db.session.commit()
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("einstellungen"))
    kalender = ha_kalender_liste()
    verwaltung = {
        "lagerort":  stammdaten_mit_anzahl("lagerort"),
        "kategorie": stammdaten_mit_anzahl("kategorie"),
        "einheit":   stammdaten_mit_anzahl("einheit"),
    }
    return render_template("einstellungen.html",
        settings=s, einkauf_count=einkauf_count, kalender=kalender, verwaltung=verwaltung)

# ── HA Kalender Integration ───────────────────────────────────────────────────

KAL_MARKER = "[essensplan"  # Präfix; pro Eintrag: [essensplan:ID]
MAHLZEIT_ZEIT = {
    "fruehstueck": ("08:00:00", "08:30:00"),
    "mittag":      ("12:00:00", "12:30:00"),
    "abend":       ("18:00:00", "18:30:00"),
}

def _ha_api():
    """Gibt (API-Basis-URL, Header) zurück – oder (None, None) außerhalb HA."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return None, None
    return "http://supervisor/core/api", {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def ha_kalender_liste():
    """Liefert alle verfügbaren calendar.* Entitäten aus Home Assistant."""
    api, hdr = _ha_api()
    if not api:
        return []
    try:
        r = requests.get(f"{api}/states", headers=hdr, timeout=(3, 7))
        r.raise_for_status()
        return sorted([
            {"entity_id": s["entity_id"],
             "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
            for s in r.json() if s["entity_id"].startswith("calendar.")
        ], key=lambda c: c["name"].lower())
    except Exception as e:
        print(f"HA Kalender-Liste Fehler: {e}", flush=True)
        return []

def ha_kalender_events_holen(ent, start_iso, end_iso):
    """Liest Kalender-Events im Zeitraum (REST, read-only)."""
    api, hdr = _ha_api()
    if not api:
        return []
    r = requests.get(f"{api}/calendars/{ent}", headers=hdr,
                     params={"start": start_iso, "end": end_iso}, timeout=(3, 7))
    r.raise_for_status()
    return r.json()

def ha_kalender_event_erstellen(ent, summary, start_dt, end_dt, description):
    """Erstellt ein Kalender-Event via calendar.create_event Service (REST)."""
    api, hdr = _ha_api()
    if not api:
        return False
    try:
        r = requests.post(f"{api}/services/calendar/create_event", headers=hdr,
            json={"entity_id": ent, "summary": summary,
                  "start_date_time": start_dt, "end_date_time": end_dt,
                  "description": description}, timeout=(3, 7))
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"HA Kalender create Fehler ({ent}): {e}", flush=True)
        return False

def ha_kalender_event_loeschen(ent, uid):
    """Löscht ein Kalender-Event via WebSocket (REST kann das nicht)."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token or not uid:
        return False
    try:
        import websocket  # websocket-client
    except ImportError:
        print("HA Kalender löschen: websocket-client fehlt", flush=True)
        return False
    ws = None
    try:
        ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=7)
        first = json.loads(ws.recv())
        if first.get("type") == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth = json.loads(ws.recv())
            if auth.get("type") != "auth_ok":
                print(f"HA Kalender WS Auth fehlgeschlagen: {auth}", flush=True)
                return False
        ws.send(json.dumps({"id": 1, "type": "calendar/event/delete",
                            "entity_id": ent, "uid": uid}))
        resp = json.loads(ws.recv())
        if not resp.get("success"):
            print(f"HA Kalender löschen fehlgeschlagen: {resp}", flush=True)
        return bool(resp.get("success"))
    except Exception as e:
        print(f"HA Kalender löschen Fehler ({ent}): {e}", flush=True)
        return False
    finally:
        if ws:
            try: ws.close()
            except Exception: pass

def kalender_eintrag_loeschen(ent, datum, entry_id):
    """Löscht das/die Kalender-Event(s) eines bestimmten Plan-Eintrags."""
    try:
        events = ha_kalender_events_holen(
            ent, datum.isoformat() + "T00:00:00",
            (datum + timedelta(days=1)).isoformat() + "T00:00:00")
    except Exception as e:
        print(f"HA Kalender lesen Fehler: {e}", flush=True)
        return 0
    marker = f"[essensplan:{entry_id}]"
    n = 0
    for e in events:
        if marker in (e.get("description") or ""):
            if ha_kalender_event_loeschen(ent, e.get("uid")):
                n += 1
    return n

def kalender_eintrag_schreiben(ent, ev):
    """Upsert: altes Event dieses Eintrags löschen, dann neu erstellen.
    Gibt True bei Erfolg zurück (Aufrufer setzt dann cal_synced_at)."""
    name = ev.rezept.name if ev.rezept else ev.freitext
    if not name:
        return False
    kalender_eintrag_loeschen(ent, ev.datum, ev.id)
    label = dict(MAHLZEITEN).get(ev.mahlzeit, ev.mahlzeit)
    z1, z2 = MAHLZEIT_ZEIT.get(ev.mahlzeit, ("12:00:00", "12:30:00"))
    return ha_kalender_event_erstellen(
        ent, f"{label}: {name}",
        f"{ev.datum.isoformat()} {z1}", f"{ev.datum.isoformat()} {z2}",
        f"Geplant über Vorratsverwaltung [essensplan:{ev.id}]")

def kalender_reconcile(ent, von, bis):
    """Zwei-Wege: im HA-Kalender gelöschte Mahlzeiten auch aus dem Plan entfernen.
    Nur Einträge berücksichtigen, die >90s synchronisiert sind (Schutz vor HA-Verzögerung)."""
    if not os.environ.get("SUPERVISOR_TOKEN", ""):
        return 0

    grenze = datetime.utcnow() - timedelta(seconds=90)
    kandidaten = Essensplan.query.filter(
        Essensplan.datum >= von, Essensplan.datum <= bis,
        Essensplan.cal_synced_at.isnot(None),
        Essensplan.cal_synced_at < grenze).all()
    # Nichts synchronisiert in dieser Woche → kein Kalender-Aufruf nötig (schneller Seitenaufruf)
    if not kandidaten:
        return 0

    try:
        events = ha_kalender_events_holen(
            ent, von.isoformat() + "T00:00:00",
            (bis + timedelta(days=1)).isoformat() + "T00:00:00")
    except Exception as e:
        print(f"HA Kalender Reconcile lesen Fehler: {e}", flush=True)
        return 0  # Kalender nicht erreichbar → nichts löschen
    vorhanden = set()
    for e in events:
        for m in re.findall(r"\[essensplan:(\d+)\]", e.get("description") or ""):
            vorhanden.add(int(m))
    geloescht = 0
    for ev in kandidaten:
        if ev.id not in vorhanden:
            db.session.delete(ev)
            geloescht += 1
    if geloescht:
        db.session.commit()
        print(f"Reconcile: {geloescht} im Kalender gelöschte Mahlzeiten aus Plan entfernt.", flush=True)
    return geloescht

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
            ("kalender_entity", "VARCHAR(100) DEFAULT ''"),
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
        if tabelle_existiert("produkt") and not spalte_existiert("produkt", "angebrochen_prozent"):
            cur.execute("ALTER TABLE produkt ADD COLUMN angebrochen_prozent INTEGER DEFAULT 100")
            conn.commit()
        for spalte, typ in [
            ("notiz", "TEXT DEFAULT ''"),
            ("bild", "VARCHAR(200) DEFAULT ''"),
            ("barcode", "VARCHAR(50) DEFAULT ''"),
            ("kcal", "FLOAT"),
            ("eiweiss", "FLOAT"),
            ("fett", "FLOAT"),
            ("kohlenhydrate", "FLOAT"),
        ]:
            if tabelle_existiert("produkt") and not spalte_existiert("produkt", spalte):
                cur.execute(f"ALTER TABLE produkt ADD COLUMN {spalte} {typ}")
                conn.commit()

        # rezept neue Spalten
        if tabelle_existiert("rezept") and not spalte_existiert("rezept", "quell_url"):
            cur.execute("ALTER TABLE rezept ADD COLUMN quell_url VARCHAR(500) DEFAULT ''")
            conn.commit()

        # essensplan
        if not tabelle_existiert("essensplan"):
            cur.execute("""CREATE TABLE essensplan (
                id INTEGER PRIMARY KEY,
                datum DATE NOT NULL,
                mahlzeit VARCHAR(20) NOT NULL,
                rezept_id INTEGER,
                freitext VARCHAR(200) DEFAULT '',
                erstellt DATETIME DEFAULT CURRENT_TIMESTAMP,
                cal_synced_at DATETIME,
                UNIQUE(datum, mahlzeit)
            )""")
            conn.commit()
        if tabelle_existiert("essensplan") and not spalte_existiert("essensplan", "cal_synced_at"):
            cur.execute("ALTER TABLE essensplan ADD COLUMN cal_synced_at DATETIME")
            conn.commit()
        if tabelle_existiert("essensplan") and not spalte_existiert("essensplan", "personen"):
            cur.execute("ALTER TABLE essensplan ADD COLUMN personen INTEGER")
            conn.commit()

        # stammdaten (Lagerorte / Kategorien / Einheiten) – Tabelle legt db.create_all() an,
        # hier nur befüllen, wenn noch leer (Erstmigration)
        def _stammdaten_leer():
            if not tabelle_existiert("stammdaten"):
                return False
            return cur.execute("SELECT COUNT(*) FROM stammdaten").fetchone()[0] == 0
        if _stammdaten_leer():
            def _add(typ, werte):
                for w in werte:
                    w = (w or "").strip()
                    if w:
                        cur.execute("INSERT OR IGNORE INTO stammdaten (typ, name) VALUES (?,?)", (typ, w))

            # Werte aus vorhandenen Produkten übernehmen
            if tabelle_existiert("produkt"):
                _add("lagerort",  [r[0] for r in cur.execute("SELECT DISTINCT lagerort FROM produkt").fetchall()])
                _add("kategorie", [r[0] for r in cur.execute("SELECT DISTINCT kategorie FROM produkt").fetchall()])
                _add("einheit",   [r[0] for r in cur.execute("SELECT DISTINCT einheit FROM produkt").fetchall()])
            # Standard-Vorgaben ergänzen
            _add("kategorie", ['Obst & Gemüse','Milchprodukte','Fleisch & Fisch','Backwaren',
                               'Tiefkühl','Getränke','Konserven','Gewürze','Süßes','Haushalt','Sonstiges'])
            _add("einheit",   ['Stück','g','kg','ml','l','Packung','Dose','Flasche','Tüte'])
            conn.commit()

        conn.close()

def _sauber_beenden(signum, frame):
    """SIGTERM sauber abfangen → Exit-Code 0 (sonst meldet der Supervisor 143)."""
    print("SIGTERM empfangen – Vorratsverwaltung beendet sauber.", flush=True)
    os._exit(0)

if __name__ == "__main__":
    print(">>> Vorratsverwaltung START – Build v1.5.8 (SIGTERM-Handler + threaded aktiv) <<<", flush=True)
    # Als PID 1 im Container: SIGTERM/SIGINT abfangen für sauberen Stop/Neustart
    signal.signal(signal.SIGTERM, _sauber_beenden)
    signal.signal(signal.SIGINT, _sauber_beenden)

    db_migrieren()
    with app.app_context():
        db.engine.dispose()
    ha_sensoren_aktualisieren()
    # threaded=True: mehrere Anfragen gleichzeitig – sonst blockiert ein langsamer
    # Request (z.B. HA-Kalender-Aufruf) das ganze Add-on → 503 bei anderen Seiten
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
