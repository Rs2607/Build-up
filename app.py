import streamlit as st

# Grundkonfiguration der App
st.set_page_config(page_title="Cargo Build", page_icon="📦", layout="centered")

# Unser vereinbartes Design (CSS) einfügen
st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(135deg, #071426, #0c2a47);
        color: #f7fbff;
    }
    .main-btn > button {
        background-color: #38dfe2 !important;
        color: #06213b !important;
        font-weight: 800 !important;
        font-size: 18px !important;
        padding: 20px !important;
        border-radius: 12px !important;
        width: 100%;
        border: none !important;
    }
    .flight-card {
        background-color: #112b46;
        border: 1px solid #294968;
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- STARTSEITE ---
st.markdown("### 📦 CARGO BUILD")
st.title("Hallo.")
st.write("Bereit für deinen nächsten Aufbau? Arbeite ruhig, aufmerksam und sicher.")
st.write("")

# Hauptaktion
st.markdown('<div class="main-btn">', unsafe_allow_html=True)
if st.button("📷 Neue Buchungsliste fotografieren"):
    st.info("Hier öffnet sich später die Kamera-Erkennung.")
st.markdown('</div>', unsafe_allow_html=True)

st.write("---")
st.subheader("Offene Flüge")

# Beispiel-Karte für einen offenen Flug
st.markdown("""
    <div class="flight-card">
        <strong style="font-size: 18px; color: #38dfe2;">XX001 · AAA ➔ BBB</strong><br>
        <span style="color: #aac2df; font-size: 14px;">Zuletzt bearbeitet: Heute, 10:15</span><br><br>
        <strong style="color: #38dfe2;">Aufbau läuft</strong> · 24 von 80 Stück
    </div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="flight-card">
        <strong style="font-size: 18px; color: #ffb84d;">YY002 · CCC ➔ DDD</strong><br>
        <span style="color: #aac2df; font-size: 14px;">Zuletzt bearbeitet: Gestern, 17:40</span><br><br>
        <strong style="color: #38dfe2;">Aufbau läuft</strong> · 51 von 96 Stück
    </div>
""", unsafe_allow_html=True)
