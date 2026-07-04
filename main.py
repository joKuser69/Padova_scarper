"""
Bot di monitoraggio annunci immobiliari Padova (Subito.it + Mitula).
Punto di ingresso eseguito da GitHub Actions ad ogni schedulazione.
"""
import sys

from config import (
    SUBITO_SEARCHES,
    MITULA_SEARCHES,
    AI_FILTER_ENABLED,
    AI_MIN_SCORE,
    MAX_NEW_LISTINGS_PER_RUN,
    STATE_FILE,
)
from scraper import subito_scraper, mitula_scraper, telegram_notify
from scraper.state import load_state, save_state, filter_new

if AI_FILTER_ENABLED:
    from scraper.ai_filter import evaluate_all


def main():
    print("=== Avvio scraping annunci Padova ===")

    state = load_state(STATE_FILE)
    seen_ids = set(state.get("seen_ids", []))
    is_first_run = state.get("last_run") is None

    all_listings = []
    all_listings.extend(subito_scraper.scrape_all(SUBITO_SEARCHES))
    all_listings.extend(mitula_scraper.scrape_all(MITULA_SEARCHES))

    print(f"Totale annunci scansionati: {len(all_listings)}")

    if is_first_run:
        print(
            "Primo avvio rilevato: memorizzo gli annunci attuali come 'già "
            "visti' senza inviare notifiche di massa. Dal prossimo run "
            "riceverai solo i NUOVI annunci."
        )
        seen_ids.update(l["id"] for l in all_listings if l.get("id"))
        save_state(STATE_FILE, seen_ids)
        telegram_notify.notify_run_summary(
            total_found=len(all_listings), total_new=0, total_sent=0
        )
        print("=== Fine esecuzione (setup iniziale) ===")
        return

    new_listings = filter_new(all_listings, seen_ids)
    print(f"Nuovi annunci (mai visti prima): {len(new_listings)}")

    # Tetto di sicurezza: se per qualche motivo troviamo un numero enorme di
    # "nuovi" annunci (es. primo run, o un selettore cambiato che rompe il
    # dedup), evitiamo di spammare centinaia di notifiche in un colpo solo.
    if len(new_listings) > MAX_NEW_LISTINGS_PER_RUN:
        print(
            f"Attenzione: {len(new_listings)} nuovi annunci superano il limite "
            f"di sicurezza ({MAX_NEW_LISTINGS_PER_RUN}). Notifico solo i più recenti."
        )
        new_listings = new_listings[:MAX_NEW_LISTINGS_PER_RUN]

    to_notify = new_listings
    if AI_FILTER_ENABLED and new_listings:
        print("Valutazione IA in corso...")
        evaluated = evaluate_all(new_listings)
        to_notify = [l for l in evaluated if l.get("ai_score", 0) >= AI_MIN_SCORE]
        print(f"Annunci che superano la soglia IA ({AI_MIN_SCORE}/10): {len(to_notify)}")

    telegram_notify.notify_new_listings(to_notify)
    telegram_notify.notify_run_summary(
        total_found=len(all_listings),
        total_new=len(new_listings),
        total_sent=len(to_notify),
    )

    # Aggiorniamo lo stato con TUTTI gli annunci visti in questo run (non solo
    # quelli notificati), così non li rivalutiamo mai più.
    seen_ids.update(l["id"] for l in all_listings if l.get("id"))
    save_state(STATE_FILE, seen_ids)

    print("=== Fine esecuzione ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE FATALE: {e}")
        sys.exit(1)
