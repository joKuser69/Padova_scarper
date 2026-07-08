"""
Funzioni di utilità condivise tra i vari moduli scraper.
"""
import re


def parse_price_eur(price_str: str):
    """Converte una stringa prezzo (es. '250.000 €', '600 EUR', '1.200,50€')
    in un intero euro. Ritorna None se non riesce a interpretarla."""
    if not price_str:
        return None

    cleaned = re.sub(r"[^\d.,]", "", price_str)
    if not cleaned:
        return None

    # Formato italiano: punto = separatore migliaia, virgola = decimali.
    # Per un filtro di budget massimo i centesimi non contano, quindi
    # teniamo solo la parte intera.
    cleaned = cleaned.split(",")[0]
    cleaned = cleaned.replace(".", "")

    try:
        return int(cleaned)
    except ValueError:
        return None


# Frammenti che, se presenti in un URL, indicano quasi certamente un link
# di utilità/navigazione e NON un singolo annuncio (footer, social, legali...)
LINK_DENYLIST_FRAGMENTS = [
    "unsubscribe", "disiscriv", "cancella-iscrizione", "preferenze-email",
    "privacy", "cookie", "termini", "condizioni", "assistenza", "help.",
    "supporto", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com", "mailto:", "tel:",
    "google.com/maps", "apps.apple.com", "play.google.com",
    "/login", "/logout", "/registrati", "/account", "/impostazioni",
]


def looks_like_navigation_link(url: str) -> bool:
    url_lower = url.lower()
    return any(fragment in url_lower for fragment in LINK_DENYLIST_FRAGMENTS)


def has_enough_specificity(url: str) -> bool:
    """Un link a un singolo annuncio di solito ha un ID numerico lungo nel
    path, oppure parole chiave tipiche di una pagina di dettaglio."""
    if re.search(r"\d{4,}", url):
        return True
    if any(kw in url.lower() for kw in ("/annuncio/", "/annunci/", "/immobile/", "/immobili/", "/dettaglio/", "/detalle/")):
        return True
    return False


def parse_area_sqm(area_str: str):
    """Converte una stringa superficie ('40 m²', '80mq', '40 m2') in float."""
    if not area_str:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m²|mq|m2)", str(area_str), re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


ROOM_WORDS = {
    "monolocale": 1,
    "bilocale": 2,
    "trilocale": 3,
    "quadrilocale": 4,
    "plurilocale": 5,
}


def parse_rooms(text: str):
    """Stima il numero TOTALE di locali da testo libero. Nota: questo è un
    conteggio complessivo (es. 'trilocale' -> 3), NON una suddivisione
    stanza per stanza — quel dettaglio non è disponibile senza visitare la
    pagina dell'annuncio."""
    if not text:
        return None
    text_lower = str(text).lower()
    for word, n in ROOM_WORDS.items():
        if word in text_lower:
            return n
    match = re.search(r"(\d+)\s*(?:local[ei]|vani|camere)", text_lower)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def find_zone(text: str, known_zones: list):
    """Cerca il nome di un quartiere noto all'interno di un testo libero."""
    if not text:
        return None
    text_lower = str(text).lower()
    for zone in known_zones:
        if zone.lower() in text_lower:
            return zone
    return None


def normalize_listing(listing: dict, known_zones: list) -> dict:
    """Riempie i campi strutturati standard (price_eur, area_sqm, rooms,
    zone) a partire dai campi grezzi disponibili, qualunque sia la fonte
    (Mitula o email). Non sovrascrive valori già validi."""
    if listing.get("price_eur") is None:
        listing["price_eur"] = parse_price_eur(listing.get("price", ""))

    if listing.get("area_sqm") is None:
        raw_area = listing.get("area")
        if isinstance(raw_area, (int, float)):
            listing["area_sqm"] = float(raw_area)
        elif raw_area:
            listing["area_sqm"] = parse_area_sqm(raw_area)

    raw_rooms = listing.get("rooms")
    parsed_rooms = None
    if isinstance(raw_rooms, (int, float)) and raw_rooms:
        parsed_rooms = int(raw_rooms)
    elif isinstance(raw_rooms, str) and raw_rooms.strip():
        try:
            parsed_rooms = int(raw_rooms)
        except ValueError:
            parsed_rooms = parse_rooms(raw_rooms)
    if not parsed_rooms:
        combined_text = f"{listing.get('title', '')} {listing.get('description', '')}"
        parsed_rooms = parse_rooms(combined_text)
    listing["rooms"] = parsed_rooms

    if not listing.get("zone"):
        zone = listing.get("location")  # chiave usata da Mitula
        if not zone:
            combined_text = f"{listing.get('title', '')} {listing.get('description', '')}"
            zone = find_zone(combined_text, known_zones)
        listing["zone"] = zone

    return listing
