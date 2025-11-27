"""
build_vocab.py

Fetches commonly observed genera in Sweden from iNaturalist
for a set of higher taxa (e.g. Insecta, Bryophyta), and writes them
to JSON files that can be used as a "vocabulary" for your quiz app.

Usage:
    python build_vocab.py
"""

import json
import os
import time
from typing import List, Dict, Any

import requests

INAT_BASE = "https://api.inaturalist.org/v1"

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

# iNaturalist place_id for Sweden (confirmed from /places/autocomplete)
SWEDEN_PLACE_ID = 7599

# Default number of TOP GENERA per group
DEFAULT_TOP_N = 100

# Maximum number of pages to fetch per taxon when calling /species_counts
# Each page contains up to 200 species.
MAX_SPECIES_PAGES = 5   # adjust as needed
MAX_RETRIES_PER_REQUEST = 5    # how many times to retry a single page
INITIAL_BACKOFF_SECONDS = 1.0  # starting wait after first 429

# Where to write the JSON files (relative to this script)
OUTPUT_DIR = "data"

# Taxa configuration: tweak as you like
TAXA_CONFIG = [
    # -------------------------
    # INSECTS
    # -------------------------
    {
        "label": "insects",
        "taxon_ids": [47158],  # Insecta
        "top_n": 70,
    },

    # -------------------------
    # PLANTS (broad)
    # -------------------------
    {
        "label": "plants",
        "taxon_ids": [47126],  # Plantae
        "top_n": 100,
    },

    # -------------------------
    # MOSSES = Bryophyta + Marchantiophyta 
    # -------------------------
    {
        "label": "mosses",
        "taxon_ids": [
            311249,   # Bryophyta (mosses)
            64615,   # Marchantiophyta (liverworts)
        ],
        "top_n": 35,
    },

    # -------------------------
    # LICHENS (Lecanoromycetes = main lichen group)
    # -------------------------
    {
        "label": "lichens",
        "taxon_ids": [54743],  # Lecanoromycetes (main lichen class)
        "top_n": 30,
    },

    # -------------------------
    # MAMMALS
    # -------------------------
    {
        "label": "mammals",
        "taxon_ids": [40151],
        "top_n": 20,
    },

    # -------------------------
    # BIRDS
    # -------------------------
    {
        "label": "birds",
        "taxon_ids": [3],
        "top_n": 50,
    },

    # -------------------------
    # FUNGI
    # -------------------------
    {
        "label": "fungi",
        "taxon_ids": [47170],  # Fungi kingdom
        "top_n": 50,
    },

    # -------------------------
    # SPIDERS
    # -------------------------
    {
        "label": "spiders",
        "taxon_ids": [47118],  # Araneae
        "top_n": 35,
    },
]

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def ensure_output_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def write_json(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_species_counts(
    taxon_id: int,
    place_id: int,
    per_page: int = 200,
    locale: str = "sv",
) -> List[Dict[str, Any]]:
    """
    Fetch leaf-taxon counts (typically species) for a given higher taxon in a place
    using /observations/species_counts.

    Respects MAX_SPECIES_PAGES and retries on 429 (normal_throttling).
    """
    results: List[Dict[str, Any]] = []
    page = 1

    while True:
        if page > MAX_SPECIES_PAGES:
            print(f"  Reached MAX_SPECIES_PAGES={MAX_SPECIES_PAGES}, stopping early.")
            break

        params = {
            "place_id": place_id,
            "taxon_id": taxon_id,
            "per_page": per_page,
            "page": page,
            "verifiable": "true",
            "locale": locale,
            "order_by": "observations_count",
            "order": "desc",
        }

        print(
            f"Requesting species_counts for taxon_id={taxon_id}, "
            f"place_id={place_id}, page={page}, per_page={per_page}..."
        )

        # --- NEW: retry loop for this single request ---
        attempt = 0
        while True:
            resp = requests.get(f"{INAT_BASE}/observations/species_counts", params=params)

            if resp.status_code == 429:
                attempt += 1
                if attempt > MAX_RETRIES_PER_REQUEST:
                    raise requests.HTTPError(
                        f"Exceeded max retries ({MAX_RETRIES_PER_REQUEST}) after 429 "
                        f"for taxon_id={taxon_id}, page={page}"
                    )
                wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"  Got 429 (throttling). Sleeping {wait:.1f}s before retry...")
                time.sleep(wait)
                continue  # retry same request

            # If it's not 429, either OK or a real error
            resp.raise_for_status()
            break
        # --- end retry loop ---

        data = resp.json()
        page_results = data.get("results", [])
        if not page_results:
            break

        results.extend(page_results)

        total = data.get("total_results", 0)
        if page * per_page >= total:
            break

        page += 1
        time.sleep(0.2)  # still be gentle between pages

    return results



