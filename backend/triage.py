"""Rank facilities by capability to treat a given injury, then by distance.

Capability dominates: a well-equipped facility 10 km away outranks a clinic
next door that would only refer the patient onward.
"""
import math

# primary: any one of these means the facility has the right specialist team.
# secondary: can manage the case, but it is not their specialty.
# min_trauma: minimum trauma_level (see db.TRAUMA_LEVELS) to handle it on-site.
INJURIES = {
    "hand_finger": {
        "label": "Hand / finger injury (cut, crush, partial amputation)",
        "primary": ["hand_surgery", "plastic_surgery"],
        "secondary": ["orthopedics", "general_surgery"],
        "min_trauma": 2,
    },
    "fracture": {
        "label": "Broken bone / suspected fracture",
        "primary": ["orthopedics"],
        "secondary": ["general_surgery"],
        "min_trauma": 2,
    },
    "head_injury": {
        "label": "Head injury (fall, blow to head, unconsciousness)",
        "primary": ["neurosurgery"],
        "secondary": ["general_surgery"],
        "min_trauma": 3,
    },
    "fall_polytrauma": {
        "label": "Fall from height / multiple serious injuries",
        "primary": ["neurosurgery", "orthopedics"],
        "secondary": ["general_surgery"],
        "min_trauma": 3,
    },
    "burns": {
        "label": "Burns (fire, electrical, chemical, scalding)",
        "primary": ["burns", "plastic_surgery"],
        "secondary": ["general_surgery"],
        "min_trauma": 2,
    },
    "deep_cut": {
        "label": "Deep cut / heavy bleeding (not hand)",
        "primary": ["general_surgery", "plastic_surgery"],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "eye_injury": {
        "label": "Eye injury",
        "primary": ["ophthalmology"],
        "secondary": ["emergency_medicine"],
        "min_trauma": 0,
    },
    "chest_pain": {
        "label": "Chest pain / suspected heart attack",
        "primary": ["cardiology"],
        "secondary": ["emergency_medicine", "general_medicine"],
        "min_trauma": 1,
    },
    # Illnesses and special emergencies. An empty `primary` means our sources don't say which
    # hospitals have the specialist team (e.g. a stroke unit), so these rank on 24x7 emergency
    # care and distance only, and the app says so.
    "pregnancy_problem": {
        "label": "Pregnancy problem (bleeding, severe pain or headache, waters breaking, baby moving less)",
        "group": "illness",
        "primary": ["obstetrics"],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "child_unwell": {
        "label": "Baby or young child seriously unwell (breathing, fever, rash, won't wake)",
        "group": "illness",
        "primary": ["pediatrics"],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "chemo_fever": {
        "label": "Fever or feeling very unwell during cancer treatment (chemotherapy)",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "stroke": {
        "label": "Stroke signs (face drooping, arm weakness, slurred speech)",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "seizure": {
        "label": "Seizure / fit",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "severe_allergy": {
        "label": "Severe allergic reaction (swelling, can't breathe)",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "snake_bite": {
        "label": "Snake bite",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "poisoning": {
        "label": "Poisoning (pesticide, chemicals, medicines, fumes)",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "low_blood_sugar": {
        "label": "Low blood sugar (diabetes: shaking, sweating, confused)",
        "group": "illness",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    # Added with sourced first aid (corpus/first_aid_cpr, _choking, _asthma, _heatstroke, _dog_bite,
    # crisis_mental_health). None names a specialist team except psychiatry for a mental health crisis.
    "collapsed_not_breathing": {
        "label": "Collapsed / not responding / not breathing normally",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "choking": {
        "label": "Choking (can't breathe, cough or speak)",
        "primary": [],
        "secondary": ["emergency_medicine"],
        "min_trauma": 1,
    },
    "asthma_breathing": {
        "label": "Asthma attack / struggling to breathe",
        "primary": [],
        "secondary": ["emergency_medicine", "general_medicine"],
        "min_trauma": 1,
    },
    "heatstroke": {
        "label": "Heatstroke (very hot, confused, not sweating)",
        "primary": [],
        "secondary": ["emergency_medicine", "general_medicine"],
        "min_trauma": 1,
    },
    "animal_bite": {
        "label": "Dog, cat or monkey bite (rabies risk)",
        "primary": [],
        "secondary": ["emergency_medicine", "general_surgery"],
        "min_trauma": 1,
    },
    "mental_health_crisis": {
        "label": "Thoughts of suicide or self-harm / mental health crisis",
        "primary": ["psychiatry"],
        "secondary": ["emergency_medicine"],
        "min_trauma": 0,
    },
}

# Display groups, ordered by what someone in a panic looks for first (frontend GROUPS has the same order).
GROUPS = {
    "urgent": ["collapsed_not_breathing", "choking", "asthma_breathing", "chest_pain", "stroke", "severe_allergy", "seizure"],
    "injury": ["deep_cut", "hand_finger", "fracture", "head_injury", "fall_polytrauma", "burns", "eye_injury",
               "animal_bite", "snake_bite"],
    "illness": ["poisoning", "heatstroke", "low_blood_sugar", "chemo_fever"],
    "mother_child": ["pregnancy_problem", "child_unwell"],
    "mind": ["mental_health_crisis"],
}
for _g, _keys in GROUPS.items():
    for _k in _keys:
        INJURIES[_k]["group"] = _g
assert all("group" in _i for _i in INJURIES.values()), "every emergency type needs a display group"

# Who the patient is, alongside any emergency. Each brings its own sourced danger-signs card
# (rag.CONDITION_DOCS); `prefer` nudges hospitals with that department up within their tier.
CONDITIONS = {
    "pregnant": {"label": "Pregnant", "prefer": "obstetrics"},
    "chemotherapy": {"label": "Having cancer treatment (chemotherapy)", "prefer": "oncology"},
    "diabetes": {"label": "Has diabetes", "prefer": None},
    "young_child": {"label": "A baby or young child", "prefer": "pediatrics"},
}

# Tiers drive both sort order and map colour.
TIER_SPECIALIST = "specialist"   # right specialty + enough trauma capability
TIER_CAN_MANAGE = "can_manage"   # partial fit: related specialty or weaker trauma setup
TIER_STABILIZE = "stabilize"     # emergency-capable, but will likely refer onward
TIER_UNCHECKED = "unchecked"     # only listed (OpenStreetMap): capability unknown, "call first"
TIER_UNSUITABLE = "unsuitable"
TIER_ORDER = [TIER_SPECIALIST, TIER_CAN_MANAGE, TIER_STABILIZE, TIER_UNCHECKED, TIER_UNSUITABLE]
MAX_UNCHECKED = 10  # nearest not-yet-checked hospitals shown after the researched ones

DEFAULT_RADIUS_KM = 20.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def assess(facility: dict, injury: dict, distance_km: float, radius_km: float,
           conditions: tuple[str, ...] = ()) -> dict:
    if facility.get("data_level") == "unchecked":
        # Nothing is known about what it can treat; never call it "not equipped" -- say "call first".
        return {"score": round(-distance_km, 2), "tier": TIER_UNCHECKED,
                "reasons": ["Not yet checked by Raahat — call before going to confirm they can treat this"]}
    specs = set(facility["specialties"])
    primary_hits = [s for s in injury["primary"] if s in specs]
    secondary_hits = [s for s in injury["secondary"] if s in specs]
    trauma_ok = facility["trauma_level"] >= injury["min_trauma"]
    er = facility["emergency_24x7"]
    reasons = []

    score = 0.0
    if primary_hits:
        score += 50 + (10 if len(primary_hits) == len(injury["primary"]) else 0)
        reasons.append("Has " + ", ".join(s.replace("_", " ") for s in primary_hits))
    elif secondary_hits:
        score += 20
        if injury["primary"]:
            reasons.append("Related specialty only: " + ", ".join(s.replace("_", " ") for s in secondary_hits))
        else:
            reasons.append("Emergency medicine (our sources don't list a specialist team for this)")
    else:
        reasons.append("No relevant specialty listed in our sources for this injury")

    shortfall = injury["min_trauma"] - facility["trauma_level"]
    if trauma_ok:
        score += 20
    else:
        score -= 10 * shortfall
        reasons.append(f"Trauma capability ({facility['trauma_label']}) below what this injury usually needs")

    if er:
        score += 10
        reasons.append("24x7 emergency department")
    elif er is None:
        reasons.append("24x7 emergency not confirmed in our sources — call ahead if you can")
    else:
        score -= 15
        reasons.append("No 24x7 emergency — may be closed at night")

    for c in conditions:
        dept = CONDITIONS[c]["prefer"]
        if dept and dept in specs:
            score += 15
            reasons.append(f"Has {dept} ({CONDITIONS[c]['label'].lower()})")

    # Distance only fine-tunes within a tier: at most -20 at the edge of the radius.
    score -= 20 * min(distance_km / radius_km, 1.0)

    if primary_hits and trauma_ok and er:
        tier = TIER_SPECIALIST
    elif (primary_hits or secondary_hits) and facility["trauma_level"] >= 1 and er:
        tier = TIER_CAN_MANAGE
    elif primary_hits and trauma_ok:
        # Right specialists but no 24x7 casualty — fine in daytime hours.
        tier = TIER_CAN_MANAGE
    elif er and facility["trauma_level"] >= 1:
        tier = TIER_STABILIZE
    else:
        tier = TIER_UNSUITABLE

    return {"score": round(score, 1), "tier": tier, "reasons": reasons}


def cost_rank(f: dict) -> int:
    """0 = usually free (government), 1 = free/low-cost likely (charitable, Aarogyasri), 2 = ask about cost."""
    if f["type"] == "govt":
        return 0
    if f["type"] == "charitable" or f.get("aarogyasri_empanelled"):
        return 1
    return 2


def rank_facilities(facilities: list[dict], injury_key: str, lat: float, lng: float,
                    radius_km: float = DEFAULT_RADIUS_KM, conditions: tuple[str, ...] = (),
                    low_cost_first: bool = False) -> list[dict]:
    injury = INJURIES[injury_key]
    results = []
    for f in facilities:
        d = haversine_km(lat, lng, f["lat"], f["lng"])
        if d > radius_km:
            continue
        results.append({**f, "distance_km": round(d, 2), **assess(f, injury, d, radius_km, conditions)})
    # "Free / low-cost first" reorders hospitals only within a tier: a cheaper hospital never
    # jumps above one better equipped for this emergency. Unchecked hospitals stay nearest-first.
    results.sort(key=lambda r: (TIER_ORDER.index(r["tier"]),
                                cost_rank(r) if low_cost_first and r["tier"] != TIER_UNCHECKED else 0, -r["score"]))
    unchecked = [r for r in results if r["tier"] == TIER_UNCHECKED][MAX_UNCHECKED:]
    if unchecked:
        drop = {id(r) for r in unchecked}
        results = [r for r in results if id(r) not in drop]
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results
