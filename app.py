import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from fpdf import FPDF
from google import genai
from google.genai import types
from PIL import Image

st.set_page_config(page_title="ULD-Aufbau", page_icon="📦", layout="centered")

STORAGE_PATH = Path("uld_app_storage.json")

# ===== KONSTANTEN =====
ST_KEY = {
    "URG", "PIL", "PER", "COL", "CRT", "ACT", "HEA", "ELI", "ELM",
    "NSC", "AVI", "DGR", "RCL", "RFL", "VAL", "VUN", "XPS", "BUP", "EMC"
}

ST_PLACES = [
    "Fremdhandling Vorhaltefläche",
    "LCAG Vorhaltefläche",
    "LCAG Warehouse",
    "Stückgut Vorhaltefläche",
    "Stückgut Warehouse",
    "Trucking Vorhaltefläche",
    "Breakdown",
    "Disponent Büro",
]

LAGER_OPTS = [
    "Perishable 1", "Perishable 2", "Perishable 3", "Perishable 4", "Perishable 5",
    *ST_PLACES,
    "Sonstiger",
]

KONT_OPTS = ["QL", "QM", "Q4", "Q5", "Q6", "Q7", "SCA", "SCB", "andere"]

MAT_FIELDS = [
    ("str", "Stricke"),
    ("gur", "Gurten"),
    ("eur", "EURO-Pal."),
    ("oes", "Verzurrösen"),
    ("b130", "Bretter 1,30"),
    ("b200", "Bretter 2,00"),
    ("b220", "Bretter 2,20"),
    ("b290", "Bretter 2,90"),
]

PT_MAP = {"U": "URGENT", "P": "PIL/PER", "M": "MUST GO", "": ""}
ORDER_MAP = {"U": 0, "P": 1, "M": 2, "": 3}

DEMO_FLIGHT = {
    "code": "DEMO01",
    "date": "01.01.2027",
    "title": "DEMO01 · 01.01.2027 · Testflug",
    "sub": "Nur zum Ausprobieren – erfundene Daten",
    "dest": "YYY",
    "segs": None,
    "data": [
        {
            "awb": "999-00000011", "o": "VIE", "d": "XXX", "stk": 3, "kg": 120.5,
            "m3": 0.8, "scc": "SPX,EAW", "p": "M", "mob": 1, "rw": True,
            "bulk": False, "msca": False, "note": "DEMO - erfundene Daten", "seg": "YYY"
        },
        {
            "awb": "999-00000022", "o": "VIE", "d": "YYY", "stk": 5, "kg": 800.0,
            "m3": 3.1, "scc": "HEA,SPX", "p": "", "mob": 2, "rw": False,
            "bulk": False, "msca": False, "note": "", "seg": "YYY"
        },
        {
            "awb": "999-00000033", "o": "VIE", "d": "ZZZ", "stk": 2, "kg": 45.0,
            "m3": 0.3, "scc": "PIL,COL", "p": "", "mob": 3, "rw": False,
            "bulk": False, "msca": False, "note": "", "seg": "YYY"
        },
    ],
}

BOOK_PROMPT = """Du bekommst Fotos einer Luftfracht-Buchungsliste (Booking List / Flight Bookings Report) für EINEN Flug, evtl. mehrere Seiten, mit möglichen handschriftlichen Notizen (Kugelschreiber, Marker). Lies ALLE Sendungen exakt ab. Antworte NUR mit JSON in diesem Format:
{"code":"Flugnummer ohne Leerzeichen, z.B. BR0062","date":"TT.MM.JJJJ","ac":"Flugzeugtyp wie gedruckt","dest":"Hauptziel des Flugs (3-Letter, Endziel der ULDs, z.B. IST oder TPE)","segs":["Zwischenstopp","Endziel"] oder null,"info":"kurze Info für die Halle, z.B. Anzahl/Art ULDs, Verpackung (doppelt Plastik), Bulk-Hinweis – max 90 Zeichen","total_stk":Zahl oder null,"total_kg":Zahl oder null,
"rows":[{"awb":"PPP-NNNNNNNN","o":"Origin","d":"Destination","stk":Zahl,"kg":Zahl,"m3":Zahl,"scc":"Codes durch Komma, z.B. SPX,EAW,ECC (ohne Leerzeichen)","p":"U"|"P"|"M"|"","mob":Zahl oder null,"rw":true/false,"bulk":true/false,"msca":true/false,"seg":"Code oder null","note":"wichtiger Hinweis max 60 Zeichen oder leer"}]}
Regeln: total_stk/total_kg = gedruckte Gesamtsumme (Grand Total). p: "U" Urgent/blau URG, "P" PIL/PER/orange, "M" Must Go (gelb markiert, MUST GO, MUST FLY) sonst "". mob: handschriftliche Rangnummer neben der Sendung (oft mit Punkt davor, Legende z.B. "• = MOB"), kleinere Zahl = wichtiger; sonst null. rw: true wenn handschriftlich "!" o.ä. markiert und Legende sagt RE-WT/wiegen. bulk: true bei Dreieck/"BULK" Markierung. msca: true wenn MSCA markiert oder als missing gekennzeichnet. seg: nur bei Flügen mit Zwischenstopp (z.B. VIE-BKK-TPE, handschriftlich getrennt/markiert): Sendungen für den Zwischenstopp bekommen dessen Code, alle anderen das Endziel; sonst null und segs null. note: z.B. "Tilt + Shockwatch", "kommt 10 Uhr". Keine Sendung auslassen, keine erfinden."""

ULD_PROMPT = 'Foto von einem Luftfracht-ULD (Palette oder Container) bzw. dessen Kennzeichnung. Lies die ULD-Nummer: 3 Buchstaben Typ (z. B. PMC, PAG, PLA, PAJ, AKE), dann 4-5 Ziffern, dann der 2-stellige Airline-Code (z. B. TK). Antworte NUR mit JSON: {"uld":"PMC 12345 TK"} oder, wenn nicht sicher lesbar, {"uld":null,"grund":"kurz auf Deutsch"}.'

