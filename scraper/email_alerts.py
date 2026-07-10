"""
Monitoraggio degli alert nativi via email dei portali immobiliari.

PERCHÉ QUESTO APPROCCIO:
Idealista, Immobiliare.it e altri portali usano sistemi anti-bot enterprise
che rendono lo scraping diretto delle loro pagine non percorribile in modo
pulito. La soluzione è usare i LORO alert ufficiali via email (la stessa
funzione "salva ricerca" disponibile a qualunque utente) e limitarsi a
leggere/parsare la propria casella Gmail dedicata: nessun accesso non
autorizzato a sistemi terzi, nessun bypass di sicurezza — solo lettura
della propria posta con le proprie credenziali.

Setup richiesto (vedi README.md):
1. Un account Gmail DEDICATO (non il tuo principale)
2. Verifica in 2 passaggi attiva su quell'account
3. Una "Password per le app" generata da https://myaccount.google.com/apppasswords
4. Alert/ricerche salvate già configurati sui portali con quell'indirizzo

ESTRAZIONE HTML: usiamo BeautifulSoup (parsing vero del DOM) invece di
tagliare l'HTML grezzo a una posizione fissa attorno al link. Il taglio a
posizione fissa può cadere nel mezzo di un tag (es. '<table border="0"
cellpad...') producendo frammenti illeggibili quando si prova a ripulirli
con una regex — bug reale riscontrato in produzione. Con un parser vero
questo non può succedere: il testo "vicino" al link è sempre preso
navigando gli elementi padre nel DOM, mai tagliando stringhe a caso.
Per le rarissime email in solo testo semplice (senza tag), usiamo un
approccio a finestra di caratteri, sicuro in quel caso perché non ci sono
tag da tagliare a metà.
"""
import email
import imaplib
import os
import re
from email.header import decode_header

from bs4 import BeautifulSoup

from config import EMAIL_SOURCES
from scraper.utils import looks_like_navigation_link, has_enough_specificity

DEBUG = os.environ.get("SCRAPER_DEBUG") == "1"
DEBUG_DIR = "debug"

IMAP_SERVER = "imap.gmail.com"

PRICE_PATTERN = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s*€|€\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)")
AREA_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m²|mq|m2)", re.IGNORECASE)

IMAGE_SKIP_KEYWORDS = ("pixel", "tracking", "1x1", "spacer", "logo", "icon")

# Email transazionali/di onboarding note: NON sono alert di nuovi annunci,
# vanno ignorate anche se arrivano da un mittente riconosciuto.
TRANSACTIONAL_SUBJECT_KEYWORDS = [
    "benvenut",
    "la tua ricerca è stata salvata",
    "ricerca salvata",
    "conferma la tua email",
    "conferma il tuo indirizzo",
    "verifica il tuo",
    "attiva il tuo account",
    "hai creato un account",
    "password dimenticata",
    "reimposta la tua password",
    "modifica le tue preferenze",
    "iscrizione newsletter",
]


