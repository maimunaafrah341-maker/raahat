/* Raahat web client. Talks only to the Flask API on the same origin. */
"use strict";

const LOCALITIES = {
  "Afzalgunj": [17.3713, 78.4804], "Amberpet": [17.3920, 78.5170], "Banjara Hills": [17.4156, 78.4347],
  "Begumpet": [17.4440, 78.4630], "Chandrayangutta": [17.3200, 78.4800], "Charminar": [17.3616, 78.4747],
  "Golconda": [17.3833, 78.4011], "Himayatnagar": [17.4010, 78.4870], "Khairatabad": [17.4120, 78.4610],
  "Malakpet": [17.3764, 78.5006], "Mehdipatnam": [17.3960, 78.4390], "Musheerabad": [17.4180, 78.5000],
  "Nampally": [17.3924, 78.4675], "Santoshnagar": [17.3480, 78.5140], "Secunderabad": [17.4399, 78.4983],
  "Tolichowki": [17.3990, 78.4150],
};
const TIERS = ["specialist", "can_manage", "stabilize", "unsuitable"];
const TIER_COLOR = { specialist: "#16a34a", can_manage: "#f59e0b", stabilize: "#dc2626", unsuitable: "#94a3b8" };

const state = {
  strings: {}, languages: {}, rtl: [], lang: "en",
  injuries: [], situations: [], sources: [], preview: null,
  injury: null, chosenSituations: new Set(), conditionList: [], conditions: new Set(),
  triage: null, selectedId: null, understood: null,
  caseData: null, pending: false, restored: false,
  map: null, markers: {},
};

const $ = (id) => document.getElementById(id);

/* ---------- helpers ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function t(key, params) {
  let s = state.strings[state.lang]?.[key] || state.strings.en?.[key] || "";
  for (const [k, v] of Object.entries(params || {})) s = s.replaceAll(`{${k}}`, v);
  return s;
}
// Minimal markdown for our own strings and Gemini output: bold, italic, [citations], line breaks.
function inlineMd(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])[_*]([^_*\n]+)[_*](?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
    .replace(/ {2}\n/g, "<br>");
}
function renderExplanation(text) {
  const blocks = String(text || "").split(/\n\s*\n|\n(?=\s*[*-] )/).map((b) => b.trim()).filter(Boolean);
  const bullets = [], paras = [];
  for (const b of blocks) {
    const m = b.match(/^[*-]\s+([\s\S]*)$/);
    (m ? bullets : paras).push(m ? m[1] : b);
  }
  // Every [Source title] becomes a badge, wherever Gemini placed it in the bullet.
  const withCites = (s) => inlineMd(s).replace(/\s*\[([^\]]+)\]\.?/g, (_, c) => ` <span class="cite">${c}</span>`);
  let html = "";
  if (bullets.length) html += `<ul>${bullets.map((b) => `<li>${withCites(b)}</li>`).join("")}</ul>`;
  if (paras.length) html += paras.map((p) => `<p>${withCites(p)}</p>`).join("");
  return html;
}
function toast(msg) {
  const el = $("toast");
  el.textContent = msg; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.hidden = true), 6000);
}
function busy(btn, on) {
  btn.disabled = on;
  const sp = btn.querySelector(".spinner");
  if (on && !sp) btn.insertAdjacentHTML("afterbegin", '<span class="spinner" aria-hidden="true"></span>');
  if (!on && sp) sp.remove();
}
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

async function api(path, body, timeoutMs = 30000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(path, body === undefined ? { signal: ctrl.signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctrl.signal,
    });
  } catch (e) {
    throw new Error(t(e.name === "AbortError" ? "timeout" : "cannot_connect"));
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) throw new Error(data?.error || t("cannot_connect"));
  return data;
}

/* ---------- language ---------- */
function applyLanguage() {
  const html = document.documentElement;
  html.lang = state.lang;
  html.dir = state.rtl.includes(state.lang) ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-md]").forEach((el) => (el.innerHTML = inlineMd(t(el.dataset.i18nMd))));
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  const [a, b] = t("tagline").split(/\s+—\s+/);
  $("title-a").textContent = a || "";
  $("title-b").textContent = b || "";
  renderInjuryControls();
  renderLegend();
  renderPreview();
  renderSteps();
  renderUnderstood();
  if (state.triage) renderResults();
  if (state.triage) renderEntitlementForm();
  renderChat();
}

