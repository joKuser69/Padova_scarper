"""
Filtro IA: valuta ogni nuovo annuncio rispetto alle preferenze dell'utente
e ritorna un punteggio 0-10 più un breve commento, così le notifiche Telegram
contengono solo ciò che conta davvero.

Supporta due provider gratuiti, scelti via config.AI_PROVIDER:
- "groq"   -> https://console.groq.com  (free tier generoso, molto veloce)
- "gemini" -> https://aistudio.google.com (free tier Gemini 1.5 Flash)

Le chiavi vanno messe come secret GitHub Actions: GROQ_API_KEY / GEMINI_API_KEY
"""
import json
import os

import requests

from config import AI_PROVIDER, AI_MODEL_GROQ, AI_MODEL_GEMINI, USER_PREFERENCES


PROMPT_TEMPLATE = """Sei un assistente che aiuta a filtrare annunci immobiliari.

PREFERENZE DELL'UTENTE:
{preferences}

ANNUNCIO DA VALUTARE:
Titolo: {title}
Prezzo: {price}
Fonte: {source}

Valuta quanto questo annuncio corrisponde alle preferenze, su una scala da 0 a 10
(10 = corrispondenza perfetta, 0 = totalmente irrilevante o categoria sbagliata).
Rispondi SOLO con un oggetto JSON, senza testo aggiuntivo, in questo formato esatto:
{{"score": <numero 0-10>, "comment": "<massimo 20 parole in italiano>"}}
"""


def _call_groq(prompt: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY non impostata")

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": AI_MODEL_GROQ,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 100,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY non impostata")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{AI_MODEL_GEMINI}:generateContent?key={api_key}"
    )
    resp = requests.post(
        url,
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse_json_response(text: str) -> dict:
    # I modelli a volte avvolgono il JSON in ```json ... ``` nonostante le istruzioni
    cleaned = text.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"score": 5, "comment": "(valutazione IA non disponibile)"}


def evaluate_listing(listing: dict) -> dict:
    """Aggiunge 'ai_score' e 'ai_comment' al dizionario dell'annuncio."""
    prompt = PROMPT_TEMPLATE.format(
        preferences=USER_PREFERENCES.strip(),
        title=listing.get("title", ""),
        price=listing.get("price", "n/d"),
        source=listing.get("source", ""),
    )

    try:
        if AI_PROVIDER == "groq":
            raw = _call_groq(prompt)
        elif AI_PROVIDER == "gemini":
            raw = _call_gemini(prompt)
        else:
            raise ValueError(f"AI_PROVIDER sconosciuto: {AI_PROVIDER}")

        result = _parse_json_response(raw)
        listing["ai_score"] = float(result.get("score", 5))
        listing["ai_comment"] = result.get("comment", "")
    except Exception as e:
        print(f"[AI] Errore valutazione annuncio '{listing.get('title')}': {e}")
        # In caso di errore IA, non blocchiamo la notifica: punteggio neutro
        listing["ai_score"] = 5.0
        listing["ai_comment"] = "(valutazione IA non riuscita)"

    return listing


def evaluate_all(listings: list) -> list:
    return [evaluate_listing(l) for l in listings]
