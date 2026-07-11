"""
Archivio persistente strutturato degli annunci monitorati (JSON).

A differenza del precedente state.py (che salvava solo un elenco di ID già
visti), questo tiene per ogni annuncio: prezzo attuale, storico dei prezzi,
mq, zona, immagine. Questo permette di:
- rilevare quando lo STESSO annuncio ricompare con un prezzo diverso
- calcolare il prezzo medio al mq per zona, aggregando su tutti gli annunci
  di cui conosciamo sia prezzo che superficie

Resta un file JSON (non SQLite) di proposito: a queste dimensioni (poche
migliaia di annunci al massimo) le prestazioni non sono un problema, e un
file JSON puoi aprirlo e leggerlo direttamente anche dall'editor web di
GitHub da telefono — una vera DB binaria sarebbe più scomoda da ispezionare
nel tuo flusso di lavoro.
"""
import json
import os
from datetime import datetime, timezone

from scraper.utils import price_is_plausible


def load_db(path: str) -> dict:
    if not os.path.exists(path):
        return {"listings": {}, "last_run": None}

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {"listings": {}, "last_run": None}

    data.setdefault("listings", {})
    data.setdefault("last_run", None)

    # Migrazione dal vecchio formato (state.py, versione precedente): teneva
    # solo un elenco piatto di id già visti, senza prezzo/mq/storico. Se lo
    # troviamo, convertiamo ogni id in una scheda minima nel nuovo formato,
    # così il primo run col nuovo codice non tratta 60 annunci Mitula già
    # noti come "nuovi" tutti insieme.
    old_seen_ids = data.pop("seen_ids", None)
    if old_seen_ids:
        now = datetime.now(timezone.utc).isoformat()
        for lid in old_seen_ids:
            if lid not in data["listings"]:
                data["listings"][lid] = {
                    "first_seen": now,
                    "last_seen": now,
                    "source": "migrato dalla versione precedente",
                    "title": None,
                    "url": None,
                    "zone": None,
                    "price_eur": None,
                    "area_sqm": None,
                    "rooms": None,
                    "image_url": None,
                    "price_history": [],
                }
        print(f"[DB] Migrati {len(old_seen_ids)} id dal vecchio formato state.json")

    # Autoguarigione: ripulisce schede salvate in precedenza con un prezzo
    # implausibile (es. errori di dati alla fonte già inquinavano la media
    # di zona prima che questo controllo esistesse). Si applica una sola
    # volta per scheda: una volta pulita, price_eur resta None finché un
    # prossimo avvistamento non porta un valore plausibile.
    sanitized = 0
    for entry in data["listings"].values():
        entry_type = entry.get("listing_type", "vendita")
        if not price_is_plausible(entry.get("price_eur"), entry.get("area_sqm"), entry_type):
            entry["price_eur"] = None
            entry["price_history"] = []
            sanitized += 1
    if sanitized:
        print(f"[DB] Ripulite {sanitized} schede con prezzo implausibile (probabili errori di dati alla fonte)")

    return data


def save_db(path: str, db: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db["last_run"] = datetime.now(timezone.utc).isoformat()

    # Evitiamo una crescita indefinita: teniamo al massimo le 3000 schede
    # viste più di recente.
    listings = db.get("listings", {})
    if len(listings) > 3000:
        sorted_items = sorted(
            listings.items(), key=lambda kv: kv[1].get("last_seen", ""), reverse=True
        )
        db["listings"] = dict(sorted_items[:3000])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def is_first_run(db: dict) -> bool:
    return db.get("last_run") is None


def upsert_listing(db: dict, listing: dict) -> dict:
    """Inserisce o aggiorna un annuncio. Ritorna:
    {'is_new': bool, 'price_changed': bool, 'old_price': int|None, 'new_price': int|None}
    """
    listings = db.setdefault("listings", {})
    lid = listing["id"]
    now = datetime.now(timezone.utc).isoformat()
    new_price = listing.get("price_eur")
    listing_type = listing.get("listing_type", "vendita")

    # Difesa extra (oltre a normalize_listing): non salvare mai un prezzo
    # implausibile nel database, altrimenti inquinerebbe la media di zona.
    if not price_is_plausible(new_price, listing.get("area_sqm"), listing_type):
        new_price = None

    result = {
        "is_new": lid not in listings,
        "price_changed": False,
        "old_price": None,
        "new_price": new_price,
    }

    if lid in listings:
        entry = listings[lid]
        old_price = entry.get("price_eur")
        if old_price is not None and new_price is not None and old_price != new_price:
            result["price_changed"] = True
            result["old_price"] = old_price
            entry.setdefault("price_history", []).append({"date": now, "price_eur": new_price})

        entry["last_seen"] = now
        if new_price is not None:
            entry["price_eur"] = new_price

        for field in ("area_sqm", "rooms", "zone", "title", "url", "image_url", "listing_type"):
            value = listing.get(field)
            if value:
                entry[field] = value
    else:
        listings[lid] = {
            "first_seen": now,
            "last_seen": now,
            "source": listing.get("source"),
            "title": listing.get("title"),
            "url": listing.get("url"),
            "zone": listing.get("zone"),
            "price_eur": new_price,
            "area_sqm": listing.get("area_sqm"),
            "rooms": listing.get("rooms"),
            "image_url": listing.get("image_url"),
            "listing_type": listing_type,
            "price_history": [{"date": now, "price_eur": new_price}] if new_price is not None else [],
        }

    return result


def zone_price_per_sqm_stats(db: dict, zone: str, exclude_id: str = None, listing_type: str = "vendita"):
    """Ritorna (media_eur_per_mq, numero_annunci_usati) per una zona,
    calcolata SOLO su annunci dello stesso tipo (vendita/affitto/asta) — non
    avrebbe senso mediare un prezzo di vendita con un canone di affitto.
    Ritorna (None, N) se ci sono meno di 3 annunci comparabili."""
    if not zone:
        return None, 0

    zone_norm = zone.strip().lower()
    values = []
    for lid, entry in db.get("listings", {}).items():
        if exclude_id and lid == exclude_id:
            continue
        if (entry.get("zone") or "").strip().lower() != zone_norm:
            continue
        if entry.get("listing_type", "vendita") != listing_type:
            continue
        price = entry.get("price_eur")
        area = entry.get("area_sqm")
        if price and area and area > 0:
            values.append(price / area)

    if len(values) < 3:
        return None, len(values)

    return sum(values) / len(values), len(values)
