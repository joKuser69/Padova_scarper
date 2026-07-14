"""
Invio notifiche Telegram per i nuovi annunci trovati (o con prezzo variato),
e gestione dei comandi in arrivo (es. /start -> manda lo storico recente).

Richiede due variabili d'ambiente: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.

Formato del messaggio: titolo, zona, mq, locali, prezzo, prezzo/mq, nota di
confronto con la media di zona (se abbiamo abbastanza dati storici), nota di
variazione prezzo (se l'annuncio era già noto con un prezzo diverso),
valutazione IA. Se disponibile un'immagine, viene inviata come foto con
questo testo come didascalia; altrimenti solo testo.

GESTIONE COMANDI: il bot non ha un server sempre acceso (gira su GitHub
Actions ogni 6 ore), quindi non può "ascoltare" in tempo reale. Ad ogni
run controlliamo invece se sono arrivati nuovi messaggi dall'ultima volta
(API getUpdates di Telegram, con lo stesso spirito del controllo email IMAP)
e rispondiamo di conseguenza — con un ritardo massimo di 6 ore, non
istantaneo, ma sufficiente per non lasciare "/start" senza risposta.
"""
import os
import time
from urllib.parse import quote

import requests


def _format_it_number(value: float, decimals: int = 0) -> str:
    """Formatta un numero in stile italiano: punto per le migliaia, virgola
    per i decimali (es. 1234.5 -> '1.234,5').

    Bug reale scoperto in produzione: il trucco 'formatta in stile inglese
    (1,234.5) poi sostituisci tutte le virgole con i punti' si rompe quando
    ci sono anche decimali, perché la sostituzione tocca sia il separatore
    delle migliaia SIA quello dei decimali, producendo '1.234.5' (due punti)
    invece di '1.234,5'. Qui separiamo esplicitamente parte intera e
    decimale prima di convertire, così non c'è ambiguità."""
    formatted = f"{value:,.{decimals}f}"
    integer_part, _, decimal_part = formatted.partition(".")
    integer_part = integer_part.replace(",", ".")
    if decimals > 0:
        return f"{integer_part},{decimal_part}"
    return integer_part


STREET_PREFIXES = ("via ", "viale ", "piazza ", "corso ", "vicolo ", "largo ", "strada ")