AWB_PROMPT = 'Foto von einem Luftfracht-Etikett oder Frachtpapier. Lies die AWB-Nummer (Air Waybill, 11 Ziffern, geschrieben als 3-stelliger Präfix + 8 Ziffern, z. B. 235-12345678). Lies außerdem, falls sichtbar, die Gesamtstückzahl der Sendung (z. B. "Total No. of Pieces 8" oder "Pcs 3/8" bedeutet gesamt 8). Antworte NUR mit JSON: {"awb":"235-12345678","stk_gesamt":8} (stk_gesamt null wenn nicht sichtbar) oder {"awb":null,"grund":"kurz auf Deutsch"}.'

WAAGE_PROMPT = 'Foto vom Display einer Waage für Luftfracht-Paletten. Lies das angezeigte Gewicht in Kilogramm (nur die Zahl). Antworte NUR mit JSON: {"kg":1234.5} oder, wenn nicht sicher lesbar, {"kg":null,"grund":"kurz auf Deutsch"}.'


# ===== DAUERHAFTE SPEICHERUNG =====
def serialize_app_data() -> str:
    payload = {
        "flights": st.session_state.flights,
        "current_fl": st.session_state.current_fl,
        "states": st.session_state.states,
        "me": st.session_state.me,
    }
    return json.dumps(payload, ensure_ascii=False)


def apply_loaded_payload(data: dict) -> None:
    flights = data.get("flights")
    if isinstance(flights, dict) and flights:
        if "DEMO" not in flights:
            flights["DEMO"] = DEMO_FLIGHT
        st.session_state.flights = flights
    else:
        st.session_state.flights = {"DEMO": DEMO_FLIGHT}

    cur = data.get("current_fl")
    if cur in st.session_state.flights:
        st.session_state.current_fl = cur
    else:
        non_demo = [k for k in st.session_state.flights if k != "DEMO"]
        st.session_state.current_fl = non_demo[-1] if non_demo else "DEMO"

    states = data.get("states")
    st.session_state.states = states if isinstance(states, dict) else {}

    me = data.get("me")
    if isinstance(me, dict):
        st.session_state.me = {
            "name": str(me.get("name", "")),
            "nr": str(me.get("nr", "")),
        }


def load_persisted_data() -> None:
    if STORAGE_PATH.exists():
        try:
            raw = STORAGE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                apply_loaded_payload(data)
                st.session_state["_last_saved_json"] = serialize_app_data()
                return
        except Exception:
            pass
    st.session_state.flights = {"DEMO": DEMO_FLIGHT}
    st.session_state.current_fl = "DEMO"
    st.session_state.states = {}
    st.session_state.me = {"name": "", "nr": ""}


def save_persisted_data() -> None:
    try:
        raw = serialize_app_data()
        if raw == st.session_state.get("_last_saved_json"):
            return
        tmp_path = STORAGE_PATH.with_suffix(".tmp")
        tmp_path.write_text(raw, encoding="utf-8")
        os.replace(tmp_path, STORAGE_PATH)
        st.session_state["_last_saved_json"] = raw
    except Exception:
        pass


# ===== SESSION STATE INITIALISIERUNG =====
if "db_loaded" not in st.session_state:
    load_persisted_data()
    st.session_state.db_loaded = True
if "flights" not in st.session_state:
    st.session_state.flights = {"DEMO": DEMO_FLIGHT}
if "current_fl" not in st.session_state:
    st.session_state.current_fl = "DEMO"
if "states" not in st.session_state:
    st.session_state.states = {}
if "me" not in st.session_state:
    st.session_state.me = {"name": "", "nr": ""}
if "api_key_input" not in st.session_state:
    st.session_state.api_key_input = ""


def get_api_key() -> str:
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY", "")
        if secret_key:
            return str(secret_key).strip()
    except Exception:
        pass
    return st.session_state.api_key_input.strip()


def get_fl() -> dict:
    if st.session_state.current_fl not in st.session_state.flights:
        st.session_state.current_fl = "DEMO"
    return st.session_state.flights[st.session_state.current_fl]


def get_state() -> dict:
    fl_key = st.session_state.current_fl
    if fl_key not in st.session_state.states:
        st.session_state.states[fl_key] = {"ulds": [], "act": 0, "extra": []}
    return st.session_state.states[fl_key]


def fmt_num(x: float, dec: int = 1) -> str:
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", " ")


def safe_latin1(text: str) -> str:
    s = str(text).replace("→", "->").replace("✓", "OK").replace("⚠", "!").replace("△", "")
    return s.encode("cp1252", errors="replace").decode("cp1252")


def used_stk(awb: str, state: dict) -> int:
    total = 0
    for u in state["ulds"]:
        for it in u["items"]:
            if it["awb"] == awb:
                total += it["stk"]
    return total


def find_shipment(awb: str, fl: dict, state: dict) -> dict | None:
    for d in fl["data"]:
        if d["awb"] == awb:
            return d
    for d in state["extra"]:
        if d["awb"] == awb:
            return d
    return None


def uld_kg(u: dict, fl: dict, state: dict) -> float:
    tot = 0.0
    for it in u["items"]:
        d = find_shipment(it["awb"], fl, state)
        if d and d["stk"] > 0:
            tot += (d["kg"] / d["stk"]) * it["stk"]
    return tot


def uld_stk(u: dict) -> int:
    return sum(it["stk"] for it in u["items"])


def check_uld(u: dict, fl: dict, state: dict) -> list[str]:
    miss = []
    if not u["items"]:
        miss.append("keine Ware")
    if not u.get("k"):
        miss.append("Kontur")
    if not u.get("dmg"):
        miss.append("Damage-Check")
    if not u.get("hc"):
        miss.append("Height-Check")
    if not u.get("lager"):
        miss.append("Lagerplatz")
    if u.get("lager") == "Sonstiger" and not u.get("lagerTxt"):
        miss.append("Text Sonstiger Lagerplatz")
    if not u.get("brutto") and not u.get("durch"):
        miss.append("Bruttogewicht")
    for it in u["items"]:
        d = find_shipment(it["awb"], fl, state)
        if d and d.get("x"):
            miss.append("NICHT GEBUCHTE AWB drauf")
            break
    return miss


