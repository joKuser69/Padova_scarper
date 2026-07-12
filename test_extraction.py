"""
Test automatici per il bot di monitoraggio annunci Padova.

Le fixture in tests/fixtures/ sono estratti REALI (email di alert, pagine
Mitula) raccolti durante lo sviluppo — non dati inventati. Ogni test qui
dentro corrisponde a un bug vero che abbiamo trovato e corretto:

- Idealista: 4 link diversi per lo stesso annuncio (foto/vedi foto/indirizzo/
  contatta) venivano trattati come 4 annunci distinti -> dedup per id
- Idealista: negli alert di ribasso prezzo, la regex prendeva il prezzo
  VECCHIO (barrato) invece del nuovo -> preferire l'ultimo prezzo trovato
- Idealista: il testo vicino al link tagliato a metà tag produceva
  frammenti HTML illeggibili nel titolo -> parsing vero con BeautifulSoup
- Casa.it: mq scritti solo nel soggetto dell'email, non vicino al link
  -> cercare anche nel soggetto
- Casa.it: prezzo codificato come &euro; (entity HTML) invece del carattere
  diretto -> verificare che venga comunque decodificato
- Wikicasa scambiato per Casa.it per via del controllo di dominio che non
  rispettava i confini di parola ("casa.it" combacia dentro "wikicasa.it")
- Link pubblicitari (doubleclick) e di gestione account (autologin) scambiati
  per annunci
- Telegram: link di tracciamento lunghi facevano superare il limite di 1024
  caratteri della didascalia foto, troncando l'URL a metà -> se il messaggio
  è troppo lungo, salta la foto e manda testo (limite 4096)

NOTA: Mitula è stato rimosso come fonte (era quella con più problemi di
affidabilità — link protetti da anti-bot indiretto, bug di parsing prezzi —
mentre gli alert email arrivano direttamente dai portali ufficiali). La
funzione parse_price_eur gestisce comunque anche il formato con virgola come
separatore delle migliaia, utile in generale e non solo per Mitula.

ESECUZIONE (da GitHub Actions, automatico ad ogni push — vedi
.github/workflows/tests.yml — oppure a mano se mai avrai un ambiente Python):
    python -m unittest discover tests -v
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from scraper.email_alerts import (
    _extract_from_html,
    _identify_source,
    _unwrap_redirect,
    _extract_price,
)
from scraper.telegram_notify import _format_it_number, notify_new_listings
from scraper.utils import (
    parse_price_eur,
    parse_area_sqm,
    parse_rooms,
    find_zone,
    price_is_plausible,
    looks_like_navigation_link,
    has_enough_specificity,
    detect_listing_type,
    exclude_rentals,
)
from config import PADOVA_ZONES


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(filename: str) -> str:
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestIdealistaPriceDropEmail(unittest.TestCase):
    """Email reale con 4 link diversi per lo stesso annuncio e due prezzi
    (vecchio barrato + nuovo)."""

    @classmethod
    def setUpClass(cls):
        html = load_fixture("idealista_pricedrop_duplicate_links.html")
        cls.listings = _extract_from_html(
            "Idealista", "Diminuzione di prezzo per la tua ricerca", html
        )

    def test_no_duplicates(self):
        """4 link per lo stesso id devono diventare 1 solo annuncio."""
        self.assertEqual(len(self.listings), 1)

    def test_price_is_the_new_one_not_the_old(self):
        """Deve prendere 225.000 (nuovo), non 230.000 (vecchio, barrato)."""
        self.assertEqual(self.listings[0]["price"], "225.000")

    def test_title_is_clean_address_not_html_fragment(self):
        title = self.listings[0]["title"]
        self.assertIn("Bilocale", title)
        self.assertNotIn("border=", title)
        self.assertNotIn("cellpadding", title)

    def test_area_extracted(self):
        self.assertIn("65", self.listings[0]["area"])

    def test_image_extracted(self):
        self.assertTrue(self.listings[0]["image_url"].startswith("https://"))

    def test_url_is_canonical_without_tracking_params(self):
        url = self.listings[0]["url"]
        self.assertTrue(url.startswith("https://www.idealista.it/immobile/"))
        self.assertNotIn("utm_", url)


class TestIdealistaSingleListingEmail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = load_fixture("idealista_single_listing.html")
        cls.listings = _extract_from_html("Idealista", "Nuovi annunci per la tua ricerca", html)

    def test_one_listing_found(self):
        self.assertEqual(len(self.listings), 1)

    def test_has_price_and_area(self):
        self.assertTrue(self.listings[0]["price"])
        self.assertTrue(self.listings[0]["area"])


class TestCasaItAstaEmail(unittest.TestCase):
    """Email 'un annuncio per email': testo vicino al link insufficiente,
    mq nel soggetto, prezzo codificato come &euro;."""

    @classmethod
    def setUpClass(cls):
        html = load_fixture("casa_it_asta_listing.html")
        cls.subject = "Un nuovo annuncio: 30 mq | Via Tullio Lombardo, Padova"
        cls.listings = _extract_from_html("Casa.it", cls.subject, html)

    def test_one_listing_found(self):
        self.assertEqual(len(self.listings), 1)

    def test_area_recovered_from_subject(self):
        """Il corpo email da solo non basta: l'mq deve arrivare dal soggetto."""
        self.assertIn("30", self.listings[0]["area"])

    def test_price_decoded_from_html_entity(self):
        """Il prezzo nella pagina usa &euro; invece del carattere diretto:
        deve comunque essere trovato (BeautifulSoup decodifica le entity)."""
        self.assertEqual(self.listings[0]["price"], "48.000")