/* ---------- injury choice (select + tiles stay in sync) ---------- */
function injuryLabel(item) { return t(`injury.${item.key}`) || item.label; }
const GROUPS = ["injury", "illness"];
function renderInjuryControls() {
  const sel = $("injury");
  const inGroup = (g) => state.injuries.filter((i) => i.group === g);
  sel.innerHTML = GROUPS.map((g) => `<optgroup label="${esc(t(`group.${g}`))}">${
    inGroup(g).map((i) => `<option value="${esc(i.key)}">${esc(injuryLabel(i))}</option>`).join("")}</optgroup>`).join("");
  sel.value = state.injury;
  renderConditionChips();
}
// Who the patient is (pregnant, on chemotherapy...): adds danger-sign cards and tells the crew.
function renderConditionChips() {
  $("cond-chips").innerHTML = state.conditionList.map((c) =>
    `<button type="button" class="chip" data-key="${esc(c.key)}" aria-pressed="${state.conditions.has(c.key)}">${esc(t(`condition.${c.key}`) || c.label)}</button>`).join("");
}
// An emergency that already says who the patient is.
const IMPLIED_CONDITION = { pregnancy_problem: "pregnant", child_unwell: "young_child", chemo_fever: "chemotherapy", low_blood_sugar: "diabetes" };
function setInjury(key) {
  state.injury = key;
  $("injury").value = key;
}
// Choosing from the list shows that emergency's first-aid card right away, like describing it does.
function pickInjury(key) {
  setInjury(key);
  const u = state.understood || {};
  state.understood = { injury: key, picked: true, life_threatening_signs: u.life_threatening_signs };
  renderUnderstood();
  renderSteps();
}

