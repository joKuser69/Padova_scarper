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
   (fatto ✅ per Idealista, Immobiliare.it, Casa.it, Bakeca, Wikicasa)

NOTA SULL'ESTRAZIONE: senza un'email reale di esempio per ogni portale, non
possiamo scrivere regex perfette al primo colpo (i link nelle email di
marketing spesso passano da redirect di tracciamento imprevedibili). Per
questo l'estrazione è volontariamente permissiva: prendiamo tutti i link
"specifici" (con un ID numerico o parole chiave da pagina di dettaglio) e
scartiamo quelli chiaramente di navigazione (disiscriviti, social, privacy).
Il filtro IA a valle fa da ulteriore rete di sicurezza contro falsi positivi.
"""
import email
import imaplib
import os
import re
from email.header import decode_header

from config import EMAIL_SOURCES
from scraper.utils import looks_like_navigation_link, has_enough_specificity

DEBUG = os.environ.get("SCRAPER_DEBUG") == "1"
DEBUG_DIR = "debug"

IMAP_SERVER = "imap.gmail.com"

PRICE_PATTERN = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s*€|€\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)")
HREF_PATTERN = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


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


def _get_email_body(msg) -> str:
    """Preferisce la parte HTML (contiene i link cliccabili), fallback su testo semplice."""
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

    return html_body or text_body


def _identify_source(from_header: str) -> str:
    from_lower = from_header.lower()
    for source_name, cfg in EMAIL_SOURCES.items():
        if any(domain in from_lower for domain in cfg["sender_domains"]):
            return source_name
    return ""


def _extract_price_near(body: str, position: int, window: int = 250) -> str:
    snippet = body[max(0, position - window): position + window]
    match = PRICE_PATTERN.search(snippet)
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def _extract_listings_from_email(source: str, subject: str, body: str) -> list:
    cfg = EMAIL_SOURCES[source]
    tight_pattern = cfg.get("listing_url_pattern")

    candidate_urls = []

    # Tentativo #1: pattern specifico del sito, se lo abbiamo configurato
    if tight_pattern:
        candidate_urls = [m.group(0).rstrip(".,;\"'") for m in tight_pattern.finditer(body)]

    # Tentativo #2 (o integrazione): tutti i link href, filtrati con la denylist
    if not candidate_urls:
        all_hrefs = HREF_PATTERN.findall(body)
        for href in all_hrefs:
            if looks_like_navigation_link(href):
                continue
            if not has_enough_specificity(href):
                continue
            candidate_urls.append(href)

    listings = []
    seen_urls = set()

    for url in candidate_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)

        position = body.find(url)
        price = _extract_price_near(body, position) if position >= 0 else ""

        listings.append(
            {
                "id": url,
                "source": f"{source} (email)",
                "title": subject,
                "price": price,
                "url": url,
                "raw": {},
            }
        )

    return listings


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
                # Non è un'email di uno dei portali configurati: la
                # lasciamo NON letta e non la tocchiamo, potrebbe essere
                # posta normale o un mittente non ancora mappato in
                # config.EMAIL_SOURCES.
                print(f"[Email] Mittente non riconosciuto, salto: {from_header[:60]}")
                continue

            body = _get_email_body(msg)

            if DEBUG:
                safe_source = re.sub(r"[^a-zA-Z0-9]+", "_", source)
                debug_path = os.path.join(DEBUG_DIR, f"email_{i}_{safe_source}.html")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(f"<!-- SUBJECT: {subject} -->\n<!-- FROM: {from_header} -->\n\n{body}")
                print(f"[Email][DEBUG] Salvato {debug_path} ({len(body)} caratteri)")

            listings = _extract_listings_from_email(source, subject, body)
            print(f"[Email] '{subject[:60]}' ({source}): {len(listings)} link candidati estratti")
            all_listings.extend(listings)

            # Segniamo come letta SOLO dopo il parsing riuscito, così un
            # errore a metà non fa perdere l'email per sempre: verrà
            # ritentata al prossimo run.
            conn.store(eid, "+FLAGS", "\\Seen")

        except Exception as e:
            print(f"[Email] Errore processando un messaggio: {e}")

    conn.logout()
    return all_listings
