"""
Invio notifiche Telegram per i nuovi annunci trovati.
Richiede due variabili d'ambiente: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.
"""
import os
import time

import requests


def _send_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID non impostate")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"[Telegram] Errore invio: {resp.status_code} {resp.text}")


def _format_listing(listing: dict) -> str:
    title = listing.get("title", "Annuncio senza titolo")
    price = listing.get("price", "")
    url = listing.get("url", "")
    source = listing.get("source", "")

    lines = [f"🏠 <b>{title}</b>"]
    if price:
        lines.append(f"💶 {price}")
    lines.append(f"📍 {source}")

    if "ai_score" in listing:
        stars = "⭐" * round(listing["ai_score"] / 2)
        lines.append(f"🤖 {stars} ({listing['ai_score']}/10) — {listing.get('ai_comment', '')}")

    if url:
        lines.append(f"🔗 {url}")

    return "\n".join(lines)


def notify_new_listings(listings: list) -> None:
    if not listings:
        print("[Telegram] Nessun nuovo annuncio da notificare.")
        return

    for listing in listings:
        try:
            _send_message(_format_listing(listing))
            time.sleep(1)  # rispetta i rate-limit di Telegram
        except Exception as e:
            print(f"[Telegram] Errore invio annuncio: {e}")

    print(f"[Telegram] Inviate {len(listings)} notifiche.")


def notify_run_summary(total_found: int, total_new: int, total_sent: int) -> None:
    """Messaggio di riepilogo, utile per sapere che il bot sta girando anche
    quando non ci sono nuovi annunci rilevanti."""
    try:
        _send_message(
            f"🔍 Run completato: {total_found} annunci scansionati, "
            f"{total_new} nuovi, {total_sent} notificati (dopo filtro IA)."
        )
    except Exception as e:
        print(f"[Telegram] Errore invio riepilogo: {e}")
