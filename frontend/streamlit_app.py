"""Streamlit UI.  Run:  streamlit run frontend/streamlit_app.py  (with the Flask API running)"""
import os

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

API_URL = os.getenv("RAAHAT_API_URL", "http://127.0.0.1:5000")

# Approximate centres of Hyderabad localities, for users who don't know coordinates.
LOCALITIES = {
    "Afzalgunj": (17.3713, 78.4804),
    "Amberpet": (17.3920, 78.5170),
    "Banjara Hills": (17.4156, 78.4347),
    "Begumpet": (17.4440, 78.4630),
    "Chandrayangutta": (17.3200, 78.4800),
    "Charminar": (17.3616, 78.4747),
    "Golconda": (17.3833, 78.4011),
    "Himayatnagar": (17.4010, 78.4870),
    "Khairatabad": (17.4120, 78.4610),
    "Malakpet": (17.3764, 78.5006),
    "Mehdipatnam": (17.3960, 78.4390),
    "Musheerabad": (17.4180, 78.5000),
    "Nampally": (17.3924, 78.4675),
    "Santoshnagar": (17.3480, 78.5140),
    "Secunderabad": (17.4399, 78.4983),
    "Tolichowki": (17.3990, 78.4150),
}

TIERS = {
    "specialist": ("green", "Best match — has the right specialists"),
    "can_manage": ("orange", "Can likely manage — related specialty"),
    "stabilize": ("red", "Emergency care only — will likely refer you on"),
    "unsuitable": ("lightgray", "Not equipped for this injury"),
}
TYPE_LABELS = {"govt": "Government", "charitable": "Charitable",
               "empanelled_private": "Private (Aarogyasri-empanelled)", "private": "Private"}

st.set_page_config(page_title="Raahat — Emergency Care Finder", page_icon="🩹", layout="wide")
st.title("🩹 Raahat — find the right emergency care")
st.caption("Hyderabad district · prototype")
st.error("**Life-threatening emergency? Call 108 for an ambulance first.**")
st.warning("Demo data: facility names are fictional and capabilities/empanelment are "
           "synthetic. Do not use for real medical decisions.", icon="⚠️")


@st.cache_data(ttl=300)
def fetch_injuries():
    return requests.get(f"{API_URL}/api/injuries", timeout=5).json()


try:
    injuries = fetch_injuries()
except requests.RequestException:
    st.error(f"Can't reach the backend at {API_URL}. Start it with `python -m backend.app`.")
    st.stop()

with st.sidebar:
    st.header("Your situation")
    injury = st.selectbox("What happened?", injuries, format_func=lambda i: i["label"])
    locality = st.selectbox("Where are you?", list(LOCALITIES), index=list(LOCALITIES).index("Charminar"))
    lat, lng = LOCALITIES[locality]
    with st.expander("Use exact coordinates instead"):
        if st.checkbox("Override locality"):
            lat = st.number_input("Latitude", value=lat, format="%.4f")
            lng = st.number_input("Longitude", value=lng, format="%.4f")
    radius = st.slider("Search radius (km)", 2, 30, 20)
    find = st.button("Find facilities", type="primary", use_container_width=True)

if find:
    resp = requests.post(f"{API_URL}/api/triage", timeout=10,
                         json={"injury": injury["key"], "lat": lat, "lng": lng, "radius_km": radius})
    if resp.ok:
        st.session_state["result"] = resp.json()
    else:
        st.error(resp.json().get("error", "Request failed"))

result = st.session_state.get("result")
if not result:
    st.info("Choose the injury and your location in the sidebar, then press **Find facilities**.")
    st.stop()

facilities = result["results"]
origin = result["origin"]
st.subheader(f"{result['injury']['label']} — {len(facilities)} facilities within range")

map_col, list_col = st.columns([3, 2])

with map_col:
    fmap = folium.Map(location=[origin["lat"], origin["lng"]], zoom_start=13, tiles="cartodbpositron")
    folium.Marker([origin["lat"], origin["lng"]], tooltip="You are here",
                  icon=folium.Icon(color="blue", icon="user")).add_to(fmap)
    for f in facilities:
        colour, tier_text = TIERS[f["tier"]]
        empanelled = "✅ Aarogyasri-empanelled" if f["aarogyasri_empanelled"] else "❌ Not Aarogyasri-empanelled"
        popup = (f"<b>#{f['rank']} {f['name']}</b><br>{tier_text}<br>"
                 f"{TYPE_LABELS[f['type']]} · {f['distance_km']} km<br>{empanelled}<br><br>"
                 + "<br>".join(f"• {r}" for r in f["reasons"]))
        folium.Marker(
            [f["lat"], f["lng"]],
            tooltip=f"#{f['rank']} {f['name']}",
            popup=folium.Popup(popup, max_width=300),
            icon=folium.Icon(color=colour, icon="ok-sign" if f["aarogyasri_empanelled"] else "remove-sign"),
        ).add_to(fmap)
    st_folium(fmap, height=560, use_container_width=True, returned_objects=[])
    st.markdown(
        " &nbsp; ".join(f":{'gray' if c == 'lightgray' else c}[●] {t}" for c, t in TIERS.values())
        + "<br>Marker symbol: ✓ = Aarogyasri-empanelled, ✗ = not empanelled",
        unsafe_allow_html=True,
    )

with list_col:
    for f in facilities[:8]:
        colour, tier_text = TIERS[f["tier"]]
        with st.container(border=True):
            st.markdown(f"**#{f['rank']} {f['name']}**  \n"
                        f":{'gray' if colour == 'lightgray' else colour}[{tier_text}]")
            st.caption(f"{TYPE_LABELS[f['type']]} · {f['locality']} · {f['distance_km']} km")
            if f["aarogyasri_empanelled"]:
                st.markdown("✅ Listed as Aarogyasri-empanelled — confirm at the hospital's Aarogyasri desk")
            else:
                st.markdown("❌ Not Aarogyasri-empanelled — Aarogyasri cashless treatment won't apply here")
            with st.expander("Why this ranking"):
                for r in f["reasons"]:
                    st.markdown(f"- {r}")
