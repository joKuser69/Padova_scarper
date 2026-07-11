"""
Bot di monitoraggio annunci immobiliari Padova.
Fonti: alert email (Idealista, Immobiliare.it, Casa.it, Bakeca, Wikicasa) +
Mitula (scraping diretto, supplementare).

Ogni annuncio (di qualunque fonte) passa da:
1. normalizzazione campi (prezzo/mq/locali/zona in formato standard)
2. upsert nel database persistente -> rileva se è nuovo o se il prezzo è
   cambiato rispetto all'ultima volta che lo abbiamo visto
3. filtro budget deterministico
4. filtro IA (rilevanza + eventuale completamento zona/mq/locali mancanti)
5. calcolo confronto con la media prezzo/mq della zona
6. notifica Telegram (con foto se disponibile)
"""
import os
import sys

from config import (
    MITULA_SEARCHES,
    AI_FILTER_ENABLED,
    AI_MIN_SCORE,
    MAX_BUDGET_EUR,
    MAX_NEW_LISTINGS_PER_RUN,
    PADOVA_ZONES,
    STATE_FILE,
)
from scraper import mitula_scraper, email_alerts, telegram_notify, db
from scraper.utils import normalize_listing

if AI_FILTER_ENABLED:
    from scraper.ai_filter import evaluate_all


def apply_budget_filter(listings: list) -> list:
    """Scarta solo gli annunci per cui riusciamo a leggere un prezzo chiaro
    che supera il budget. Se il prezzo non è interpretabile, lo lasciamo
    passare: meglio un falso positivo in più che perdere un annuncio buono."""
    kept = []
    dropped = 0
    for listing in listings:
        price_value = listing.get("price_eur")
        if price_value is not None and price_value > MAX_BUDGET_EUR:
            dropped += 1
            continue
        kept.append(listing)

    if dropped:
        print(f"Filtro budget: scartati {dropped} annunci sopra {MAX_BUDGET_EUR}€")
    return kept


def attach_zone_stats(listings: list, database: dict) -> None:
    """Aggiunge a ogni annuncio la media prezzo/mq della sua zona (se
    disponibile), calcolata sul database storico — solo tra annunci dello
    stesso tipo (vendita/affitto/asta)."""
    for listing in listings:
        listing_type = listing.get("listing_type", "vendita")
        avg, count = db.zone_price_per_sqm_stats(
            database, listing.get("zone"), exclude_id=listing.get("id"), listing_type=listing_type
        )
        listing["zone_avg_price_sqm"] = avg
        listing["zone_sample_count"] = count


def main():
    print("=== Avvio monitoraggio annunci Padova ===")

    database = db.load_db(STATE_FILE)
    first_run = db.is_first_run(database)

    # --- Fonte 1: alert email ---
    imap_email = os.environ.get("IMAP_EMAIL")
    imap_app_password = os.environ.get("IMAP_APP_PASSWORD")

    email_listings = []
    if imap_email and imap_app_password:
        email_listings = email_alerts.fetch_new_listings(imap_email, imap_app_password)
        print(f"[Email] Totale link candidati estratti: {len(email_listings)}")
    else:
        print("[Email] IMAP_EMAIL / IMAP_APP_PASSWORD non configurati, salto questa fonte.")

    # --- Fonte 2: Mitula ---
    mitula_listings = mitula_scraper.scrape_all(MITULA_SEARCHES)
    print(f"[Mitula] Totale annunci scansionati: {len(mitula_listings)}")

    # --- Normalizzazione: ogni annuncio, di qualunque fonte, ottiene gli
    # stessi campi standard (price_eur, area_sqm, rooms, zone) ---
    all_scanned = email_listings + mitula_listings
    for listing in all_scanned:
        normalize_listing(listing, PADOVA_ZONES)

    # --- Upsert nel database: rileva nuovi annunci e variazioni di prezzo ---
    # Mitula = scan dell'intero catalogo attuale: al primissimo run lo
    # registriamo silenziosamente (senza notificare tutto) per non fare un
    # flood. Le email invece rappresentano già "eventi" (alert veri e propri
    # dai portali), quindi passano sempre, anche al primo run.
    candidates = []

    for listing in email_listings:
        result = db.upsert_listing(database, listing)
        if result["is_new"] or result["price_changed"]:
            if result["price_changed"]:
                listing["price_change"] = {"old": result["old_price"], "new": result["new_price"]}
            candidates.append(listing)

    for listing in mitula_listings:
        result = db.upsert_listing(database, listing)
        if first_run:
            continue  # solo registrazione silenziosa al primo avvio
        if result["is_new"] or result["price_changed"]:
            if result["price_changed"]:
                listing["price_change"] = {"old": result["old_price"], "new": result["new_price"]}
            candidates.append(listing)

    if first_run:
        print(
            "Primo avvio rilevato: catalogo Mitula registrato silenziosamente "
            "senza notificare tutto in blocco. Le email (alert veri) sono "
            "comunque state processate normalmente."
        )

    print(f"Totale annunci nuovi o con prezzo variato: {len(candidates)}")

    if len(candidates) > MAX_NEW_LISTINGS_PER_RUN:
        print(
            f"Attenzione: {len(candidates)} annunci superano il limite di "
            f"sicurezza ({MAX_NEW_LISTINGS_PER_RUN}). Notifico solo i primi."
        )
        candidates = candidates[:MAX_NEW_LISTINGS_PER_RUN]

    # --- Filtro budget deterministico ---
    candidates = apply_budget_filter(candidates)

    # --- Filtro IA qualitativo (completa anche zona/mq/locali se mancanti) ---
    to_notify = candidates
    if AI_FILTER_ENABLED and candidates:
        print("Valutazione IA in corso...")
        candidates = evaluate_all(candidates)
        to_notify = [l for l in candidates if l.get("ai_score", 0) >= AI_MIN_SCORE]
        print(f"Annunci che superano la soglia IA ({AI_MIN_SCORE}/10): {len(to_notify)}")

    # --- Confronto con la media di zona (ora che zona/mq sono più completi
    # possibile grazie anche al passaggio IA) ---
    attach_zone_stats(to_notify, database)

    sent = telegram_notify.notify_new_listings(to_notify)

    db.save_db(STATE_FILE, database)

    print("=== Fine esecuzione ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE FATALE: {e}")
        sys.exit(1)
