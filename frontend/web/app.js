/* Raahat web client. Talks only to the Flask API on the same origin. */
"use strict";

// Area name -> [lat, lng], loaded from /api/localities (data/localities.json, OpenStreetMap coordinates).
let LOCALITIES = {};
const ZONES = ["central", "old_city", "secunderabad", "west", "east", "south"];
const TIERS = ["specialist", "can_manage", "stabilize", "unchecked", "unsuitable"];
const TIER_COLOR = { specialist: "#16a34a", can_manage: "#f59e0b", stabilize: "#dc2626", unchecked: "#6b7f99",
  unsuitable: "#94a3b8", offline: "#64748b" };

const state = {
  strings: {}, languages: {}, rtl: [], lang: "en",
  injuries: [], situations: [], sources: [], helplines: null,
  injury: null, chosenSituations: new Set(), conditionList: [], conditions: new Set(),
  triage: null, selectedId: null, understood: null,
  caseData: null, pending: false, restored: false,
  map: null, markers: {},
  checklistRules: null, docs: new Set(), resultsFeedback: null, reported: {},
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

/* ---------- anonymous usage events (see backend/analytics.py for what is kept) ---------- */
// A random id per case, so one person's search, answers and feedback can be grouped
// without knowing who they are. "Start a new case" makes a new one.
function newSessionId() {
  return (crypto.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`).slice(0, 36);
}
let session = newSessionId();
function sessionId() { return session; }
// Fire-and-forget: a lost event must never slow down or break an emergency lookup.
function track(kind, value, extra = {}) {
  const body = JSON.stringify({ kind, value, session: sessionId(), language: state.lang,
    injury: state.triage?.injury.key || state.injury, ...extra });
  try {
    if (navigator.sendBeacon?.("/api/event", new Blob([body], { type: "application/json" }))) return;
  } catch { /* fall back to fetch */ }
  fetch("/api/event", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
}

/* ---------- dates: "checked on" labels ---------- */
const STALE_DAYS = 90; // hospital details older than this get a "may be out of date" warning
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  try { return d.toLocaleDateString(`${state.lang}-IN`, { day: "numeric", month: "short", year: "numeric" }); }
  catch { return iso; }
}
function daysSince(iso) { return iso ? Math.floor((Date.now() - new Date(`${iso}T00:00:00`).getTime()) / 86400000) : null; }

async function api(path, body, timeoutMs = 30000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(path, body === undefined ? { signal: ctrl.signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctrl.signal,
    });
  } catch (e) {
    const err = new Error(t(e.name === "AbortError" ? "timeout" : "cannot_connect"));
    err.network = true; // no answer at all (offline, dropped, timed out) -- callers may fall back to saved data
    throw err;
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
  renderPics();
  if (state.localities) renderLocalities();
  renderLegend();
  renderHelplines();
  renderSteps();
  renderUnderstood();
  if (state.triage) renderResults();
  if (state.triage) renderEntitlementForm();
  renderChat();
}

/* ---------- injury choice (select + tiles stay in sync) ---------- */
function injuryLabel(item) { return t(`injury.${item.key}`) || item.label; }
const GROUPS = ["urgent", "injury", "illness", "mother_child", "mind"]; // same order as backend triage.GROUPS
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
// Choosing from the list works like describing it: we show what was chosen, and first aid comes with the hospitals.
function pickInjury(key) {
  setInjury(key);
  const u = state.understood || {};
  state.understood = { injury: key, picked: true, life_threatening_signs: u.life_threatening_signs };
  renderUnderstood();
  renderSteps();
}

/* ---------- picture buttons: tap what happened, no reading or typing needed ---------- */
// The emergencies people bring most often. Everything else is in "Type it, or choose from the full list".
const PICS = [
  { key: "fracture", icon: "fracture" },
  { key: "deep_cut", icon: "deep_cut", label: "bleeding" },
  { key: "chest_pain", icon: "chest_pain", label: "chest" },
  { key: "collapsed_not_breathing", icon: "pulse", label: "collapsed" },
  { key: "fall_polytrauma", icon: "car", label: "accident", situation: "road_accident" },
  { key: "burns", icon: "burns", label: "burn" },
  { key: "pregnancy_problem", icon: "pregnancy_problem", label: "pregnancy" },
  { key: "child_unwell", icon: "child_unwell", label: "child" },
  { key: "other", icon: "plus", label: "other" },
];
function renderPics() {
  $("pics").innerHTML = PICS.map((p) => `<button type="button" class="pic" data-pic="${p.key}" aria-pressed="${state.injury === p.key && !!state.understood?.picked}">
    <svg class="pic__icon" aria-hidden="true"><use href="#i-${p.icon}"/></svg><span class="pic__label">${esc(t(`pic.${p.label || p.key}`))}</span></button>`).join("");
}
function onPic(ev) {
  const btn = ev.target.closest(".pic");
  if (!btn) return;
  const p = PICS.find((x) => x.key === btn.dataset.pic);
  if (p.key === "other") {
    $("more-ways").open = true;
    $("injury").focus();
    $("more-ways").scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (p.situation) { state.chosenSituations.add(p.situation); renderChips(); }
  clearResults();
  pickInjury(p.key);
  // Life-threatening picks (not breathing, chest pain) show "call 108 now" first.
  if (state.injuries.find((i) => i.key === p.key)?.group === "urgent") {
    state.understood.life_threatening_signs = true;
    renderUnderstood();
  }
  renderPics();
  $("understood").scrollIntoView({ behavior: "smooth", block: "start" });
}

// A new emergency hides the previous hospital list until the person searches again.
function clearResults() {
  if ($("results").hidden) return;
  $("results").hidden = true;
  $("entitlements").hidden = true;
  state.triage = null;
}

/* ---------- describe (free text -> suggestions) ---------- */
async function onDescribe(e) {
  e.preventDefault();
  const text = $("describe-text").value.trim();
  if (!text) return;
  const btn = $("describe-btn");
  busy(btn, true);
  try {
    const res = await api("/api/understand", { text, session: sessionId(), language: state.lang }, 60000);
    applyUnderstanding(res, text);
  } catch (err) {
    state.understood = { error: err.message };
    renderUnderstood();
  } finally {
    busy(btn, false);
  }
}

// One path for typed and spoken descriptions: fill in everything the AI understood (what happened,
// who the patient is, their situation, their area), show it back so they can correct it, and -- if we
// know where they are -- search straight away instead of making them find another button.
function applyUnderstanding(res, text) {
  state.understood = { ...res, text };
  if (res.injury) setInjury(res.injury);
  state.chosenSituations = new Set(res.situations || []);
  // "We can't pay" or "we have a ration card": put free and low-cost hospitals first.
  if (state.chosenSituations.has("cant_pay") || state.chosenSituations.has("bpl_card")) $("low-cost").checked = true;
  state.conditions = new Set([...(res.conditions || []), ...(IMPLIED_CONDITION[res.injury] ? [IMPLIED_CONDITION[res.injury]] : [])]);
  renderConditionChips();
  $("situation-text").value = (text || "").slice(0, 500);
  renderChips();
  if (res.area && LOCALITIES[res.area]) {
    $("locality").value = res.area;
    $("locality").dispatchEvent(new Event("change")); // a named area replaces "my location"
  }
  // Never jump to the hospital list: show what we understood and the first aid, then let the person
  // confirm where they are and tap "Find hospitals" themselves.
  state.understood.knowPlace = !!(res.area && LOCALITIES[res.area]) || $("use-coords").checked;
  clearResults();
  renderUnderstood();
  renderSteps();
  $("understood").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderUnderstood() {
  const u = state.understood;
  const box = $("understood");
  if (!u) { box.innerHTML = ""; return; }
  let html = "";
  if (u.life_threatening_signs) {
    html += `<div class="alert alert--urgent"><svg class="ico"><use href="#i-phone"/></svg><span>${inlineMd(t("urgent"))}</span>
      <a class="alert__call alert__call--light" href="tel:108">108</a></div>`;
  }
  if (u.error) html += `<p class="note note--warn">${esc(u.error)}</p>`;
  else if (u.injury) {
    const item = state.injuries.find((i) => i.key === u.injury);
    if (!u.picked) {
      // "What we understood": their own words back (heard or summarised), the emergency, the area.
      const who = [...state.conditions].map((c) => t(`condition.${c}`)).join(", ");
      html += `<div class="understood-card">
        <p class="understood-card__title">${esc(t("understood.title"))}</p>
        ${u.transcript ? `<p class="understood-card__heard"><b>${esc(t("voice.heard"))}:</b> “${esc(u.transcript)}”</p>` : ""}
        ${u.summary ? `<p class="understood-card__summary">${esc(u.summary)}</p>` : ""}
        <p class="understood-card__row"><b>${esc(item ? injuryLabel(item) : u.injury)}</b>${who ? ` · ${esc(who)}` : ""}${
          u.area ? ` · ${esc(t("understood.area", { area: u.area }))}` : ""}</p>
        <p class="understood-card__next">${esc(u.knowPlace ? t("understood.confirm_place") : t("understood.need_place"))} ${esc(t("understood.change"))}</p>
      </div>`;
    } else html += `<p class="note note--info">${esc(t("understood.confirm_place"))}</p>`;
    // First aid comes with the hospital list (step 1 of "Your next steps"), after "Find hospitals".
  } else html += `<p class="note note--info">${esc(t("not_understood"))}</p>`;
  box.innerHTML = html;
}

// Areas grouped by part of the city, alphabetical within each, so a long list stays easy to scan.
function renderLocalities() {
  const sel = $("locality");
  const current = sel.value;
  sel.innerHTML = ZONES.map((z) => {
    const names = state.localities.filter((l) => l.zone === z).map((l) => l.name).sort((a, b) => a.localeCompare(b));
    return names.length ? `<optgroup label="${esc(t(`zone.${z}`))}">${names.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>` : "";
  }).join("");
  if (current) sel.value = current;
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
    track("action", "geo_used");
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
      low_cost_first: $("low-cost").checked,
      // A named area is logged as-is; GPS is rounded to ~1 km on the server.
      session: sessionId(), language: state.lang, area: $("use-coords").checked ? null : $("locality").value,
    });
    const ids = state.triage.results.map((f) => f.id);
    state.selectedId = ids.includes(selectId) ? selectId : (ids[0] ?? null);
    state.resultsFeedback = null;
    $("results").hidden = false;
    $("entitlements").hidden = !state.triage.results.length;
    renderResults();
    renderEntitlementForm();
    renderChat();
    if (scroll) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    if (err.network && state.facilities?.length) {
      showOffline(lat, lng, Number($("radius").value), scroll);
      track("action", "offline_search");
    } else toast(err.message);
  } finally {
    busy(btn, false);
  }
}

/* ---------- offline: the saved hospital list, by distance only ---------- */
function haversineKm(lat1, lng1, lat2, lng2) {
  const r = (d) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lng2 - lng1) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}
// Without the server we can't check which hospitals can treat this emergency, so we don't pretend to:
// every hospital gets the grey "offline" label and the page says to call 108 if it's serious.
function showOffline(lat, lng, radius, scroll) {
  // Same order as online, minus the capability check: researched hospitals by distance, then the
  // nearest few that Raahat hasn't checked yet.
  const near = state.facilities
    .map((f) => ({ ...f, distance_km: haversineKm(lat, lng, f.lat, f.lng), reasons: [],
                   tier: notChecked(f) ? "unchecked" : "offline" }))
    .filter((f) => f.distance_km <= radius)
    .sort((a, b) => a.distance_km - b.distance_km);
  const results = [...near.filter((f) => f.tier === "offline"), ...near.filter((f) => f.tier === "unchecked").slice(0, 10)]
    .map((f, i) => ({ ...f, rank: i + 1 }));
  const item = state.injuries.find((i) => i.key === state.injury);
  state.triage = { offline: true, injury: { key: state.injury, label: item?.label || "", specialist_data: true, needs: [] },
    conditions: [...state.conditions], origin: { lat, lng }, results };
  state.selectedId = results[0]?.id ?? null;
  $("results").hidden = false;
  $("entitlements").hidden = true; // questions need the server
  renderResults();
  if (scroll) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}
function onSearch(e) { e.preventDefault(); runSearch(); }

function directionsUrl(f) { return `https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.lng}`; }
// iPhones get Apple Maps as a second choice; Google Maps stays first because most people here use it.
const IS_IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
function appleMapsLink(f) {
  if (!IS_IOS) return "";
  return `<a class="btn btn--ghost btn--sm dir-link" data-id="${f.id}" href="https://maps.apple.com/?daddr=${f.lat},${f.lng}&dirflg=d" target="_blank" rel="noopener">${esc(t("maps.apple"))}</a>`;
}
// A sourced number only: a wrong number in an emergency is worse than none.
function phoneButton(f, primary = false) {
  if (!f.phone) return "";
  return `<a class="btn ${primary ? "btn--primary" : "btn--ghost"} btn--sm call-hospital" data-id="${f.id}" href="tel:${esc(f.phone.number)}"
    title="${esc(t("phone.source"))}: ${esc(f.phone.source.label)}"><svg class="ico"><use href="#i-phone"/></svg>${esc(t(`phone.${f.phone.kind}`))}</a>`;
}
function phoneNote(f) {
  return f.phone
    ? `<p class="phone-src">${esc(t("phone.source"))}: <a href="${esc(f.phone.source.url)}" target="_blank" rel="noopener">${esc(f.phone.source.label)}</a> · ${esc(f.phone.number)}</p>`
    : `<p class="phone-src">${esc(t("phone.none"))}</p>`;
}
function sourceTitle(docId) { return state.sources.find((x) => x.doc_id === docId)?.title || ""; }
function citeText(docId) {
  const s = state.sources.find((x) => x.doc_id === docId);
  if (!s) return "";
  return esc(s.title) + (s.verified ? ` · ${esc(t("answer.verified", { date: fmtDate(s.verified) }))}` : "");
}
function citePill(docId) { const c = citeText(docId); return c ? `<br><span class="cite">${c}</span>` : ""; }
function tierPill(f) { return `<span class="pill pill--tier" style="--tier:${TIER_COLOR[f.tier]}">${esc(t(`tier.${f.tier}`))}</span>`; }

// Family message: what happened, where they're going, directions, and (if GPS was used) where they are now.
async function shareFacility(f) {
  track("action", "share", { facility_id: f.id, tier: f.tier });
  const item = state.injuries.find((i) => i.key === state.triage?.injury.key);
  let text = t("share.text_full", { injury: item ? injuryLabel(item) : "", name: f.name, url: directionsUrl(f) });
  const o = state.triage?.origin;
  if ($("use-coords").checked && o) text += `\n${t("share.where_am_i", { url: `https://maps.google.com/?q=${o.lat},${o.lng}` })}`;
  try {
    if (navigator.share) { await navigator.share({ text }); return; }
  } catch { return; /* user cancelled */ }
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener");
}

// Helplines beside 108 (data/helplines.json): every row is a call button, each with its source.
function prettyNumber(n) { return n.startsWith("+91") ? `0${n.slice(3, 5)} ${n.slice(5, 9)} ${n.slice(9)}` : n; }
function renderHelplines() {
  const box = $("helplines");
  if (!box || !state.helplines) return;
  box.innerHTML = state.helplines.map((h) => `
    <li><a class="helpline" href="tel:${esc(h.number)}" title="${esc(h.source.label)}">
      <b class="helpline__num" dir="ltr">${esc(prettyNumber(h.number))}</b><span>${esc(t(`help.${h.key}`))}</span></a></li>`).join("");
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
// Mental health crisis: the helplines come first, as big call buttons, then the sourced steps.
function crisisCardHtml(card) {
  return `<div class="firstaid firstaid--crisis">
    <div class="firstaid__head"><p class="firstaid__title"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("crisis.title"))}</p>${speakButton(".firstaid")}</div>
    <div class="crisis__calls">
      <a class="btn btn--sos" href="tel:108"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("call108.button"))}</a>
      <a class="btn btn--primary helpline-link" href="tel:14416"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("crisis.telemanas"))}</a>
      <a class="btn btn--ghost helpline-link" href="tel:+914066202000"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("crisis.roshni"))}</a>
    </div>
    <ul class="firstaid__steps">${card.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <p class="firstaid__dont"><b>${esc(t("firstaid.dont"))}:</b> ${card.cautions.map(esc).join(" ")}</p>
    <p class="firstaid__note"><span class="cite">${esc(card.title)}${card.verified ? ` · ${esc(t("answer.verified", { date: fmtDate(card.verified) }))}` : ""}</span></p>
  </div>`;
}
function guideCardHtml(card) {
  if (card.kind === "crisis") return crisisCardHtml(card);
  const danger = card.kind === "danger";
  const list = danger ? "ul" : "ol";
  return `<div class="firstaid${danger ? " firstaid--danger" : ""}">
    <div class="firstaid__head"><p class="firstaid__title"><svg class="ico"><use href="#i-${danger ? "alert" : "sparkle"}"/></svg>${esc(t(danger ? "danger.title" : "firstaid.title"))}</p>${speakButton(".firstaid")}</div>
    <${list} class="firstaid__steps">${card.steps.map((x) => `<li>${esc(x)}</li>`).join("")}</${list}>
    <p class="firstaid__dont"><b>${esc(t("firstaid.dont"))}:</b> ${card.cautions.map(esc).join(" ")}</p>
    ${card.translated ? `<details><summary>${esc(t("show_english"))}</summary><${list} class="firstaid__steps english">${card.steps_en.map((x) => `<li>${esc(x)}</li>`).join("")}</${list}></details>` : ""}
    <p class="firstaid__note">${esc(t("firstaid.note"))} <span class="cite">${esc(card.title)}${card.verified ? ` · ${esc(t("answer.verified", { date: fmtDate(card.verified) }))}` : ""}</span></p>
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
    `<li><div>${go}${f.phone ? callScript(f, notChecked(f)) : ""}</div></li>`,
    ...(state.checklistRules ? [`<li><div>${checklistHtml(f)}</div></li>`] : []),
    `<li><div>${esc(t("steps.ask"))}${citePill("clinical_establishments_act")}${refuseCardHtml()}</div></li>`,
    `<li><div>${esc(t(`steps.emp_${empKey(f)}`))}${citePill("telangana_aarogyasri")}${payCardHtml()}</div></li>`,
  ];
  if (worker) steps.push(`<li><div>${esc(t("steps.bocw"))}${citePill("telangana_bocw")}</div></li>`);
  if (state.chosenSituations.has("road_accident")) {
    steps.push(`<li><div>${esc(t("steps.road"))}${citePill("road_accident_cashless")}</div></li>`);
    steps.push(`<li><div>${esc(t("steps.police"))}${citePill("parmanand_katara_case")}</div></li>`);
  }
  if (state.chosenSituations.has("helped_stranger")) steps.push(`<li><div>${esc(t("steps.samaritan"))}${citePill("good_samaritan")}</div></li>`);
  steps.push(`<li><div><a href="#entitlements">${esc(t("steps.more"))}</a></div></li>`);
  box.innerHTML = `
    <div class="steps__head">
      <div><h3>${esc(t("steps.title"))}</h3><p class="steps__for">${esc(t("steps.for", { name: f.name }))}</p></div>
      <div class="steps__actions">
        ${phoneButton(f, true)}
        <a class="btn btn--primary btn--sm dir-link" data-id="${f.id}" href="${directionsUrl(f)}" target="_blank" rel="noopener"><svg class="ico"><use href="#i-nav"/></svg>${esc(t("directions"))}</a>
        ${appleMapsLink(f)}
        <button type="button" class="btn btn--ghost btn--sm" id="desk-btn"><svg class="ico"><use href="#i-doc"/></svg>${esc(t("desk.button"))}</button>
        <button type="button" class="btn btn--ghost btn--sm" id="share-btn"><svg class="ico"><use href="#i-share"/></svg>${esc(t("share"))}</button>
        ${speakButton(".steps")}
      </div>
    </div>
    <ol>${steps.join("")}</ol>`;
  $("share-btn").addEventListener("click", () => shareFacility(f));
  $("desk-btn").addEventListener("click", () => openDeskCard(f));
  $("refuse-desk").addEventListener("click", () => openDeskCard(f, true));
}