def _is_transactional_email(subject: str) -> bool:
    subject_lower = subject.lower()
    return any(kw in subject_lower for kw in TRANSACTIONAL_SUBJECT_KEYWORDS)


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                decoded += text.decode(enc or "utf-8", errors="replace")
            except LookupError:
                decoded += text.decode("utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _get_email_body(msg):
    """Ritorna (contenuto, is_html). Preferisce la parte HTML."""
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue

            if content_type == "text/html":
                html_body += decoded
            elif content_type == "text/plain":
                text_body += decoded
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace") if payload else ""
        except Exception:
            decoded = ""
        if msg.get_content_type() == "text/html":
            html_body = decoded
        else:
            text_body = decoded

    if html_body:
        return html_body, True
    return text_body, False


def _identify_source(from_header: str) -> str:
    from_lower = from_header.lower()
    for source_name, cfg in EMAIL_SOURCES.items():
        for domain in cfg["sender_domains"]:
            # Lookbehind negativo: il carattere subito prima del dominio non
            # deve essere una lettera/cifra, altrimenti "casa.it" combacerebbe
            # anche dentro "wikicasa.it" (bug reale riscontrato in produzione).
            pattern = r"(?<![a-z0-9])" + re.escape(domain.lower())
            if re.search(pattern, from_lower):
                return source_name
    return ""


def _unwrap_redirect(url: str) -> str:
    """Molti link di email marketing sono redirect di tracciamento che
    portano la vera destinazione in un parametro di query (es.
    '?u=https%3A%2F%2Fsito.it%2F...'). Se lo troviamo, usiamo direttamente
    quella destinazione."""
    from urllib.parse import urlparse, parse_qs

    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("u", "url", "redirect", "r", "dest", "target"):
            if key in qs and qs[key]:
                candidate = qs[key][0]
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    return candidate
    except Exception:
        pass
    return url


def _get_nearby_text(anchor, max_levels: int = 4, min_len: int = 15, max_len: int = 300) -> str:
    """Risale i genitori del link nel DOM cercando un blocco di testo di
    dimensione ragionevole — verosimilmente la 'card' di un singolo annuncio
    in un layout email a tabelle. Sempre testo pulito: BeautifulSoup separa
    correttamente i tag, niente frammenti a metà."""
    node = anchor
    best = anchor.get_text(separator=" ", strip=True)

    for _ in range(max_levels):
        if node.parent is None:
            break
        node = node.parent
        candidate = node.get_text(separator=" ", strip=True)
        if min_len <= len(candidate) <= max_len:
            return candidate
        if len(candidate) > len(best) and len(candidate) <= max_len * 3:
            best = candidate

    return best[:max_len]


def _get_nearby_image(anchor, max_levels: int = 4) -> str:
    img = anchor.find("img")
    if img:
        src = img.get("src") or img.get("data-src") or ""
        if src and not any(kw in src.lower() for kw in IMAGE_SKIP_KEYWORDS):
            return src

    node = anchor
    for _ in range(max_levels):
        if node.parent is None:
            break
        node = node.parent
        img = node.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src and not any(kw in src.lower() for kw in IMAGE_SKIP_KEYWORDS):
                return src
    return ""


def _canonicalize_url(url: str, tight_pattern) -> str:
    """Per i pattern stretti (Idealista, Immobiliare.it), un annuncio ha
    spesso più link (foto, indirizzo, 'vedi foto', contatta) che puntano
    tutti allo stesso ID ma con parametri di tracciamento diversi (utm_link=
    propertyLowPricePhoto vs propertyLowPriceLink vs propertyLowPriceContact,
    ecc). Senza normalizzare, verrebbero trattati come annunci DIVERSI,
    causando notifiche duplicate per lo stesso immobile. Togliamo la query
    string per ottenere un id/url canonico e pulito."""
    if not tight_pattern:
        return url
    match = tight_pattern.search(url)
    if not match:
        return url
    base = match.group(0).split("?")[0]
    if not base.endswith("/"):
        base += "/"
    return base


def _common_ancestor(tags):
    """Antenato comune più profondo di una lista di tag BeautifulSoup —
    rappresenta la 'card' che contiene tutti i link relativi allo stesso
    annuncio, qualunque sia la sua reale estensione nel layout a tabelle."""
    if not tags:
        return None
    if len(tags) == 1:
        return tags[0]

    chains = []
    for t in tags:
        chain = []
        node = t
        while node is not None:
            chain.append(node)
            node = node.parent
        chains.append(chain)

    common_ids = set(id(n) for n in chains[0])
    for chain in chains[1:]:
        common_ids &= set(id(n) for n in chain)

    for node in chains[0]:
        if id(node) in common_ids:
            return node
    return tags[0]


def _extract_price(text: str) -> str:
    """Estrae il prezzo dal testo. Per gli alert di ribasso prezzo compaiono
    DUE prezzi (vecchio barrato + nuovo), nell'ordine 'da X a Y': prendiamo
    l'ULTIMO valore trovato, che è quello attuale. Escludiamo i valori
    seguiti da /m² o /mq, che sono il prezzo al metro quadro, non il totale."""
    candidates = []
    for m in PRICE_PATTERN.finditer(text):
        value = (m.group(1) or m.group(2) or "").strip()
        if not value:
            continue
        tail = text[m.end(): m.end() + 6].lower()
        if "/m²" in tail or "/mq" in tail or tail.strip().startswith(("m²", "mq")):
            continue
        candidates.append(value)
    return candidates[-1] if candidates else ""


def _pick_title(anchors, container_text: str, subject: str) -> str:
    """Preferisce il testo proprio di uno dei link (es. l'indirizzo), se
    sostanzioso: è quasi sempre più pulito e specifico del testo dell'intera
    card, che può includere frasi di apertura generiche ('Ciao [nome]...')."""
    for a in anchors:
        own_text = a.get_text(strip=True)
        if len(own_text) >= 15:
            return own_text[:100]
    if len(container_text) >= 15:
        return container_text[:80]
    return subject


def _extract_from_html(source: str, subject: str, body: str) -> list:
    cfg = EMAIL_SOURCES[source]
    tight_pattern = cfg.get("listing_url_pattern")

    soup = BeautifulSoup(body, "html.parser")

    # Raggruppiamo TUTTI i link per id/url canonico: più anchor per lo
    # stesso annuncio finiscono nello stesso gruppo, invece di generare
    # candidati duplicati.
    groups = {}  # url_canonico -> lista di anchor tag
    order = []   # per mantenere l'ordine di comparsa

    for anchor in soup.find_all("a", href=True):
        raw_url = _unwrap_redirect(anchor["href"])

        if tight_pattern:
            if not tight_pattern.search(raw_url):
                continue
            canonical = _canonicalize_url(raw_url, tight_pattern)
        else:
            if looks_like_navigation_link(raw_url) or not has_enough_specificity(raw_url):
                continue
            canonical = raw_url.rstrip(".,;\"'")

        if canonical not in groups:
            groups[canonical] = []
            order.append(canonical)
        groups[canonical].append(anchor)

    listings = []

    for canonical_url in order:
        anchors = groups[canonical_url]

        if len(anchors) >= 2:
            # Più link per lo stesso annuncio: l'antenato comune copre
            # l'intera card (foto + prezzo + descrizione + bottoni),
            # qualunque sia la sua estensione reale nel layout.
            container = _common_ancestor(anchors)
            nearby_text = container.get_text(separator=" ", strip=True)[:500] if container else ""
        else:
            nearby_text = _get_nearby_text(anchors[0])

        image_url = ""
        for a in anchors:
            image_url = _get_nearby_image(a)
            if image_url:
                break

        # Cerchiamo prezzo/mq sia nel testo della card SIA nel soggetto:
        # per email "un annuncio per email" (es. Casa.it), il testo vicino al
        # link è spesso troppo corto e mq/prezzo stanno nel soggetto stesso
        # (es. "Un nuovo annuncio: 30 mq | Via Tullio Lombardo, Padova").
        search_text = f"{nearby_text} {subject}"

        price = _extract_price(search_text)

        area_match = AREA_PATTERN.search(search_text)
        area = area_match.group(0) if area_match else ""

        title = _pick_title(anchors, nearby_text, subject)

        listings.append(
            {
                "id": canonical_url,
                "source": f"{source} (email)",
                "title": title,
                "description": search_text.strip()[:300],
                "price": price,
                "area": area,
                "image_url": image_url,
                "url": canonical_url,
                "raw": {},
            }
        )

    return listings


def _extract_from_plain_text(source: str, subject: str, body: str) -> list:
    """Fallback per le rarissime email in solo testo (nessun tag HTML da
    parsare, quindi il taglio a finestra di caratteri è sicuro qui)."""
    cfg = EMAIL_SOURCES[source]
    tight_pattern = cfg.get("listing_url_pattern")

    url_pattern = tight_pattern or re.compile(r"https?://[^\s\"'<>]+")
    candidate_urls = [m.group(0).rstrip(".,;\"'") for m in url_pattern.finditer(body)]

    listings = []
    seen_urls = set()

    for url in candidate_urls:
        url = _unwrap_redirect(url)
        if not tight_pattern:
            if looks_like_navigation_link(url) or not has_enough_specificity(url):
                continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        position = body.find(url)
        window = 250
        snippet = body[max(0, position - window): position + window] if position >= 0 else ""

        price = _extract_price(snippet)
        area_match = AREA_PATTERN.search(snippet)
        area = area_match.group(0) if area_match else ""
        clean_snippet = re.sub(r"\s+", " ", snippet).strip()

        title = clean_snippet[:80] if len(clean_snippet) >= 15 else subject

        listings.append(
            {
                "id": url,
                "source": f"{source} (email)",
                "title": title,
                "description": clean_snippet[:300],
                "price": price,
                "area": area,
                "image_url": "",
                "url": url,
                "raw": {},
            }
        )

    return listings


def _extract_listings_from_email(source: str, subject: str, body: str, is_html: bool) -> list:
    if is_html:
        return _extract_from_html(source, subject, body)
    return _extract_from_plain_text(source, subject, body)


def fetch_new_listings(imap_email: str, imap_app_password: str) -> list:
    all_listings = []

    conn = imaplib.IMAP4_SSL(IMAP_SERVER)
    try:
        conn.login(imap_email, imap_app_password)
    except imaplib.IMAP4.error as e:
        print(f"[Email] ERRORE di login IMAP: {e}")
        print("[Email] Verifica IMAP_EMAIL e IMAP_APP_PASSWORD nei GitHub Secrets.")
        return []

    conn.select("INBOX")

    status, data = conn.search(None, "UNSEEN")
    if status != "OK":
        print("[Email] Ricerca email non riuscita")
        conn.logout()
        return []

    email_ids = data[0].split()
    print(f"[Email] {len(email_ids)} email non lette da processare")

    if DEBUG:
        os.makedirs(DEBUG_DIR, exist_ok=True)

    for i, eid in enumerate(email_ids):
        try:
            status, msg_data = conn.fetch(eid, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_mime_header(msg.get("Subject", ""))
            from_header = _decode_mime_header(msg.get("From", ""))
            source = _identify_source(from_header)

            if not source:
                print(f"[Email] Mittente non riconosciuto, salto: {from_header[:60]}")
                continue

            if _is_transactional_email(subject):
                print(f"[Email] Email transazionale (non è un alert), ignoro: '{subject[:60]}' ({source})")
                conn.store(eid, "+FLAGS", "\\Seen")
                continue

            body, is_html = _get_email_body(msg)

            if DEBUG:
                safe_source = re.sub(r"[^a-zA-Z0-9]+", "_", source)
                ext = "html" if is_html else "txt"
                debug_path = os.path.join(DEBUG_DIR, f"email_{i}_{safe_source}.{ext}")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(f"<!-- SUBJECT: {subject} -->\n<!-- FROM: {from_header} -->\n\n{body}")
                print(f"[Email][DEBUG] Salvato {debug_path} ({len(body)} caratteri, html={is_html})")

            listings = _extract_listings_from_email(source, subject, body, is_html)
            print(f"[Email] '{subject[:60]}' ({source}): {len(listings)} link candidati estratti")
            all_listings.extend(listings)

            # Segniamo come letta SOLO dopo il parsing riuscito, così un
            # errore a metà non fa perdere l'email per sempre.
            conn.store(eid, "+FLAGS", "\\Seen")

        except Exception as e:
            print(f"[Email] Errore processando un messaggio: {e}")

    conn.logout()
    return all_listings