/* ---------- describe (free text -> suggestions) ---------- */
async function onDescribe(e) {
  e.preventDefault();
  const text = $("describe-text").value.trim();
  if (!text) return;
  const btn = $("describe-btn");
  busy(btn, true);
  try {
    const res = await api("/api/understand", { text }, 60000);
    state.understood = { ...res, text };
    if (res.injury) setInjury(res.injury);
    state.chosenSituations = new Set(res.situations || []);
    state.conditions = new Set([...(res.conditions || []), ...(IMPLIED_CONDITION[res.injury] ? [IMPLIED_CONDITION[res.injury]] : [])]);
    renderConditionChips();
    $("situation-text").value = text.slice(0, 500);
    renderChips();
  } catch (err) {
    state.understood = { error: err.message };
  } finally {
    busy(btn, false);
  }
  renderUnderstood();
  renderSteps();
  $("understood").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderUnderstood() {
  const u = state.understood;
  const box = $("understood");
  if (!u) { box.innerHTML = ""; return; }
  let html = "";
  if (u.life_threatening_signs) html += `<div class="alert alert--urgent"><svg class="ico"><use href="#i-phone"/></svg><span>${inlineMd(t("urgent"))}</span></div>`;
  if (u.error) html += `<p class="note note--warn">${esc(u.error)}</p>`;
  else if (u.injury) {
    const item = state.injuries.find((i) => i.key === u.injury);
    if (!u.picked) html += `<p class="note note--ok">${inlineMd(t("understood", { injury: item ? injuryLabel(item) : u.injury, button: t("find_button") }))}</p>`;
    html += guideCards(u.injury);
  } else html += `<p class="note note--info">${esc(t("not_understood"))}</p>${guideCards(null)}`;
  box.innerHTML = html;
}

/* ---------- search ---------- */
// The phone's own location is the most accurate start point; the area list is the fallback.
function useMyLocation() {
  const status = $("geo-status");
  if (!navigator.geolocation) { toast(t("flow.geo_fail")); return; }
  status.hidden = false;
  status.textContent = t("flow.locating");
  navigator.geolocation.getCurrentPosition((pos) => {
    $("lat").value = pos.coords.latitude.toFixed(5);
    $("lng").value = pos.coords.longitude.toFixed(5);
    $("use-coords").checked = true;
    status.textContent = `✓ ${t("flow.located")}`;
  }, () => {
    status.hidden = true;
    toast(t("flow.geo_fail"));
  }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
}
function searchOrigin() {
  if ($("use-coords").checked) {
    const lat = parseFloat($("lat").value), lng = parseFloat($("lng").value);
    if (Number.isFinite(lat) && Number.isFinite(lng)) return [lat, lng];
  }
  return LOCALITIES[$("locality").value];
}
async function runSearch({ scroll = true, selectId = null } = {}) {
  const btn = $("search-btn");
  const [lat, lng] = searchOrigin();
  busy(btn, true);
  try {
    state.triage = await api("/api/triage", {
      injury: state.injury, lat, lng, radius_km: Number($("radius").value), conditions: [...state.conditions],
    });
    const ids = state.triage.results.map((f) => f.id);
    state.selectedId = ids.includes(selectId) ? selectId : (ids[0] ?? null);
    $("results").hidden = false;
    $("entitlements").hidden = !state.triage.results.length;
    renderResults();
    renderEntitlementForm();
    renderChat();
    if (scroll) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    busy(btn, false);
  }
}
function onSearch(e) { e.preventDefault(); runSearch(); }

function directionsUrl(f) { return `https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.lng}`; }
function sourceTitle(docId) { return state.sources.find((x) => x.doc_id === docId)?.title || ""; }
function citePill(docId) { const title = sourceTitle(docId); return title ? `<br><span class="cite">${esc(title)}</span>` : ""; }
function tierPill(f) { return `<span class="pill pill--tier" style="--tier:${TIER_COLOR[f.tier]}">${esc(t(`tier.${f.tier}`))}</span>`; }

async function shareFacility(f) {
  const text = t("share_text", { name: f.name, url: directionsUrl(f) });
  try {
    if (navigator.share) { await navigator.share({ text }); return; }
  } catch { return; /* user cancelled */ }
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener");
}

function renderPreview() {
  const box = $("preview-list");
  if (!state.preview) { box.innerHTML = ""; return; }
  const item = state.injuries.find((i) => i.key === state.preview.injury.key);
  $("preview-injury").textContent = t("preview_near", { injury: item ? injuryLabel(item) : "", place: "Charminar" });
  $("preview-badge").textContent = t("preview_badge");
  box.innerHTML = state.preview.results.slice(0, 4).map((f) => `
    <li class="preview__row">
      <span class="preview__rank">${f.rank}</span>
      <div>
        <div class="preview__name">${esc(f.name)}</div>
        <div class="preview__meta">${tierPill(f)}<span>${Number(f.distance_km).toFixed(1)} km</span></div>
      </div>
      <span class="emp-badge emp-badge--${empKey(f)}" title="Aarogyasri">${EMP_MARK[empKey(f)]}</span>
    </li>`).join("");
  $("preview-foot").textContent = `${state.sources.filter((x) => x.kind === "legal").length} ${t("stat.sources")}`;
}

// Sourced cards: first aid for the emergency, danger signs for who the patient is. Never generated.
const guideCache = {};
function loadGuide(kind, key) {
  const cacheKey = `${kind}:${key}:${state.lang}`;
  if (guideCache[cacheKey] === undefined) {
    guideCache[cacheKey] = null; // loading
    const q = kind === "injury" ? `first_aid?injury=` : `danger_signs?condition=`;
    api(`/api/${q}${encodeURIComponent(key)}&language=${state.lang}`, undefined, 90000)
      .then((c) => { guideCache[cacheKey] = c; renderSteps(); renderUnderstood(); })
      .catch(() => { delete guideCache[cacheKey]; });
  }
  return guideCache[cacheKey];
}
function guideCards(injuryKey) {
  const wanted = [...(injuryKey ? [["injury", injuryKey]] : []), ...[...state.conditions].map((c) => ["condition", c])];
  const seen = new Set();
  let html = "";
  for (const [kind, key] of wanted) {
    const card = loadGuide(kind, key);
    if (!card || seen.has(card.doc_id)) continue; // e.g. pregnancy problem + pregnant: one card
    seen.add(card.doc_id);
    html += guideCardHtml(card);
  }
  return html;
}
function guideCardHtml(card) {
  const danger = card.kind === "danger";
  const list = danger ? "ul" : "ol";
  return `<div class="firstaid${danger ? " firstaid--danger" : ""}">
    <div class="firstaid__head"><p class="firstaid__title"><svg class="ico"><use href="#i-${danger ? "alert" : "sparkle"}"/></svg>${esc(t(danger ? "danger.title" : "firstaid.title"))}</p>${speakButton(".firstaid")}</div>
    <${list} class="firstaid__steps">${card.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</${list}>
    <p class="firstaid__dont"><b>${esc(t("firstaid.dont"))}:</b> ${card.cautions.map(esc).join(" ")}</p>
    ${card.translated ? `<details><summary>${esc(t("show_english"))}</summary><${list} class="firstaid__steps english">${card.steps_en.map((x) => `<li>${esc(x)}</li>`).join("")}</${list}></details>` : ""}
    <p class="firstaid__note">${esc(t("firstaid.note"))} <span class="cite">${esc(card.title)}</span></p>
  </div>`;
}

function renderSteps() {
  const box = $("next-steps");
  const f = state.triage?.results.find((x) => x.id === state.selectedId);
  if (!f) { box.innerHTML = ""; return; }
  const urgent = state.understood?.life_threatening_signs;
  const worker = state.chosenSituations.has("construction_worker") || state.chosenSituations.has("informal_worker");
  const go = inlineMd(t("steps.go", { name: f.name, km: Number(f.distance_km).toFixed(1), tier: "%TIER%" }))
    .replace("%TIER%", tierPill(f));
  const who = [...state.conditions].map((c) => t(`condition.${c}`)).join(", ");
  const tell = who ? `<p class="steps__tell">${esc(t("steps.tell", { who }))}</p>` : "";
  const steps = [
    `<li class="${urgent ? "is-urgent" : ""}"><div>${inlineMd(t("steps.call"))}${tell}${guideCards(state.triage.injury.key)}</div></li>`,
    `<li><div>${go}</div></li>`,
    `<li><div>${esc(t("steps.ask"))}${citePill("clinical_establishments_act")}</div></li>`,
    `<li><div>${esc(t(`steps.emp_${empKey(f)}`))}${citePill("telangana_aarogyasri")}</div></li>`,
  ];
  if (worker) steps.push(`<li><div>${esc(t("steps.bocw"))}${citePill("telangana_bocw")}</div></li>`);
  steps.push(`<li><div><a href="#entitlements">${esc(t("steps.more"))}</a></div></li>`);
  box.innerHTML = `
    <div class="steps__head">
      <div><h3>${esc(t("steps.title"))}</h3><p class="steps__for">${esc(t("steps.for", { name: f.name }))}</p></div>
      <div class="steps__actions">
        <a class="btn btn--primary btn--sm" href="${directionsUrl(f)}" target="_blank" rel="noopener"><svg class="ico"><use href="#i-nav"/></svg>${esc(t("directions"))}</a>
        <button type="button" class="btn btn--ghost btn--sm" id="share-btn"><svg class="ico"><use href="#i-share"/></svg>${esc(t("share"))}</button>
        ${speakButton(".steps")}
      </div>
    </div>
    <ol>${steps.join("")}</ol>`;
  $("share-btn").addEventListener("click", () => shareFacility(f));
}

// Aarogyasri status is tri-state: true, false, or null (not verified in our sources).
function empKey(f) { return f.aarogyasri_empanelled === true ? "yes" : f.aarogyasri_empanelled === false ? "no" : "unknown"; }
const EMP_MARK = { yes: "✓", no: "✕", unknown: "?" };
function empLine(f) { return t(`emp.${empKey(f)}`); }
function sourcesBlock(f) {
  if (!f.sources?.length) return "";
  return `<details class="fac__sources"><summary>${esc(t("sources_checked", { date: f.checked_on || "" }))}</summary><ul>${
    f.sources.map((x) => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a></li>`).join("")}</ul></details>`;
}
function typeLine(f) { return `${t(`type.${f.type}`)} · ${f.locality} · ${Number(f.distance_km).toFixed(1)} km`; }

function renderResults() {
  const { results, origin, injury } = state.triage;
  const item = state.injuries.find((i) => i.key === injury.key);
  $("found").innerHTML = inlineMd(t("found", { label: item ? injuryLabel(item) : injury.label, n: results.length }));
  const none = !results.length;
  $("spec-note").hidden = injury.specialist_data && !none;
  $("spec-note").textContent = none ? t("flow.none_near", { km: $("radius").value }) : t("no_specialist_data");
  document.querySelector(".metrics").hidden = !injury.specialist_data || none;
  document.querySelector(".results__grid").hidden = none;

  const specialists = results.filter((f) => f.tier === "specialist");
  $("m-specialists").textContent = specialists.length;
  $("m-nearest").textContent = specialists.length ? Math.min(...specialists.map((f) => f.distance_km)).toFixed(1) : "—";
  $("m-empanelled").textContent = specialists.filter((f) => f.aarogyasri_empanelled === true).length;

  const note = state.lang !== "en" ? `<p class="small">${esc(t("reasons_english_note"))}</p>` : "";
  $("facility-list").innerHTML = results.slice(0, 8).map((f) => `
    <li class="fac" style="--tier:${TIER_COLOR[f.tier]}" data-id="${f.id}" tabindex="0" aria-current="${f.id === state.selectedId}">
      <div class="fac__name"><span class="fac__rank">#${f.rank}</span>${esc(f.name)}</div>
      <span class="pill pill--tier">${esc(t(`tier.${f.tier}`))}</span>
      <p class="fac__meta">${esc(typeLine(f))}</p>
      <p class="fac__emp">${esc(empLine(f))}</p>
      <div class="fac__actions">
        <a class="btn btn--ghost btn--sm" href="${directionsUrl(f)}" target="_blank" rel="noopener"><svg class="ico"><use href="#i-nav"/></svg>${esc(t("directions"))}</a>
      </div>
      <details><summary>${esc(t("why_ranking"))}</summary>${note}
        <ul>${(f.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("") || `<li>${esc(t("no_reasons"))}</li>`}</ul>
      </details>
      ${sourcesBlock(f)}
    </li>`).join("");

  renderSteps();
  drawMap(origin, results);
}

function drawMap(origin, results) {
  if (!window.L) return; // map library blocked/offline: the list still works
  if (!state.map) {
    state.map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(state.map);
    state.layer = L.layerGroup().addTo(state.map);
  }
  state.layer.clearLayers();
  state.markers = {};
  const you = L.marker([origin.lat, origin.lng], { icon: L.divIcon({ className: "", html: '<div class="you"></div>', iconSize: [18, 18] }), zIndexOffset: 1000 });
  you.bindTooltip("📍").addTo(state.layer);

  for (const f of results) {
    const icon = L.divIcon({
      className: "",
      html: `<div class="pin" style="--tier:${TIER_COLOR[f.tier]}"><span>${EMP_MARK[empKey(f)]}</span></div>`,
      iconSize: [34, 34], iconAnchor: [17, 34], popupAnchor: [0, -30],
    });
    const m = L.marker([f.lat, f.lng], { icon, title: `#${f.rank} ${f.name}` })
      .bindPopup(`<div class="popup__name">#${f.rank} ${esc(f.name)}</div>
        <div><span class="pill pill--tier" style="--tier:${TIER_COLOR[f.tier]}">${esc(t(`tier.${f.tier}`))}</span></div>
        <div class="muted">${esc(typeLine(f))}</div><div>${esc(empLine(f))}</div>`)
      .on("click", () => selectFacility(f.id, false))
      .addTo(state.layer);
    state.markers[f.id] = m;
  }
  const focus = results.filter((f) => f.tier === "specialist").slice(0, 5);
  const pts = [[origin.lat, origin.lng], ...(focus.length ? focus : results.slice(0, 5)).map((f) => [f.lat, f.lng])];
  state.map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });
  setTimeout(() => state.map.invalidateSize(), 60);
}