def aggregate_to_genera(
    species_counts: List[Dict[str, Any]],
    top_n: int,
) -> List[Dict[str, Any]]:
    """
    Aggregate species-level results up to genera.

    species_counts items look like:
        {
          "taxon": {...},
          "count": <int>,
          ...
        }

    We derive genus as the first word of taxon.name.
    """
    genus_map: Dict[str, Dict[str, Any]] = {}

    for item in species_counts:
        taxon = item.get("taxon") or {}
        count = item.get("count") or 0

        sci = taxon.get("name")
        if not sci:
            continue

        # Derive genus naively as first token (works fine for most cases)
        genus_name = sci.split(" ")[0]

        if genus_name not in genus_map:
            genus_map[genus_name] = {
                "scientificName": genus_name,
                "swedishName": None,
                "rank": "genus",
                "taxonId": None,     # we don't have a genus taxon_id here
                "obsCount": 0,
            }

        genus_entry = genus_map[genus_name]
        genus_entry["obsCount"] += int(count)

        # if we don't yet have a Swedish name for this genus, borrow the first
        # available Swedish species name as a hint (optional)
        if genus_entry["swedishName"] is None:
            sw = taxon.get("preferred_common_name")
            if sw:
                genus_entry["swedishName"] = sw

    # Sort by obsCount descending and take top_n
    genera_sorted = sorted(
        genus_map.values(),
        key=lambda g: g["obsCount"],
        reverse=True,
    )

    return genera_sorted[:top_n]


def build_group_vocab(label: str, taxon_id: int, top_n: int) -> List[Dict[str, Any]]:
    """
    For a given broad taxon (e.g. Insecta), get species_counts in Sweden,
    aggregate to genera, and return top_n genera.
    """
    species_counts = fetch_species_counts(
        taxon_id=taxon_id,
        place_id=SWEDEN_PLACE_ID,
        per_page=200,
        locale="sv",
    )

    print(f"  -> got {len(species_counts)} leaf taxa (species+etc) for {label}")

    top_genera = aggregate_to_genera(species_counts, top_n=top_n)
    print(f"  -> aggregated to {len(top_genera)} genera (top {top_n})")

    return top_genera

def build_group_vocab_multi_taxa(label: str, taxon_ids: list, top_n: int):
    all_species_counts = []

    for tid in taxon_ids:
        print(f"Fetching species for {label} from taxon_id={tid} ...")
        sc = fetch_species_counts(
            taxon_id=tid,
            place_id=SWEDEN_PLACE_ID,
            per_page=200,
            locale="sv",
        )
        print(f"  Got {len(sc)} leaf taxa for taxon_id={tid}")
        all_species_counts.extend(sc)

    # Aggregate everything to genera
    top_genera = aggregate_to_genera(all_species_counts, top_n=top_n)
    return top_genera


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main() -> None:
    ensure_output_dir(OUTPUT_DIR)

    for cfg in TAXA_CONFIG:
        label = cfg["label"]
        taxon_ids = cfg["taxon_ids"]   # <-- FIX: plural
        top_n = cfg.get("top_n", DEFAULT_TOP_N)

        print(f"\n=== Fetching top {top_n} genera for group '{label}' ===")

        genera = build_group_vocab_multi_taxa(
            label=label,
            taxon_ids=taxon_ids,      # <-- FIX: pass the plural variable
            top_n=top_n,
        )

        out_path = os.path.join(OUTPUT_DIR, f"{label}_genera_sweden.json")
        write_json(genera, out_path)

        print(f"  -> wrote {len(genera)} entries to {out_path}")

    print("\nDone. Commit the JSON files in 'data/' to your GitHub repo.")


if __name__ == "__main__":
    main()