# ===== GEMINI HELPER =====
def call_gemini_json(prompt: str, files: list, model_name: str = "gemini-2.5-flash") -> dict:
    api_key = get_api_key()
    if not api_key:
        raise ValueError("Kein Gemini API-Key hinterlegt.")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    contents = [prompt]
    for f in files:
        img = Image.open(f)
        img.thumbnail((2400, 2400))
        contents.append(img)

    models_to_try = [model_name]
    for fallback in ("gemini-2.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash-lite"):
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    last_err = None
    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(resp.text)
        except Exception as e:
            last_err = e
    raise last_err


# ===== PDF ZEICHNUNG (FORM 752c - UNVERÄNDERTES LAYOUT) =====
class StatementPDF(FPDF):
    def lw(self, w: float):
        self.set_line_width(w * 0.3528)

    def col(self, r: float, g: float, b: float):
        ri, gi, bi = int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
        self.set_draw_color(ri, gi, bi)
        self.set_text_color(ri, gi, bi)

    def txt(self, t, x: float, y: float, size: float, bold: bool = False, al: str = "left"):
        s = safe_latin1(t)
        self.set_font("Helvetica", "B" if bold else "", size)
        w = self.get_string_width(s)
        if al == "center":
            x = x - w / 2.0
        elif al == "right":
            x = x - w
        self.text(x, y, s)