function renderLegend() {
  $("legend").innerHTML = TIERS.map((k) =>
    `<span class="legend__item"><span class="swatch" style="background:${TIER_COLOR[k]}"></span>${esc(t(`tier.${k}`))}</span>`).join("")
    + `<span class="legend__item">✓ / ✕ / ? Aarogyasri</span>`;
}

function selectFacility(id, fromList = true) {
  state.selectedId = id;
  document.querySelectorAll(".fac").forEach((el) => el.setAttribute("aria-current", String(Number(el.dataset.id) === id)));
  $("ent-facility").value = String(id);
  const m = state.markers[id];
  if (m && fromList) { state.map.panTo(m.getLatLng()); m.openPopup(); }
  renderSteps();
  if (state.caseData) { syncCase(); saveCase(); }
}

/* ---------- entitlements ---------- */
function renderChips() {
  $("chips").innerHTML = state.situations.map((s) =>
    `<button type="button" class="chip" data-key="${esc(s.key)}" aria-pressed="${state.chosenSituations.has(s.key)}">${esc(t(`situation.${s.key}`) || s.label)}</button>`).join("");
}
function renderEntitlementForm() {
  const results = state.triage?.results || [];
  $("ent-facility").innerHTML = results.map((f) => `<option value="${f.id}">#${f.rank} ${esc(f.name)}</option>`).join("");
  if (state.selectedId != null) $("ent-facility").value = String(state.selectedId);
  renderChips();
}
/* ---------- conversation with memory (saved on this device only) ---------- */
const CASE_KEY = "raahat.case.v1";
const HISTORY_SENT = 6; // recent messages sent with each question