/* ---------- paying for treatment: with a card, and without one ---------- */
function payCardHtml() {
  const hasCard = state.chosenSituations.has("bpl_card");
  const block = (key, open) => `<details class="pay__opt"${open ? " open" : ""}><summary>${esc(t(`pay.${key}_title`))}</summary>
    <p>${esc(t(`pay.${key}_body`))}${citePill("aarogyasri_how_to_use")}</p></details>`;
  return `<div class="pay">
    <p class="pay__title">${esc(t("pay.title"))}</p>
    <p class="pay__always">${esc(t("pay.always"))}${citePill("clinical_establishments_act")}</p>
    ${block("have", hasCard)}${block("none", !hasCard)}
  </div>`;
}

/* ---------- if a hospital refuses: the law, what to do now, and complaint routes afterwards ---------- */
const REFUSED = ["turned_away", "asked_to_pay_first", "referred_elsewhere"];
function refuseCardHtml() {
  const open = REFUSED.some((s) => state.chosenSituations.has(s));
  const tip = '<span class="docs__star" aria-hidden="true">*</span>';
  return `<details class="refuse"${open ? " open" : ""}>
    <summary><svg class="ico"><use href="#i-alert"/></svg>${esc(t("refuse.title"))}</summary>
    <div class="refuse__body">
      ${speakButton(".refuse__body")}
      <p class="refuse__law">${esc(t("refuse.law"))}${citePill("clinical_establishments_act")}</p>
      <p>${esc(t("refuse.court"))}${citePill("parmanand_katara_case")}</p>
      <p class="refuse__h">${esc(t("refuse.now"))}</p>
      <ul class="refuse__list">
        <li>${esc(t("refuse.now_ask"))}</li>
        <li>${esc(t("refuse.now_go"))}${tip}</li>
        <li>${esc(t("refuse.now_note"))}${tip}</li>
      </ul>
      <button type="button" class="btn btn--primary btn--sm" id="refuse-desk"><svg class="ico"><use href="#i-doc"/></svg>${esc(t("refuse.show"))}</button>
      <p class="refuse__h">${esc(t("refuse.later"))}</p>
      <ul class="refuse__list">
        <li>${esc(t("refuse.dra"))}${citePill("clinical_establishments_act")}</li>
        <li>${esc(t("refuse.consumer"))}${citePill("consumer_protection_medical")}</li>
        <li>${esc(t("refuse.court_case"))}${citePill("paschim_banga_case")}</li>
        <li>${esc(t("refuse.aid"))}${citePill("legal_aid_nalsa")}</li>
      </ul>
      <a class="btn btn--ghost btn--sm refuse__aid" href="tel:15100" ><svg class="ico"><use href="#i-phone"/></svg>${esc(t("refuse.call_aid"))}</a>
      <p class="refuse__note">${esc(t("refuse.note"))}</p>
      <p class="docs__tip">* ${esc(t("docs.tip"))}</p>
    </div>
  </details>`;
}

