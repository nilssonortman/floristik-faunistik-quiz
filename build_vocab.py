#!/usr/bin/env python3
"""
Build species-level vocabularies for faunistics quiz from iNaturalist.

For each configured group (insects, plants, mosses, etc.), this script:
  1) Calls /observations/species_counts to get the most observed species in Sweden
  2) Deduplicates species across multiple higher taxa if needed
  3) Fetches full taxon info (to get family, etc.) via /v1/taxa
  4) Fetches ONE example observation with a usable photo per species
  5) Writes a JSON file with:

     [
       {
         "scientificName": "Bombus terrestris",
         "swedishName": "Mörk jordhumla",
         "genusName": "Bombus",
         "familyName": "Apidae",              # Latin family name (backwards-compatible)
         "familyScientificName": "Apidae",    # same as above
         "familySwedishName": "bin",          # Swedish family name if available
         "rank": "species",
         "taxonId": 52856,
         "obsCount": 1234,
         "exampleObservation": {
           "obsId": 1234567,
           "photoUrl": ".../large.jpg",
           "observer": "some_user",
           "licenseCode": "cc-by",
           "obsUrl": "https://www.inaturalist.org/observations/1234567"
         }
       },
       ...
     ]
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

INAT_BASE = "https://api.inaturalist.org/v1"

# iNaturalist place_id for Sweden (confirmed from /places/autocomplete)
SWEDEN_PLACE_ID = 7599

# Default number of TOP items per group (only used if top_n not given)
DEFAULT_TOP_N = 100

# Maximum number of pages to fetch per taxon when calling /observations/species_counts
# Each page contains up to 200 species.
MAX_SPECIES_PAGES = 3  # adjust as needed
MAX_RETRIES_PER_REQUEST = 5  # how many times to retry a single page on 429
INITIAL_BACKOFF_SECONDS = 1.0  # starting wait after first 429

# Where to write the JSON files (relative to this script)
OUTPUT_DIR = "data"

# Licenses we consider "safe" for student-facing usage
CONFIG_ALLOWED_LICENSES = ["cc0", "cc-by", "cc-by-nc"]

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
            311249,  # Bryophyta (mosses)
            64615,   # Marchantiophyta (liverworts)
        ],
        "top_n": 35,
    },
    # -------------------------
    # LICHENS (Lecanoromycetes = main lichen class)
    # -------------------------
    {
        "label": "lichens",
        "taxon_ids": [54743],  # Lecanoromycetes
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
# Helpers
# -------------------------------------------------------------------

def ensure_output_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def write_json(obj: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# -------------------------------------------------------------------
# iNat API calls
# -------------------------------------------------------------------

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
            f"  Requesting species_counts for taxon_id={taxon_id}, "
            f"place_id={place_id}, page={page}, per_page={per_page}..."
        )

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
                print(f"    Got 429 (throttling). Sleeping {wait:.1f}s before retry...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            break

        data = resp.json()
        page_results = data.get("results", [])
        if not page_results:
            break

        results.extend(page_results)

        total = data.get("total_results", 0)
        if page * per_page >= total:
            break

        page += 1
        time.sleep(0.2)  # be gentle between pages

    return results


def fetch_taxon_details(taxon_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Fetch full taxon info (including ancestors with family) for a list of taxon IDs.
    Uses /v1/taxa/<ids> and returns a dict taxonId -> taxon object.

    Batches in chunks to avoid URL length issues.
    """
    result: Dict[int, Dict[str, Any]] = {}
    if not taxon_ids:
        return result

    chunk_size = 30

    for i in range(0, len(taxon_ids), chunk_size):
        chunk = taxon_ids[i:i + chunk_size]
        url = f"{INAT_BASE}/taxa/{','.join(str(t) for t in chunk)}"
        # Swedish locale + preferred_place_id to get Swedish common names where available
        params = {
            "locale": "sv",
            "preferred_place_id": SWEDEN_PLACE_ID,
        }

        print(f"  Enriching taxonomy for taxon_ids {chunk[0]}..{chunk[-1]}")

        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("results", []):
            result[t["id"]] = t

        time.sleep(0.2)

    return result