class TestSourceIdentification(unittest.TestCase):
    """Bug reale: 'casa.it' combaciava anche dentro 'wikicasa.it'."""

    def test_wikicasa_not_confused_with_casa_it(self):
        result = _identify_source("Wikicasa <notifiche@email.notifiche.wikicasa.it>")
        self.assertEqual(result, "Wikicasa")

    def test_real_casa_it_still_recognized(self):
        result = _identify_source("Casa.it <noreply@casa.it>")
        self.assertEqual(result, "Casa.it")

    def test_casa_it_subdomain_still_recognized(self):
        result = _identify_source("Casa.it <alerts@mail.casa.it>")
        self.assertEqual(result, "Casa.it")

    def test_tecnocasa_not_confused_with_casa_it(self):
        """Stessa collisione di 'wikicasa.it': 'casa.it' è una sottostringa
        anche di 'tecnocasa.it'. Verifica che il fix generale (confini di
        parola) protegga automaticamente anche questo caso."""
        result = _identify_source("TecnoCasa <noreply@tecnocasa.it>")
        self.assertEqual(result, "TecnoCasa")


class TestLinkFiltering(unittest.TestCase):
    """Link visti in produzione che NON devono mai passare per annunci."""

    def test_casa_it_autologin_link_rejected(self):
        url = (
            "https://www.casa.it/my/session/callback?action=autologin&t=abc123def456"
            "&r=https%3A%2F%2Fwww.casa.it%2Fmy%2Fricerche%2Fpreferiti&utm_content=editAlert"
        )
        self.assertTrue(looks_like_navigation_link(url))

    def test_doubleclick_ad_tracker_rejected(self):
        url = "http://pubads.g.doubleclick.net/gampad/jump?iu=/72543886/csa.vendita&c=1783507427468"
        self.assertTrue(looks_like_navigation_link(url))
        self.assertFalse(has_enough_specificity(url))

    def test_real_idealista_listing_link_accepted(self):
        url = "https://www.idealista.it/immobile/34567891/"
        self.assertFalse(looks_like_navigation_link(url))
        self.assertTrue(has_enough_specificity(url))

    def test_bakeca_redirect_unwrapped_to_clean_url(self):
        wrapped = (
            "https://t.mailnews.bakeca.it/fw19c3/43166401/77890/1704074891.html"
            "?h=abc&s=def&u=https%3A%2F%2Fpadova.bakeca.it%2Fdettaglio%2Fvendita-case"
            "%2Fvilla-di-312-m178-4zkg297610558%3Futm_source%3DAlert"
        )
        clean = _unwrap_redirect(wrapped)
        self.assertTrue(clean.startswith("https://padova.bakeca.it/dettaglio/"))


class TestPriceExtraction(unittest.TestCase):
    def test_prefers_last_price_excluding_per_sqm(self):
        """Simula un testo con vecchio prezzo, nuovo prezzo, e prezzo/m²:
        deve prendere il nuovo, ignorando quello al metro quadro."""
        text = "sceso da 230.000 € a 225.000 € 3.462 €/m²"
        self.assertEqual(_extract_price(text), "225.000")

    def test_single_price(self):
        text = "In vendita a 180.000 €"
        self.assertEqual(_extract_price(text), "180.000")

    def test_no_price_found(self):
        self.assertEqual(_extract_price("nessun prezzo qui"), "")


