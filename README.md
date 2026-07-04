# Bot monitoraggio annunci immobiliari Padova

Monitora Subito.it e Mitula (che aggrega anche Immobiliare.it) per nuovi
annunci a Padova, li filtra con un'IA gratuita in base alle tue preferenze,
e ti notifica su Telegram solo quelli rilevanti.

## Cosa NON fa (e perché)

Questo bot **non include Idealista.it, Immobiliare.it diretto o Casa.it**.
Questi siti usano sistemi anti-bot enterprise (es. DataDome) pensati per
bloccare esplicitamente lo scraping automatizzato. Aggirarli richiederebbe
tecniche di evasione della sicurezza che non è cosa che questo progetto fa.
Per quei siti, usa la funzione nativa "Salva ricerca + notifica email/app"
(gratuita e ufficiale).

## Setup

### 1. Configura le tue ricerche e preferenze

Apri `config.py` e modifica:
- `SUBITO_SEARCHES` / `MITULA_SEARCHES`: incolla gli URL delle tue ricerche
  (vai sul sito, imposta i filtri che vuoi — prezzo, zona, mq — e copia l'URL
  della pagina risultati).
- `USER_PREFERENCES`: descrivi in linguaggio naturale cosa cerchi. Questo
  testo viene usato dall'IA per valutare ogni annuncio.
- `AI_MIN_SCORE`: soglia (0-10) sotto la quale un annuncio non ti viene
  notificato. Metti `0` se vuoi ricevere comunque tutto.

### 2. Crea le chiavi API necessarie

**Telegram** (hai già fatto):
- Token del bot da @BotFather
- Chat ID (se non lo hai: scrivi un messaggio al tuo bot, poi visita
  `https://api.telegram.org/bot<TOKEN>/getUpdates` e cerca `"chat":{"id":...}`)

**IA gratuita** — scegli UNA delle due:
- **Groq** (consigliato, molto veloce): registrati su https://console.groq.com
  → crea una API key. Tier gratuito generoso.
- **Gemini**: registrati su https://aistudio.google.com/apikey → crea una
  API key. Tier gratuito Gemini 1.5 Flash.

Se usi Gemini invece di Groq, cambia `AI_PROVIDER = "gemini"` in `config.py`.

### 3. Aggiungi i secret su GitHub

Nel tuo repository: **Settings → Secrets and variables → Actions → New
repository secret**. Aggiungi:

| Nome | Valore |
|---|---|
| `TELEGRAM_BOT_TOKEN` | il token del tuo bot |
| `TELEGRAM_CHAT_ID` | il tuo chat id |
| `GROQ_API_KEY` | (se usi Groq) |
| `GEMINI_API_KEY` | (se usi Gemini) |

### 4. Push del codice

Carica tutti questi file nel tuo repository GitHub (rispettando la struttura
delle cartelle, specialmente `.github/workflows/scraper.yml`).

### 5. Primo avvio

Vai su **Actions** nel tuo repo → seleziona "Monitoraggio annunci Padova" →
**Run workflow** per un test manuale immediato (invece di aspettare i 30
minuti del cron).

**Il primo run è speciale**: registra tutti gli annunci esistenti come "già
visti" senza notificarli tutti insieme (altrimenti riceveresti centinaia di
messaggi in un colpo solo). Riceverai solo un messaggio di riepilogo. Dal
secondo run in poi, riceverai le notifiche per i NUOVI annunci.

## Se qualcosa non funziona al primo run reale

I siti web cambiano struttura HTML periodicamente, quindi è possibile che
alcuni selettori vadano aggiustati. Controlla i log del run su GitHub Actions:

- Se vedi `0 annunci trovati` per Subito.it → il sito potrebbe aver cambiato
  la struttura di `__NEXT_DATA__`. Serve aggiornare `subito_scraper.py`.
- Se vedi `0 annunci trovati` per Mitula → potrebbero aver cambiato i
  microdati schema.org. Serve aggiornare `mitula_scraper.py`.

Portami i log dell'errore e sistemiamo insieme il selettore.

## Personalizzare la frequenza

Nel file `.github/workflows/scraper.yml`, modifica la riga cron:

```yaml
- cron: "*/30 * * * *"   # ogni 30 minuti (default)
- cron: "0 * * * *"      # ogni ora
- cron: "*/15 * * * *"   # ogni 15 minuti (più aggressivo, valuta se necessario)
```

Nota: GitHub Actions su piano gratuito ha un limite di minuti di esecuzione
mensili. Con run di ~1-2 minuti ogni 30 minuti, resti ampiamente dentro il
limite gratuito per un repository privato o pubblico.

## Struttura del progetto

```
config.py                    # tutte le impostazioni personalizzabili
main.py                      # orchestratore principale
scraper/
  subito_scraper.py          # Playwright, rendering JS
  mitula_scraper.py          # requests + BeautifulSoup
  ai_filter.py                # valutazione IA (Groq/Gemini)
  telegram_notify.py         # invio notifiche
  state.py                    # dedup tra run successivi
data/state.json              # stato persistente (annunci già visti)
.github/workflows/scraper.yml  # schedulazione automatica
```
