"""
Configurazione centrale del bot di monitoraggio annunci Padova.
Modifica questo file per personalizzare fonti, filtri e preferenze.
"""
import re

# ---------------------------------------------------------------------------
# QUARTIERI DI PADOVA (per riconoscere la zona nel testo di email/annunci
# quando non è già disponibile come dato strutturato)
# ---------------------------------------------------------------------------
PADOVA_ZONES = [
    "Centro Storico", "Centro", "Santo", "Portello", "Arcella", "Santa Croce",
    "Santa Rita", "San Carlo", "Forcellini", "Stanga", "Voltabarozzo",
    "Chiesanuova", "Guizza", "Mortise", "Brentella", "Bassanello",
    "Palestro", "Sacra Famiglia", "Montà", "Salboro", "Camin", "Terranegra",
    "Pontevigodarzere", "Torre", "San Lazzaro",
]

# ---------------------------------------------------------------------------
# BUDGET MASSIMO (filtro deterministico, applicato PRIMA dell'IA)
# ---------------------------------------------------------------------------
MAX_BUDGET_EUR = 250_000

# Se True, gli annunci classificati come "affitto" vengono scartati subito,
# prima ancora di finire nel database o passare dal filtro IA — non solo
# etichettati, proprio esclusi dal flusso. Non riguarda le aste (restano).
EXCLUDE_RENTALS = True

# ---------------------------------------------------------------------------
# FONTI VIA EMAIL ALERT
# Per ogni portale: domini mittente per riconoscerlo, e (opzionale) un
# pattern regex specifico per i link agli annunci. Se 'listing_url_pattern'
# è None, viene usata l'estrazione generica (tutti i link "specifici",
# scartando quelli di navigazione tramite denylist in scraper/utils.py).
#
# I pattern specifici per Idealista e Immobiliare.it sono basati sulla
# struttura nota dei loro URL pubblici; per Casa.it, Bakeca e Wikicasa
# partiamo con l'estrazione generica e li affiniamo dopo aver visto le
# prime email reali (modalità debug).
# ---------------------------------------------------------------------------
EMAIL_SOURCES = {
    "Idealista": {
        "sender_domains": ["idealista.it"],
        "listing_url_pattern": re.compile(r"https?://(?:www\.)?idealista\.it/immobile/\d+[^\s\"'<>]*"),
    },
    "Immobiliare.it": {
        "sender_domains": ["immobiliare.it"],
        "listing_url_pattern": re.compile(r"https?://(?:www\.)?immobiliare\.it/annunci/\d+[^\s\"'<>]*"),
    },
    "Casa.it": {
        "sender_domains": ["casa.it"],
        "listing_url_pattern": None,  # da affinare con email reale
    },
    "Bakeca": {
        "sender_domains": ["bakeca.it"],
        "listing_url_pattern": None,  # da affinare con email reale
    },
    "Wikicasa": {
        "sender_domains": ["wikicasa.it"],
        "listing_url_pattern": re.compile(r"https?://(?:www\.)?wikicasa\.it/\d+/[^\s\"'<>]*"),
    },
    "TecnoCasa": {
        "sender_domains": ["tecnocasa.it"],
        "listing_url_pattern": None,  # da affinare con email reale
    },
    "Subito.it": {
        "sender_domains": ["subito.it"],
        "listing_url_pattern": None,  # da affinare con email reale
    },
}

# ---------------------------------------------------------------------------
# FILTRO IA (Groq o Gemini, entrambi gratuiti)
# ---------------------------------------------------------------------------
AI_FILTER_ENABLED = True

USER_PREFERENCES = """
Cerco un appartamento a Padova con queste caratteristiche, in ordine di importanza:
- Zona: centro storico, Santo, Portello, oppure vicino ospedale/università
- Almeno 2 locali, se possibile con balcone o terrazzo
- Piano preferibilmente non terra
- Evita: annunci di sole camere singole, uffici, box/garage travestiti da "immobili"
- Va bene sia da privato che da agenzia
- Budget massimo 250.000€ (già filtrato automaticamente, ma tienilo presente
  nella valutazione qualitativa)
"""

AI_MIN_SCORE = 5
AI_PROVIDER = "groq"
AI_MODEL_GROQ = "llama-3.1-8b-instant"
AI_MODEL_GEMINI = "gemini-1.5-flash"

# ---------------------------------------------------------------------------
# COMPORTAMENTO GENERALE
# ---------------------------------------------------------------------------
MAX_NEW_LISTINGS_PER_RUN = 30

STATE_FILE = "data/state.json"