/* ---------- "show to hospital staff": what to say, when someone can't say it ---------- */
function tIn(lang, key, params) {
  let s = state.strings[lang]?.[key] || state.strings.en?.[key] || "";
  for (const [k, v] of Object.entries(params || {})) s = s.replaceAll(`{${k}}`, v);
  return s;
}
// The same fixed, hand-written sentences as the rest of the page: nothing here is generated.
function deskLines(lang, f, refused = false) {
  const injury = state.triage.injury.key;
  const who = [...state.conditions].map((c) => tIn(lang, `condition.${c}`)).join(", ");
  const lines = [`<p class="desk__what">${esc(tIn(lang, `injury.${injury}`))}</p>`];
  if (who) lines.push(`<p class="desk__who"><b>${esc(tIn(lang, "desk.who"))}:</b> ${esc(who)}</p>`);
  lines.push(`<p class="desk__ask">${esc(tIn(lang, "desk.stabilise"))}</p>`, `<p>${esc(tIn(lang, "desk.law"))}</p>`);
  // Being refused: add the Supreme Court's words and a polite request to put the reason in writing.
  if (refused) lines.push(`<p>${esc(tIn(lang, "desk.court"))}</p>`, `<p class="desk__ask">${esc(tIn(lang, "desk.refused"))}</p>`);
  if (state.chosenSituations.has("road_accident") || state.chosenSituations.has("helped_stranger")) {
    lines.push(`<p>${esc(tIn(lang, "desk.police"))}</p>`);
  }
  if (state.chosenSituations.has("road_accident")) lines.push(`<p>${esc(tIn(lang, "desk.road"))}</p>`);
  if (f.aarogyasri_empanelled !== false && (state.chosenSituations.has("bpl_card") || state.chosenSituations.has("cant_pay"))) {
    lines.push(`<p>${esc(tIn(lang, "desk.aarogyasri"))}</p>`);
  }
  return lines.join("");
}
function openDeskCard(f, refused = false) {
  const dlg = $("desk");
  const cites = [...new Set(["clinical_establishments_act",
    ...(refused ? ["parmanand_katara_case"] : []),
    ...(state.chosenSituations.has("road_accident") ? ["parmanand_katara_case", "road_accident_cashless"] : [])])]
    .map((d) => `<span class="cite">${citeText(d)}</span>`).join(" ");
  dlg.innerHTML = `<div class="desk">
    <div class="desk__top"><p class="desk__hint">${esc(t("desk.hint"))}</p>
      <button type="button" class="btn btn--ghost btn--sm" id="desk-close">${esc(t("desk.close"))}</button></div>
    <p class="desk__title"><svg class="ico"><use href="#i-plus"/></svg>${esc(t("desk.title"))}</p>
    <div class="desk__body" lang="${state.lang}">${deskLines(state.lang, f, refused)}</div>
    ${state.lang !== "en" ? `<div class="desk__body desk__body--en" lang="en" dir="ltr"><p class="desk__label">${esc(t("desk.english"))}</p>${deskLines("en", f, refused)}</div>` : ""}
    <p class="desk__cites">${cites}</p>
  </div>`;
  $("desk-close").addEventListener("click", () => dlg.close());
  dlg.showModal();
  track("action", refused ? "refuse_desk" : "desk_card", { facility_id: f.id, tier: f.tier });
}