function loadCase() {
  try { return JSON.parse(store.get(CASE_KEY) || "null"); } catch { return null; }
}
function saveCase() { store.set(CASE_KEY, JSON.stringify(state.caseData)); }
function syncCase() {
  state.caseData = {
    ...(state.caseData || { messages: [] }),
    injury: state.triage?.injury.key || state.injury,
    locality: $("locality").value,
    facilityId: state.selectedId,
    situations: [...state.chosenSituations],
    conditions: [...state.conditions],
    notes: $("situation-text").value.trim(),
  };
}
function newCase() {
  state.caseData = null;
  try { localStorage.removeItem(CASE_KEY); } catch { /* storage blocked */ }
  state.chosenSituations = new Set();
  state.conditions = new Set();
  $("situation-text").value = "";
  state.restored = false;
  renderChips();
  renderConditionChips();
  renderSteps();
  renderChat();
}

/* ---------- voice: speak the description, hear the guidance ---------- */
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const SPEECH_LANG = { en: "en-IN", hi: "hi-IN", te: "te-IN", ur: "ur-IN" };
let speakingBtn = null;

function speakButton(rootSelector) {
  if (!("speechSynthesis" in window)) return "";
  return `<button type="button" class="speak-btn" data-speak="${rootSelector}"><svg class="ico"><use href="#i-speaker"/></svg><span>${esc(t("voice.read"))}</span></button>`;
}

