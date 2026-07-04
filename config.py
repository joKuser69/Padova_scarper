"""
Configurazione centrale del bot di monitoraggio annunci Padova.
Modifica questo file per personalizzare ricerche e preferenze.
"""

# ---------------------------------------------------------------------------
# RICERCHE SUBITO.IT
# Ogni URL è una ricerca già filtrata su subito.it (categoria, zona, prezzo...).
# Vai su subito.it, imposta i filtri che vuoi, copia l'URL della pagina risultati.
# ---------------------------------------------------------------------------
SUBITO_SEARCHES = [
    {
        "name": "Appartamenti in affitto - Padova",
        "url": "https://www.subito.it/annunci-veneto/affitto/appartamenti/padova/",
    },
    {
        "name": "Appartamenti in vendita - Padova",
        "url": "https://www.subito.it/annunci-veneto/vendita/appartamenti/padova/",
    },
]

# ---------------------------------------------------------------------------
# RICERCHE MITULA (aggrega anche annunci di Immobiliare.it)
# Stessa logica: costruisci la ricerca su immobiliare.mitula.it e incolla l'URL.
# ---------------------------------------------------------------------------
MITULA_SEARCHES = [
    {
        "name": "Appartamenti in affitto - Padova (Mitula)",
        "url": "https://immobiliare.mitula.it/affitto-appartamento-padova",
    },
    {
        "name": "Appartamenti in vendita - Padova (Mitula)",
        "url": "https://immobiliare.mitula.it/vendita-appartamento-padova",
    },
]

# ---------------------------------------------------------------------------
# FILTRO IA (opzionale ma attivo di default)
# Descrivi in linguaggio naturale cosa cerchi. Il modello valuterà ogni nuovo
# annuncio contro questa descrizione e assegnerà un punteggio di rilevanza.
# ---------------------------------------------------------------------------
AI_FILTER_ENABLED = True

USER_PREFERENCES = """
Cerco un appartamento a Padova con queste caratteristiche, in ordine di importanza:
- Zona: centro storico, Santo, Portello, oppure vicino ospedale/università
- Almeno 2 locali, se possibile con balcone o terrazzo
- Piano preferibilmente non terra
- Evita: annunci di sole camere singole, uffici, box/garage travestiti da "immobili"
- Va bene sia da privato che da agenzia
"""

# Punteggio minimo (0-10) sotto il quale l'annuncio NON viene notificato.
# Metti 0 se vuoi ricevere comunque tutti gli annunci nuovi (l'IA aggiunge solo un commento).
AI_MIN_SCORE = 5

# Provider IA gratuito: "groq" oppure "gemini"
AI_PROVIDER = "groq"
AI_MODEL_GROQ = "llama-3.1-8b-instant"
AI_MODEL_GEMINI = "gemini-1.5-flash"

# ---------------------------------------------------------------------------
# COMPORTAMENTO SCRAPER (rispetto rate-limit, buona educazione verso i siti)
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS = 8          # pausa minima tra una richiesta e l'altra
MAX_NEW_LISTINGS_PER_RUN = 30      # tetto di sicurezza per singola esecuzione
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

STATE_FILE = "data/state.json"
