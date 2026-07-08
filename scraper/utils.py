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