function voiceFor(lang) {
  const voices = window.speechSynthesis.getVoices();
  const want = SPEECH_LANG[lang].toLowerCase();
  return voices.find((v) => v.lang.replace("_", "-").toLowerCase() === want)
    || voices.find((v) => v.lang.toLowerCase().startsWith(lang));
}

// Text a person should hear: skip citation badges, buttons, notes and collapsed English originals.
function speakableText(root) {
  const clone = root.cloneNode(true);
  clone.querySelectorAll(".cite, details, button, .firstaid__note, .mt-label, .model, .steps__for, .steps__actions")
    .forEach((n) => n.remove());
  // A detached clone has no layout, so separate list items and paragraphs explicitly (gives the voice a pause).
  clone.querySelectorAll("li, p, h3").forEach((n) => n.append(" "));
  return clone.textContent.replace(/\s+/g, " ").trim();
}

function stopSpeaking() {
  window.speechSynthesis.cancel();
  if (speakingBtn) speakingBtn.querySelector("span").textContent = t("voice.read");
  speakingBtn = null;
}

function toggleSpeak(btn) {
  const wasThis = speakingBtn === btn;
  stopSpeaking();
  if (wasThis) return;
  const root = btn.closest(btn.dataset.speak);
  const voice = voiceFor(state.lang);
  // Never read Telugu/Hindi/Urdu text with an English voice: it would be unintelligible.
  if (!voice && state.lang !== "en") { toast(t("voice.no_voice")); return; }
  const u = new SpeechSynthesisUtterance(speakableText(root));
  u.lang = SPEECH_LANG[state.lang];
  if (voice) u.voice = voice;
  u.rate = 0.9;
  u.onend = u.onerror = () => { if (speakingBtn === btn) stopSpeaking(); };
  speakingBtn = btn;
  btn.querySelector("span").textContent = t("voice.stop");
  window.speechSynthesis.speak(u);
}

// Someone in an emergency may be breathless and pause mid-sentence. Browsers end recognition at
// the first pause, so keep restarting it and only finish after a real silence, a tap, or a time cap.
const SILENCE_MS = 4000;       // quiet this long after speaking = done
const FIRST_WORD_MS = 10000;   // time allowed before the first word
const MAX_LISTEN_MS = 90000;
let recognition = null;
const listen = { finals: "", interim: "", started: 0, lastHeard: 0, stop: false, timer: null };

function showHeard() { $("describe-text").value = `${listen.finals} ${listen.interim}`.replace(/\s+/g, " ").trim(); }

function startRecognition() {
  const rec = new SpeechRec();
  rec.lang = SPEECH_LANG[state.lang];
  rec.interimResults = true;
  rec.continuous = true;
  rec.onresult = (ev) => {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) listen.finals += ` ${r[0].transcript}`;
      else interim += ` ${r[0].transcript}`;
    }
    listen.interim = interim;
    listen.lastHeard = Date.now();
    showHeard();
  };
  rec.onerror = (ev) => {
    // "no-speech"/"aborted" just mean a pause or a restart; only a blocked mic is fatal.
    if (ev.error === "not-allowed" || ev.error === "service-not-allowed" || ev.error === "audio-capture") {
      listen.stop = true;
      toast(t("voice.no_mic"));
    }
  };
  rec.onend = () => {
    if (rec !== recognition) return;
    listen.finals += ` ${listen.interim}`; // keep words that never became "final" before the cut-off
    listen.interim = "";
    if (!listen.stop && Date.now() - listen.started < MAX_LISTEN_MS) {
      try { startRecognition(); return; } catch { /* fall through and finish */ }
    }
    finishListening();
  };
  recognition = rec;
  rec.start();
}

function finishListening() {
  clearInterval(listen.timer);
  recognition = null;
  $("mic-btn").classList.remove("is-listening");
  $("mic-label").textContent = t("voice.speak");
  showHeard();
  // Spoken description goes straight to "understand" -- no extra button to find under stress.
  if ($("describe-text").value.trim()) $("describe-form").requestSubmit();
}

function stopListening() {
  listen.stop = true;
  try { recognition?.stop(); } catch { finishListening(); }
}

function toggleListening() {
  if (recognition) { stopListening(); return; }
  Object.assign(listen, { finals: "", interim: "", started: Date.now(), lastHeard: 0, stop: false });
  $("describe-text").value = "";
  $("mic-btn").classList.add("is-listening");
  $("mic-label").textContent = t("voice.listening");
  listen.timer = setInterval(() => {
    const now = Date.now();
    const quiet = listen.lastHeard ? now - listen.lastHeard > SILENCE_MS : now - listen.started > FIRST_WORD_MS;
    if (quiet || now - listen.started > MAX_LISTEN_MS) stopListening();
  }, 500);
  startRecognition();
}

