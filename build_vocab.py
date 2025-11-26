"""
build_vocab.py

Fetches the most commonly observed genera in Sweden from iNaturalist
for a set of higher taxa (e.g. Insecta, Bryophyta), and writes them
to JSON files that can be used as a "vocabulary" for your quiz app.

Usage:
    python build_vocab.py

You can tweak TAXA_CONFIG below to control which groups and how many
genera per group to fetch.
"""

import json
import os
import time
from typing import List, Dict, Any, Optional

import requests

INAT_BASE = "https://api.inaturalist.org/v1"

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

# iNaturalist place_id for Sweden.
# You can look this up via:
#   https://api.inaturalist.org/v1/places/autocomplete?q=Sweden
SWEDEN_PLACE_ID = 7599  # adjust if needed

# How many top genera per group you want
DEFAULT_TOP_N = 100

# Where to write the JSON files (relative to this script)
OUTPUT_DIR = "data"

# Taxa configuration:
#   key: a short label you'll use in your quiz ("insects", "mosses", etc.)
#   taxon_id: iNat taxon ID for the broad group
#   top_n: how many genera to fetch (overrides DEFAULT_TOP_N if provided)
#
# You can look up taxon IDs via:
#   https://api.inaturalist.org/v1/taxa/autocomplete?q=Insecta
TAXA_CONFIG = [
    {
        "label": "insects",
        "taxon_id": 47158,   # Insecta
        "top_n": 10,
    },
]

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def fetch_top_genera(
    taxon_id: int,
    place_id: int,
    top_n: int = DEFAULT_TOP_N,
    locale: str = "sv",
    per_page: int = 100,
) -> List[Dict[str, Any]]:
    """
    Fetch top genera for a given higher taxon in a given place
    using the /observations/taxa endpoint.

    Returns a list of dicts with keys:
        scientificName, swedishName, rank, taxonId, obsCount
    """
    results: List[Dict[str, Any]] = []
    page = 1

    while len(results) < top_n:
        remaining = top_n - len(results)
        page_size = min(per_page, remaining)

        params = {
            "place_id": place_id,
            "taxon_id": taxon_id,
            "rank": "genus",
            "locale": locale,
            "per_page": page_size,
            "page": page,
            "order_by": "observation_count",
            "order": "desc",
        }

        print(
            f"Requesting genera for taxon_id={taxon_id}, page={page}, "
            f"per_page={page_size}..."
        )
        resp = requests.get(f"{INAT_BASE}/observations/taxa", params=params)
        resp.raise_for_status()
        data = resp.json()

        page_results = data.get("results", [])
        if not page_results:
            # No more data
            break

        for t in page_results:
            # Some fields may vary; be defensive.
            sci = t.get("name")
            if not sci:
                continue

            swedish = t.get("preferred_common_name")
            rank = t.get("rank")
            taxon_id_res = t.get("id")

            # observation count can be under different keys depending on API;
            # cover both:
            obs_count = (
                t.get("observation_count")
                or t.get("count")
                or 0
            )

            results.append(
                {
                    "scientificName": sci,
                    "swedishName": swedish,
                    "rank": rank,
                    "taxonId": taxon_id_res,
                    "obsCount": obs_count,
                }
            )

        # If fewer than requested returned, we're at the end
        if len(page_results) < page_size:
            break

        page += 1
        # Be gentle to the API
        time.sleep(0.2)

    # In case the API returned more than top_n due to pagination issues,
    # we sort again and trim.
    results.sort(key=lambda r: r["obsCount"], reverse=True)
    return results[:top_n]


def ensure_output_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def write_json(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main() -> None:
    ensure_output_dir(OUTPUT_DIR)

    for cfg in TAXA_CONFIG:
        label = cfg["label"]
        taxon_id = cfg["taxon_id"]
        top_n = cfg.get("top_n", DEFAULT_TOP_N)

        print(f"\n=== Fetching top {top_n} genera for group '{label}' ===")
        genera = fetch_top_genera(
            taxon_id=taxon_id,
            place_id=SWEDEN_PLACE_ID,
            top_n=top_n,
            locale="sv",
        )

        # You can further filter/curate here if desired,
        # e.g. drop genera without Swedish names or with very low obsCount.
        # Example:
        # genera = [g for g in genera if g["swedishName"] is not None]

        out_path = os.path.join(OUTPUT_DIR, f"{label}_genera_sweden.json")
        write_json(genera, out_path)

        print(f"  -> wrote {len(genera)} entries to {out_path}")

    print("\nDone. Commit the JSON files in 'data/' to your GitHub repo.")


if __name__ == "__main__":
    main()