def fetch_example_observation_for_species(taxon_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch a single example observation with a usable photo for a species (taxon_id).
    Prefer Sweden, fall back to worldwide.

    Returns a dict with:
      {
        "obsId": ...,
        "photoUrl": ...,
        "observer": ...,
        "licenseCode": ...,
        "obsUrl": ...
      }
    or None if nothing usable is found.
    """

    def try_fetch(place_id: Optional[int]) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "taxon_id": taxon_id,
            "photos": "true",
            "per_page": 30,
            "order": "desc",
            "order_by": "created_at",
            "locale": "sv",
            "quality_grade": "research",
        }
        if place_id is not None:
            params["place_id"] = place_id

        resp = requests.get(f"{INAT_BASE}/observations", params=params)
        if resp.status_code == 429:
            print(f"    429 throttling for taxon_id={taxon_id}, sleeping 2s...")
            time.sleep(2.0)
            resp = requests.get(f"{INAT_BASE}/observations", params=params)

        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])

    # Try Sweden, then global
    results = try_fetch(SWEDEN_PLACE_ID)
    if not results:
        results = try_fetch(None)
    if not results:
        return None

    raw = results[0]  # could randomize if you like
    photos = raw.get("photos") or []
    if not photos:
        return None

    # Prefer allowed licenses, otherwise first
    photo = None
    for p in photos:
        code = (p.get("license_code") or raw.get("license_code") or "").lower()
        if code in CONFIG_ALLOWED_LICENSES:
            photo = p
            break
    if photo is None:
        photo = photos[0]

    url = photo.get("url")
    if not url:
        return None
    # Use "large" version
    photo_url = url.replace("square.", "large.")

    observer = (raw.get("user") or {}).get("login") or "unknown"
    license_code = photo.get("license_code") or raw.get("license_code")

    return {
        "obsId": raw.get("id"),
        "photoUrl": photo_url,
        "observer": observer,
        "licenseCode": license_code,
        "obsUrl": f"https://www.inaturalist.org/observations/{raw.get('id')}",
    }


# -------------------------------------------------------------------
# Vocab builder (species-level)
# -------------------------------------------------------------------

def build_group_vocab_multi_taxa_species(label: str, taxon_ids: List[int], top_n: int):
    """
    For a given group (e.g. 'insects') defined by one or more higher taxon_ids,
    fetch species_counts for each taxon_id, merge them, deduplicate by species
    (taxon.id), and return up to top_n species with extra fields:

        scientificName (species),
        swedishName,
        genusName,
        familyName (Latin),
        familyScientificName (Latin),
        familySwedishName (if available),
        rank,
        taxonId,
        obsCount,
        exampleObservation
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

    print(f"  Keeping top {len(top_species)} species for {label}")

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

        family_scientific_name: Optional[str] = None
        family_swedish_name: Optional[str] = None

        for anc in ancestors:
            if anc.get("rank") == "family":
                family_scientific_name = anc.get("name")
                family_swedish_name = anc.get("preferred_common_name")
                break

        print(f"  Fetching example observation for {sci} (taxon_id={tid})...")
        example_obs = fetch_example_observation_for_species(tid)

        if example_obs is None:
            print(f"    -> No usable observation found for {sci}, skipping this species.")
            continue

        vocab.append(
            {
                "scientificName": sci,
                "swedishName": sw,
                "genusName": genus_name,
                # Backwards-compatible field for existing app.js (Latin family name):
                "familyName": family_scientific_name,
                # New explicit family fields:
                "familyScientificName": family_scientific_name,
                "familySwedishName": family_swedish_name,
                "rank": enriched.get("rank"),
                "taxonId": tid,
                "obsCount": entry["count"],
                "exampleObservation": example_obs,
            }
        )

    print(f"  Built vocab with {len(vocab)} species for {label}")
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
