"""
Scraper per Mitula (immobiliare.mitula.it), aggregatore che include anche
annunci provenienti da Immobiliare.it e Subito.it.

Selettori verificati direttamente sull'HTML reale del sito (luglio 2026):
ogni annuncio è un tag <article class="listing listing-card ..."> con i dati
principali già disponibili come attributi data-* (niente bisogno di parsing
fragile del testo visibile).
"""
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT, REQUEST_DELAY_SECONDS

DEBUG = os.environ.get("SCRAPER_DEBUG") == "1"
DEBUG_DIR = "debug"


def _extract_listings(soup: BeautifulSoup, base_name: str) -> list:
    listings = []

    for article in soup.select("article.listing-card"):
        listing_id = article.get("data-listingid")
        if not listing_id:
            continue

        price = article.get("data-price", "")
        currency = article.get("data-currency", "")
        location = article.get("data-location", "")
        area = article.get("data-floorarea", "")
        rooms = article.get("data-rooms", "")

        ptype_el = article.select_one(".tag--listing--property-type")
        property_type = ptype_el.get_text(strip=True) if ptype_el else "Immobile"

        desc_el = article.select_one(".listing-card__description__text")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Titolo leggibile costruito dai dati strutturati (il sito non ha un
        # vero e proprio campo "titolo" separato dalla location)
        title_parts = [property_type, "-", location]
        if area:
            title_parts.append(f"({area})")
        title = " ".join(p for p in title_parts if p)

        price_str = f"{price} {currency}".strip() if price else ""

        listings.append(
            {
                "id": listing_id,
                "source": base_name,
                "title": title,
                "price": price_str,
                "location": location,
                "rooms": rooms,
                "area": area,
                "description": description,
                "url": f"https://immobiliare.mitula.it/adclickdetail/{listing_id}",
                "raw": {},
            }
        )

    return listings


def scrape_mitula_search(name: str, url: str) -> list:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    # Il server spesso non dichiara il charset nell'header Content-Type,
    # e requests di default assume ISO-8859-1 in quel caso, producendo
    # caratteri accentati corrotti anche se la pagina è in realtà UTF-8.
    resp.encoding = "utf-8"

    if DEBUG:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
        debug_path = os.path.join(DEBUG_DIR, f"mitula_{safe_name}.html")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(
            f"[Mitula][DEBUG] status={resp.status_code} HTML salvato in "
            f"{debug_path} ({len(resp.text)} caratteri)"
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = _extract_listings(soup, name)

    if DEBUG:
        print(f"[Mitula][DEBUG] Annunci estratti: {len(listings)}")

    return listings


def scrape_all(searches: list) -> list:
    all_listings = []
    for search in searches:
        try:
            results = scrape_mitula_search(search["name"], search["url"])
            print(f"[Mitula] '{search['name']}': {len(results)} annunci trovati")
            all_listings.extend(results)
        except Exception as e:
            print(f"[Mitula] ERRORE su '{search['name']}': {e}")
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_listings
