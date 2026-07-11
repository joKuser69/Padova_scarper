"""
Funzioni di utilità condivise tra i vari moduli scraper.
"""
import re


def parse_price_eur(price_str: str):
    """Converte una stringa prezzo in un intero euro.

    Gestisce sia il formato italiano ('250.000,50' punto=migliaia,
    virgola=decimali) sia quello inglese, usato da Mitula ('30,000 EUR'
    virgola=migliaia). Bug reale scoperto dai test automatici: assumere
    solo il formato italiano troncava '30,000 EUR' a 30, invece di 30000 —
    interessava praticamente ogni prezzo di vendita Mitula.

    Euristica: se compaiono sia punto che virgola, l'ultimo dei due è il
    separatore decimale. Se compare solo uno dei due, guardiamo quante
    cifre lo seguono: 3 cifre = separatore delle migliaia, altrimenti
    decimali (i prezzi immobiliari non hanno mai più di 2 cifre decimali).
    """
    if not price_str:
        return None

    cleaned = re.sub(r"[^\d.,]", "", str(price_str))
    if not cleaned:
        return None

    has_dot = "." in cleaned
    has_comma = "," in cleaned

    if has_dot and has_comma:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").split(",")[0]
        else:
            cleaned = cleaned.replace(",", "").split(".")[0]
    elif has_comma:
        after = cleaned.split(",")[-1]
        cleaned = cleaned.replace(",", "") if len(after) == 3 else cleaned.split(",")[0]
    elif has_dot:
        after = cleaned.split(".")[-1]
        cleaned = cleaned.replace(".", "") if len(after) == 3 else cleaned.split(".")[0]

    try:
        return int(cleaned)
    except ValueError:
        return None


# Frammenti che, se presenti in un URL, indicano quasi certamente un link
# di utilità/navigazione e NON un singolo annuncio (footer, social, legali,
# gestione account/alert...)
LINK_DENYLIST_FRAGMENTS = [
    "unsubscribe", "disiscriv", "cancella-iscrizione", "preferenze-email",
    "privacy", "cookie", "termini", "condizioni", "assistenza", "help.",
    "supporto", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com", "mailto:", "tel:",
    "google.com/maps", "apps.apple.com", "play.google.com",
    "/login", "/logout", "/registrati", "/account", "/impostazioni",
    # Link di gestione alert/account visti in email reali (es. Casa.it):
    # portano a pagine "le mie ricerche", non a un singolo annuncio.
    "autologin", "session/callback", "editalert", "edit-alert",
    "/my/", "/mio/", "/preferiti", "/ricerche-salvate",
    # Reti pubblicitarie/tracking note che comparivano in email reali,
    # NON sono mai link ad annunci (es. banner pubblicitari nelle email)
    "doubleclick.net", "googlesyndication.com", "google-analytics.com",
    "googletagmanager.com", "pubads.g.doubleclick",
]


def looks_like_navigation_link(url: str) -> bool:
    url_lower = url.lower()
    return any(fragment in url_lower for fragment in LINK_DENYLIST_FRAGMENTS)


def has_enough_specificity(url: str) -> bool:
    """Un link a un singolo annuncio di solito ha un ID numerico lungo nel
    PERCORSO dell'URL. Controlliamo solo il percorso (prima del '?') e non
    la query string, perché lì spesso vivono token di sessione/tracciamento
    lunghi (es. 't=...', 'aid=...') che sembrano ID ma non lo sono."""
    path = url.split("?", 1)[0]
    if re.search(r"\d{4,}", path):
        return True
    if any(kw in path.lower() for kw in ("/annuncio/", "/annunci/", "/immobile/", "/immobili/", "/dettaglio/", "/detalle/")):
        return True
    return False


def parse_area_sqm(area_str: str):
    """Converte una stringa superficie ('40 m²', '80mq', '40 m2', '40 m 2')
    in float. L'ultima variante (spazio tra m e 2) capita quando un apice
    HTML (²) viene 'appiattito' in testo semplice."""
    if not area_str:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m\s?²|mq|m\s?2)\b", str(area_str), re.IGNORECASE)
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


# Sotto queste soglie un prezzo è quasi certamente un errore di dati alla
# fonte (es. campo prezzo mancante letto come valore residuo), non un vero
# affare da 30€ per un appartamento di 60 m². Meglio trattarlo come
# "sconosciuto" piuttosto che mostrarlo come un fatto — e soprattutto,
# escluderlo dal calcolo della media di zona, dove un singolo valore assurdo
# può falsare il confronto per TUTTI gli annunci futuri di quella zona.
#
# Soglie differenziate per tipo: un affitto legittimo ha un prezzo/mq molto
# più basso di una vendita (es. 8€/mq/mese è normale in affitto, sarebbe
# assurdo in vendita). Usare la soglia "vendita" su un affitto scarterebbe
# erroneamente prezzi veri.
MIN_PLAUSIBLE_PRICE_PER_SQM = 200  # €/m² (vendita/asta)
MIN_PLAUSIBLE_PRICE_EUR = 10_000    # € (vendita/asta, senza mq noti)
MIN_PLAUSIBLE_PRICE_PER_SQM_AFFITTO = 3  # €/m²/mese
MIN_PLAUSIBLE_PRICE_EUR_AFFITTO = 150     # € (affitto, senza mq noti)

AUCTION_PATTERN = re.compile(r"\basta\b|base\s+d.asta|vendita\s+giudiziaria", re.IGNORECASE)
RENTAL_PATTERN = re.compile(r"\baffitto\b|\blocazione\b|canone\s+(?:mensile|di\s+locazione)", re.IGNORECASE)


def detect_listing_type(text: str, url: str = "") -> str:
    """Ritorna 'asta', 'affitto' o 'vendita' (default) in base a parole
    chiave nel testo/URL dell'annuncio. Un'asta giudiziaria mostra una BASE
    D'ASTA, non un prezzo di vendita fisso — vale la pena saperlo prima di
    considerarla un affare."""
    combined = f"{text} {url}"
    if AUCTION_PATTERN.search(combined):
        return "asta"
    if RENTAL_PATTERN.search(combined):
        return "affitto"
    return "vendita"


def price_is_plausible(price_eur, area_sqm, listing_type: str = "vendita") -> bool:
    if price_eur is None:
        return True
    if listing_type == "affitto":
        min_per_sqm, min_total = MIN_PLAUSIBLE_PRICE_PER_SQM_AFFITTO, MIN_PLAUSIBLE_PRICE_EUR_AFFITTO
    else:
        min_per_sqm, min_total = MIN_PLAUSIBLE_PRICE_PER_SQM, MIN_PLAUSIBLE_PRICE_EUR
    if area_sqm and area_sqm > 0:
        return (price_eur / area_sqm) >= min_per_sqm
    return price_eur >= min_total


def exclude_rentals(listings: list) -> list:
    """Scarta gli annunci classificati come 'affitto'. Richiede che
    normalize_listing sia già stato chiamato (altrimenti 'listing_type'
    non è ancora impostato e nulla verrebbe scartato)."""
    return [l for l in listings if l.get("listing_type") != "affitto"]


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

    listing["listing_type"] = detect_listing_type(
        f"{listing.get('title', '')} {listing.get('description', '')}",
        listing.get("url", ""),
    )

    if not price_is_plausible(listing.get("price_eur"), listing.get("area_sqm"), listing["listing_type"]):
        listing["price_suspect"] = True
        listing["price_eur"] = None

    return listing