def _build_maps_link(listing: dict) -> str:
    """Link di ricerca Google Maps (nessuna API key richiesta). Preferisce
    il titolo se sembra contenere un indirizzo vero (via/piazza/corso...),
    più preciso della sola zona; altrimenti usa la zona. Aggiunge sempre
    'Padova' per disambiguare se non già presente nel testo."""
    title = listing.get("title", "") or ""
    zone = listing.get("zone", "") or ""

    if any(prefix in title.lower() for prefix in STREET_PREFIXES):
        query = title
    elif zone:
        query = zone
    else:
        return ""

    if "padova" not in query.lower():
        query = f"{query}, Padova"

    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def _send_message(text: str, chat_id=None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

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


def _send_photo(photo_url: str, caption: str, chat_id=None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

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
    return f"{arrow} Prezzo {label}: da {_format_it_number(old_price)}€ a {_format_it_number(new_price)}€ ({diff_pct:.0f}%)"


def _format_zone_avg_note(listing: dict) -> str:
    avg = listing.get("zone_avg_price_sqm")
    sample_count = listing.get("zone_sample_count", 0)
    price_sqm = listing.get("price_per_sqm")
    listing_type = listing.get("listing_type", "vendita")
    type_suffix = " affitto" if listing_type == "affitto" else ""

    if avg is None:
        if sample_count > 0:
            noun = "annuncio tracciato" if sample_count == 1 else "annunci tracciati"
            return f"📊 Zona {listing.get('zone')}{type_suffix}: dati insufficienti per una media affidabile ({sample_count} {noun} finora)"
        return ""

    if price_sqm is None:
        return f"📊 Media zona{type_suffix} {listing.get('zone')}: {_format_it_number(avg, 1)}€/m² (su {sample_count} annunci)"

    diff_pct = (price_sqm - avg) / avg * 100
    if diff_pct <= -5:
        verdict = f"🟢 {abs(diff_pct):.0f}% sotto media"
    elif diff_pct >= 5:
        verdict = f"🔴 {diff_pct:.0f}% sopra media"
    else:
        verdict = "🟡 in linea con la media"

    return f"📊 Media zona{type_suffix}: {_format_it_number(avg, 1)}€/m² → questo annuncio {verdict}"


TYPE_BADGES = {
    "asta": "⚖️ ASTA GIUDIZIARIA",
    "affitto": "🔑 AFFITTO",
}

TYPE_PRICE_LABELS = {
    "asta": "Base d'asta",
    "affitto": "Canone mensile",
}


def _format_listing(listing: dict) -> str:
    title = listing.get("title", "Annuncio senza titolo")
    source = listing.get("source", "")
    zone = listing.get("zone")
    area_sqm = listing.get("area_sqm")
    rooms = listing.get("rooms")
    price_eur = listing.get("price_eur")
    url = listing.get("url", "")
    listing_type = listing.get("listing_type", "vendita")

    lines = [f"🏠 <b>{title}</b>"]

    badge = TYPE_BADGES.get(listing_type)
    if badge:
        lines.append(badge)

    meta_bits = []
    if zone:
        meta_bits.append(f"📍 {zone}")
    meta_bits.append(f"🏙 {source}")
    lines.append("  ".join(meta_bits))

    maps_link = _build_maps_link(listing)
    if maps_link:
        lines.append(f'🗺️ <a href="{maps_link}">Vedi su mappa</a>')

    detail_bits = []
    if area_sqm:
        detail_bits.append(f"📐 {area_sqm:.0f} m²")
    if rooms:
        detail_bits.append(f"🚪 {rooms} local{'e' if rooms == 1 else 'i'}")
    if detail_bits:
        lines.append("  ".join(detail_bits))

    price_label = TYPE_PRICE_LABELS.get(listing_type, "💶")
    price_prefix = f"{price_label}: " if listing_type in TYPE_PRICE_LABELS else "💶 "

    if price_eur:
        price_line = f"{price_prefix}{_format_it_number(price_eur)}€"
        if listing_type == "affitto":
            price_line += "/mese"
        if area_sqm:
            price_per_sqm = price_eur / area_sqm
            listing["price_per_sqm"] = price_per_sqm
            unit_label = "€/m²/mese" if listing_type == "affitto" else "€/m²"
            price_line += f"  (💹 {_format_it_number(price_per_sqm, 1)}{unit_label})"
        lines.append(price_line)
    elif listing.get("price_suspect"):
        lines.append("💶 prezzo non affidabile alla fonte — controlla l'annuncio")
    elif listing.get("price"):
        lines.append(f"{price_prefix}{listing['price']}")

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


PHOTO_CAPTION_LIMIT = 1024


def _send_listing(listing: dict, chat_id=None) -> bool:
    """Invia un singolo annuncio (foto+didascalia se possibile, altrimenti
    solo testo) al chat_id indicato, o a TELEGRAM_CHAT_ID se non specificato.
    Funzione condivisa tra le notifiche live e l'invio storico su /start."""
    text = _format_listing(listing)
    image_url = listing.get("image_url")

    success = False
    if image_url and len(text) <= PHOTO_CAPTION_LIMIT:
        success = _send_photo(image_url, text, chat_id=chat_id)
    elif image_url:
        print(
            f"[Telegram] Messaggio di {len(text)} caratteri supera il limite "
            f"didascalia ({PHOTO_CAPTION_LIMIT}): salto la foto, invio solo testo "
            "per non troncare il link a metà."
        )

    if not success:
        success = _send_message(text, chat_id=chat_id)

    return success


def notify_new_listings(listings: list) -> int:
    """Ritorna il numero di notifiche EFFETTIVAMENTE inviate con successo."""
    if not listings:
        print("[Telegram] Nessun nuovo annuncio da notificare.")
        return 0

    sent = 0
    for listing in listings:
        try:
            if _send_listing(listing):
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


# ---------------------------------------------------------------------------
# GESTIONE COMANDI IN ARRIVO (es. /start)
# ---------------------------------------------------------------------------

def _get_updates(offset=None) -> list:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return []

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        print(f"[Telegram] Errore nel controllo messaggi in arrivo: {e}")
        return []


def check_start_commands(database: dict) -> list:
    """Controlla se qualcuno ha mandato /start dall'ultimo controllo (usando
    l'offset salvato nel database, così non rispondiamo due volte allo
    stesso comando). Ritorna la lista dei chat_id da cui è arrivato un nuovo
    /start in questo run."""
    last_update_id = database.get("telegram_last_update_id")
    offset = (last_update_id + 1) if last_update_id is not None else None

    updates = _get_updates(offset=offset)
    if not updates:
        return []

    new_starters = []
    max_update_id = last_update_id

    for update in updates:
        update_id = update.get("update_id")
        if update_id is not None and (max_update_id is None or update_id > max_update_id):
            max_update_id = update_id

        message = update.get("message", {}) or {}
        text = (message.get("text") or "").strip()
        chat_id = message.get("chat", {}).get("id")

        if chat_id and text.startswith("/start"):
            new_starters.append(chat_id)

    if max_update_id is not None:
        database["telegram_last_update_id"] = max_update_id

    return new_starters


def send_history_to_chat(chat_id, database: dict, count: int = 20) -> None:
    """Manda gli ultimi N annunci tracciati a un chat_id specifico — la
    risposta a chi preme /start e non ha ancora visto nulla."""
    from scraper.db import zone_price_per_sqm_stats

    all_entries = list(database.get("listings", {}).items())
    all_entries.sort(key=lambda kv: kv[1].get("last_seen") or "", reverse=True)
    recent = all_entries[:count]

    if not recent:
        _send_message(
            "👋 Ciao! Il bot è attivo e sta monitorando gli alert email. "
            "Non ho ancora trovato annunci: ti avviserò appena disponibile.",
            chat_id=chat_id,
        )
        return

    _send_message(
        f"👋 Ciao! Ecco gli ultimi {len(recent)} annunci trovati finora. "
        "Da adesso in poi riceverai anche le notifiche dei nuovi.",
        chat_id=chat_id,
    )
    time.sleep(1)

    for listing_id, entry in recent:
        try:
            listing = dict(entry)  # copia: non modifichiamo il database
            listing["id"] = listing_id
            avg, sample_count = zone_price_per_sqm_stats(
                database, listing.get("zone"), exclude_id=listing_id,
                listing_type=listing.get("listing_type", "vendita"),
            )
            listing["zone_avg_price_sqm"] = avg
            listing["zone_sample_count"] = sample_count

            _send_listing(listing, chat_id=chat_id)
            time.sleep(1)
        except Exception as e:
            print(f"[Telegram] Errore invio storico per {listing_id}: {e}")