def draw_statement_page(pdf: StatementPDF, o: dict):
    pdf.add_page()
    L, R = 12.0, 198.0
    MID = L + 92.0
    bx = MID + 8.0
    u = o["u"]

    pdf.col(0, 0, 0)
    pdf.lw(1.2)
    pdf.txt("ULD - Statement", L, 20, 22, True)
    pdf.txt("Cargo - Handling", L + 80, 20, 11)
    pdf.txt("Flug:", L, 34, 13)
    pdf.line(L + 15, 35, L + 52, 35)
    pdf.txt("Dest.:", L + 60, 34, 13)
    pdf.rect(L + 75, 26, 22, 12)
    pdf.rect(bx, 28, R - bx, 34)

    checks_txt = [
        "ULD CHECKED FOR DAMAGES",
        "HEIGHT CHECK PERFORMED",
        "Check and ensure airworthiness of BUP/TRU",
    ]
    for i, t in enumerate(checks_txt):
        pdf.txt(t, bx + 2, 28 + i * 8.5 + 6, 7.5)
        pdf.line(bx, 36.5 + i * 8.5, R, 36.5 + i * 8.5)

    pdf.line(R - 14, 28, R - 14, 45)
    pdf.txt("OK", bx + 8, 59.5, 9)
    pdf.txt("NOT OK", bx + 50, 59.5, 9)
    for x in [bx + 22, bx + 40, R - 14]:
        pdf.line(x, 53.5, x, 62)

    pdf.rect(L, 40, MID + 8 - L, 22)
    pdf.txt("ULD - Number", L + 2, 48, 13)
    pdf.txt("Paletten / Container:", L + 2, 58.5, 8)
    pdf.line(L + 32, 59, MID + 5, 59)

    top, rows, rh = 62.0, 18, 8.3
    c1, c2 = L + 52.0, L + 70.0
    bt = top + 12.0 + rows * rh
    pdf.rect(L, top, MID - L, bt - top)
    pdf.txt("Air Waybill", (L + c1) / 2, top + 7.5, 10, False, "center")
    pdf.txt("Pcs", (c1 + c2) / 2, top + 5, 8, False, "center")
    pdf.txt("Stück", (c1 + c2) / 2, top + 9.5, 8, False, "center")
    pdf.txt("Special-", (c2 + MID) / 2, top + 5, 8, False, "center")
    pdf.txt("Cargo", (c2 + MID) / 2, top + 9.5, 8, False, "center")
    for x in [c1, c2]:
        pdf.line(x, top, x, bt)
    for i in range(rows + 1):
        pdf.line(L, top + 12 + i * rh, MID, top + 12 + i * rh)

    pdf.rect(MID, top, R - MID, bt - top)
    sx = (MID + R) / 2.0
    pdf.lw(0.8)
    pdf.rect(sx - 5, 70, 10, 30)
    for dx in range(0, 10, 2):
        pdf.line(sx - 5 + dx, 82, sx - 4 + dx, 82)
    pdf.line(sx - 5, 100, sx, 111)
    pdf.line(sx + 5, 100, sx, 111)
    pdf.ellipse(sx - 1, 111, 2, 2)
    pdf.rect(sx - 9, 66, 3, 3)
    pdf.rect(sx + 6, 66, 3, 3)
    pdf.txt("hohe Seite", sx, 68.3, 5, False, "center")
    pdf.lw(1.2)

    ly = 117.0
    pdf.line(MID, ly, R, ly)
    pdf.txt("Lagerplatz", (MID + R) / 2, ly + 6, 10, False, "center")
    pdf.line(MID, ly + 9, R, ly + 9)
    pdf.txt("Perishable", MID + 1.5, ly + 15, 10)
    px = [MID + 24, MID + 37, MID + 50, MID + 63, MID + 80]
    for i, x in enumerate(px):
        pdf.line(x, ly + 9, x, ly + 18)
        nxt = px[i + 1] if i + 1 < len(px) else R
        pdf.txt(str(i + 1), (x + nxt) / 2, ly + 15, 10, False, "center")
    pdf.line(MID, ly + 18, R, ly + 18)

    yy = ly + 18.0
    for p in ST_PLACES:
        pdf.txt(p, MID + 40, yy + 5.5, 10, False, "center")
        pdf.line(R - 16, yy, R - 16, yy + 8)
        yy += 8.0
        pdf.line(MID, yy, R, yy)

    pdf.txt("Sonstiger Lagerplatz:", MID + 3, yy + 6, 10)
    pdf.line(MID + 45, yy, MID + 45, yy + 8)
    pdf.line(MID, yy + 8, R, yy + 8)

    kt = bt
    kw = (MID - L) / 4.0
    pdf.rect(L, kt, MID - L, 38)
    pdf.txt("KONTUR", L + 4, kt + 8, 15, True)
    pdf.line(L + 38, kt, L + 38, kt + 10)
    pdf.line(L, kt + 10, MID, kt + 10)

    for i, t in enumerate(["Stricke", "Gurten", "EURO - Pal.", "Verzurrösen"]):
        pdf.txt(t, L + kw * (i + 0.5), kt + 14, 8, False, "center")
    for i, t in enumerate(["1,30m", "2,00 m", "2,20m", "2,90m"]):
        pdf.txt("Bretter", L + kw * (i + 0.5), kt + 25.5, 8, False, "center")
        pdf.txt(t, L + kw * (i + 0.5), kt + 28.5, 8, False, "center")
    for y in [kt + 16, kt + 22, kt + 30]:
        pdf.line(L, y, MID, y)
    for i in range(1, 4):
        pdf.line(L + kw * i, kt + 10, L + kw * i, kt + 38)

    pdf.rect(MID, kt, R - MID, 38)
    pdf.line(MID, kt + 22, R, kt + 22)
    pdf.txt("Grossweight", MID + 2, kt + 27, 8.5)
    pdf.txt("Bruttogewicht:", MID + 2, kt + 34, 11)
    pdf.line(MID + 30, kt + 35, R - 10, kt + 35)
    pdf.txt("kg", R - 8, kt + 34, 13, True)

    for i, (a, b) in enumerate([("Name / PersNr.:", "Name / PersNr.:"), ("Unterschrift DG:", "Unterschrift MA:")]):
        y0 = kt + 38 + i * 10
        pdf.rect(L, y0, R - L, 10)
        pdf.line(MID, y0, MID, y0 + 10)
        pdf.txt(a, L + 2, y0 + 6.5, 9.5)
        pdf.txt(b, MID + 2, y0 + 6.5, 9.5)

    # ---- Ausgefüllte Werte (Blau) ----
    pdf.col(0.05, 0.15, 0.55)
    pdf.txt(o["flug"], L + 17, 33.5, 14, True)
    pdf.txt(u.get("dest") or o["dest"], L + 86, 34, 16, True, "center")
    pdf.txt(u["nr"], L + 42, 48.5, 18, True)
    pdf.txt(u.get("k", ""), (L + 38 + MID) / 2, kt + 8, 22, True, "center")

    for i, it in enumerate(o["items"][:rows]):
        yb = top + 12 + i * rh + 5.8
        pdf.txt(it["awb"], L + 2, yb, 11.5, True)
        stk_str = f"{it['stk']}/{it['tot']}" if it.get("tot") and it["tot"] != it["stk"] else str(it["stk"])
        pdf.txt(stk_str, (c1 + c2) / 2, yb, 11.5, True, "center")
        sp = [c.strip() for c in str(it.get("scc", "")).split(",") if c.strip() in ST_KEY][:3]
        pdf.txt(" ".join(sp), (c2 + MID) / 2, yb - 0.3, 7 if len(sp) > 2 else 8, True, "center")

    def mark_x(x: float, y: float, sz: float = 13):
        pdf.txt("X", x, y, sz, True, "center")

    if u.get("dmg"):
        mark_x(R - 7, 34)
    if u.get("hc"):
        mark_x(R - 7, 42.5)
    if u.get("bup") == "OK":
        mark_x(bx + 31, 60.5)
    elif u.get("bup") == "NOT OK":
        mark_x(R - 7, 60.5)
    if u.get("hs") == "links":
        mark_x(sx - 7.5, 68.6, 9)
    elif u.get("hs") == "rechts":
        mark_x(sx + 7.5, 68.6, 9)

    if not u.get("offload"):
        pdf.txt("Höhe:", MID + 3, 80, 11, True)
        pdf.txt(f"{u['h']} cm" if u.get("h") else "-", MID + 3, 86, 13, True)
    if u.get("durch"):
        pdf.txt("DURCHGEHER", MID + 3, 110, 9, True)

    lg = u.get("lager") or ""
    if lg.startswith("Perishable"):
        n = int(lg.split()[-1])
        x0 = px[n - 1]
        x1 = px[n] if n < len(px) else R
        pdf.lw(1.6)
        pdf.line(x0 + 2, ly + 10, x1 - 2, ly + 17)
        pdf.line(x0 + 2, ly + 17, x1 - 2, ly + 10)
        pdf.lw(1.2)
    elif lg in ST_PLACES:
        mark_x(R - 8, ly + 18 + ST_PLACES.index(lg) * 8 + 6)
    elif lg == "Sonstiger":
        pdf.txt(u.get("lagerTxt", ""), MID + 47, ly + 18 + 64 + 6, 10, True)

    m = u.get("mat") or {}
    for i, k in enumerate(["str", "gur", "eur", "oes"]):
        if m.get(k) and str(m[k]) != "0":
            pdf.txt(str(m[k]), L + kw * (i + 0.5), kt + 20.6, 12, True, "center")
    for i, k in enumerate(["b130", "b200", "b220", "b290"]):
        if m.get(k) and str(m[k]) != "0":
            pdf.txt(str(m[k]), L + kw * (i + 0.5), kt + 35.5, 12, True, "center")

    if u.get("brutto"):
        pdf.txt(str(u["brutto"]), MID + 34, kt + 34, 16, True)

    me = o["me"]
    if me.get("name") or me.get("nr"):
        pdf.txt(f"{me.get('name', '')} / {me.get('nr', '')}", MID + 30, kt + 44.5, 11, True)

    tot_stk = sum(it["stk"] for it in o["items"])
    pdf.txt(
        f"{len(o['items'])} AWB · {tot_stk} Stk · Ware ca. {round(o['kg']):,} kg".replace(",", " "),
        MID + 2, kt + 6, 8
    )
    if not u.get("brutto") and not u.get("durch") and not u.get("offload"):
        pdf.txt("Bruttogewicht nach Verwiegung eintragen", MID + 2, kt + 11, 8)
    if len(o["items"]) > rows:
        pdf.txt(f"+ {len(o['items']) - rows} weitere AWB - Beiblatt!", L + 2, bt - 1, 8, True)

    pdf.col(0, 0, 0)
    pdf.txt("Ausgefüllt mit ULD-Aufbau-App · Vorlage nachgebaut nach Form 752c", L, 291, 5.5)


