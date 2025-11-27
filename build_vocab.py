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
MAX_SPECIES_PAGES = 3   # adjust as needed
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

def fetch_taxon_details(taxon_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Fetch full taxon info (including ancestors with family) for a list of taxon IDs.
    Uses /v1/taxa/<ids> and returns a dict taxonId -> taxon object.

    Batches in chunks of 30 to avoid URL length / rate issues.
    """
    result: Dict[int, Dict[str, Any]] = {}
    if not taxon_ids:
        return result

    chunk_size = 30

    for i in range(0, len(taxon_ids), chunk_size):
        chunk = taxon_ids[i:i + chunk_size]
        url = f"{INAT_BASE}/taxa/{','.join(str(t) for t in chunk)}"
        # Use English locale to ensure full ancestor hierarchy is present
        params = {"locale": "en"}

        print(f"  Enriching taxonomy for taxon_ids {chunk[0]}..{chunk[-1]}")

        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("results", []):
            result[t["id"]] = t

        time.sleep(0.2)  # be kind to API

    return result



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

def build_group_vocab_multi_taxa_species(label: str, taxon_ids: list, top_n: int):
    """
    For a given group (e.g. 'insects') defined by one or more higher taxon_ids,
    fetch species_counts for each taxon_id, merge them, deduplicate by species
    (taxon.id), and return the top_n species with extra fields:

        scientificName (species),
        swedishName,
        genusName,
        familyName,
        rank,
        taxonId,
        obsCount
    """
    all_species_counts: List[Dict[str, Any]] = []

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

    # Deduplicate by species taxonId, keeping the highest count
    species_map: Dict[int, Dict[str, Any]] = {}  # taxonId -> {"taxon": ..., "count": ...}

    for item in all_species_counts:
        taxon = item.get("taxon") or {}
        tid = taxon.get("id")
        if not tid:
            continue
        count = int(item.get("count") or 0)

        existing = species_map.get(tid)
        if existing is None or count > existing.get("count", 0):
            species_map[tid] = {
                "taxon": taxon,
                "count": count,
            }

    species_list = list(species_map.values())
    species_list.sort(key=lambda x: x["count"], reverse=True)
    top_species = species_list[:top_n]

    # Enrich with full taxonomy (ancestors incl. family) using /v1/taxa
    taxon_ids_list = [
        e["taxon"]["id"] for e in top_species if e["taxon"].get("id") is not None
    ]
    tax_details = fetch_taxon_details(taxon_ids_list)

    vocab: List[Dict[str, Any]] = []

    for entry in top_species:
        taxon = entry["taxon"]
        tid = taxon.get("id")
        if not tid:
            continue

        sci = taxon.get("name")
        if not sci:
            continue

        sw = taxon.get("preferred_common_name")
        genus_name = sci.split(" ")[0]

        # Use enriched taxon if available (for ancestors/family)
        enriched = tax_details.get(tid, taxon)
        ancestors = enriched.get("ancestors") or []

        family_name = None
        for anc in ancestors:
            if anc.get("rank") == "family":
                family_name = anc.get("name")
                break

        vocab.append(
            {
                "scientificName": sci,          # species binomial
                "swedishName": sw,
                "genusName": genus_name,
                "familyName": family_name,
                "rank": enriched.get("rank"),
                "taxonId": tid,
                "obsCount": entry["count"],
            }
        )

    return vocab

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main() -> None:
    ensure_output_dir(OUTPUT_DIR)

    for cfg in TAXA_CONFIG:
        label = cfg["label"]
        taxon_ids = cfg["taxon_ids"]
        top_n = cfg.get("top_n", DEFAULT_TOP_N)

        print(f"\n=== Fetching top {top_n} species for group '{label}' ===")

        vocab = build_group_vocab_multi_taxa_species(
            label=label,
            taxon_ids=taxon_ids,
            top_n=top_n,
        )

        out_path = os.path.join(OUTPUT_DIR, f"{label}_vocab_sweden.json")
        write_json(vocab, out_path)

        print(f"  -> wrote {len(vocab)} entries to {out_path}")

    print("\nDone. Commit the JSON files in 'data/' to your GitHub repo.")


if __name__ == "__main__":
    main()
