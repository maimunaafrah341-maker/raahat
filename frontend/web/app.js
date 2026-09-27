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
  injury: null, chosenSituations: new Set(),
  triage: null, selectedId: null, entitlements: null, understood: null,
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
  const withCites = (s) => inlineMd(s).replace(/\s*\[([^\]]+)\]\.?\s*$/, (_, c) => `<br><span class="cite">${c}</span>`);
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
  // An explanation is language-specific; ask again rather than show the old language.
  if (state.entitlements && state.entitlements.language !== state.lang) state.entitlements = null;
  renderEntitlementResult();
}

/* ---------- injury choice (select + tiles stay in sync) ---------- */
function injuryLabel(item) { return t(`injury.${item.key}`) || item.label; }
function renderInjuryControls() {
  const sel = $("injury");
  sel.innerHTML = state.injuries.map((i) => `<option value="${esc(i.key)}">${esc(injuryLabel(i))}</option>`).join("");
  sel.value = state.injury;
  $("injury-tiles").innerHTML = state.injuries.map((i) => `
    <button type="button" class="tile" role="listitem" data-key="${esc(i.key)}" aria-pressed="${i.key === state.injury}">
      <span class="tile__icon"><svg class="ico"><use href="#i-${esc(i.key)}"/></svg></span>
      <span class="tile__label">${esc(injuryLabel(i))}</span>
    </button>`).join("");
}
function setInjury(key) {
  state.injury = key;
  $("injury").value = key;
  document.querySelectorAll(".tile").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === key)));
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
    $("situation-text").value = text.slice(0, 500);
    renderChips();
  } catch (err) {
    state.understood = { error: err.message };
  } finally {
    busy(btn, false);
  }
  renderUnderstood();
  renderSteps();
  if (state.understood?.injury) $("search-form").scrollIntoView({ behavior: "smooth", block: "center" });
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
    html += `<p class="note note--ok">${inlineMd(t("understood", { injury: item ? injuryLabel(item) : u.injury, button: t("find_button") }))}</p>`;
  } else html += `<p class="note note--info">${esc(t("not_understood"))}</p>`;
  box.innerHTML = html;
}

/* ---------- search ---------- */
function searchOrigin() {
  if ($("use-coords").checked) {
    const lat = parseFloat($("lat").value), lng = parseFloat($("lng").value);
    if (Number.isFinite(lat) && Number.isFinite(lng)) return [lat, lng];
  }
  return LOCALITIES[$("locality").value];
}
async function onSearch(e) {
  e.preventDefault();
  const btn = $("search-btn");
  const [lat, lng] = searchOrigin();
  busy(btn, true);
  try {
    state.triage = await api("/api/triage", { injury: state.injury, lat, lng, radius_km: Number($("radius").value) });
    state.selectedId = state.triage.results[0]?.id ?? null;
    state.entitlements = null;
    $("start-info").hidden = true;
    $("results").hidden = false;
    $("entitlements").hidden = !state.triage.results.length;
    renderResults();
    renderEntitlementForm();
    renderEntitlementResult();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  } finally {
    busy(btn, false);
  }
}

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
  $("preview-injury").textContent = item ? injuryLabel(item) : "";
  box.innerHTML = state.preview.results.slice(0, 4).map((f) => `
    <li class="preview__row">
      <span class="preview__rank">${f.rank}</span>
      <div>
        <div class="preview__name">${esc(f.name)}</div>
        <div class="preview__meta">${tierPill(f)}<span>${Number(f.distance_km).toFixed(1)} km</span></div>
      </div>
      <span class="emp-badge emp-badge--${empKey(f)}" title="Aarogyasri">${EMP_MARK[empKey(f)]}</span>
    </li>`).join("");
  $("preview-foot").textContent = `${state.sources.length} ${t("stat.sources")}`;
}