def build_offload_pages(fl: dict, state: dict) -> list[dict]:
    items = []
    for d in fl["data"]:
        left = d["stk"] - used_stk(d["awb"], state)
        if left > 0:
            items.append({
                "awb": d["awb"],
                "stk": left,
                "tot": d["stk"],
                "scc": d.get("scc", ""),
                "kg": (d["kg"] / d["stk"]) * left if d["stk"] > 0 else 0,
            })
    pages = []
    for i in range(0, len(items), 18):
        chunk = items[i:i + 18]
        pages.append({
            "flug": fl["code"],
            "dest": "VIE",
            "u": {"nr": "OFFLOAD", "dest": "VIE", "k": "", "offload": True},
            "me": st.session_state.me,
            "items": chunk,
            "kg": sum(x["kg"] for x in chunk),
        })
    return pages


def generate_statements_pdf(ulds_to_print: list[dict], include_offload: bool, fl: dict, state: dict) -> bytes:
    pdf = StatementPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    for u in ulds_to_print:
        items = []
        for it in u["items"]:
            d = find_shipment(it["awb"], fl, state)
            items.append({
                "awb": it["awb"],
                "stk": it["stk"],
                "tot": d["stk"] if d else it["stk"],
                "scc": d.get("scc", "") if d else "",
            })
        draw_statement_page(pdf, {
            "flug": fl["code"],
            "dest": fl["dest"],
            "u": u,
            "me": st.session_state.me,
            "items": items,
            "kg": uld_kg(u, fl, state),
        })
    if include_offload:
        for op in build_offload_pages(fl, state):
            draw_statement_page(pdf, op)
    return bytes(pdf.output())


# ===== SIDEBAR: API-KEY & FLUG-AUSWAHL =====
with st.sidebar:
    st.subheader("Flug & Einstellungen")
    fl_keys = list(st.session_state.flights.keys())
    sel_fl = st.selectbox(
        "Aktiver Flug",
        fl_keys,
        index=fl_keys.index(st.session_state.current_fl) if st.session_state.current_fl in fl_keys else 0,
        format_func=lambda k: f"{st.session_state.flights[k]['code']} ({st.session_state.flights[k]['date']})",
    )
    if sel_fl != st.session_state.current_fl:
        st.session_state.current_fl = sel_fl
        save_persisted_data()
        st.rerun()

    if st.session_state.current_fl != "DEMO":
        if st.button("🗑 Aktiven Flug löschen", use_container_width=True):
            del_k = st.session_state.current_fl
            st.session_state.flights.pop(del_k, None)
            st.session_state.states.pop(del_k, None)
            rem = [k for k in st.session_state.flights if k != "DEMO"]
            st.session_state.current_fl = rem[-1] if rem else "DEMO"
            save_persisted_data()
            st.rerun()

    st.divider()
    st.subheader("Mitarbeiter (für Statement)")
    st.session_state.me["name"] = st.text_input("Name", value=st.session_state.me["name"])
    st.session_state.me["nr"] = st.text_input("PersNr.", value=st.session_state.me["nr"])

    st.divider()
    if get_api_key():
        st.success("Gemini API-Key aktiv")
    else:
        st.warning("Kein API-Key in Secrets gefunden")
        st.session_state.api_key_input = st.text_input(
            "Gemini API-Key (lokal für diese Sitzung)",
            value=st.session_state.api_key_input,
            type="password",
        )

    with st.expander("Sicherung (Backup-Datei)", expanded=False):
        st.caption("Alle Flüge & ULDs werden automatisch gespeichert. Zusätzlich kannst du hier eine Sicherung herunterladen:")
        st.download_button(
            "⬇ Backup speichern (.json)",
            data=serialize_app_data().encode("utf-8"),
            file_name=f"ULD_Backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
        )
        up_bak = st.file_uploader("Backup laden (.json)", type=["json"], key="bak_up")
        if up_bak and st.button("Backup wiederherstellen", use_container_width=True):
            try:
                loaded = json.loads(up_bak.read().decode("utf-8"))
                apply_loaded_payload(loaded)
                save_persisted_data()
                st.success("Backup wiederhergestellt!")
                st.rerun()
            except Exception as e:
                st.error(f"Ungültige Backup-Datei: {e}")


# ===== HEADER =====
fl = get_fl()
state = get_state()
open_ships = [d for d in fl["data"] if used_stk(d["awb"], state) < d["stk"]]
open_prio = [d for d in open_ships if d.get("p")]

st.markdown(f"### {fl['title']}")
if fl.get("sub"):
    st.caption(fl["sub"])

c1, c2, c3 = st.columns(3)
c1.metric("Offene AWBs", f"{len(open_ships)} / {len(fl['data'])}")
c2.metric("Angelegte ULDs", len(state["ulds"]))
c3.metric("Prio offen", len(open_prio))

tab_send, tab_ulds, tab_stmt, tab_new = st.tabs(["1. Sendungen", "2. ULDs", "3. Statement", "＋ Neuer Flug"])


