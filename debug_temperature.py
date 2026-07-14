#!/usr/bin/env python3
"""
Script di DEBUG, non fa parte della pipeline. Risponde a una domanda
precisa lasciata aperta dal fix del 2026-07-10: quando il modello ha
rifiutato con 400 "temperature is deprecated for this model", ho tolto il
parametro DEL TUTTO (default None in call_claude()) senza verificare se
fosse un problema del valore specifico (0.4) o del parametro in sé per
qualunque valore. Differenza importante: se il modello accetta ALCUNI
valori di temperature, possiamo fissarne uno basso per rendere il prodotto
più prevedibile/consistente per i clienti reali, invece di dipendere dal
default (probabilmente alto/più "creativo") dell'API.

Ogni chiamata qui è MINIMA (poche parole, "rispondi solo OK") apposta per
costare pochissimo — non genera un itinerario completo, testa solo se la
API accetta la richiesta con quel valore di temperature.

Uso:
  python debug_temperature.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import SETTINGS

VALUES_TO_TEST = [0.0, 0.4, 0.7, 1.0]  # più None (= parametro assente), testato a parte


def try_call(client, model: str, temperature) -> tuple[bool, str]:
    kwargs = dict(
        model=model,
        max_tokens=10,
        messages=[{"role": "user", "content": "Rispondi solo con la parola OK."}],
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return True, text.strip()
    except Exception as e:  # vogliamo vedere qualunque errore dell'API, non solo BadRequestError
        return False, str(e)


def main():
    if not SETTINGS.anthropic_api_key:
        print("❌ ANTHROPIC_API_KEY mancante nel .env")
        sys.exit(1)

    import anthropic
    from src.claude_engine import select_model

    client = anthropic.Anthropic(api_key=SETTINGS.anthropic_api_key)
    # Testa sul modello che la pipeline usa davvero di default (BALANCED, viaggio breve)
    model = select_model("BALANCED", 3)
    print(f"Modello sotto test: {model}\n")

    print(f"{'=' * 60}\ntemperature NON impostata (comportamento attuale del prototipo)\n{'=' * 60}")
    ok, msg = try_call(client, model, None)
    print(f"{'✅ accettato' if ok else '❌ rifiutato'} — {msg}\n")

    for t in VALUES_TO_TEST:
        print(f"{'=' * 60}\ntemperature={t}\n{'=' * 60}")
        ok, msg = try_call(client, model, t)
        print(f"{'✅ accettato' if ok else '❌ rifiutato'} — {msg}\n")

    print(
        "Se almeno un valore basso (0.0-0.4) risulta ✅ accettato, conviene fissarlo "
        "esplicitamente in src/claude_engine.py (parametro temperature di call_claude) per "
        "rendere gli itinerari più consistenti da run a run — un prodotto commerciale non "
        "dovrebbe variare troppo la sua risposta su uno stesso identico input. Se TUTTI i "
        "valori risultano ❌, il parametro è davvero deprecato per questo modello e resta "
        "corretto lasciarlo non impostato: incolla questo output così lo documentiamo."
    )


if __name__ == "__main__":
    main()