function renderSteps() {
  const box = $("next-steps");
  const f = state.triage?.results.find((x) => x.id === state.selectedId);
  if (!f) { box.innerHTML = ""; return; }
  const urgent = state.understood?.life_threatening_signs;
  const worker = state.chosenSituations.has("construction_worker") || state.chosenSituations.has("informal_worker");
  const go = inlineMd(t("steps.go", { name: f.name, km: Number(f.distance_km).toFixed(1), tier: "%TIER%" }))
    .replace("%TIER%", tierPill(f));
  const steps = [
    `<li class="${urgent ? "is-urgent" : ""}"><div>${inlineMd(t("steps.call"))}</div></li>`,
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
  if (state.entitlements && state.entitlements.facility_id !== id) { state.entitlements = null; renderEntitlementResult(); }
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
function renderEntitlementResult() {
  const box = $("ent-result");
  const e = state.entitlements;
  if (!e) {
    box.innerHTML = `<div class="ent__placeholder"><div><svg class="ico"><use href="#i-shield"/></svg><p>${esc(t("eligible_caption"))}</p></div></div>`;
    return;
  }
  if (e.loading) {
    box.innerHTML = `<p class="mt-label">${esc(t("spinner"))}</p><div class="skeleton"><div></div><div></div><div></div><div></div></div>`;
    return;
  }
  const translated = e.explanation_translated;
  let html = "";
  if (translated) html += `<p class="mt-label"><svg class="ico"><use href="#i-sparkle"/></svg>${esc(t("mt_label"))}</p>`;
  else if (state.lang !== "en" && e.generated) html += `<p class="mt-label">${esc(t("translation_failed"))}</p>`;
  html += `<div class="explanation">${renderExplanation(translated || e.explanation)}</div>`;
  if (translated) html += `<details><summary>${esc(t("show_english"))}</summary><div class="explanation english">${renderExplanation(e.explanation)}</div></details>`;
  html += `<details><summary>${esc(t("sources_used"))}</summary><div class="sources">${(e.sources || []).map((s) =>
    `<div><b>${esc(s.title)}</b>${esc(s.citation)}</div>`).join("")}</div></details>`;
  if (e.model?.generation) html += `<p class="model">${esc(t("generated_by", { gen: e.model.generation, emb: e.model.embedding }))}</p>`;
  box.innerHTML = html;
}
async function onExplain(e) {
  e.preventDefault();
  const btn = $("ent-btn");
  const facilityId = Number($("ent-facility").value);
  state.entitlements = { loading: true };
  renderEntitlementResult();
  busy(btn, true);
  try {
    const body = { injury: state.triage.injury.key, facility_id: facilityId, situations: [...state.chosenSituations], language: state.lang };
    const text = $("situation-text").value.trim();
    if (text) body.situation = text;
    const res = await api("/api/entitlements", body, 120000);
    state.entitlements = { ...res, facility_id: facilityId, language: state.lang };
  } catch (err) {
    state.entitlements = null;
    toast(err.message);
  } finally {
    busy(btn, false);
  }
  renderEntitlementResult();
  if (window.matchMedia("(max-width: 980px)").matches) $("ent-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- boot ---------- */
async function init() {
  try {
    const [i18n, injuries, situations, facilities, sources] = await Promise.all([
      api("/api/i18n"), api("/api/injuries"), api("/api/situations"), api("/api/facilities"), api("/api/sources"),
    ]);
    Object.assign(state, { strings: i18n.strings, languages: i18n.languages, rtl: i18n.rtl, injuries, situations, sources });
    $("sources-band").innerHTML = sources.map((x) => `<li>${esc(x.title)}</li>`).join("");
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

  $("lang").addEventListener("change", () => { state.lang = $("lang").value; store.set("raahat.lang", state.lang); applyLanguage(); });
  $("locality").addEventListener("change", syncCoords);
  $("radius").addEventListener("input", () => ($("radius-val").textContent = $("radius").value));
  $("injury").addEventListener("change", () => setInjury($("injury").value));
  $("injury-tiles").addEventListener("click", (ev) => {
    const tile = ev.target.closest(".tile");
    if (!tile) return;
    setInjury(tile.dataset.key);
    $("search-form").scrollIntoView({ behavior: "smooth", block: "center" });
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
  $("search-form").addEventListener("submit", onSearch);
  $("ent-form").addEventListener("submit", onExplain);

  applyLanguage();

  // Hero preview shows a real ranking (first injury type, Charminar) rather than a mock.
  const [pla, plng] = LOCALITIES.Charminar;
  api("/api/triage", { injury: state.injury, lat: pla, lng: plng }).then((res) => { state.preview = res; renderPreview(); }).catch(() => {});
}

init();
