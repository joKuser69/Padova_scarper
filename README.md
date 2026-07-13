# Bot monitoraggio annunci immobiliari Padova

Legge gli alert email nativi di Idealista, Immobiliare.it, Casa.it, Bakeca,
Wikicasa, TecnoCasa e Subito.it, filtra per budget e con un'IA gratuita in
base alle tue preferenze, e ti notifica su Telegram solo gli annunci
rilevanti — con foto, mq, locali, prezzo/mq, confronto con la media di zona,
e variazioni di prezzo nel tempo sullo stesso annuncio. Gira su GitHub
Actions ogni 15 minuti, zero costi.

Nota: Mitula è stato rimosso come fonte supplementare. Era quella con più
problemi di affidabilità (link protetti da un sistema di tracciamento non
sempre stabile, un bug di parsing prezzi scoperto solo dai test), mentre gli
alert email arrivano direttamente e ufficialmente dai portali stessi.

## Funzionalità

- **Storico prezzi**: ogni annuncio è tracciato nel tempo in `data/state.json`
  (un vero mini-database, non solo un elenco di id). Se lo stesso annuncio
  ricompare con un prezzo diverso, te lo segnala esplicitamente.
- **Media prezzo/mq per zona**: calcolata separatamente per vendita/affitto
  (mediare i due insieme non avrebbe senso). Serve un minimo di 3 annunci
  comparabili prima di mostrare una media.
- **Distinzione vendita / affitto / asta**: un'asta giudiziaria mostra la
  "base d'asta" (spesso molto sotto il valore di mercato, non un affare
  diretto) — badge "⚖️ ASTA GIUDIZIARIA" in evidenza. Un affitto ha soglie
  di prezzo plausibile completamente diverse da una vendita (8€/mq/mese è
  normale in affitto, sarebbe assurdo in vendita) — badge "🔑 AFFITTO".
- **Foto**: se disponibile un'immagine, viene inviata come foto con i
  dettagli come didascalia (fallback automatico a solo testo se l'immagine
  non è raggiungibile, o se il messaggio è troppo lungo per una didascalia
  — successo anche questo, con un link Mitula troncato a metà).
- **Risposta a "/start"**: chi avvia il bot per la prima volta riceve subito
  gli ultimi 20 annunci tracciati, invece di trovare un canale vuoto in
  attesa del primo nuovo annuncio. Il bot non ha un server sempre acceso
  (gira su GitHub Actions ogni 15 minuti), quindi la risposta non è
  istantanea — arriva al run successivo, entro 15 minuti al massimo.
- **Test automatici** (`tests/`): fixture con email/pagine REALI raccolte
  durante lo sviluppo, non dati inventati. Girano da soli ad ogni modifica
  del codice tramite `.github/workflows/tests.yml` — se una modifica rompe
  l'estrazione di un sito, lo vedi subito come ❌ su GitHub, senza dover
  aspettare un run reale e mandare log avanti e indietro.
- **Limite noto**: il numero di locali (es. "trilocale" = 3) è disponibile,
  ma la suddivisione stanza per stanza no — quel dettaglio esiste solo nella
  pagina protetta del singolo annuncio, che il bot non visita di proposito.

## Come funziona (in breve)

Idealista e Immobiliare.it usano sistemi anti-bot enterprise pensati per
bloccare lo scraping diretto. Invece di combatterli, usiamo la loro stessa
funzionalità ufficiale di **alert via email** — quella che chiunque può
attivare da "salva ricerca" — puntata su un Gmail dedicato. Il bot legge
quella casella (con le tue credenziali, via App Password), estrae i link
agli annunci dalle email, e li rilancia su Telegram. Nessun accesso non
autorizzato a nessun sito: solo lettura della tua posta.

## Setup

### 1. L'account Gmail dedicato (hai già fatto la parte "alert attivi" ✅)

Ti serve ancora:
1. **Verifica in 2 passaggi** attiva su quel Gmail: vai su
   `myaccount.google.com/security` → "Verifica in due passaggi" → attivala.
2. **App Password**: dopo aver attivato la verifica in 2 passaggi, vai su
   `myaccount.google.com/apppasswords` → crea una password per "Mail" →
   copiala subito (Google la mostra una volta sola).
3. L'IMAP è **già attivo di default** su Gmail dal 2025, nessun altro
   passaggio necessario.

⚠️ Importante: se questo Gmail ha già email vecchie non lette in arrivo dagli
alert (essendo attivi da un po'), il primo run del bot le processerà tutte
insieme. Se vuoi evitare una raffica di notifiche al primo avvio, apri
l'inbox una volta e segna tutto come "già letto" prima di attivare il bot.
In ogni caso c'è un tetto di sicurezza (`MAX_NEW_LISTINGS_PER_RUN` in
`config.py`) che limita le notifiche in un singolo run.

### 2. Configura le tue preferenze

Apri `config.py` (tramite l'editor web di GitHub, matita in alto a destra sul
file) e modifica se vuoi:
- `MAX_BUDGET_EUR`: già impostato a 250.000
- `USER_PREFERENCES`: descrizione libera di cosa cerchi (per il filtro IA)
- `EXCLUDE_RENTALS`: già impostato a True (esclude gli affitti)

### 3. Crea la API key IA gratuita

Registrati su **console.groq.com** → crea una API key (tier gratuito
generoso, modelli Llama velocissimi). In alternativa Gemini
(`aistudio.google.com/apikey`) cambiando `AI_PROVIDER = "gemini"` in
`config.py`.

