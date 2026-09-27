"""Streamlit UI.  Run:  streamlit run frontend/streamlit_app.py  (with the Flask API running)"""
import os
import sys

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import LANGUAGES, RTL, STRINGS, t  # noqa: E402

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

_, lang_col = st.columns([4, 1])
with lang_col:
    LANG = st.selectbox("Language / भाषा / భాష / زبان", list(LANGUAGES),
                        format_func=LANGUAGES.get, key="lang")
if LANG in RTL:
    st.markdown("<style>[data-testid='stMarkdownContainer'], [data-testid='stAlert'] "
                "{ direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)


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


def _label(kind, item):
    """Localized label for an injury/situation from the API; falls back to the API's own label."""
    key = f"{kind}.{item.get('key')}"
    return t(LANG, key) if key in STRINGS["en"] else item.get("label", "")


def _show_connection_error():
    st.error(t(LANG, "cannot_connect"))
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
        return t(LANG, "emp.yes")
    return t(LANG, "emp.no")


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
        tier_text = t(LANG, f"tier.{tier}")
        type_text = t(LANG, f"type.{facility.get('type')}")
        empanelment = _empanelment_line(facility)
        reasons = facility.get("reasons") or []
        reason_html = "<br>".join(
            f"• {_escape_html(reason)}" for reason in reasons
        ) or t(LANG, "no_reasons")

        popup_html = (
            f"<strong>{_escape_html(facility.get('name', ''))}</strong><br>"
            f"{_escape_html(tier_text)}<br>"
            f"{_escape_html(type_text)} · {_escape_html(_distance_text(facility.get('distance_km')))} km<br>"
            f"{_escape_html(empanelment)}<br><br>"
            f"{reason_html}"
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
        st.error(t(LANG, "timeout"))
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
    tier_text = t(LANG, f"tier.{tier}")
    tier_color = TIER_COLOR.get(tier, "gray")
    type_text = t(LANG, f"type.{facility.get('type')}")
    locality = facility.get("locality", "")
    distance = _distance_text(facility.get("distance_km"))

    with st.container(border=True):
        st.markdown(f"**#{facility.get('rank', '')} {facility.get('name', '')}**")
        st.markdown(f":{tier_color}[{tier_text}]")
        st.write(f"{type_text} · {locality} · {distance} km")
        st.write(_empanelment_line(facility))
        with st.expander(t(LANG, "why_ranking")):
            reasons = facility.get("reasons") or []
            if reasons:
                if LANG != "en":
                    st.caption(t(LANG, "reasons_english_note"))
                for reason in reasons:
                    st.markdown(f"- {reason}")
            else:
                st.write(t(LANG, "no_reasons"))


def render_entitlements(data):
    translated = data.get("explanation_translated")
    english = data.get("explanation", "")
    with st.container(border=True):
        if translated:
            st.caption(t(LANG, "mt_label"))
            st.markdown(translated)
        else:
            if LANG != "en" and data.get("generated"):
                st.caption(t(LANG, "translation_failed"))
            st.markdown(english)
    if translated:
        with st.expander(t(LANG, "show_english")):
            st.markdown(english)
    sources = data.get("sources") or []
    with st.expander(t(LANG, "sources_used")):
        for source in sources:
            st.markdown(
                f"**{source.get('title', '')}**\n\n{source.get('citation', '')}"
            )
    model = data.get("model") or {}
    if model.get("generation") is not None:
        st.caption(t(LANG, "generated_by", gen=model.get("generation"), emb=model.get("embedding")))


st.title("Raahat")
st.markdown(t(LANG, "tagline"))
st.caption(t(LANG, "caption"))

st.error(t(LANG, "banner_108"))
st.warning(t(LANG, "demo_warning"))

try:
    injuries = fetch_injuries()
    situations = fetch_situations()
except requests.exceptions.Timeout:
    st.error(t(LANG, "timeout"))
    st.stop()
except requests.exceptions.RequestException:
    _show_connection_error()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if not injuries:
    st.error("No injuries are available from the server right now.")
    st.stop()


def understand_description(text):
    """Ask the backend to read a free-text description; store suggestions to pre-fill the forms."""
    try:
        with st.spinner(t(LANG, "understanding")):
            response = requests.post(f"{API_URL}/api/understand", json={"text": text}, timeout=60)
    except requests.exceptions.RequestException:
        _show_connection_error()
    if not response.ok:
        st.session_state.understood = {"error": _response_error(response)}
        return
    st.session_state.understood = response.json()
    st.session_state.understood["text"] = text


with st.container(border=True):
    st.subheader(t(LANG, "describe_header"))
    with st.form("raahat_describe_form"):
        description = st.text_area(t(LANG, "describe_label"), placeholder=t(LANG, "describe_placeholder"),
                                   max_chars=1000)
        if st.form_submit_button(t(LANG, "understand_button")) and description.strip():
            understand_description(description.strip())

understood = st.session_state.get("understood") or {}
if understood.get("life_threatening_signs"):
    st.error(t(LANG, "urgent"))
if understood.get("error"):
    st.warning(understood["error"])
elif understood:
    injury_keys = [i["key"] for i in injuries]
    if understood.get("injury") in injury_keys:
        picked = injuries[injury_keys.index(understood["injury"])]
        st.success(t(LANG, "understood", injury=_label("injury", picked), button=t(LANG, "find_button")))
    else:
        st.info(t(LANG, "not_understood"))

prefill_injury = understood.get("injury")
prefill_index = next((i for i, item in enumerate(injuries) if item["key"] == prefill_injury), 0)

with st.container(border=True):
    st.subheader(t(LANG, "find_care"))
    with st.form("raahat_search_form"):
        injury_index = st.selectbox(
            t(LANG, "injury"),
            options=list(range(len(injuries))),
            index=prefill_index,
            format_func=lambda index: _label("injury", injuries[index]),
        )
        locality = st.selectbox(
            t(LANG, "location"),
            options=list(LOCALITIES.keys()),
            index=list(LOCALITIES.keys()).index("Charminar"),
        )

        default_lat, default_lng = LOCALITIES[locality]
        with st.expander(t(LANG, "exact_coords")):
            use_exact_coordinates = st.checkbox(t(LANG, "override_coords"))
            exact_lat = st.number_input(
                t(LANG, "latitude"),
                value=float(default_lat),
                step=0.0001,
                format="%.4f",
            )
            exact_lng = st.number_input(
                t(LANG, "longitude"),
                value=float(default_lng),
                step=0.0001,
                format="%.4f",
            )

        radius_km = st.slider(t(LANG, "radius"), min_value=2, max_value=30, value=20)
        search_submitted = st.form_submit_button(t(LANG, "find_button"), type="primary")

if search_submitted:
    selected_injury = injuries[injury_index]
    search_lat = exact_lat if use_exact_coordinates else default_lat
    search_lng = exact_lng if use_exact_coordinates else default_lng
    run_search(selected_injury, search_lat, search_lng, radius_km)

if "triage_data" not in st.session_state:
    st.info(t(LANG, "start_info"))
else:
    triage_data = st.session_state.triage_data
    results = triage_data.get("results", [])
    selected_injury = triage_data.get("injury", {})
    injury_label = _label("injury", selected_injury)

    st.markdown(t(LANG, "found", label=injury_label, n=len(results)))

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
    metric_columns[0].metric(t(LANG, "metric_specialists"), len(specialists))
    metric_columns[1].metric(
        t(LANG, "metric_nearest"),
        _distance_text(nearest_specialist.get("distance_km"))
        if nearest_specialist
        else "—",
    )
    metric_columns[2].metric(
        t(LANG, "metric_empanelled"),
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
        st.markdown(t(LANG, "legend"))

    with list_column:
        st.subheader(t(LANG, "nearby"))
        for facility in results[:8]:
            render_card(facility)

    st.header(t(LANG, "eligible_header"))
    st.caption(t(LANG, "eligible_caption"))

    if results:
        situation_by_key = {s["key"]: s for s in situations}
        with st.form("raahat_entitlements_form"):
            facility_index = st.selectbox(
                t(LANG, "hospital_select"),
                options=list(range(len(results))),
                format_func=lambda index: (
                    f"#{results[index].get('rank', '')} {results[index].get('name', '')}"
                ),
            )
            situation_keys = st.multiselect(
                t(LANG, "situations_q"),
                options=list(situation_by_key),
                format_func=lambda key: _label("situation", situation_by_key[key]),
                default=[k for k in understood.get("situations", []) if k in situation_by_key],
                help=t(LANG, "situations_help"),
            )
            situation = st.text_area(
                t(LANG, "anything_else"),
                value=(understood.get("text") or "")[:500],
                placeholder=t(LANG, "anything_placeholder"),
                max_chars=500,
            )
            explain_submitted = st.form_submit_button(t(LANG, "explain_button"))

        if explain_submitted:
            facility = results[facility_index]
            st.session_state.pop("entitlements_data", None)
            st.session_state.pop("entitlements_facility_id", None)
            request_body = {
                "injury": selected_injury["key"],
                "facility_id": facility["id"],
                "situations": situation_keys,
                "language": LANG,
            }
            if situation.strip():
                request_body["situation"] = situation.strip()

            try:
                with st.spinner(t(LANG, "spinner")):
                    response = requests.post(
                        f"{API_URL}/api/entitlements",
                        json=request_body,
                        timeout=90,
                    )
            except requests.exceptions.Timeout:
                st.error(t(LANG, "timeout"))
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
            st.session_state.entitlements_lang = LANG

        chosen_facility_id = results[facility_index].get("id")
        if (
            "entitlements_data" in st.session_state
            and st.session_state.get("entitlements_facility_id") == chosen_facility_id
            and st.session_state.get("entitlements_lang") == LANG
        ):
            render_entitlements(st.session_state.entitlements_data)
    else:
        st.info(t(LANG, "no_facilities"))