# ===== TAB 1: SENDUNGEN =====
with tab_send:
    with st.expander("📷 AWB-Etikett fotografieren / hochladen", expanded=False):
        awb_cam = st.file_uploader("Foto vom AWB-Label", type=["jpg", "jpeg", "png"], key="awb_up")
        if awb_cam and st.button("AWB aus Foto lesen", use_container_width=True):
            try:
                with st.spinner("Lese AWB..."):
                    res = call_gemini_json(AWB_PROMPT, [awb_cam], "gemini-2.5-flash")
                if res.get("awb"):
                    st.session_state["last_scanned_awb"] = res["awb"]
                    st.success(f"Erkannt: **{res['awb']}**" + (f" (Etikett: {res['stk_gesamt']} Stk)" if res.get("stk_gesamt") else ""))
                else:
                    st.error(f"Nicht lesbar: {res.get('grund', '')}")
            except Exception as e:
                st.error(f"Fehler: {e}")

    col_f1, col_f2 = st.columns([3, 2])
    default_q = st.session_state.get("last_scanned_awb", "")
    filt = col_f1.text_input("AWB-Endziffern oder Ziel suchen", value=default_q, placeholder="z. B. 54125013 oder IST")
    if col_f2.button("Filter löschen", use_container_width=True):
        st.session_state["last_scanned_awb"] = ""
        st.rerun()

    if not state["ulds"]:
        st.info("Noch keine PMC/ULD angelegt. Lege zuerst eine ULD an:")
        u_c1, u_c2, u_c3 = st.columns([3, 2, 1])
        q_nr = u_c1.text_input("ULD-Nummer", placeholder=f"PMC 12345 {fl['code'][:2]}", key="q_uld_nr")
        q_k = u_c2.selectbox("Kontur", KONT_OPTS, key="q_uld_k")
        if u_c3.button("＋", key="q_uld_add", use_container_width=True) and q_nr.strip():
            state["ulds"].append({
                "nr": q_nr.strip().upper(),
                "k": q_k,
                "dest": fl["dest"],
                "items": [],
                "mat": {},
            })
            state["act"] = len(state["ulds"]) - 1
            save_persisted_data()
            st.rerun()
    else:
        uld_labels = [f"{u['nr']} · {u['k']} ({uld_stk(u)} Stk)" for u in state["ulds"]]
        state["act"] = st.selectbox(
            "Aktive Ziel-ULD zum Verbauen",
            range(len(state["ulds"])),
            index=min(state["act"], len(state["ulds"]) - 1),
            format_func=lambda i: uld_labels[i],
        )

    all_shipments = fl["data"] + state["extra"]
    filtered = [
        d for d in all_shipments
        if not filt.strip() or filt.strip().lower() in (d["awb"] + d["d"] + d.get("scc", "")).lower()
    ]

    if not filtered and filt.strip():
        st.warning(f"Keine Sendung für '{filt}' in der Buchungsliste gefunden.")
        if st.button(f"'{filt.strip()}' als NICHT GEBUCHT trotzdem anlegen"):
            clean_awb = filt.strip().upper()
            if not any(x["awb"] == clean_awb for x in state["extra"]):
                state["extra"].append({
                    "awb": clean_awb, "stk": 99, "kg": 0.0, "m3": 0.0,
                    "scc": "NICHT GEBUCHT", "o": "?", "d": "?", "p": "", "x": True
                })
            save_persisted_data()
            st.rerun()

    for d in filtered:
        u_cnt = used_stk(d["awb"], state)
        left = d["stk"] - u_cnt
        badges = []
        if d.get("mob") is not None:
            badges.append(f"**[MOB {d['mob']}]**")
        elif d.get("p"):
            badges.append(f"**[{PT_MAP[d['p']]}]**")
        if d.get("bulk"):
            badges.append("`BULK`")
        if d.get("rw"):
            badges.append("`! WIEGEN`")
        if d.get("msca"):
            badges.append("`MSCA`")
        if fl.get("segs") and d.get("seg") and d["seg"] != fl["dest"]:
            badges.append(f"`NUR {d['seg']}`")

        with st.container(border=True):
            r1, r2 = st.columns([3, 1])
            r1.markdown(f"{' '.join(badges)} **{d['awb']}** &nbsp; `{d['o']} → {d['d']}`")
            r2.markdown(f"**{fmt_num(d['kg'])} kg** · {fmt_num(d['m3'], 2)} m³")
            stk_tot = d["stk"]
            status_lbl = "✓ komplett" if left <= 0 else f"offen {left} / {stk_tot} Stk"
            note_lbl = f" · {d['note']}" if d.get("note") else ""
            st.caption(f"Status: {status_lbl} · SCC: {d.get('scc', '-')}{note_lbl}")

            if left > 0 and state["ulds"]:
                b1, b2 = st.columns([1, 2])
                qty_to_add = b1.number_input(
                    "Stück", min_value=1, max_value=left, value=left,
                    key=f"qty_{d['awb']}", label_visibility="collapsed"
                )
                if b2.button(f"Auf {state['ulds'][state['act']]['nr']} verbauen", key=f"btn_{d['awb']}", use_container_width=True):
                    target_u = state["ulds"][state["act"]]
                    ud = target_u.get("dest") or fl["dest"]
                    if fl.get("segs") and d.get("seg") and d["seg"] != ud:
                        st.error(f"⛔ {d['awb']} geht nach {d['seg']} – darf NICHT auf {target_u['nr']} (Dest {ud})!")
                    else:
                        existing = next((it for it in target_u["items"] if it["awb"] == d["awb"]), None)
                        if existing:
                            existing["stk"] += int(qty_to_add)
                        else:
                            target_u["items"].append({"awb": d["awb"], "stk": int(qty_to_add)})
                        if d.get("x"):
                            d["stk"] = used_stk(d["awb"], state)
                        save_persisted_data()
                        st.rerun()