class TestUtilityParsing(unittest.TestCase):
    def test_parse_price_italian_format(self):
        self.assertEqual(parse_price_eur("250.000 €"), 250000)
        self.assertEqual(parse_price_eur("600 EUR"), 600)
        self.assertEqual(parse_price_eur("1.200,50€"), 1200)
        self.assertIsNone(parse_price_eur(""))
        self.assertIsNone(parse_price_eur("gratis"))

    def test_parse_price_mitula_comma_thousands_format(self):
        """Bug reale grave: Mitula usa la virgola come separatore delle
        migliaia ('30,000 EUR' = 30.000€), non come decimali. Il parsing
        'solo italiano' troncava a 30 — interessava PRATICAMENTE OGNI
        prezzo di vendita Mitula, mascherato dal filtro di plausibilità
        che li scartava silenziosamente come 'errori di dati'."""
        self.assertEqual(parse_price_eur("30,000 EUR"), 30000)
        self.assertEqual(parse_price_eur("1,200,000"), 1200000)  # caso reale: un immobile da 1,2 milioni
        self.assertEqual(parse_price_eur("48,000"), 48000)

    def test_parse_area(self):
        self.assertEqual(parse_area_sqm("40 m²"), 40.0)
        self.assertEqual(parse_area_sqm("80mq"), 80.0)
        self.assertIsNone(parse_area_sqm(""))

    def test_parse_rooms_from_words(self):
        self.assertEqual(parse_rooms("Bel trilocale luminoso"), 3)
        self.assertEqual(parse_rooms("monolocale arredato"), 1)

    def test_parse_rooms_from_number(self):
        self.assertEqual(parse_rooms("appartamento con 4 locali"), 4)

    def test_find_zone_in_text(self):
        self.assertEqual(find_zone("Bilocale zona Arcella, Padova", PADOVA_ZONES), "Arcella")
        self.assertIsNone(find_zone("Bilocale in centro città", ["Zona Inesistente"]))

    def test_price_plausibility(self):
        """Caso reale: 30€ per 60mq era un errore di dati che inquinava la
        media di zona."""
        self.assertFalse(price_is_plausible(30, 60.0))
        self.assertTrue(price_is_plausible(165000, 70.0))
        self.assertTrue(price_is_plausible(None, 50.0))  # nessun prezzo = niente da giudicare


class TestWikicasaDigestEmail(unittest.TestCase):
    """Email reale con 5 annunci: i link usano un token compresso
    (base64+zlib) invece di un normale redirect con parametro di query."""

    @classmethod
    def setUpClass(cls):
        html = load_fixture("wikicasa_digest.html")
        cls.listings = _extract_from_html("Wikicasa", "Annuncio appena caricato ⚡️", html)

    def test_five_listings_found_not_zero(self):
        """Prima del fix sul token compresso: 0-1 candidati. Deve trovarne 5."""
        self.assertEqual(len(self.listings), 5)

    def test_urls_are_clean_wikicasa_listing_links(self):
        for listing in self.listings:
            with self.subTest(url=listing["url"]):
                self.assertRegex(listing["url"], r"^https://www\.wikicasa\.it/\d+/")

    def test_price_does_not_swallow_adjacent_area_number(self):
        """Bug reale: '€ 210.000 127 m 2' veniva letto come prezzo
        '210.000 127' invece di '210.000', perché lo spazio era ammesso come
        separatore delle migliaia e si è 'mangiato' il numero successivo."""
        for listing in self.listings:
            with self.subTest(price=listing["price"]):
                self.assertNotIn(" ", listing["price"])

    def test_area_recognized_with_split_superscript(self):
        """Bug reale: '²' diventa 'm 2' (con spazio) in testo semplice; la
        regex si aspettava 'm²' o 'm2' senza spazio e non trovava nulla."""
        for listing in self.listings:
            with self.subTest(area=listing["area"]):
                self.assertTrue(listing["area"])
                self.assertIsNotNone(parse_area_sqm(listing["area"]))