function renderAnswer(m) {
  const translated = m.lang === state.lang ? m.translated : null;
  let html = "";
  if (translated) html += `<p class="mt-label"><svg class="ico"><use href="#i-sparkle"/></svg>${esc(t("mt_label"))}</p>`;
  else if (state.lang !== "en" && m.generated) html += `<p class="mt-label">${esc(t("translation_failed"))}</p>`;
  html += `<div class="explanation">${renderExplanation(translated || m.content)}</div>${speakButton(".msg--ai")}`;
  if (translated) html += `<details><summary>${esc(t("show_english"))}</summary><div class="explanation english">${renderExplanation(m.content)}</div></details>`;
  if (m.sources?.length) html += `<details><summary>${esc(t("sources_used"))}</summary><div class="sources">${m.sources.map((x) =>
    `<div><b>${esc(x.title)}</b>${esc(x.citation)}</div>`).join("")}</div></details>`;
  if (m.model?.generation) html += `<p class="model">${esc(t("generated_by", { gen: m.model.generation, emb: m.model.embedding }))}</p>`;
  return html;
}

function renderChat() {
  const box = $("ent-result");
  const msgs = state.caseData?.messages || [];
  let html = "";
  if (state.restored && msgs.length) html += `<p class="note note--ok">${esc(t("welcome_back"))}</p>`;
  if (!msgs.length && !state.pending) {
    html += `<div class="ent__placeholder"><div><svg class="ico"><use href="#i-shield"/></svg><p>${esc(t("eligible_caption"))}</p></div></div>`;
  }
  html += `<div class="chat-log">${msgs.map((m) => m.role === "user"
    ? `<div class="msg msg--user"><span class="msg__who">${esc(t("chat_you"))}</span><p>${esc(m.content)}</p></div>`
    : `<div class="msg msg--ai">${renderAnswer(m)}</div>`).join("")}`;
  if (state.pending) html += `<div class="msg msg--ai"><p class="mt-label">${esc(t("spinner"))}</p><div class="skeleton"><div></div><div></div></div></div>`;
  html += `</div>
    <div class="suggest">${["q.1", "q.2", "q.3", "q.4"].map((k) => `<button type="button" class="chip suggest__q" data-q="${esc(t(k))}">${esc(t(k))}</button>`).join("")}</div>
    <form class="ask" id="ask-form">
      <textarea id="ask-input" rows="2" maxlength="500" placeholder="${esc(t("ask_placeholder"))}"></textarea>
      <button type="submit" class="btn btn--primary" ${state.pending ? "disabled" : ""}>${esc(t("ask_button"))}</button>
    </form>
    <div class="memory"><span>${esc(t("memory_note"))}</span>${msgs.length ? `<button type="button" class="btn btn--ghost btn--sm" id="new-case">${esc(t("new_case"))}</button>` : ""}</div>`;
  box.innerHTML = html;
  const log = box.querySelector(".chat-log");
  if (log) log.scrollTop = log.scrollHeight;
}

