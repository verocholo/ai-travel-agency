"""
Redazione dei segreti dai messaggi d'errore — src/redaction.py.

[ESTRATTO 2026-08-01 da `pipeline._redact_secrets()`] Le due espressioni
regolari qui sotto nascono da un leak REALE trovato nell'audit del
2026-07-31: Geocoding e Distance Matrix passano la GOOGLE_MAPS_KEY come
query param `key=...`, e il messaggio di una
`requests.exceptions.RequestException` porta con sé la URL completa —
quindi la chiave vera finiva nel campo `data_layer_error` restituito al
client.

Vengono estratte in un modulo proprio perché ora servono in DUE posti:
`pipeline.py` (che le usa da sempre) e `alerting.py` (che manda i
messaggi d'errore a un webhook esterno — esattamente il posto dove un
leak sarebbe peggiore, perché esce dal perimetro del servizio). Copiarle
avrebbe creato due implementazioni destinate a divergere, che è il modo
tipico in cui una difesa di sicurezza smette silenziosamente di
funzionare in metà dei casi.

`pipeline._redact_secrets` resta come alias, così nulla di ciò che lo
chiamava (incluso un test dell'audit) si rompe.
"""
from __future__ import annotations

import re

_SECRET_QS_RE = re.compile(r"(key=)[^&\s'\"]+", re.IGNORECASE)
_SECRET_HDR_RE = re.compile(
    r"((?:x-api-key|x-goog-api-key)['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}]+", re.IGNORECASE
)
# [AGGIUNTO 2026-08-01] Le chiavi Anthropic (`sk-ant-...`) non viaggiano in
# query string ma compaiono in chiaro in alcuni messaggi dell'SDK, e
# `SERVICE_API_KEY` può finire in un log di richiesta. Un token che comincia
# per `sk-` è riconoscibile senza ambiguità: lo redigo ovunque appaia.
_SECRET_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE)


def redact_secrets(msg: str) -> str:
    """Sostituisce con REDACTED ogni credenziale riconoscibile nel testo.

    Non è (e non può essere) esaustiva: è una rete che copre le forme in cui
    le chiavi di QUESTO progetto finiscono davvero nei messaggi d'errore.
    Accetta qualunque input e ritorna sempre una stringa — un errore dentro
    la redazione non deve mai impedire di segnalare l'errore originale.
    """
    if not isinstance(msg, str):
        msg = str(msg)
    msg = _SECRET_QS_RE.sub(r"\1REDACTED", msg)
    msg = _SECRET_HDR_RE.sub(r"\1REDACTED", msg)
    msg = _SECRET_TOKEN_RE.sub("sk-REDACTED", msg)
    return msg
