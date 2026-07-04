"""
Scraper per Mitula (immobiliare.mitula.it), aggregatore che include anche
annunci provenienti da Immobiliare.it e Subito.it. A differenza di Subito.it,
Mitula renderizza i contenuti lato server: bastano requests + BeautifulSoup.
"""
import hashlib
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT, REQUEST_DELAY_SECONDS

DEBUG = os.environ.get("SCRAPER_DEBUG") == "1"
DEBUG_DIR = "debug"


def _make_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _extract_via_microdata(soup: BeautifulSoup, base_name: str) -> list:
    """Tentativo #1: molti aggregatori usano microdati schema.org per la SEO
    (rich snippets) — è la fonte più stabile se presente."""
    listings = []
    items = soup.select("[itemtype*='schema.org']")

    for item in items:
        title_el = item.select_one("[itemprop='name']")
        price_el = item.select_one("[itemprop='price']")
        link_el = item if item.name == "a" else item.find("a", href=True)

        if not title_el or not link_el:
            continue

        href = link_el.get("href", "")
        if not href:
            continue

        listings.append(
            {
                "id": _make_id(href),
                "source": base_name,
                "title": title_el.get_text(strip=True),
                "price": price_el.get_text(strip=True) if price_el else "",
                "url": href if href.startswith("http") else f"https://immobiliare.mitula.it{href}",
                "raw": {},
            }
        )

    return listings


def _extract_via_generic_cards(soup: BeautifulSoup, base_name: str) -> list:
    """Tentativo #2 (fallback): card generiche con link a dettaglio annuncio."""
    listings = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/detalle/" not in href and "/dettaglio/" not in href and "/annuncio/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        listings.append(
            {
                "id": _make_id(href),
                "source": base_name,
                "title": title,
                "price": "",
                "url": href if href.startswith("http") else f"https://immobiliare.mitula.it{href}",
                "raw": {},
            }
        )

    return listings


def scrape_mitula_search(name: str, url: str) -> list:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

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

    listings = _extract_via_microdata(soup, name)
    if DEBUG:
        print(f"[Mitula][DEBUG] Estrazione via microdati: {len(listings)} risultati")

    if not listings:
        listings = _extract_via_generic_cards(soup, name)
        if DEBUG:
            print(f"[Mitula][DEBUG] Estrazione via card generiche: {len(listings)} risultati")

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
