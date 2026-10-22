"""'Documents to carry' per emergency, patient condition and situation.

Each item is a UI string `doc.<key>` (backend/i18n.py). `source` is the corpus document
that backs the item, shown as a citation; None marks a practical tip with no cited
source, and the app labels it that way rather than inventing a citation.
"""

ITEMS = {
    # Always useful
    "aadhaar":         {"source": None},
    "phone":           {"source": None},
    "medicines":       {"source": None},
    # Aarogyasri: "Beneficiaries need a BPL ration card / scheme enrollment"
    "ration_card":     {"source": "telangana_aarogyasri"},
    "aarogyasri_card": {"source": "telangana_aarogyasri"},
    # Who the patient is
    "referral":        {"source": None},
    "chemo":           {"source": None},
    "mcp":             {"source": None},
    "child":           {"source": None},
    "diabetes":        {"source": None},
    # What happened / situation
    "poison":          {"source": "first_aid_poisoning"},
    "bocw":            {"source": "telangana_bocw"},
}

ALWAYS = ["aadhaar", "phone", "medicines"]
SCHEME = ["ration_card", "aarogyasri_card"]
BY_INJURY = {"poisoning": ["poison"], "chemo_fever": ["chemo", "referral"],
             "pregnancy_problem": ["mcp"], "child_unwell": ["child"], "low_blood_sugar": ["diabetes"]}
BY_CONDITION = {"chemotherapy": ["chemo", "referral"], "pregnant": ["mcp"],
                "young_child": ["child"], "diabetes": ["diabetes"]}
BY_SITUATION = {"construction_worker": ["bocw"]}


def rules() -> dict:
    """Everything the page needs to build the checklist without another request."""
    return {"items": ITEMS, "always": ALWAYS, "scheme": SCHEME,
            "by_injury": BY_INJURY, "by_condition": BY_CONDITION, "by_situation": BY_SITUATION}


def checklist(injury: str, conditions: list[str] = (), situations: list[str] = ()) -> dict:
    """{'patient': [...], 'scheme': [...]} item keys, in display order, without repeats."""
    patient = [*BY_INJURY.get(injury, []), *(i for c in conditions for i in BY_CONDITION.get(c, [])),
               *(i for s in situations for i in BY_SITUATION.get(s, [])), *ALWAYS]
    return {"patient": list(dict.fromkeys(patient)), "scheme": list(SCHEME)}