async function ask(question, shownText) {
  if (state.pending || !state.triage) return;
  syncCase();
  const previous = state.caseData.messages.slice(-HISTORY_SENT).map((m) => ({ role: m.role, content: m.content }));
  state.caseData.messages.push({ role: "user", content: shownText || question });
  state.pending = true;
  renderChat();
  try {
    const body = {
      injury: state.caseData.injury, facility_id: state.caseData.facilityId,
      situations: state.caseData.situations, conditions: state.caseData.conditions || [],
      language: state.lang, history: previous,
    };
    if (question) body.question = question;
    if (state.caseData.notes) body.situation = state.caseData.notes;
    const res = await api("/api/entitlements", body, 120000);
    state.caseData.messages.push({
      role: "assistant", content: res.explanation, translated: res.explanation_translated,
      lang: state.lang, sources: res.sources, model: res.model, generated: res.generated,
    });
    saveCase();
  } catch (err) {
    state.caseData.messages.pop(); // let them retry the same question
    toast(err.message);
  } finally {
    state.pending = false;
    renderChat();
  }
  $("ent-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function onExplain(e) {
  e.preventDefault();
  ask(null, t("overview_q"));
}

/* Re-open the last case saved on this device: same search, hospital, situations and conversation. */
async function restoreCase() {
  const c = loadCase();
  if (!c?.injury || !state.injuries.some((i) => i.key === c.injury)) return;
  state.caseData = c;
  state.restored = true;
  setInjury(c.injury);
  if (LOCALITIES[c.locality]) { $("locality").value = c.locality; $("locality").dispatchEvent(new Event("change")); }
  state.chosenSituations = new Set(c.situations || []);
  state.conditions = new Set(c.conditions || []);
  renderConditionChips();
  $("situation-text").value = c.notes || "";
  await runSearch({ scroll: false, selectId: c.facilityId });
}

/* ---------- boot ---------- */
async function init() {
  try {
    const [i18n, injuries, situations, facilities, sources, conditionList] = await Promise.all([
      api("/api/i18n"), api("/api/injuries"), api("/api/situations"), api("/api/facilities"), api("/api/sources"),
      api("/api/conditions"),
    ]);
    Object.assign(state, { strings: i18n.strings, languages: i18n.languages, rtl: i18n.rtl, injuries, situations, sources, conditionList });
    $("sources-band").innerHTML = sources.filter((x) => x.kind === "legal").map((x) => `<li>${esc(x.title)}</li>`).join("");
    $("stat-injuries").textContent = injuries.length;
    $("stat-facilities").textContent = facilities.length;
  } catch (err) {
    document.querySelector("main").insertAdjacentHTML("afterbegin",
      `<div class="container"><p class="demo-note">${esc(err.message || "Cannot connect to the Raahat server.")}</p></div>`);
    return;
  }

  const saved = store.get("raahat.lang");
  state.lang = state.languages[saved] ? saved : "en";
  state.injury = state.injuries[0]?.key;

  $("lang").innerHTML = Object.entries(state.languages).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("lang").value = state.lang;
  $("locality").innerHTML = Object.keys(LOCALITIES).map((n) => `<option>${esc(n)}</option>`).join("");
  $("locality").value = "Charminar";
  const syncCoords = () => { const [la, ln] = LOCALITIES[$("locality").value]; $("lat").value = la; $("lng").value = ln; };
  syncCoords();

  $("lang").addEventListener("change", () => { if ("speechSynthesis" in window) stopSpeaking(); state.lang = $("lang").value; store.set("raahat.lang", state.lang); applyLanguage(); });
  $("locality").addEventListener("change", () => {
    syncCoords();
    $("use-coords").checked = false; // an area picked by hand replaces "my location"
    $("geo-status").hidden = true;
  });
  $("radius").addEventListener("input", () => ($("radius-val").textContent = $("radius").value));
  $("injury").addEventListener("change", () => pickInjury($("injury").value));
  $("geo-btn").addEventListener("click", useMyLocation);
  $("cond-chips").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    const k = chip.dataset.key;
    state.conditions.has(k) ? state.conditions.delete(k) : state.conditions.add(k);
    chip.setAttribute("aria-pressed", String(state.conditions.has(k)));
    renderUnderstood();
    // Conditions change the ranking (e.g. pregnant -> hospitals with obstetrics first).
    if (state.triage) runSearch({ scroll: false, selectId: state.selectedId });
  });
  $("chips").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".chip");
    if (!chip) return;
    const k = chip.dataset.key;
    state.chosenSituations.has(k) ? state.chosenSituations.delete(k) : state.chosenSituations.add(k);
    chip.setAttribute("aria-pressed", String(state.chosenSituations.has(k)));
    renderSteps();
  });
  $("facility-list").addEventListener("click", (ev) => {
    if (ev.target.closest("details, a")) return;
    const li = ev.target.closest(".fac");
    if (li) selectFacility(Number(li.dataset.id));
  });
  $("facility-list").addEventListener("keydown", (ev) => {
    const li = ev.target.closest(".fac");
    if (li && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); selectFacility(Number(li.dataset.id)); }
  });
  $("ent-facility").addEventListener("change", () => selectFacility(Number($("ent-facility").value)));
  $("describe-form").addEventListener("submit", onDescribe);
  if (SpeechRec) { $("mic-btn").hidden = false; $("mic-btn").addEventListener("click", toggleListening); }
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".speak-btn");
    if (btn) { ev.stopPropagation(); toggleSpeak(btn); }
  });
  if ("speechSynthesis" in window) window.speechSynthesis.getVoices(); // voices load asynchronously
  $("search-form").addEventListener("submit", onSearch);
  $("ent-form").addEventListener("submit", onExplain);
  $("ent-result").addEventListener("submit", (ev) => {
    if (ev.target.id !== "ask-form") return;
    ev.preventDefault();
    const q = $("ask-input").value.trim();
    if (q) ask(q);
  });
  $("ent-result").addEventListener("click", (ev) => {
    const q = ev.target.closest(".suggest__q");
    if (q) ask(q.dataset.q);
    if (ev.target.closest("#new-case")) newCase();
  });

  applyLanguage();
  restoreCase();

  // Hero preview shows a real ranking (first injury type, Charminar) rather than a mock.
  const [pla, plng] = LOCALITIES.Charminar;
  api("/api/triage", { injury: state.injury, lat: pla, lng: plng }).then((res) => { state.preview = res; renderPreview(); }).catch(() => {});
}

init();