# ===== TAB 2: ULDs & STATEMENT-FELDER =====
with tab_ulds:
    with st.expander("＋ Neue ULD anlegen (manuell oder per Foto)", expanded=len(state["ulds"]) == 0):
        uld_cam = st.file_uploader("Optional: Foto von ULD-Kennzeichnung", type=["jpg", "jpeg", "png"], key="uld_up")
        if uld_cam and st.button("ULD-Nummer aus Foto lesen"):
            try:
                with st.spinner("Lese ULD..."):
                    res = call_gemini_json(ULD_PROMPT, [uld_cam], "gemini-2.5-flash")
                if res.get("uld"):
                    st.session_state["new_uld_prefill"] = res["uld"].upper()
                    st.success(f"Erkannt: {res['uld']}")
                else:
                    st.error(f"Nicht lesbar: {res.get('grund', '')}")
            except Exception as e:
                st.error(f"Fehler: {e}")

        nc1, nc2, nc3 = st.columns([3, 2, 2])
        new_nr = nc1.text_input("ULD-Nummer", value=st.session_state.get("new_uld_prefill", ""), placeholder="PMC 12345 TK")
        new_k = nc2.selectbox("Kontur", KONT_OPTS, key="new_k_sel")
        new_dest = nc3.text_input("Dest.", value=fl["dest"], key="new_dest_in").upper()
        if st.button("ULD anlegen", type="primary", use_container_width=True) and new_nr.strip():
            state["ulds"].append({
                "nr": new_nr.strip().upper(),
                "k": new_k,
                "dest": new_dest.strip() or fl["dest"],
                "items": [],
                "mat": {},
            })
            state["act"] = len(state["ulds"]) - 1
            st.session_state["new_uld_prefill"] = ""
            save_persisted_data()
            st.rerun()

    for ix, u in enumerate(state["ulds"]):
        miss = check_uld(u, fl, state)
        status_txt = f"⚠ Fehlt: {', '.join(miss)}" if miss else "✓ Vollständig"
        with st.container(border=True):
            hc1, hc2 = st.columns([3, 1])
            hc1.markdown(f"#### {u['nr']} · {u['k']} {'(AKTIV)' if ix == state['act'] else ''}")
            if ix != state["act"]:
                if hc2.button("Aktiv setzen", key=f"act_{ix}", use_container_width=True):
                    state["act"] = ix
                    save_persisted_data()
                    st.rerun()

            st.caption(f"{uld_stk(u)} Stk · Ware ca. {fmt_num(uld_kg(u, fl, state))} kg · {status_txt}")

            if u["items"]:
                for j, it in enumerate(u["items"]):
                    d = find_shipment(it["awb"], fl, state)
                    ic1, ic2, ic3 = st.columns([4, 2, 1])
                    ic1.write(f"**{it['awb']}** (→ {d['d'] if d else '?'})")
                    ic2.write(f"{it['stk']}/{d['stk'] if d else it['stk']} Stk")
                    if ic3.button("✕", key=f"rm_{ix}_{j}"):
                        u["items"].pop(j)
                        save_persisted_data()
                        st.rerun()

            with st.expander("Statement-Felder ausfüllen (Form 752c)", expanded=bool(miss)):
                fc1, fc2 = st.columns(2)
                u["k"] = fc1.selectbox("Kontur", KONT_OPTS, index=KONT_OPTS.index(u["k"]) if u["k"] in KONT_OPTS else 0, key=f"uk_{ix}")
                u["dest"] = fc2.text_input("Dest.", value=u.get("dest", fl["dest"]), key=f"ud_{ix}").upper()

                fc3, fc4 = st.columns(2)
                u["h"] = fc3.text_input("Höhe (cm)", value=u.get("h", ""), key=f"uh_{ix}")
                u["brutto"] = fc4.text_input("Bruttogewicht (kg)", value=u.get("brutto", ""), key=f"ub_{ix}")

                w_cam = st.file_uploader(f"📷 Waagen-Display für {u['nr']} ablesen", type=["jpg", "jpeg", "png"], key=f"w_{ix}")
                if w_cam and st.button(f"Gewicht übernehmen ({u['nr']})", key=f"wbtn_{ix}"):
                    try:
                        with st.spinner("Lese Waage..."):
                            res = call_gemini_json(WAAGE_PROMPT, [w_cam], "gemini-2.5-flash")
                        if res.get("kg") is not None:
                            u["brutto"] = str(round(float(res["kg"]), 1)).replace(".", ",")
                            save_persisted_data()
                            st.rerun()
                        else:
                            st.error(f"Nicht lesbar: {res.get('grund', '')}")
                    except Exception as e:
                        st.error(f"Fehler: {e}")

                cc1, cc2, cc3 = st.columns(3)
                u["dmg"] = cc1.checkbox("Damage-Check ✓", value=u.get("dmg", False), key=f"dmg_{ix}")
                u["hc"] = cc2.checkbox("Height-Check ✓", value=u.get("hc", False), key=f"hc_{ix}")
                u["durch"] = cc3.checkbox("Durchgeher", value=u.get("durch", False), key=f"du_{ix}")

                rc1, rc2 = st.columns(2)
                bup_opts = ["", "OK", "NOT OK"]
                u["bup"] = rc1.selectbox("BUP/TRU", bup_opts, index=bup_opts.index(u.get("bup", "")), key=f"bup_{ix}")
                hs_opts = ["", "links", "rechts"]
                u["hs"] = rc2.selectbox("Hohe Seite", hs_opts, index=hs_opts.index(u.get("hs", "")), key=f"hs_{ix}")

                st.markdown("**Material**")
                m_cols = st.columns(4)
                u.setdefault("mat", {})
                for m_idx, (mk, mlbl) in enumerate(MAT_FIELDS):
                    u["mat"][mk] = m_cols[m_idx % 4].text_input(mlbl, value=str(u["mat"].get(mk, "")), key=f"mat_{ix}_{mk}")

                l_idx = LAGER_OPTS.index(u["lager"]) + 1 if u.get("lager") in LAGER_OPTS else 0
                sel_l = st.selectbox("Lagerplatz", [""] + LAGER_OPTS, index=l_idx, key=f"lg_{ix}")
                u["lager"] = sel_l
                if sel_l == "Sonstiger":
                    u["lagerTxt"] = st.text_input("Sonstiger Lagerplatz Text", value=u.get("lagerTxt", ""), key=f"lgt_{ix}")

            bc1, bc2 = st.columns([3, 1])
            single_pdf = generate_statements_pdf([u], False, fl, state)
            bc1.download_button(
                f"🖨 Statement {u['nr']} als PDF",
                data=single_pdf,
                file_name=f"Statement_{fl['code']}_{u['nr'].replace(' ', '_')}.pdf",
                mime="application/pdf",
                key=f"dl_{ix}",
                use_container_width=True,
            )
            if bc2.button("Löschen", key=f"del_{ix}", use_container_width=True):
                state["ulds"].pop(ix)
                state["act"] = max(0, len(state["ulds"]) - 1)
                save_persisted_data()
                st.rerun()


