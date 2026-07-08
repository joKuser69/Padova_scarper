"""
Bot di monitoraggio annunci immobiliari Padova.
Fonti: alert email (Idealista, Immobiliare.it, Casa.it, Bakeca, Wikicasa) +
Mitula (scraping diretto, supplementare).
Punto di ingresso eseguito da GitHub Actions ad ogni schedulazione.
"""
import os
import sys

from config import (
    MITULA_SEARCHES,
    AI_FILTER_ENABLED,
    AI_MIN_SCORE,
    MAX_BUDGET_EUR,
    MAX_NEW_LISTINGS_PER_RUN,
    STATE_FILE,
)
from scraper import mitula_scraper, email_alerts, telegram_notify
from scraper.state import load_state, save_state, filter_new
from scraper.utils import parse_price_eur

if AI_FILTER_ENABLED:
    from scraper.ai_filter import evaluate_all


def apply_budget_filter(listings: list) -> list:
    """Scarta solo gli annunci per cui riusciamo a leggere un prezzo chiaro
    che supera il budget. Se il prezzo non è interpretabile, lo lasciamo
    passare: meglio un falso positivo in più che perdere un annuncio buono."""
    kept = []
    dropped = 0
    for listing in listings:
        price_value = parse_price_eur(listing.get("price", ""))
        if price_value is not None and price_value > MAX_BUDGET_EUR:
            dropped += 1
            continue
        kept.append(listing)

    if dropped:
        print(f"Filtro budget: scartati {dropped} annunci sopra {MAX_BUDGET_EUR}€")
    return kept


def main():
    print("=== Avvio monitoraggio annunci Padova ===")

    # --- Fonte 1: alert email (Idealista, Immobiliare.it, Casa.it, Bakeca, Wikicasa) ---
    imap_email = os.environ.get("IMAP_EMAIL")
    imap_app_password = os.environ.get("IMAP_APP_PASSWORD")

    email_listings = []
    if imap_email and imap_app_password:
        email_listings = email_alerts.fetch_new_listings(imap_email, imap_app_password)
        print(f"[Email] Totale link candidati estratti: {len(email_listings)}")
    else:
        print("[Email] IMAP_EMAIL / IMAP_APP_PASSWORD non configurati, salto questa fonte.")

    # --- Fonte 2: Mitula (supplementare, con dedup basato su state.json) ---
    state = load_state(STATE_FILE)
    seen_ids = set(state.get("seen_ids", []))
    is_first_run = state.get("last_run") is None

    mitula_listings = mitula_scraper.scrape_all(MITULA_SEARCHES)
    print(f"[Mitula] Totale annunci scansionati: {len(mitula_listings)}")

    if is_first_run:
        print(
            "Primo avvio rilevato per Mitula: memorizzo gli annunci attuali "
            "come 'già visti' senza notificarli tutti insieme."
        )
        seen_ids.update(l["id"] for l in mitula_listings if l.get("id"))
        save_state(STATE_FILE, seen_ids)
        mitula_new = []
    else:
        mitula_new = filter_new(mitula_listings, seen_ids)
        print(f"[Mitula] Nuovi annunci: {len(mitula_new)}")

    # --- Unione delle due fonti ---
    # Le email sono già "nuove per definizione" (erano email non lette,
    # marcate lette solo dopo il parsing): non passano dal dedup su state.json.
    new_listings = email_listings + mitula_new
    print(f"Totale nuovi annunci da valutare: {len(new_listings)}")

    if len(new_listings) > MAX_NEW_LISTINGS_PER_RUN:
        print(
            f"Attenzione: {len(new_listings)} nuovi annunci superano il limite "
            f"di sicurezza ({MAX_NEW_LISTINGS_PER_RUN}). Notifico solo i primi."
        )
        new_listings = new_listings[:MAX_NEW_LISTINGS_PER_RUN]

    # --- Filtro budget deterministico (prima dell'IA, più affidabile per i numeri) ---
    new_listings = apply_budget_filter(new_listings)

    # --- Filtro IA qualitativo ---
    to_notify = new_listings
    if AI_FILTER_ENABLED and new_listings:
        print("Valutazione IA in corso...")
        evaluated = evaluate_all(new_listings)
        to_notify = [l for l in evaluated if l.get("ai_score", 0) >= AI_MIN_SCORE]
        print(f"Annunci che superano la soglia IA ({AI_MIN_SCORE}/10): {len(to_notify)}")

    telegram_notify.notify_new_listings(to_notify)

    # Niente riepilogo se non c'è nulla di nuovo: con un run ogni 15 minuti,
    # un messaggio "0 nuovi" ripetuto diventerebbe rumore inutile su Telegram.
    if new_listings:
        telegram_notify.notify_run_summary(
            total_found=len(email_listings) + len(mitula_listings),
            total_new=len(new_listings),
            total_sent=len(to_notify),
        )

    # Aggiorniamo lo stato SOLO con gli id di Mitula (l'email si auto-gestisce
    # tramite il flag "letta" della casella IMAP).
    if not is_first_run:
        seen_ids.update(l["id"] for l in mitula_listings if l.get("id"))
        save_state(STATE_FILE, seen_ids)

    print("=== Fine esecuzione ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE FATALE: {e}")
        sys.exit(1)