/* ---------- documents to carry (rules: backend/checklist.py) ---------- */
function checklistItems() {
  const r = state.checklistRules;
  const injury = state.triage?.injury.key || state.injury;
  const patient = [
    ...(r.by_injury[injury] || []),
    ...[...state.conditions].flatMap((c) => r.by_condition[c] || []),
    ...[...state.chosenSituations].flatMap((s) => r.by_situation[s] || []),
    ...r.always,
  ];
  return { patient: [...new Set(patient)], scheme: r.scheme };
}
function docItem(key) {
  const src = state.checklistRules.items[key]?.source;
  const ticked = state.docs.has(key);
  // Cited items show their source; the rest are marked as practical tips (*), never given a made-up citation.
  return `<li><label class="docs__item"><input type="checkbox" data-doc="${esc(key)}" ${ticked ? "checked" : ""}>
    <span>${esc(t(`doc.${key}`))}${src ? ` <span class="cite">${citeText(src)}</span>` : '<span class="docs__star" aria-hidden="true">*</span>'}</span></label></li>`;
}
function checklistHtml(f) {
  const { patient, scheme } = checklistItems();
  return `<div class="docs">
    <div class="firstaid__head"><p class="docs__title"><svg class="ico"><use href="#i-doc"/></svg>${esc(t("docs.title"))}</p>${speakButton(".docs")}</div>
    <p class="docs__delay">${esc(t("docs.dont_delay"))}${citePill("clinical_establishments_act")}</p>
    <p class="docs__group">${esc(t("docs.patient"))}</p>
    <ul class="docs__list">${patient.map(docItem).join("")}</ul>
    <p class="docs__group">${esc(t("docs.scheme"))}</p>
    ${f.aarogyasri_empanelled === false ? `<p class="docs__note">${esc(t("docs.scheme_not_here"))}</p>` : ""}
    <ul class="docs__list">${scheme.map(docItem).join("")}</ul>
    <p class="docs__tip">* ${esc(t("docs.tip"))}</p>
  </div>`;
}