# ===== TAB 3: STATEMENT & ABSCHLUSS =====
with tab_stmt:
    st.subheader("Abschluss & Gesamt-PDF (Form 752c)")

    all_problems = []
    for u in state["ulds"]:
        m = check_uld(u, fl, state)
        if m:
            all_problems.append(f"**{u['nr']}**: {', '.join(m)}")
    if open_prio:
        all_problems.append(f"**{len(open_prio)} Prio-Sendungen** noch nicht verbaut")

    if not state["ulds"]:
        st.info("Noch keine ULDs angelegt.")
    elif all_problems:
        st.warning("⚠ Bitte vor dem Drucken prüfen:\n\n" + "\n".join(f"- {p}" for p in all_problems))
    else:
        st.success("✅ Alle ULDs sind vollständig ausgefüllt und alle Prio-Sendungen sind verbaut!")

    offload_pages = build_offload_pages(fl, state)
    offload_count = sum(len(p["items"]) for p in offload_pages)
    st.write(f"**ULDs:** {len(state['ulds'])} | **Offload-AWBs:** {offload_count}")

    if state["ulds"]:
        ts_str = datetime.now().strftime("%Y%m%d%H%M")
        full_pdf = generate_statements_pdf(state["ulds"], True, fl, state)
        st.download_button(
            f"⬇ Alle Statements ({len(state['ulds'])}) + Offload als PDF speichern",
            data=full_pdf,
            file_name=f"Statements_{fl['code']}_{ts_str}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )

    if offload_pages:
        off_pdf = generate_statements_pdf([], True, fl, state)
        st.download_button(
            f"🖨 Nur Offload-Statement ({offload_count} AWB) als PDF",
            data=off_pdf,
            file_name=f"Offload_{fl['code']}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )


# ===== TAB 4: NEUER FLUG (BUCHUNGSLISTE EINLESEN) =====
with tab_new:
    st.subheader("Neuen Flug aus Buchungsliste anlegen")
    st.caption("Fotos der Buchungsliste hochladen (einzelne oder mehrere Seiten). Handschriftliche MOB-Ränge, !, △ und Ziele werden automatisch erkannt.")

    uploaded_pages = st.file_uploader(
        "Seiten der Buchungsliste auswählen / fotografieren",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="book_pages",
    )

    if uploaded_pages and st.button("Buchungsliste mit Gemini lesen", type="primary", use_container_width=True):
        try:
            with st.spinner("Lese Buchungsliste (kann 15–40 Sek. dauern)..."):
                parsed = call_gemini_json(BOOK_PROMPT, uploaded_pages, "gemini-2.5-flash")
            if not parsed or not parsed.get("rows"):
                st.error("Keine Sendungen erkannt. Bitte schärfere Fotos hochladen.")
            else:
                for r in parsed["rows"]:
                    r["stk"] = int(r.get("stk") or 0)
                    r["kg"] = float(r.get("kg") or 0.0)
                    r["m3"] = float(r.get("m3") or 0.0)
                    r["scc"] = re.sub(r"\s+", "", str(r.get("scc") or ""))
                    r["mob"] = int(r["mob"]) if r.get("mob") not in (None, "") else None
                    r["p"] = r.get("p") or ""
                    if r["mob"] == 1 and not r["p"]:
                        r["p"] = "M"
                    if isinstance(parsed.get("segs"), list) and r.get("d") in parsed["segs"]:
                        r["seg"] = r["d"]
                    if not r.get("seg"):
                        r["seg"] = parsed.get("dest")

                has_mob = any(x["mob"] is not None for x in parsed["rows"])
                parsed["rows"].sort(
                    key=lambda a: (
                        (999 if a.get("msca") else (a["mob"] or 99)) if has_mob else ORDER_MAP.get(a["p"], 3),
                        a.get("d", ""),
                    )
                )
                st.session_state["parsed_booking"] = parsed
        except Exception as e:
            st.error(f"Fehler beim Lesen: {e}")

    if "parsed_booking" in st.session_state:
        pb = st.session_state["parsed_booking"]
        ts = sum(x["stk"] for x in pb["rows"])
        tk = sum(x["kg"] for x in pb["rows"])
        st.success(
            f"**{pb.get('code', 'FLUG')} · {pb.get('date', '')} · {pb.get('ac', '')}** → {pb.get('dest', '?')}\n\n"
            f"{len(pb['rows'])} Sendungen · {ts} Stk · {fmt_num(tk)} kg"
        )
        if pb.get("info"):
            st.info(pb["info"])

        if st.button("✓ Stimmt – Flug übernehmen", type="primary", use_container_width=True):
            code = re.sub(r"\s+", "", str(pb.get("code") or "FLUG")).upper()
            date_digits = re.sub(r"\D+", "", str(pb.get("date") or ""))
            fl_key = f"{code}_{date_digits}" if date_digits else code
            segs = pb.get("segs") if isinstance(pb.get("segs"), list) and len(pb["segs"]) > 1 else None
            sub = pb.get("info") or ""
            if segs:
                sub = (sub + " · " if sub else "") + f"{'→'.join(segs)} · nicht mischen!"

            st.session_state.flights[fl_key] = {
                "code": code,
                "date": pb.get("date") or "",
                "title": f"{code} · {pb.get('date', '')} · {pb.get('ac', '')}",
                "sub": sub,
                "dest": str(pb.get("dest") or "").upper(),
                "segs": segs,
                "data": pb["rows"],
            }
            st.session_state.current_fl = fl_key
            del st.session_state["parsed_booking"]
            save_persisted_data()
            st.rerun()

# ===== AUTOMATISCHES SPEICHERN NACH JEDER ÄNDERUNG =====
save_persisted_data()