### 4. Aggiungi i secret su GitHub

Dal tuo repository, anche da iPhone Safari: **Settings → Secrets and
variables → Actions → New repository secret**. Aggiungi questi 5:

| Nome | Valore |
|---|---|
| `IMAP_EMAIL` | l'indirizzo Gmail dedicato |
| `IMAP_APP_PASSWORD` | la App Password a 16 caratteri generata sopra |
| `TELEGRAM_BOT_TOKEN` | il token del tuo bot |
| `TELEGRAM_CHAT_ID` | il tuo chat id |
| `GROQ_API_KEY` | la key creata su console.groq.com |

### 5. Carica i file nel repository

**Da iPhone, senza terminale:**
- Scarica lo zip che ti ho preparato, aprilo con l'app **File** di iOS
  (tap sul file → "Decomprimi") per ottenere la cartella con tutti i file.
- Su GitHub, nel tuo repo, usa **Add file → Upload files**: Safari ti fa
  scegliere più file insieme dall'app File. Ricrea la stessa struttura di
  cartelle (`.github/workflows/`, `scraper/`, `data/`).
- In alternativa, per singoli file, usa **Add file → Create new file** e
  incolla il contenuto a mano (funziona bene per file piccoli come
  `config.py`).

### 6. Rendi il repository privato (fortemente consigliato)

**Settings → General → Danger Zone → Change visibility → Private.** A
differenza del vecchio approccio (solo scraping di pagine pubbliche), questo
bot maneggia contenuti della tua posta elettronica. Su un repo pubblico, i
log e gli artifact di GitHub Actions sono visibili a chiunque — meglio di
no, anche se le password vere restano comunque mascherate come secret. I
repository privati sono gratuiti e illimitati su GitHub, e i minuti gratuiti
di Actions (2.000/mese) bastano ampiamente per un run leggero ogni 15 minuti.

### 7. Primo avvio

**Actions → "Monitoraggio annunci Padova" → Run workflow.**

## Se i link estratti dalle email non sono giusti

Non avendo un esempio reale delle email di alert di ogni portale, l'estrazione
per Casa.it, Bakeca, TecnoCasa e Subito.it parte con una logica generica
(prende i link che sembrano puntare a un singolo annuncio, scarta quelli di
navigazione). Wikicasa aveva lo stesso trattamento finché non abbiamo visto
email reali e scritto un pattern preciso — probabile che serva lo stesso
per le due fonti appena aggiunte. Dopo il primo run reale:

1. Vai sul run completato in **Actions**, scarica l'artifact **debug-html**
   in fondo alla pagina (contiene l'HTML delle email processate, con nomi
   tipo `email_0_Casa_it.html`)
2. Caricamelo qui in chat
3. Ti scrivo un pattern regex preciso per quel portale, esattamente come
   abbiamo già fatto per Idealista e Wikicasa

Stesso discorso se dopo un po' iniziano ad arrivare troppi falsi positivi
(link non pertinenti): mandami un run recente e affiniamo il filtro.

## Struttura del progetto

```
config.py                    # fonti, budget, quartieri, preferenze IA
main.py                      # orchestratore principale
scraper/
  email_alerts.py             # legge Gmail via IMAP, estrae link+dati dagli alert
  ai_filter.py                 # valutazione IA (Groq/Gemini) + completamento zona/mq/locali
  telegram_notify.py          # invio notifiche (testo o foto), formattazione ricca
  db.py                        # database persistente: storico prezzi, media di zona
  utils.py                     # parsing prezzi/mq/locali/tipo, normalizzazione annunci
tests/
  test_extraction.py          # test automatici su email/pagine reali
  fixtures/                    # le email/pagine vere usate dai test
data/state.json                # database persistente (storico completo, non solo id)
.github/workflows/
  scraper.yml                  # schedulazione bot ogni 15 minuti
  tests.yml                    # test automatici ad ogni modifica del codice
```

## Eseguire i test

I test girano automaticamente su GitHub ad ogni push (niente da fare). Se
un giorno avrai un ambiente Python a disposizione, si eseguono anche a mano:

```
python -m unittest discover tests -v
```

Quando trovi un nuovo caso limite (un'email che non si comporta come
previsto), il modo più veloce per farmelo sistemare per sempre è: mandami
l'artifact debug-html come hai già fatto finora — lo aggiungo ai test come
fixture permanente, così quel caso specifico non si romperà mai più senza
che tu te ne accorga subito.

## Se hai già un `data/state.json` da una versione precedente

Nessuna azione richiesta: il bot rileva automaticamente il vecchio formato
(un semplice elenco di id, senza prezzo/storico) e lo converte al primo run,
senza notificarti di nuovo in blocco tutto quello che già conteneva. Vedrai
un log tipo `[DB] Migrati N id dal vecchio formato state.json` — è normale,
succede una volta sola.

Le schede storiche con `source` contenente "Mitula" (da prima della
rimozione) restano nel database e continuano a contribuire alle medie di
zona — non serve ripulirle a mano, semplicemente non si aggiorneranno più.


## Nota su Subito.it

Subito.it è stato rimosso dallo scraping diretto: i test hanno mostrato un
blocco esplicito di **Akamai Bot Manager** (stessa categoria di protezione
di Idealista/Immobiliare.it) contro le richieste automatizzate da GitHub
Actions. Se attivi anche lì l'alert via email con lo stesso Gmail dedicato,
aggiungilo a `EMAIL_SOURCES` in `config.py` — il bot lo tratterà esattamente
come gli altri 5.
