"""
Gestione dello stato persistente: tiene traccia degli annunci già notificati
così da segnalare solo quelli NUOVI ad ogni esecuzione.
"""
import json
import os
from datetime import datetime, timezone


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"seen_ids": [], "last_run": None}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"seen_ids": [], "last_run": None}


def save_state(path: str, seen_ids: set) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Teniamo solo gli ultimi 5000 id per evitare che il file cresca all'infinito
    trimmed = list(seen_ids)[-5000:]
    data = {
        "seen_ids": trimmed,
        "last_run": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def filter_new(listings: list, seen_ids: set) -> list:
    """Ritorna solo gli annunci il cui id non è già in seen_ids."""
    new_listings = []
    for listing in listings:
        lid = listing.get("id")
        if not lid:
            continue
        if lid not in seen_ids:
            new_listings.append(listing)
    return new_listings
