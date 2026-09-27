"""Streamlit UI.  Run:  streamlit run frontend/streamlit_app.py  (with the Flask API running)"""
import os

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

API_URL = os.getenv("RAAHAT_API_URL", "http://127.0.0.1:5000")

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

TIER_TEXT = {
    "specialist": "Best match — has the right specialists",
    "can_manage": "Can likely manage — related specialty",
    "stabilize": "Emergency care only — will likely refer you on",
    "unsuitable": "Not equipped for this injury",
}

TIER_COLOR = {
    "specialist": "green",
    "can_manage": "orange",
    "stabilize": "red",
    "unsuitable": "gray",
}

MAP_TIER_COLOR = {
    "specialist": "green",
    "can_manage": "orange",
    "stabilize": "red",
    "unsuitable": "lightgray",
}

TYPE_LABEL = {
    "govt": "Government",
    "charitable": "Charitable",
    "empanelled_private": "Private (Aarogyasri-empanelled)",
    "private": "Private",
}


st.set_page_config(page_title="Raahat", page_icon="✚", layout="wide")
st.markdown(
    """
    <style>
    :root { --raahat-teal: #0f766e; }
    [data-testid="stAppViewContainer"] { background: #fbfcfc; }
    [data-testid="stMarkdownContainer"] { font-size: 1rem; }
    h1, h2, h3 { color: var(--raahat-teal); }
    .stButton > button { background: #0f766e; color: white; border: 0; }
    .stButton > button:hover { background: #115e59; color: white; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-color: #dbe5e3; }
    @media (max-width: 640px) {
        [data-testid="stHorizontalBlock"] { flex-direction: column; gap: 0.5rem; }
        [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _response_error(response):
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return f"Request failed (HTTP {response.status_code})."


def _fetch_list(path):
    response = requests.get(f"{API_URL}{path}", timeout=15)
    if not response.ok:
        raise RuntimeError(_response_error(response))
    try:
        items = response.json()
    except ValueError as exc:
        raise RuntimeError(f"The server returned an unreadable {path} response.") from exc
    if not isinstance(items, list):
        raise RuntimeError(f"The server returned an invalid {path} response.")
    return items


@st.cache_data(ttl=300)
def fetch_injuries():
    return _fetch_list("/api/injuries")


@st.cache_data(ttl=300)
def fetch_situations():
    return _fetch_list("/api/situations")


def _show_connection_error():
    st.error("Cannot connect to the Raahat server. Please try again when the server is available.")
    st.stop()


def _escape_html(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _distance_text(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _empanelment_line(facility):
    if facility.get("aarogyasri_empanelled"):
        return "✅ Listed as Aarogyasri-empanelled — confirm at the hospital's Aarogyasri desk"
    return "❌ Not Aarogyasri-empanelled — Aarogyasri cashless treatment won't apply here"


def build_map(origin, results):
    map_view = folium.Map(
        location=[origin["lat"], origin["lng"]],
        zoom_start=13,
        tiles="cartodbpositron",
    )
    folium.Marker(
        location=[origin["lat"], origin["lng"]],
        tooltip="You are here",
        icon=folium.Icon(color="blue", icon="user", prefix="glyphicon"),
    ).add_to(map_view)

    for facility in results:
        tier = facility.get("tier", "unsuitable")
        tier_text = TIER_TEXT.get(tier, tier)
        type_text = TYPE_LABEL.get(facility.get("type"), facility.get("type", ""))
        empanelment = _empanelment_line(facility)
        reasons = facility.get("reasons") or []
        reason_html = "<br>".join(
            f"• {_escape_html(reason)}" for reason in reasons
        ) or "No ranking reasons provided."

        popup_html = (
            f"<strong>{_escape_html(facility.get('name', ''))}</strong><br>"
            f"Tier: {_escape_html(tier_text)}<br>"
            f"Type: {_escape_html(type_text)}<br>"
            f"Distance: {_escape_html(_distance_text(facility.get('distance_km')))} km<br>"
            f"{_escape_html(empanelment)}<br>"
            f"Reasons:<br>{reason_html}"
        )

        folium.Marker(
            location=[facility["lat"], facility["lng"]],
            tooltip=f"#{facility.get('rank', '')} {facility.get('name', '')}",
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(
                color=MAP_TIER_COLOR.get(tier, "lightgray"),
                icon="ok-sign" if facility.get("aarogyasri_empanelled") else "remove-sign",
                prefix="glyphicon",
            ),
        ).add_to(map_view)

    return map_view


def run_search(injury, lat, lng, radius_km):
    for key in ("triage_data", "search_map", "entitlements_data", "entitlements_facility_id"):
        st.session_state.pop(key, None)

    try:
        response = requests.post(
            f"{API_URL}/api/triage",
            json={
                "injury": injury["key"],
                "lat": lat,
                "lng": lng,
                "radius_km": radius_km,
            },
            timeout=30,
        )
    except requests.exceptions.Timeout:
        st.error("The Raahat server did not respond in time. Please try again.")
        st.stop()
    except requests.exceptions.RequestException:
        _show_connection_error()

    if not response.ok:
        st.error(_response_error(response))
        st.stop()

    try:
        data = response.json()
    except ValueError:
        st.error("The server returned an unreadable search response.")
        st.stop()

    st.session_state.triage_data = data
    st.session_state.search_map = build_map(data["origin"], data.get("results", []))


def render_card(facility):
    tier = facility.get("tier", "unsuitable")
    tier_text = TIER_TEXT.get(tier, tier)
    tier_color = TIER_COLOR.get(tier, "gray")
    type_text = TYPE_LABEL.get(facility.get("type"), facility.get("type", ""))
    locality = facility.get("locality", "")
    distance = _distance_text(facility.get("distance_km"))

    with st.container(border=True):
        st.markdown(f"**#{facility.get('rank', '')} {facility.get('name', '')}**")
        st.markdown(f":{tier_color}[{tier_text}]")
        st.write(f"{type_text} · {locality} · {distance} km")
        st.write(_empanelment_line(facility))
        with st.expander("Why this ranking"):
            reasons = facility.get("reasons") or []
            if reasons:
                for reason in reasons:
                    st.markdown(f"- {reason}")
            else:
                st.write("No ranking reasons provided.")


def render_entitlements(data):
    with st.container(border=True):
        st.markdown(data.get("explanation", ""))
    sources = data.get("sources") or []
    with st.expander("Sources used"):
        for source in sources:
            st.markdown(
                f"**{source.get('title', '')}**\n\n{source.get('citation', '')}"
            )
    model = data.get("model") or {}
    if model.get("generation") is not None:
        st.caption(
            f"Generated by {model.get('generation')} · retrieval via {model.get('embedding')}"
        )


st.title("Raahat")
st.markdown("Find the right emergency care — and know your options")
st.caption("Hyderabad district · prototype")

st.error("**Life-threatening emergency? Call 108 for an ambulance first.**")
st.warning(
    "Demo data: facility names are fictional and capabilities/empanelment are synthetic. "
    "Do not use for real medical decisions."
)

try:
    injuries = fetch_injuries()
    situations = fetch_situations()
except requests.exceptions.Timeout:
    st.error("The Raahat server did not respond in time. Please try again.")
    st.stop()
except requests.exceptions.RequestException:
    _show_connection_error()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if not injuries:
    st.error("No injuries are available from the server right now.")
    st.stop()

with st.container(border=True):
    st.subheader("Find emergency care")
    with st.form("raahat_search_form"):
        injury_index = st.selectbox(
            "Injury",
            options=list(range(len(injuries))),
            format_func=lambda index: injuries[index]["label"],
        )
        locality = st.selectbox(
            "Your location",
            options=list(LOCALITIES.keys()),
            index=list(LOCALITIES.keys()).index("Charminar"),
        )

        default_lat, default_lng = LOCALITIES[locality]
        with st.expander("Use exact coordinates"):
            use_exact_coordinates = st.checkbox("Override location coordinates")
            exact_lat = st.number_input(
                "Latitude",
                value=float(default_lat),
                step=0.0001,
                format="%.4f",
            )
            exact_lng = st.number_input(
                "Longitude",
                value=float(default_lng),
                step=0.0001,
                format="%.4f",
            )

        radius_km = st.slider("Search radius (km)", min_value=2, max_value=30, value=20)
        search_submitted = st.form_submit_button("Find hospitals", type="primary")

if search_submitted:
    selected_injury = injuries[injury_index]
    search_lat = exact_lat if use_exact_coordinates else default_lat
    search_lng = exact_lng if use_exact_coordinates else default_lng
    run_search(selected_injury, search_lat, search_lng, radius_km)

if "triage_data" not in st.session_state:
    st.info("Choose an injury and location, then press “Find hospitals”.")
else:
    triage_data = st.session_state.triage_data
    results = triage_data.get("results", [])
    selected_injury = triage_data.get("injury", {})
    injury_label = selected_injury.get("label", "")

    st.markdown(f"**{injury_label}** — {len(results)} facilities found")

    specialists = [facility for facility in results if facility.get("tier") == "specialist"]
    nearest_specialist = None
    if specialists:
        nearest_specialist = min(
            specialists,
            key=lambda facility: float(facility.get("distance_km", float("inf"))),
        )
    empanelled_specialists = sum(
        1
        for facility in specialists
        if facility.get("aarogyasri_empanelled")
    )

    metric_columns = st.columns(3)
    metric_columns[0].metric("Specialist results", len(specialists))
    metric_columns[1].metric(
        "Nearest specialist distance (km)",
        _distance_text(nearest_specialist.get("distance_km"))
        if nearest_specialist
        else "—",
    )
    metric_columns[2].metric(
        "Aarogyasri-empanelled specialists",
        empanelled_specialists,
    )

    map_column, list_column = st.columns([3, 2])
    with map_column:
        st_folium(
            st.session_state.search_map,
            height=500,
            use_container_width=True,
            returned_objects=[],
            key="raahat_results_map",
        )
        st.markdown(
            "**Map legend:** Green — specialist · Orange — can manage · "
            "Red — stabilize · Light gray — unsuitable  \n"
            "✓ — Aarogyasri-empanelled · ✗ — not Aarogyasri-empanelled"
        )

    with list_column:
        st.subheader("Nearby facilities")
        for facility in results[:8]:
            render_card(facility)

    st.header("What you may be eligible for")
    st.caption(
        "Generated by Gemini from the Clinical Establishments Act, a Supreme Court judgment, "
        "Aarogyasri and the BOCW Welfare Board rules. This is general information, not legal advice."
    )

    if results:
        with st.form("raahat_entitlements_form"):
            facility_index = st.selectbox(
                "Hospital you are going to / went to",
                options=list(range(len(results))),
                format_func=lambda index: (
                    f"#{results[index].get('rank', '')} {results[index].get('name', '')}"
                ),
            )
            situation_keys = st.multiselect(
                "Which of these apply to you? (optional)",
                options=[s["key"] for s in situations],
                format_func={s["key"]: s["label"] for s in situations}.get,
                help="Ticking these helps show only the schemes and laws relevant to you.",
            )
            situation = st.text_area(
                "Anything else about you?",
                placeholder="e.g. was injured at a house construction site, family of 5",
                max_chars=500,
            )
            explain_submitted = st.form_submit_button("Explain my options")

        if explain_submitted:
            facility = results[facility_index]
            st.session_state.pop("entitlements_data", None)
            st.session_state.pop("entitlements_facility_id", None)
            request_body = {
                "injury": selected_injury["key"],
                "facility_id": facility["id"],
                "situations": situation_keys,
            }
            if situation.strip():
                request_body["situation"] = situation.strip()

            try:
                with st.spinner("Checking schemes and laws that may apply…"):
                    response = requests.post(
                        f"{API_URL}/api/entitlements",
                        json=request_body,
                        timeout=90,
                    )
            except requests.exceptions.Timeout:
                st.error("The Raahat server did not respond in time. Please try again.")
                st.stop()
            except requests.exceptions.RequestException:
                _show_connection_error()

            if not response.ok:
                st.error(_response_error(response))
                st.stop()

            try:
                entitlements_data = response.json()
            except ValueError:
                st.error("The server returned an unreadable entitlements response.")
                st.stop()

            st.session_state.entitlements_data = entitlements_data
            st.session_state.entitlements_facility_id = facility["id"]

        chosen_facility_id = results[facility_index].get("id")
        if (
            "entitlements_data" in st.session_state
            and st.session_state.get("entitlements_facility_id") == chosen_facility_id
        ):
            render_entitlements(st.session_state.entitlements_data)
    else:
        st.info("No facilities were found for this search.")
