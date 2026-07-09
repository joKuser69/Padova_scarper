"""
Invio notifiche Telegram per i nuovi annunci trovati (o con prezzo variato).
Richiede due variabili d'ambiente: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.

Formato del messaggio: titolo, zona, mq, locali, prezzo, prezzo/mq, nota di
confronto con la media di zona (se abbiamo abbastanza dati storici), nota di
variazione prezzo (se l'annuncio era già noto con un prezzo diverso),
valutazione IA. Se disponibile un'immagine, viene inviata come foto con
questo testo come didascalia; altrimenti solo testo.
"""
import os
import time

import requests


def _send_message(text: str) -> bool:
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
        print(f"[Telegram] Errore invio messaggio: {resp.status_code} {resp.text}")
        return False
    return True


def _send_photo(photo_url: str, caption: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID non impostate")

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption[:1024],  # limite Telegram per le didascalie
            "parse_mode": "HTML",
        },
        timeout=20,
    )
    if not resp.ok:
        # Non è un errore grave: capita se l'URL immagine non è raggiungibile
        # da Telegram (link scaduto, hotlink protetto, ecc). Ricadiamo sul
        # messaggio di solo testo.
        print(f"[Telegram] Foto non inviabile ({resp.status_code}), uso testo semplice")
        return False
    return True


def _format_price_change_note(listing: dict) -> str:
    change = listing.get("price_change")
    if not change:
        return ""
    old_price = change["old"]
    new_price = change["new"]
    if new_price < old_price:
        arrow, label = "🔻", "sceso"
    else:
        arrow, label = "🔺", "salito"
    diff_pct = abs(new_price - old_price) / old_price * 100
    return f"{arrow} Prezzo {label}: da {old_price:,}€ a {new_price:,}€ ({diff_pct:.0f}%)".replace(",", ".")


def _format_zone_avg_note(listing: dict) -> str:
    avg = listing.get("zone_avg_price_sqm")
    sample_count = listing.get("zone_sample_count", 0)
    price_sqm = listing.get("price_per_sqm")

    if avg is None:
        if sample_count > 0:
            noun = "annuncio tracciato" if sample_count == 1 else "annunci tracciati"
            return f"📊 Zona {listing.get('zone')}: dati insufficienti per una media affidabile ({sample_count} {noun} finora)"
        return ""

    if price_sqm is None:
        return f"📊 Media zona {listing.get('zone')}: {avg:,.0f}€/m² (su {sample_count} annunci)".replace(",", ".")

    diff_pct = (price_sqm - avg) / avg * 100
    if diff_pct <= -5:
        verdict = f"🟢 {abs(diff_pct):.0f}% sotto media"
    elif diff_pct >= 5:
        verdict = f"🔴 {diff_pct:.0f}% sopra media"
    else:
        verdict = "🟡 in linea con la media"

    return f"📊 Media zona: {avg:,.0f}€/m² → questo annuncio {verdict}".replace(",", ".")


def _format_listing(listing: dict) -> str:
    title = listing.get("title", "Annuncio senza titolo")
    source = listing.get("source", "")
    zone = listing.get("zone")
    area_sqm = listing.get("area_sqm")
    rooms = listing.get("rooms")
    price_eur = listing.get("price_eur")
    url = listing.get("url", "")

    lines = [f"🏠 <b>{title}</b>"]

    meta_bits = []
    if zone:
        meta_bits.append(f"📍 {zone}")
    meta_bits.append(f"🏙 {source}")
    lines.append("  ".join(meta_bits))

    detail_bits = []
    if area_sqm:
        detail_bits.append(f"📐 {area_sqm:.0f} m²")
    if rooms:
        detail_bits.append(f"🚪 {rooms} local{'e' if rooms == 1 else 'i'}")
    if detail_bits:
        lines.append("  ".join(detail_bits))

    if price_eur:
        price_line = f"💶 {price_eur:,}€".replace(",", ".")
        if area_sqm:
            price_per_sqm = price_eur / area_sqm
            listing["price_per_sqm"] = price_per_sqm
            price_line += f"  (💹 {price_per_sqm:,.0f}€/m²)".replace(",", ".")
        lines.append(price_line)
    elif listing.get("price_suspect"):
        lines.append("💶 prezzo non affidabile alla fonte — controlla l'annuncio")
    elif listing.get("price"):
        lines.append(f"💶 {listing['price']}")

    zone_note = _format_zone_avg_note(listing)
    if zone_note:
        lines.append(zone_note)

    price_change_note = _format_price_change_note(listing)
    if price_change_note:
        lines.append(price_change_note)

    if "ai_score" in listing:
        stars = "⭐" * max(1, round(listing["ai_score"] / 2))
        comment = listing.get("ai_comment", "")
        lines.append(f"🤖 {stars} ({listing['ai_score']:.0f}/10) — {comment}")

    if url:
        lines.append(f"🔗 {url}")

    return "\n".join(lines)


def notify_new_listings(listings: list) -> int:
    """Ritorna il numero di notifiche EFFETTIVAMENTE inviate con successo."""
    if not listings:
        print("[Telegram] Nessun nuovo annuncio da notificare.")
        return 0

    sent = 0
    for listing in listings:
        try:
            text = _format_listing(listing)
            image_url = listing.get("image_url")

            success = False
            if image_url:
                success = _send_photo(image_url, text)

            if not success:
                success = _send_message(text)

            if success:
                sent += 1
            time.sleep(1)  # rispetta i rate-limit di Telegram
        except Exception as e:
            print(f"[Telegram] Errore invio annuncio: {e}")

    if sent == 0:
        print(
            "[Telegram] ATTENZIONE: 0 notifiche inviate su "
            f"{len(listings)} tentativi. Controlla che il bot non sia "
            "bloccato e che TELEGRAM_CHAT_ID sia corretto."
        )
    else:
        print(f"[Telegram] Inviate {sent}/{len(listings)} notifiche.")

    return sent


def notify_run_summary(total_found: int, total_new: int, total_sent: int) -> None:
    try:
        _send_message(
            f"🔍 Run completato: {total_found} annunci scansionati, "
            f"{total_new} nuovi/variati, {total_sent} notificati (dopo filtro IA)."
        )
    except Exception as e:
        print(f"[Telegram] Errore invio riepilogo: {e}")
