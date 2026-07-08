# Bot monitoraggio annunci immobiliari Padova

Legge gli alert email nativi di Idealista, Immobiliare.it, Casa.it, Bakeca e
Wikicasa (più Mitula come fonte supplementare via scraping leggero), filtra
per budget e con un'IA gratuita in base alle tue preferenze, e ti notifica
su Telegram solo gli annunci rilevanti. Gira su GitHub Actions ogni 15 minuti,
zero costi, zero server da gestire.

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
- `MITULA_SEARCHES`: URL delle ricerche Mitula per Padova

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

Non avendo un esempio reale delle email di alert dei 5 portali, l'estrazione
per Casa.it, Bakeca e Wikicasa parte con una logica generica (prende i link
che sembrano puntare a un singolo annuncio, scarta quelli di navigazione).
Dopo il primo run reale:

1. Vai sul run completato in **Actions**, scarica l'artifact **debug-html**
   in fondo alla pagina (contiene l'HTML delle email processate, con nomi
   tipo `email_0_Casa_it.html`)
2. Caricamelo qui in chat
3. Ti scrivo un pattern regex preciso per quel portale, esattamente come
   abbiamo già fatto per Mitula

Stesso discorso se dopo un po' iniziano ad arrivare troppi falsi positivi
(link non pertinenti): mandami un run recente e affiniamo il filtro.

## Struttura del progetto

```
config.py                    # fonti, budget, preferenze IA — il file che modifichi di più
main.py                      # orchestratore principale
scraper/
  email_alerts.py             # legge Gmail via IMAP, estrae link dagli alert
  mitula_scraper.py           # requests + BeautifulSoup, fonte supplementare
  ai_filter.py                 # valutazione IA (Groq/Gemini)
  telegram_notify.py          # invio notifiche
  state.py                     # dedup per Mitula (l'email si autogestisce via IMAP)
  utils.py                     # parsing prezzi, filtro link di navigazione
data/state.json               # stato persistente (solo id Mitula)
.github/workflows/scraper.yml   # schedulazione ogni 15 minuti
```

## Nota su Subito.it

Subito.it è stato rimosso dallo scraping diretto: i test hanno mostrato un
blocco esplicito di **Akamai Bot Manager** (stessa categoria di protezione
di Idealista/Immobiliare.it) contro le richieste automatizzate da GitHub
Actions. Se attivi anche lì l'alert via email con lo stesso Gmail dedicato,
aggiungilo a `EMAIL_SOURCES` in `config.py` — il bot lo tratterà esattamente
come gli altri 5.
