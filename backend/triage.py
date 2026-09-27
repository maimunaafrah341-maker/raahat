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
}

# Tiers drive both sort order and map colour.
TIER_SPECIALIST = "specialist"   # right specialty + enough trauma capability
TIER_CAN_MANAGE = "can_manage"   # partial fit: related specialty or weaker trauma setup
TIER_STABILIZE = "stabilize"     # emergency-capable, but will likely refer onward
TIER_UNSUITABLE = "unsuitable"
TIER_ORDER = [TIER_SPECIALIST, TIER_CAN_MANAGE, TIER_STABILIZE, TIER_UNSUITABLE]

DEFAULT_RADIUS_KM = 20.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def assess(facility: dict, injury: dict, distance_km: float, radius_km: float) -> dict:
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
        reasons.append("Related specialty only: " + ", ".join(s.replace("_", " ") for s in secondary_hits))
    else:
        reasons.append("No relevant specialty for this injury")

    shortfall = injury["min_trauma"] - facility["trauma_level"]
    if trauma_ok:
        score += 20
    else:
        score -= 10 * shortfall
        reasons.append(f"Trauma capability ({facility['trauma_label']}) below what this injury usually needs")

    if er:
        score += 10
        reasons.append("24x7 emergency department")
    else:
        score -= 15
        reasons.append("No 24x7 emergency — may be closed at night")

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


def rank_facilities(facilities: list[dict], injury_key: str, lat: float, lng: float,
                    radius_km: float = DEFAULT_RADIUS_KM) -> list[dict]:
    injury = INJURIES[injury_key]
    results = []
    for f in facilities:
        d = haversine_km(lat, lng, f["lat"], f["lng"])
        if d > radius_km:
            continue
        results.append({**f, "distance_km": round(d, 2), **assess(f, injury, d, radius_km)})
    results.sort(key=lambda r: (TIER_ORDER.index(r["tier"]), -r["score"]))
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results