// Aarogyasri status is tri-state: true, false, or null (not verified in our sources).
function empKey(f) { return f.aarogyasri_empanelled === true ? "yes" : f.aarogyasri_empanelled === false ? "no" : "unknown"; }
const EMP_MARK = { yes: "✓", no: "✕", unknown: "?" };
function empLine(f) {
  // Evidence from the official scheme registry is stronger than news or a hospital's own website: say which.
  return t(f.aarogyasri_empanelled === true && f.aarogyasri_evidence === "official" ? "emp.yes_official" : `emp.${empKey(f)}`);
}
function sourcesBlock(f) {
  if (!f.sources?.length) return "";
  return `<div class="fac__sources"><p class="fac__sub">${esc(t("sources_checked", { date: fmtDate(f.checked_on) }))}</p><ul>${
    f.sources.map((x) => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a></li>`).join("")}</ul></div>`;
}
function typeLine(f) { return `${t(`type.${f.type}`)} · ${f.locality} · ${Number(f.distance_km).toFixed(1)} km`; }

// How much Raahat has checked this hospital (phone / public sources / not yet), and how long ago.
// Not researched by Raahat: only listed (OpenStreetMap), or also in the scheme's official list.
function notChecked(f) { return f.data_level === "unchecked" || f.data_level === "registry"; }
function checkedLine(f) {
  if (f.data_level === "unchecked") return `<p class="checked checked--unchecked">${esc(t("trust.unchecked"))}</p>`;
  // In the scheme's official list: proof it is in the Aarogyasri network, not of what it can treat.
  if (f.data_level === "registry") {
    const link = f.scheme_source ? ` <a href="${esc(f.scheme_source.url)}" target="_blank" rel="noopener">${esc(t("trust.registry_link"))}</a>` : "";
    return `<p class="checked checked--registry">${esc(t("trust.registry", { date: fmtDate(f.checked_on) }))}${link}</p>`;
  }
  const days = daysSince(f.checked_on);
  if (days === null) return "";
  if (days > STALE_DAYS) return `<p class="checked checked--stale">${esc(t("checked.stale", { days }))}</p>`;
  const key = f.data_level === "phone_verified" ? "trust.phone_verified" : "trust.public";
  return `<p class="checked">${esc(t(key, { date: fmtDate(f.checked_on) }))}</p>`;
}

// "What to ask when you call": useful for every hospital, essential for ones we haven't checked.
function callScript(f, open = false) {
  const injury = state.triage?.injury;
  if (!injury) return "";
  const item = state.injuries.find((i) => i.key === injury.key);
  const need = injury.needs?.length ? injury.needs.map((s) => t(`spec.${s}`)).join(" / ") : t("call.need_default");
  const text = t("call.script", { emergency: item ? injuryLabel(item) : injury.label, need });
  return `<details class="callscript"${open ? " open" : ""}><summary>${esc(t("call.title"))}</summary>
    <p class="callscript__text">${esc(text)}</p>
    <div class="callscript__actions"><button type="button" class="btn btn--ghost btn--sm copy-btn" data-text="${esc(text)}">${esc(t("call.copy"))}</button>${speakButton(".callscript")}</div>
  </details>`;
}
// Does the scheme registry list this hospital for the specialist team this emergency needs?
// A registry list can be incomplete, so a missing speciality means "ask", never "not covered".
// Shown on the card only when there's something to say; the full list lives under "More details".
function schemeVerdict(f) {
  const needs = state.triage?.injury.needs || [];
  if (f.aarogyasri_empanelled === false || !f.scheme_specialties || !needs.length) return "";
  const match = needs.find((s) => f.scheme_specialties.includes(s));
  return `<p class="scheme ${match ? "scheme--ok" : "scheme--ask"}">${esc(match ? t("scheme.match", { spec: t(`spec.${match}`) }) : t("scheme.nomatch"))}</p>`;
}
function schemeList(f) {
  if (f.aarogyasri_empanelled === false) return "";
  if (!f.scheme_specialties) return `<p class="scheme scheme--unknown">${esc(t("scheme.unknown"))}</p>`;
  const list = f.scheme_specialties.map((s) => t(`spec.${s}`)).join(", ");
  const src = f.scheme_source ? ` <a href="${esc(f.scheme_source.url)}" target="_blank" rel="noopener">${esc(f.scheme_source.label)}</a>` : "";
  return `<p class="scheme">${esc(t("scheme.listed", { list }))}</p>${src ? `<p class="scheme scheme--src">${src}</p>` : ""}`;
}
const REPORTS = ["no_emergency", "wrong_phone", "no_aarogyasri", "closed", "other"];
function reportBlock(f) {
  if (state.reported[f.id]) return `<p class="report__thanks">${esc(t("report.thanks"))}</p>`;
  return `<div class="report"><p class="fac__sub"><svg class="ico"><use href="#i-flag"/></svg>${esc(t("report.title"))}</p>
    <div class="chips">${REPORTS.map((r) => `<button type="button" class="chip report__btn" data-id="${f.id}" data-value="${r}">${esc(t(`report.${r}`))}</button>`).join("")}</div></div>`;
}

// One hospital, one decision: name, distance and the two buttons that matter. Details stay below.
function renderBest(f, noMatch = false) {
  const box = $("best");
  box.hidden = !f && !noMatch;
  box.classList.toggle("best--none", noMatch);
  if (noMatch) {
    box.innerHTML = `<p class="best__name">${esc(t("best.none_title"))}</p><p class="best__more">${esc(t("best.none_body"))}</p>
      <div class="best__actions"><a class="btn btn--sos" href="tel:108"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("call108.button"))}</a></div>`;
    return;
  }
  if (!f) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <p class="best__label">${esc(t("best.title"))}</p>
    <p class="best__name">${esc(f.name)}</p>
    <p class="best__meta">${tierPill(f)} <span>${esc(t("best.km", { km: Number(f.distance_km).toFixed(1) }))}</span></p>
    <div class="best__actions">
      ${phoneButton(f, true)}
      <a class="btn ${f.phone ? "btn--ghost" : "btn--primary"} dir-link" data-id="${f.id}" href="${directionsUrl(f)}" target="_blank" rel="noopener"><svg class="ico"><use href="#i-nav"/></svg>${esc(t("directions"))}</a>
      ${speakButton(".best")}
    </div>
    <p class="best__more">${esc(t("best.caveat"))} ${esc(t("best.more"))}</p>`;
}

function renderResults() {
  const { results, origin, injury } = state.triage;
  const item = state.injuries.find((i) => i.key === injury.key);
  $("found").innerHTML = inlineMd(t("found", { label: item ? injuryLabel(item) : injury.label, n: results.length }));
  const none = !results.length;
  const offline = !!state.triage.offline;
  $("spec-note").hidden = injury.specialist_data && !none && !offline;
  $("spec-note").textContent = offline ? t("offline.note")
    : none ? t("flow.none_near", { km: $("radius").value }) : t("no_specialist_data");
  $("spec-note").classList.toggle("note--warn", offline);
  document.querySelector(".metrics").hidden = !injury.specialist_data || none || offline;
  document.querySelector(".results__grid").hidden = none;

  const specialists = results.filter((f) => f.tier === "specialist");
  $("m-specialists").textContent = specialists.length;
  $("m-nearest").textContent = specialists.length ? Math.min(...specialists.map((f) => f.distance_km)).toFixed(1) : "—";
  $("m-empanelled").textContent = specialists.filter((f) => f.aarogyasri_empanelled === true).length;

  const note = state.lang !== "en" ? `<p class="small">${esc(t("reasons_english_note"))}</p>` : "";
  // Researched hospitals first. Then, only where they'd help (e.g. on the city's edge, where the
  // researched ones are far), up to 4 not-yet-checked hospitals that are closer than the best options.
  const capable = results.filter((f) => f.tier !== "unchecked" && f.tier !== "unsuitable");
  // "Not equipped" hospitals only when nothing better is within reach.
  const researched = capable.length ? capable : results.filter((f) => f.tier === "unsuitable");
  const best = researched.slice(0, 3).map((f) => f.distance_km);
  const nearer = best.length ? Math.min(...best) : Infinity;
  const closer = results.filter((f) => f.tier === "unchecked" && f.distance_km < nearer).slice(0, 4);
  // No hospital we've checked can treat this nearby: say so, and send people to 108 rather than to a
  // hospital we know isn't equipped or haven't checked.
  const noMatch = !capable.length && results.length > 0;
  renderBest(noMatch ? null : researched[0], noMatch);
  const card = (f) => `
    <li class="fac" style="--tier:${TIER_COLOR[f.tier]}" data-id="${f.id}" tabindex="0" aria-current="${f.id === state.selectedId}">
      <div class="fac__name"><span class="fac__rank">#${f.rank}</span>${esc(f.name)}</div>
      <span class="pill pill--tier">${esc(t(`tier.${f.tier}`))}</span>
      <p class="fac__meta">${esc(typeLine(f))}</p>
      <p class="fac__emp">${esc(empLine(f))}</p>
      ${schemeVerdict(f)}
      ${checkedLine(f)}
      <div class="fac__actions">
        ${phoneButton(f)}
        <a class="btn btn--ghost btn--sm dir-link" data-id="${f.id}" href="${directionsUrl(f)}" target="_blank" rel="noopener"><svg class="ico"><use href="#i-nav"/></svg>${esc(t("directions"))}</a>
        ${appleMapsLink(f)}
      </div>
      ${notChecked(f) && f.phone ? callScript(f) : ""}
      <details class="fac__more"><summary>${esc(t("fac.more"))}</summary>
        ${phoneNote(f)}
        ${schemeList(f)}
        <p class="fac__sub">${esc(t("why_ranking"))}</p>${note}
        <ul>${(f.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("") || `<li>${esc(t("no_reasons"))}</li>`}</ul>
        ${sourcesBlock(f)}
        ${reportBlock(f)}
      </details>
    </li>`;
  $("facility-list").innerHTML = (noMatch ? `<li class="fac-group fac-group--warn">${esc(t("list.no_checked_match", { km: $("radius").value }))}</li>` : "")
    + researched.slice(0, 6).map(card).join("")
    + (closer.length ? `<li class="fac-group">${esc(t("list.closer_unchecked"))}</li>${closer.map(card).join("")}` : "");
  $("results-feedback").innerHTML = results.length
    ? feedbackHtml(t("helpful.results_q"), state.resultsFeedback, 'data-target="results"') : "";

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
  you.bindTooltip(t("you_are_here") || "You").addTo(state.layer);

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
    docs: [...state.docs],
    session,
  };
}
function newCase() {
  state.caseData = null;
  try { localStorage.removeItem(CASE_KEY); } catch { /* storage blocked */ }
  session = newSessionId();
  state.docs = new Set();
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
  return `<button type="button" class="speak-btn" data-speak="${rootSelector}"><svg class="ico"><use href="#i-speaker"/></svg><span>${esc(t("voice.read"))}</span></button>`;
}