class TestListingTypeClassification(unittest.TestCase):
    """Distinguere vendita/affitto/asta: hanno semantiche di prezzo diverse
    (un affitto a 900€ non è un errore di dati, una vendita a 900€ lo è)."""

    def test_auction_detected(self):
        text = "Appartamento in vendita in Via Tullio Lombardo, Arcella, Padova (PD) ASTA da € 48.000"
        self.assertEqual(detect_listing_type(text), "asta")

    def test_rental_detected(self):
        self.assertEqual(detect_listing_type("Bilocale in affitto zona Arcella, canone mensile 650€"), "affitto")

    def test_sale_is_default(self):
        self.assertEqual(detect_listing_type("Trilocale in vendita zona Portello, 225.000 €"), "vendita")

    def test_rental_price_not_flagged_implausible(self):
        """Un affitto a 900€/80mq (11,25€/mq/mese) è normale, non un errore
        di dati — la soglia vendita (200€/mq) lo scarterebbe erroneamente."""
        self.assertTrue(price_is_plausible(900, 80.0, listing_type="affitto"))

    def test_same_price_would_be_implausible_as_sale(self):
        """Lo stesso 900€/80mq PER UNA VENDITA è chiaramente un errore."""
        self.assertFalse(price_is_plausible(900, 80.0, listing_type="vendita"))

    def test_auction_starting_bid_plausible(self):
        self.assertTrue(price_is_plausible(48000, 30.0, listing_type="asta"))

    def test_exclude_rentals_keeps_sales_and_auctions(self):
        listings = [
            {"id": "1", "listing_type": "vendita"},
            {"id": "2", "listing_type": "affitto"},
            {"id": "3", "listing_type": "asta"},
            {"id": "4", "listing_type": "affitto"},
        ]
        kept = exclude_rentals(listings)
        kept_ids = {l["id"] for l in kept}
        self.assertEqual(kept_ids, {"1", "3"})


class TestItalianNumberFormatting(unittest.TestCase):
    """Bug reale segnalato dall'utente: 'formatta all'inglese poi sostituisci
    le virgole con i punti' produceva '1.325.4€/m²' (due punti) invece di
    '1.325,4€/m²', perché la sostituzione confondeva separatore delle
    migliaia e separatore decimale."""

    def test_thousands_with_decimal_no_double_dot(self):
        self.assertEqual(_format_it_number(1325.4, 1), "1.325,4")

    def test_below_thousand_uses_comma_decimal(self):
        self.assertEqual(_format_it_number(804.2, 1), "804,2")

    def test_integer_no_decimals(self):
        self.assertEqual(_format_it_number(66750, 0), "66.750")

    def test_millions_with_decimal(self):
        self.assertEqual(_format_it_number(1200000, 0), "1.200.000")

    def test_boundary_exactly_one_thousand(self):
        self.assertEqual(_format_it_number(1000.0, 1), "1.000,0")


class TestTelegramCaptionLengthFallback(unittest.TestCase):
    """Bug reale segnalato dall'utente: un link di tracciamento Mitula (circa
    850 caratteri) sommato al resto del messaggio superava i 1024 caratteri
    del limite didascalia foto di Telegram. La didascalia veniva troncata a
    metà URL, producendo un link rotto che 'non porta da nessuna parte'."""

    def _make_listing(self, url_length: int) -> dict:
        return {
            "title": "Appartamento - Voltabarozzo, Padova (83 m²)",
            "source": "Appartamenti in vendita - Padova (Mitula)",
            "zone": "Voltabarozzo, Padova",
            "area_sqm": 83.0,
            "rooms": 5,
            "price_eur": 66750,
            "zone_avg_price_sqm": 1325.4,
            "zone_sample_count": 5,
            "ai_score": 6.0,
            "ai_comment": "Zona centrale, 5 locali, 83 mq",
            "image_url": "https://example.com/foto.jpg",
            "url": "https://clk.thribee.com/?" + "x" * url_length,
        }

    def test_long_url_skips_photo_uses_text_message(self):
        """Con un URL lungo come quello reale di Mitula, il messaggio totale
        supera 1024 caratteri: NON deve tentare la foto (che troncherebbe
        il link), deve andare diretto al messaggio di testo completo."""
        listing = self._make_listing(url_length=800)  # produce un testo >1024 in totale

        with patch("scraper.telegram_notify._send_photo") as mock_photo, \
             patch("scraper.telegram_notify._send_message", return_value=True) as mock_text:
            notify_new_listings([listing])

        mock_photo.assert_not_called()
        mock_text.assert_called_once()
        sent_text = mock_text.call_args[0][0]
        self.assertIn(listing["url"], sent_text)  # il link deve essere INTEGRO, non troncato

    def test_short_url_still_tries_photo(self):
        """Con un messaggio corto, il comportamento normale (foto con
        didascalia) deve restare invariato — non vogliamo perdere le foto
        per tutti gli annunci solo per sistemare il caso dei link lunghi."""
        listing = self._make_listing(url_length=20)

        with patch("scraper.telegram_notify._send_photo", return_value=True) as mock_photo, \
             patch("scraper.telegram_notify._send_message") as mock_text:
            notify_new_listings([listing])

        mock_photo.assert_called_once()
        mock_text.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
