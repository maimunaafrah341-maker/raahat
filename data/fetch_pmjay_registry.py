"""Fetch the official list of PM-JAY empanelled hospitals in Greater Hyderabad -> data/registry_pmjay.json.

Telangana runs Aarogyasri together with Ayushman Bharat PM-JAY, so a hospital empanelled under PM-JAY in
Telangana is in the scheme's network. The source is the National Health Authority's hospital search
(https://hospitals.pmjay.gov.in, "Empanelled Hospitals"). Its result pages need a captcha, but the
form's own hospital-name list doesn't, and filtering that list by district and hospital type tells us,
for each hospital: that it is empanelled, which district, and whether it is public or private. (The list
ignores the speciality filter, so specialities are NOT taken from here; they need the captcha search.)
Nothing here says whether a hospital has a 24x7 emergency or what it can treat tonight.

Run:  python data/fetch_pmjay_registry.py      (then re-seed: python data/seed_facilities.py)
"""
import http.cookiejar
import json
import time
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent / "registry_pmjay.json"
BASE = "https://hospitals.pmjay.gov.in/Search/"
SEARCH_PAGE = BASE + "empnlWorkFlow.htm?actionFlag=ViewRegisteredHosptlsNew"
STATE = "36"  # Telangana
# Greater Hyderabad spans these districts (codes from the form's own district list).
DISTRICTS = {"507": "Hyderabad", "700": "Medchal Malkajgiri", "518": "Ranga Reddy", "691": "Sangareddy"}
TYPES = {"Public": "govt", "PrivateNP": "charitable", "PrivateP": "private"}
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
opener.addheaders = [("User-Agent", "Mozilla/5.0 (Raahat research script)")]


def names(district: str, hosp_type: str = "-1") -> list[str]:
    url = (f"{BASE}empanelApplicationForm.htm?actionVal=GETHOSPNAMESLIST&stateId={STATE}&empanelmentType=PMJAY"
           f"&distCode={district}&hospType={hosp_type}&hospSpec=-1&hospName=-1&specSearch=N")
    for attempt in range(4):
        try:
            with opener.open(urllib.request.Request(url, method="POST"), timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
            break
        except OSError:
            time.sleep(3 * (attempt + 1))
    else:
        raise SystemExit(f"registry did not answer: {url}")
    text = text.strip().lstrip("*").strip("[]")
    return sorted({part.split("~")[1].strip() for part in text.split(",") if "~" in part and part.split("~")[1].strip()})


def main() -> None:
    opener.open(SEARCH_PAGE, timeout=60).read()  # session cookie, as a browser gets it
    hospitals: dict[tuple[str, str], dict] = {}
    for dist, dist_name in DISTRICTS.items():
        for code, kind in TYPES.items():
            for name in names(dist, hosp_type=code):
                hospitals[(dist, name)] = {"name": name, "district": dist_name, "type": kind}
            time.sleep(0.5)
        for name in names(dist):  # a few have no hospital type in the registry
            hospitals.setdefault((dist, name), {"name": name, "district": dist_name, "type": "unknown"})
        print(f"{dist_name}: {sum(1 for d, _ in hospitals if d == dist)} empanelled hospitals", flush=True)
    rows = sorted(hospitals.values(),
                  key=lambda h: (h["district"], h["name"].lower()))
    OUT.write_text(json.dumps({
        "source": "National Health Authority, Ayushman Bharat PM-JAY hospital search: Empanelled Hospitals, "
                  "State: Telangana, empanelment type PMJAY",
        "source_url": SEARCH_PAGE,
        "fetched_on": date.today().isoformat(),
        "note": "Telangana runs Aarogyasri together with PM-JAY. Being empanelled is not proof of a 24x7 emergency "
                "or of what a hospital can treat at a given time; specialities are not included.",
        "hospitals": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} hospitals -> {OUT.name}")


if __name__ == "__main__":
    main()
