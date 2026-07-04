"""
Scraper per Subito.it.

Subito.it è un'app React/Next.js: i risultati NON sono nell'HTML grezzo ma
vengono popolati via JavaScript. Per questo usiamo Playwright, che renderizza
la pagina come farebbe un browser vero.

IMPORTANTE: non chiamiamo mai direttamente l'endpoint interno /hades/ (che il
robots.txt del sito segnala come non consentito ai bot). Ci limitiamo a
caricare la pagina pubblica e leggere il DOM già renderizzato, esattamente
come farebbe una persona che visita il sito con un browser normale.
"""
import hashlib
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

from config import USER_AGENT

DEBUG = os.environ.get("SCRAPER_DEBUG") == "1"
DEBUG_DIR = "debug"


def _make_id(url: str) -> str:
    """ID stabile basato sull'URL dell'annuncio (funziona anche se il sito
    non espone un id numerico facile da estrarre)."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _extract_from_next_data(html: str, base_name: str) -> list:
    """Tentativo #1: molte app Next.js incorporano i dati della pagina in
    <script id="__NEXT_DATA__">. Se lo troviamo, è la fonte più affidabile."""
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    listings = []

    def walk(node):
        """Cerca ricorsivamente liste di dizionari che sembrano annunci
        (hanno almeno un titolo/subject e un urn/link)."""
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and _looks_like_ad(item):
                    listings.append(_normalize_ad(item, base_name))
                else:
                    walk(item)

    walk(data)
    return listings


def _looks_like_ad(item: dict) -> bool:
    keys = {k.lower() for k in item.keys()}
    has_title = any(k in keys for k in ("subject", "title", "name"))
    has_link = any(k in keys for k in ("urn", "url", "item_url", "link"))
    return has_title and has_link


def _normalize_ad(item: dict, base_name: str) -> dict:
    title = item.get("subject") or item.get("title") or item.get("name") or ""
    url = item.get("urn") or item.get("url") or item.get("item_url") or item.get("link") or ""
    price = item.get("price") or item.get("prezzo") or ""
    if isinstance(price, dict):
        price = price.get("value", "")
    return {
        "id": _make_id(url) if url else _make_id(title),
        "source": base_name,
        "title": str(title).strip(),
        "price": str(price).strip(),
        "url": url,
        "raw": item,
    }


def _extract_from_dom(page, base_name: str) -> list:
    """Tentativo #2 (fallback): estrazione via selettori DOM generici.
    Cerca link ad annunci individuali (pattern tipico subito.it: pagina che
    finisce in un ID numerico + .htm)."""
    anchors = page.query_selector_all("a[href*='.htm']")
    listings = []
    seen_urls = set()

    for a in anchors:
        href = a.get_attribute("href") or ""
        if not re.search(r"-\d{6,}\.htm", href):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        title = (a.inner_text() or "").strip()
        if not title:
            continue

        listings.append(
            {
                "id": _make_id(href),
                "source": base_name,
                "title": title,
                "price": "",
                "url": href if href.startswith("http") else f"https://www.subito.it{href}",
                "raw": {},
            }
        )

    return listings


def scrape_subito_search(name: str, url: str) -> list:
    """Renderizza una pagina di ricerca Subito.it e ritorna la lista di annunci."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        # "domcontentloaded" invece di "networkidle": subito.it fa polling/
        # richieste continue in background che con networkidle non
        # terminerebbero mai entro il timeout, lasciandoci con la pagina
        # ancora vuota.
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Aspettiamo esplicitamente che compaia un link ad un annuncio reale,
        # invece di una sleep fissa alla cieca. Se non compare entro 15s,
        # proseguiamo comunque e diagnostichiamo cosa è successo.
        try:
            page.wait_for_selector("a[href*='.htm']", timeout=15000)
        except Exception:
            pass

        # Piccolo scroll: molti siti caricano gli annunci solo quando la
        # card entra nel viewport (lazy loading).
        page.mouse.wheel(0, 3000)
        time.sleep(2)

        html = page.content()

        if DEBUG:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", name)
            debug_path = os.path.join(DEBUG_DIR, f"subito_{safe_name}.html")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[Subito][DEBUG] HTML salvato in {debug_path} ({len(html)} caratteri)")

        listings = _extract_from_next_data(html, name)
        if DEBUG:
            print(f"[Subito][DEBUG] Estrazione via __NEXT_DATA__: {len(listings)} risultati")

        if not listings:
            listings = _extract_from_dom(page, name)
            if DEBUG:
                anchors_total = len(page.query_selector_all("a"))
                anchors_htm = len(page.query_selector_all("a[href*='.htm']"))
                print(
                    f"[Subito][DEBUG] Estrazione via DOM: {len(listings)} risultati "
                    f"(link totali: {anchors_total}, link con '.htm': {anchors_htm})"
                )

        browser.close()

    return listings


def scrape_all(searches: list) -> list:
    all_listings = []
    for search in searches:
        try:
            results = scrape_subito_search(search["name"], search["url"])
            print(f"[Subito] '{search['name']}': {len(results)} annunci trovati")
            all_listings.extend(results)
        except Exception as e:
            print(f"[Subito] ERRORE su '{search['name']}': {e}")
    return all_listings