function voiceFor(lang) {
  if (!("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  const want = SPEECH_LANG[lang].toLowerCase();
  return voices.find((v) => v.lang.replace("_", "-").toLowerCase() === want)
    || voices.find((v) => v.lang.toLowerCase().startsWith(lang));
}

// Text a person should hear: skip citation badges, buttons, notes and collapsed English originals.
function speakableText(root) {
  const clone = root.cloneNode(true);
  clone.querySelectorAll(".cite, details, button, .firstaid__note, .mt-label, .model, .steps__for, .steps__actions, .from, .feedback, .docs__tip, .eyebrow, .best__actions, input")
    .forEach((n) => n.remove());
  // A detached clone has no layout, so separate list items and paragraphs explicitly (gives the voice a pause).
  clone.querySelectorAll("li, p, h3").forEach((n) => n.append(" "));
  return clone.textContent.replace(/\s+/g, " ").trim();
}

// Most phones and laptops have no Telugu or Urdu voice (and many no Hindi one), so when the
// phone can't speak the language, the server reads it with Gemini, a sentence or two at a time.
const SPEAK_CHUNK = 260;
let serverSpeech = null; // { audio, aborted, urls }

function speechChunks(text) {
  const sentences = text.match(/[^.!?।۔]+[.!?।۔]*\s*/g) || [text];
  const chunks = [];
  let cur = "";
  for (const s of sentences) {
    // The first chunk is one sentence, so the voice starts within a few seconds.
    if (cur && (cur.length + s.length > SPEAK_CHUNK || chunks.length === 0)) { chunks.push(cur.trim()); cur = ""; }
    cur += s;
    while (cur.length > SPEAK_CHUNK) { // one very long sentence: split at a space
      const cut = cur.lastIndexOf(" ", SPEAK_CHUNK) > 0 ? cur.lastIndexOf(" ", SPEAK_CHUNK) : SPEAK_CHUNK;
      chunks.push(cur.slice(0, cut).trim());
      cur = cur.slice(cut);
    }
  }
  if (cur.trim()) chunks.push(cur.trim());
  return chunks.filter(Boolean);
}

async function fetchSpeech(text, lang) {
  const res = await fetch("/api/speak", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language: lang }),
  });
  if (!res.ok) throw new Error(`speak ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

async function speakWithServer(btn, text, lang) {
  const job = { audio: new Audio(), aborted: false, urls: [] };
  serverSpeech = job;
  // The first words take a few seconds: say so, or people tap again (which stops it) and think it's broken.
  btn.classList.add("is-loading");
  btn.querySelector("span").textContent = t("voice.loading");
  job.audio.addEventListener("playing", () => {
    if (speakingBtn !== btn) return;
    btn.classList.remove("is-loading");
    btn.querySelector("span").textContent = t("voice.stop");
  });
  const chunks = speechChunks(text);
  let next = fetchSpeech(chunks[0], lang);
  try {
    for (let i = 0; i < chunks.length; i++) {
      const url = await next;
      if (job.aborted) return;
      job.urls.push(url);
      next = i + 1 < chunks.length ? fetchSpeech(chunks[i + 1], lang) : null; // fetch ahead while this plays
      next?.catch(() => {});
      job.audio.src = url;
      await new Promise((resolve, reject) => {
        job.audio.onended = resolve;
        job.audio.onerror = reject;
        job.audio.play().catch(reject);
      });
      if (job.aborted) return;
    }
  } catch {
    if (!job.aborted) toast(t("voice.no_voice"));
  }
  if (speakingBtn === btn) stopSpeaking();
}

function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (serverSpeech) {
    serverSpeech.aborted = true;
    serverSpeech.audio.pause();
    serverSpeech.urls.forEach((u) => URL.revokeObjectURL(u));
    serverSpeech = null;
  }
  if (speakingBtn) {
    speakingBtn.classList.remove("is-loading", "is-speaking");
    speakingBtn.querySelector("span").textContent = t("voice.read");
  }
  speakingBtn = null;
}

function toggleSpeak(btn) {
  const wasThis = speakingBtn === btn;
  stopSpeaking();
  if (wasThis) return;
  const root = btn.closest(btn.dataset.speak);
  const text = speakableText(root);
  if (!text) return;
  speakingBtn = btn;
  btn.classList.add("is-speaking");
  btn.querySelector("span").textContent = t("voice.stop");
  track("action", "read_aloud");
  const voice = voiceFor(state.lang);
  // Telugu, Hindi and Urdu always use the server's voice: many phones list a voice for them that
  // was never downloaded, and then the browser plays nothing at all. English uses the phone's own.
  if (state.lang !== "en" || !voice) {
    speakWithServer(btn, text, state.lang);
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LANG[state.lang];
  if (voice) u.voice = voice;
  u.rate = 0.9;
  u.onend = u.onerror = () => { if (speakingBtn === btn) stopSpeaking(); };
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

/* Voice, understood by Gemini: record, wait for the person to stop talking, send the audio.
 * The browser's own recognition needs the right language picked in advance and struggles with
 * Telugu/Hindi/Urdu mixed with English; Gemini hears all four and the mixes, and returns what it
 * heard plus the filled-in form. Phones that can't record fall back to the browser's recognition. */
const CAN_RECORD = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder && (window.AudioContext || window.webkitAudioContext));
const rec = { stream: null, mr: null, chunks: [], ctx: null, timer: null, started: 0, lastLoud: 0, noise: 0, busy: false };

function micState(mode) {
  const btn = $("mic-btn");
  btn.classList.toggle("is-listening", mode === "listening");
  btn.disabled = mode === "processing";
  if (mode !== "listening") $("mic-level").style.transform = "scaleX(0)";
  $("mic-label").textContent = t(mode === "listening" ? "voice.listening" : mode === "processing" ? "voice.processing" : "voice.speak");
}

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch { toast(t("voice.no_mic")); return; }
  Object.assign(rec, { stream, chunks: [], started: Date.now(), lastLoud: 0, noise: 0, signal: false });
  rec.mr = new MediaRecorder(stream);
  rec.mr.ondataavailable = (e) => { if (e.data.size) rec.chunks.push(e.data); };
  rec.mr.onstop = onRecordingStopped;
  rec.mr.start(250);
  micState("listening");
  // Silence detection: the first half second sets the room's noise level; after that, quiet for
  // SILENCE_MS after speaking (or FIRST_WORD_MS before any speech, or MAX_LISTEN_MS overall) ends it.
  const Ctx = window.AudioContext || window.webkitAudioContext;
  rec.ctx = new Ctx();
  rec.ctx.resume?.();
  const analyser = rec.ctx.createAnalyser();
  analyser.fftSize = 1024;
  rec.ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  rec.timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const x of buf) sum += x * x;
    const rms = Math.sqrt(sum / buf.length);
    const now = Date.now();
    if (rms > 0) rec.signal = true;
    $("mic-level").style.transform = `scaleX(${Math.min(1, rms * 12).toFixed(2)})`;
    // Some phones never feed the level meter; then only a tap or the time cap ends the recording.
    if (!rec.signal && now - rec.started > 2000) { if (now - rec.started > MAX_LISTEN_MS) stopRecording(); return; }
    if (now - rec.started < 500) { rec.noise = Math.max(rec.noise, rms); return; }
    if (rms > Math.max(0.012, rec.noise * 2.5)) rec.lastLoud = now;
    const quiet = rec.lastLoud ? now - rec.lastLoud > SILENCE_MS : now - rec.started > FIRST_WORD_MS;
    if (quiet || now - rec.started > MAX_LISTEN_MS) stopRecording();
  }, 100);
}

function stopRecording() {
  clearInterval(rec.timer);
  if (rec.mr?.state === "recording") rec.mr.stop();
  rec.stream?.getTracks().forEach((tr) => tr.stop());
}

// Decode whatever the phone recorded (webm/opus, mp4/aac...) and re-encode as 16 kHz mono WAV,
// a format Gemini accepts on every phone. A minute is about 2 MB.
async function toWav16k(blob, ctx) {
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  str(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([out], { type: "audio/wav" });
}

async function onRecordingStopped() {
  const ctx = rec.ctx;
  rec.ctx = null;
  const blob = new Blob(rec.chunks, { type: rec.mr.mimeType || "audio/webm" });
  // Too short to hold any words (an accidental tap): don't send it.
  if (Date.now() - rec.started < 1200 || !blob.size) { ctx?.close(); micState("idle"); return; }
  micState("processing");
  const timer = new AbortController();
  const stop = setTimeout(() => timer.abort(), 60000);
  try {
    const wav = await toWav16k(blob, ctx);
    const r = await fetch(`/api/understand_audio?language=${state.lang}&session=${encodeURIComponent(sessionId())}`,
      { method: "POST", headers: { "Content-Type": "audio/wav" }, body: wav, signal: timer.signal });
    const res = await r.json().catch(() => null);
    if (!r.ok) throw new Error(res?.error || t("cannot_connect"));
    if (!res.transcript) { toast(t("voice.nothing")); return; }
    $("describe-text").value = res.transcript;
    applyUnderstanding(res, res.transcript);
  } catch (err) {
    toast(err.name === "AbortError" ? t("timeout") : err.message || t("cannot_connect"));
  } finally {
    clearTimeout(stop);
    ctx?.close();
    micState("idle");
  }
}

function onMic() {
  if (CAN_RECORD) {
    if (rec.mr?.state === "recording") stopRecording();
    else if (!$("mic-btn").disabled) startRecording();
  } else toggleListening();
}

// Tap to start and tap to stop, or press and hold while talking like a WhatsApp voice note:
// people used to voice notes hold the button and let go, which a tap-only button ignores.
const HOLD_MS = 700;
function wireMic() {
  const btn = $("mic-btn");
  if (!CAN_RECORD) { btn.addEventListener("click", onMic); return; }
  let pressedAt = 0;
  btn.addEventListener("pointerdown", (ev) => {
    if (btn.disabled || ev.button > 0) return;
    pressedAt = Date.now();
    onMic();
  });
  btn.addEventListener("pointerup", () => {
    const held = pressedAt && Date.now() - pressedAt > HOLD_MS;
    pressedAt = 0;
    if (held && rec.mr?.state === "recording") stopRecording();
  });
  btn.addEventListener("contextmenu", (ev) => ev.preventDefault()); // long press shouldn't open a menu
  btn.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onMic(); } });
  btn.addEventListener("click", (ev) => ev.preventDefault());
}

// "Was this helpful?" -- one answer per item; the choice is remembered so it isn't asked twice.
function feedbackHtml(question, chosen, attrs) {
  if (chosen) return `<p class="feedback__thanks">${esc(t("helpful.thanks"))}</p>`;
  return `<div class="feedback__row"><span>${esc(question)}</span>
    <button type="button" class="chip feedback__btn" ${attrs} data-value="yes">${esc(t("helpful.yes"))}</button>
    <button type="button" class="chip feedback__btn" ${attrs} data-value="no">${esc(t("helpful.no"))}</button></div>`;
}
// Which document each answer came from and when it was last checked, always visible.
function sourceLine(sources) {
  return `<p class="from"><b>${esc(t("answer.from"))}:</b> ${sources.map((x) =>
    `<span class="cite">${esc(x.title)}${x.verified ? ` · ${esc(t("answer.verified", { date: fmtDate(x.verified) }))}` : ""}</span>`).join(" ")}</p>`;
}

function renderAnswer(m, index) {
  const fb = `<div class="feedback">${feedbackHtml(t("helpful.q"), m.feedback, `data-target="answer" data-msg="${index}"`)}</div>`;
  if (m.lowConfidence) {
    // Never shown as an answer: Raahat's sources didn't cover the question, so it says so.
    return `<div class="unsure"><p class="unsure__title"><svg class="ico"><use href="#i-alert"/></svg>${esc(t("unsure.title"))}</p>
      <p>${esc(t("unsure.body"))}</p>
      <a class="btn btn--sos btn--sm" href="tel:108"><svg class="ico"><use href="#i-phone"/></svg>${esc(t("call108.button"))}</a></div>${fb}`;
  }
  const translated = m.lang === state.lang ? m.translated : null;
  let html = "";
  if (translated) html += `<p class="mt-label"><svg class="ico"><use href="#i-sparkle"/></svg>${esc(t("mt_label"))}</p>`;
  else if (state.lang !== "en" && m.generated) html += `<p class="mt-label">${esc(t("translation_failed"))}</p>`;
  html += `<div class="explanation">${renderExplanation(translated || m.content)}</div>`;
  // Name the documents the answer actually cites (retrieval can bring in ones it didn't use).
  const cited = (m.sources || []).filter((s) => m.content.includes(`[${s.title}]`));
  if (cited.length || m.sources?.length) html += sourceLine(cited.length ? cited : m.sources);
  html += speakButton(".msg--ai");
  if (translated) html += `<details><summary>${esc(t("show_english"))}</summary><div class="explanation english">${renderExplanation(m.content)}</div></details>`;
  if (m.sources?.length) html += `<details><summary>${esc(t("sources_used"))}</summary><div class="sources">${m.sources.map((x) =>
    `<div><b>${esc(x.title)}</b>${esc(x.citation)}</div>`).join("")}</div></details>`;
  if (m.model?.generation) html += `<p class="model">${esc(t("generated_by", { gen: m.model.generation, emb: m.model.embedding }))}</p>`;
  return html + fb;
}

function renderChat() {
  const box = $("ent-result");
  const msgs = state.caseData?.messages || [];
  let html = "";
  if (state.restored && msgs.length) html += `<p class="note note--ok">${esc(t("welcome_back"))}</p>`;
  if (!msgs.length && !state.pending) {
    html += `<div class="ent__placeholder"><div><svg class="ico"><use href="#i-shield"/></svg><p>${esc(t("eligible_caption"))}</p></div></div>`;
  }
  html += `<div class="chat-log">${msgs.map((m, i) => m.role === "user"
    ? `<div class="msg msg--user"><span class="msg__who">${esc(t("chat_you"))}</span><p>${esc(m.content)}</p></div>`
    : `<div class="msg msg--ai">${renderAnswer(m, i)}</div>`).join("")}`;
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
      language: state.lang, history: previous, session: sessionId(),
    };
    if (question) body.question = question;
    if (state.caseData.notes) body.situation = state.caseData.notes;
    const res = await api("/api/entitlements", body, 120000);
    state.caseData.messages.push({
      role: "assistant", content: res.explanation, translated: res.explanation_translated,
      lang: state.lang, sources: res.sources, model: res.model, generated: res.generated,
      lowConfidence: res.low_confidence,
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
  if (c.session) session = c.session;
  state.docs = new Set(c.docs || []);
  setInjury(c.injury);
  if (LOCALITIES[c.locality]) { $("locality").value = c.locality; $("locality").dispatchEvent(new Event("change")); }
  state.chosenSituations = new Set(c.situations || []);
  state.conditions = new Set(c.conditions || []);
  renderConditionChips();
  $("situation-text").value = c.notes || "";
  await runSearch({ scroll: false, selectId: c.facilityId });
}

/* ---------- offline: save what's needed without signal (frontend/web/sw.js) ---------- */
async function enableOffline() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
  } catch { return; }
  // Save every first-aid and danger-signs card in English while the phone is idle and online (the
  // worker shows these when a translated card wasn't saved). Skipped on data-saver connections.
  if (!navigator.onLine || navigator.connection?.saveData) return;
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 3000));
  idle(async () => {
    // The person's own language too: those translations are saved on the server, so this is quick.
    const langs = [...new Set(["en", state.lang])];
    const urls = langs.flatMap((lang) => [
      ...state.injuries.map((i) => `/api/first_aid?injury=${encodeURIComponent(i.key)}&language=${lang}`),
      ...state.conditionList.map((c) => `/api/danger_signs?condition=${encodeURIComponent(c.key)}&language=${lang}`),
    ]);
    for (const u of urls) { try { await fetch(u); } catch { return; } }
    $("offline-ready").hidden = false;
  });
}

/* ---------- boot ---------- */
async function init() {
  try {
    const [i18n, injuries, situations, facilities, sources, conditionList, checklistRules, localities, helplines] = await Promise.all([
      api("/api/i18n"), api("/api/injuries"), api("/api/situations"), api("/api/facilities"), api("/api/sources"),
      api("/api/conditions"), api("/api/checklist").catch(() => null), api("/api/localities"),
      api("/api/helplines").catch(() => null),
    ]);
    Object.assign(state, { strings: i18n.strings, languages: i18n.languages, rtl: i18n.rtl, injuries, situations, sources,
      conditionList, checklistRules, facilities, localities, helplines });
    LOCALITIES = Object.fromEntries(localities.map((l) => [l.name, [l.lat, l.lng]]));
    $("sources-band").innerHTML = sources.filter((x) => x.kind === "legal").map((x) => `<li>${esc(x.title)}</li>`).join("");
    $("stat-injuries").textContent = injuries.length;
    $("stat-facilities").textContent = facilities.filter((f) => !notChecked(f)).length; // researched only
  } catch (err) {
    document.querySelector("main").insertAdjacentHTML("afterbegin",
      `<div class="container"><p class="demo-note">${esc(err.message || "Cannot connect to the Raahat server.")}</p></div>`);
    return;
  }

  // First visit: start in the phone's own language (te/hi/ur) if it's one we have.
  const saved = store.get("raahat.lang");
  const phoneLang = (navigator.languages || [navigator.language || ""]).map((l) => l.slice(0, 2).toLowerCase())
    .find((l) => state.languages[l]);
  state.lang = state.languages[saved] ? saved : (phoneLang || "en");
  state.injury = state.injuries[0]?.key;

  $("lang").innerHTML = Object.entries(state.languages).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("lang").value = state.lang;
  renderLocalities();
  $("locality").value = "Charminar";
  const syncCoords = () => { const [la, ln] = LOCALITIES[$("locality").value]; $("lat").value = la; $("lng").value = ln; };
  syncCoords();

  $("lang").addEventListener("change", () => { stopSpeaking();state.lang = $("lang").value; store.set("raahat.lang", state.lang); applyLanguage(); });
  $("locality").addEventListener("change", () => {
    syncCoords();
    $("use-coords").checked = false; // an area picked by hand replaces "my location"
    $("geo-status").hidden = true;
  });
  $("radius").addEventListener("input", () => ($("radius-val").textContent = $("radius").value));
  $("injury").addEventListener("change", () => { clearResults(); pickInjury($("injury").value); renderPics(); });
  $("pics").addEventListener("click", onPic);
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
  // Anonymous counts of the actions that matter: calling 108, getting directions, sharing.
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a");
    if (!a) return;
    if (a.getAttribute("href") === "tel:108") track("action", "call_108");
    else if (a.classList.contains("refuse__aid")) track("action", "call_legal_aid");
    else if (a.classList.contains("helpline") || a.classList.contains("helpline-link")) track("action", "call_helpline");
    else if (a.classList.contains("call-hospital")) {
      const f = state.triage?.results.find((x) => x.id === Number(a.dataset.id));
      track("action", "call_hospital", { facility_id: f?.id, tier: f?.tier });
    } else if (a.classList.contains("dir-link")) {
      const f = state.triage?.results.find((x) => x.id === Number(a.dataset.id));
      track("action", "directions", { facility_id: f?.id, tier: f?.tier });
    }
  });
  // Copy the call script (to paste into WhatsApp or read from the screen while calling).
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".copy-btn");
    if (!btn) return;
    ev.stopPropagation();
    try { await navigator.clipboard.writeText(btn.dataset.text); btn.textContent = `✓ ${t("call.copied")}`; }
    catch { toast(btn.dataset.text); } // no clipboard access: show the text so it can be read out
  });
  // "Was this helpful?" on results and on answers.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".feedback__btn");
    if (!btn) return;
    const { target, value } = btn.dataset;
    if (target === "results") {
      state.resultsFeedback = value;
      const f = state.triage?.results.find((x) => x.id === state.selectedId);
      track("feedback", value, { target, facility_id: f?.id, tier: f?.tier });
      $("results-feedback").innerHTML = feedbackHtml("", value, "");
    } else if (target === "answer") {
      const m = state.caseData?.messages[Number(btn.dataset.msg)];
      if (!m) return;
      m.feedback = value;
      track("feedback", value, { target, facility_id: state.selectedId, doc_ids: (m.sources || []).map((s) => s.doc_id) });
      saveCase();
      renderChat();
    }
  });
  $("next-steps").addEventListener("change", (ev) => {
    const cb = ev.target.closest("[data-doc]");
    if (!cb) return;
    if (cb.checked) state.docs.add(cb.dataset.doc); else state.docs.delete(cb.dataset.doc);
    if (state.caseData) { syncCase(); saveCase(); }
    if (cb.checked) track("action", "checklist_tick");
  });
  $("facility-list").addEventListener("click", (ev) => {
    const rep = ev.target.closest(".report__btn");
    if (rep) {
      const id = Number(rep.dataset.id);
      const f = state.triage?.results.find((x) => x.id === id);
      track("report", rep.dataset.value, { facility_id: id, tier: f?.tier });
      state.reported[id] = rep.dataset.value;
      rep.closest(".report").outerHTML = `<p class="report__thanks">${esc(t("report.thanks"))}</p>`;
      return;
    }
    if (ev.target.closest("details, a, .report__thanks")) return;
    const li = ev.target.closest(".fac");
    if (li) selectFacility(Number(li.dataset.id));
  });
  $("facility-list").addEventListener("keydown", (ev) => {
    const li = ev.target.closest(".fac");
    if (li && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); selectFacility(Number(li.dataset.id)); }
  });
  $("ent-facility").addEventListener("change", () => selectFacility(Number($("ent-facility").value)));
  $("describe-form").addEventListener("submit", onDescribe);
  if (CAN_RECORD || SpeechRec) { $("mic-btn").hidden = false; $("mic-hint").hidden = false; wireMic(); }
  // Phones: the helplines list starts folded so the form is the first thing on screen.
  if (window.matchMedia("(max-width: 600px)").matches) $("helplines-box").open = false;
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".speak-btn");
    if (btn) { ev.stopPropagation(); toggleSpeak(btn); }
  });
  if ("speechSynthesis" in window) window.speechSynthesis.getVoices(); // voices load asynchronously
  $("search-form").addEventListener("submit", onSearch);
  $("low-cost").checked = store.get("raahat.lowcost") === "1";
  $("low-cost").addEventListener("change", () => {
    store.set("raahat.lowcost", $("low-cost").checked ? "1" : "0");
    if (!$("results").hidden && state.injury) runSearch({ scroll: false });
  });
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
  // A saved case is no longer reopened on load: every visit starts at "What happened?".
  enableOffline();
}

init();
