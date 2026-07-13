"""
Bot di monitoraggio annunci immobiliari Padova.
Fonte unica: alert email nativi di Idealista, Immobiliare.it, Casa.it,
Bakeca, Wikicasa, TecnoCasa, Subito.it (rimosso Mitula: era la fonte con più
problemi di affidabilità — anti-bot indiretto sui link, bug di parsing
prezzi — mentre gli alert email arrivano direttamente dai portali ufficiali).

Ogni run controlla anche se qualcuno ha scritto "/start" al bot dall'ultima
volta: in quel caso gli manda gli ultimi 20 annunci tracciati, così chi
inizia a usarlo non trova un canale vuoto in attesa del primo nuovo annuncio.

Ogni annuncio passa da:
1. normalizzazione campi (prezzo/mq/locali/zona/tipo in formato standard)
2. esclusione affitti (se EXCLUDE_RENTALS=True in config.py)
3. upsert nel database persistente -> rileva se è nuovo o se il prezzo è
   cambiato rispetto all'ultima volta che lo abbiamo visto
4. filtro budget deterministico
5. filtro IA (rilevanza + eventuale completamento zona/mq/locali mancanti)
6. calcolo confronto con la media prezzo/mq della zona
7. notifica Telegram (con foto se disponibile)
"""
import os
import sys

from config import (
    AI_FILTER_ENABLED,
    AI_MIN_SCORE,
    EXCLUDE_RENTALS,
    MAX_BUDGET_EUR,
    MAX_NEW_LISTINGS_PER_RUN,
    PADOVA_ZONES,
    STATE_FILE,
)
from scraper import email_alerts, telegram_notify, db
from scraper.utils import normalize_listing, exclude_rentals

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

    # --- Comandi in arrivo (es. /start): il bot non ha un server sempre
    # acceso, quindi controlliamo ad ogni run se qualcuno ha scritto dopo
    # l'ultimo controllo, con un ritardo massimo di 15 minuti. ---
    new_starters = telegram_notify.check_start_commands(database)
    for chat_id in new_starters:
        print(f"[Telegram] Nuovo /start da chat_id={chat_id}, invio storico recente")
        telegram_notify.send_history_to_chat(chat_id, database, count=20)

    imap_email = os.environ.get("IMAP_EMAIL")
    imap_app_password = os.environ.get("IMAP_APP_PASSWORD")

    if not imap_email or not imap_app_password:
        print("ERRORE: IMAP_EMAIL / IMAP_APP_PASSWORD non configurati. Niente da fare.")
        return

    listings = email_alerts.fetch_new_listings(imap_email, imap_app_password)
    print(f"Totale link candidati estratti dalle email: {len(listings)}")

    # --- Normalizzazione: prezzo/mq/locali/zona/tipo in formato standard ---
    for listing in listings:
        normalize_listing(listing, PADOVA_ZONES)

    # --- Esclusione affitti (se configurata): fuori dal flusso fin da
    # subito, niente db, niente chiamate IA sprecate su annunci che non
    # vuoi comunque vedere ---
    if EXCLUDE_RENTALS:
        before = len(listings)
        listings = exclude_rentals(listings)
        dropped = before - len(listings)
        if dropped:
            print(f"Esclusi {dropped} annunci in affitto (EXCLUDE_RENTALS=True)")

    # --- Upsert nel database: le email sono già "nuove per definizione"
    # (erano non lette), ma registriamo comunque ogni annuncio per lo
    # storico prezzi e la media di zona. Notifichiamo se è nuovo O se il
    # prezzo è cambiato rispetto a un avvistamento precedente (stesso
    # annuncio ricomparso in un alert successivo). ---
    candidates = []
    for listing in listings:
        result = db.upsert_listing(database, listing)
        if result["price_changed"]:
            listing["price_change"] = {"old": result["old_price"], "new": result["new_price"]}
        candidates.append(listing)

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

    # --- Confronto con la media di zona ---
    attach_zone_stats(to_notify, database)

    telegram_notify.notify_new_listings(to_notify)

    db.save_db(STATE_FILE, database)

    print("=== Fine esecuzione ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE FATALE: {e}")
        sys.exit(1)
