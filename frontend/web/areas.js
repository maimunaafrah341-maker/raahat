/* Area search: find Hyderabad areas from a few typed letters.
 *
 * Tolerates spelling variants (Amirpet / Ameerpet, Kukatpalli / Kukatpally), alternate names (KPHB,
 * LB Nagar / Lal Bahadur Nagar, from `aliases` in data/localities.json), small typos, and names typed in
 * Telugu, Hindi or Urdu script (transliterated, then compared by their consonants).
 * Used by app.js in the page and by tests/test_area_search.py through node.
 */
"use strict";
(function (root) {
  // Telugu and Devanagari: consonants carry an "a" unless a vowel sign or virama follows.
  const TE_CONS = "కkఖkగgఘgఙnచcఛcజjఝjఞnటtఠtడdఢdణnతtథtదdధdనnపpఫfబbభbమmయyరrఱrలlళlవvశsషsసsహh";
  const TE_VOW = "అaఆaఇiఈiఉuఊuఋrఎeఏeఐaiఒoఓoఔau";
  const TE_SIGN = "ాaిiీiుuూuృrెeేeైaiొoోoౌau";
  const HI_CONS = "कkखkगgघgङnचcछcजjझjञnटtठtडdढdणnतtथtदdधdनnपpफfबbभbमmयyरrलlळlवvशsषsसsहh";
  const HI_VOW = "अaआaइiईiउuऊuऋrएeऐaiओoऔau";
  const HI_SIGN = "ाaिiीiुuूuृrेeैaiोoौau";
  // Urdu writes few vowels; the consonant comparison below does the rest.
  const UR = "اaآaبbپpتtٹtثsجjچcحhخkدdڈdذzرrڑrزzژzسsشsصsضzطtظzغgفfقkکkكkگgلlمmنnںnوuہhهhھ‌یiيiےe";

  function table(s) {
    const m = {};
    // Entries are one script character followed by its Latin letters.
    for (const [, ch, lat] of s.matchAll(/([^a-z])([a-z]*)/g)) m[ch] = lat;
    return m;
  }
  const T = {
    te: { cons: table(TE_CONS), vow: table(TE_VOW), sign: table(TE_SIGN), virama: "్", nasal: "ం", dropFinalA: false },
    hi: { cons: table(HI_CONS), vow: table(HI_VOW), sign: table(HI_SIGN), virama: "्", nasal: "ंँ", dropFinalA: true },
  };
  const URDU = table(UR);

  function abugida(s, t) {
    let out = "";
    const chars = [...s];
    chars.forEach((ch, i) => {
      if (t.cons[ch] !== undefined) {
        out += t.cons[ch];
        const next = chars[i + 1];
        const inherent = !(next && (t.sign[next] !== undefined || next === t.virama || next === "़"));
        // Hindi drops the "a" at the end of a word (कुकट = kukat).
        const endOfWord = !next || !(t.cons[next] !== undefined || t.vow[next] !== undefined || t.sign[next] !== undefined);
        if (inherent && !(t.dropFinalA && endOfWord)) out += "a";
      } else if (t.vow[ch] !== undefined) out += t.vow[ch];
      else if (t.sign[ch] !== undefined) out += t.sign[ch];
      else if (t.nasal.includes(ch)) out += "n";
      else if (ch === t.virama || ch === "़" || ch === "ః" || ch === "ः" || ch === "‌" || ch === "‍") { /* none */ }
      else out += ch;
    });
    return out;
  }

  function toLatin(s) {
    if (/[ఀ-౿]/.test(s)) return abugida(s, T.te);
    if (/[ऀ-ॿ]/.test(s)) return abugida(s, T.hi);
    if (/[؀-ۿ]/.test(s)) return [...s].map((ch) => URDU[ch] ?? (/[؀-ۿ]/.test(ch) ? "" : ch)).join("");
    return s;
  }

  // One spelling for the sounds Hyderabad names are written many ways: ee/i, oo/ou/u, th/t, y/i, doubles.
  function norm(s) {
    let x = toLatin(String(s).normalize("NFC")).toLowerCase().replace(/[^a-z]/g, "");
    x = x.replace(/ph/g, "f").replace(/([kgcjtdbs])h/g, "$1").replace(/ck/g, "k").replace(/q/g, "k").replace(/x/g, "ks")
      .replace(/z/g, "j").replace(/w/g, "v").replace(/y/g, "i").replace(/ee/g, "i").replace(/oo|ou/g, "u");
    return x.replace(/(.)\1+/g, "$1");
  }
  const skeleton = (n) => n.replace(/[aeiou]/g, "").replace(/(.)\1+/g, "$1");

  // Edit distance with swaps (Damerau), stopping early once it's clearly too far.
  function distance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev2 = null, prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let best = i;
      for (let j = 1; j <= b.length; j++) {
        let d = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d = Math.min(d, prev2[j - 2] + 1);
        cur.push(d);
        best = Math.min(best, d);
      }
      if (best > max) return max + 1;
      prev2 = prev;
      prev = cur;
    }
    return prev[b.length];
  }

  // Precompute the spellings to compare against, once per area list.
  function index(areas) {
    return areas.map((a) => {
      const names = [a.name, ...(a.aliases || [])];
      return { area: a, forms: names.map((n) => {
        const words = String(n).split(/[\s.\-']+/).filter(Boolean).map(norm).filter(Boolean);
        const whole = norm(n);
        return { label: n, whole, words, skel: skeleton(whole) };
      }) };
    });
  }

  /* Best matches first: start of a name, then inside a name, then a near spelling, then same consonants.
   * Returns [{ area, label }] where label is the alias that matched when it wasn't the name itself. */
  function match(query, indexed, limit = 6) {
    const q = norm(query);
    // At least two typed letters (in any script), not two after folding ("x" becomes "ks").
    if (q.length < 2 || [...String(query).replace(/[\s\p{P}]/gu, "")].length < 2) return [];
    const qs = skeleton(q);
    const allowed = q.length >= 7 ? 2 : q.length >= 4 ? 1 : 0;
    const found = [];
    for (const item of indexed) {
      let best = null;
      for (const f of item.forms) {
        let score = null;
        if (f.whole.startsWith(q) || f.words.some((w) => w.startsWith(q))) score = 0;
        else if (q.length >= 3 && f.whole.includes(q)) score = 1;
        else if (allowed && (distance(q, f.whole.slice(0, q.length), allowed) <= allowed
          || distance(q, f.whole, allowed) <= allowed)) score = 2;
        else if (qs.length >= 3 && (f.skel.startsWith(qs) || (qs.length >= 4 && f.skel.includes(qs)))) score = 3;
        if (score !== null && (!best || score < best.score)) best = { score, label: f.label };
      }
      if (best) found.push({ area: item.area, label: best.label === item.area.name ? null : best.label, score: best.score });
    }
    found.sort((a, b) => a.score - b.score || a.area.name.length - b.area.name.length || a.area.name.localeCompare(b.area.name));
    return found.slice(0, limit).map(({ area, label }) => ({ area, label }));
  }

  const api = { norm, toLatin, index, match };
  root.RaahatAreas = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
