"""
Allarme sui fallimenti — src/alerting.py.

[AGGIUNTO 2026-08-01 — punto 5 del feedback "da investitore" del
2026-08-01: "cinque dipendenze esterne, nessun allarme. Se lo scenario
fallisce in silenzio alle due di notte, il primo a scoprirlo è un cliente
che ha pagato e non ha ricevuto niente."]

Il servizio degrada già bene (ogni sezione del PDF è best-effort, ogni
errore diventa un JSON leggibile invece di un traceback), ma degradare
bene in silenzio è esattamente il problema: un PDF consegnato senza
cartine e senza guide è indistinguibile, per chi guarda da fuori, da uno
completo.

Questo modulo manda una notifica compatta a un webhook quando qualcosa
va storto o quando un documento esce degradato. Tre regole di progetto,
tutte deliberate:

1. **Non può mai far fallire la richiesta.** Qualunque eccezione qui
   dentro — webhook irraggiungibile, DNS rotto, URL malformata, timeout —
   viene inghiottita e loggata. Un allarme che rompe la consegna del PDF
   sarebbe peggio del problema che segnala.
2. **Non può mai far uscire un segreto.** Ogni testo passa da
   `redaction.redact_secrets()` prima di lasciare il processo: il webhook
   è un endpoint esterno, cioè il posto peggiore dove far finire una
   GOOGLE_MAPS_KEY (leak reale già trovato nell'audit del 2026-07-31).
3. **Non può mai far uscire dati personali del cliente.** Nel corpo
   dell'allarme non entrano email, nome, note libere del form. Solo
   destinazione, durata e identificatori tecnici: quanto basta per capire
   COSA è rotto senza spedire il cliente a un servizio terzo.

Configurazione, tutta via variabili d'ambiente (nessuna chiave nel repo):

    ALERT_WEBHOOK_URL   URL a cui fare POST di un JSON. Se assente, il
                        modulo è completamente inerte: nessuna chiamata di
                        rete, nessun errore. È il comportamento di oggi.
    ALERT_MIN_LEVEL     "warning" (default) o "error": con "error" passano
                        solo i fallimenti veri, non i documenti degradati.
    ALERT_TIMEOUT_S     timeout della POST, default 5 secondi.

Funziona con qualunque endpoint che accetti un POST JSON: uno webhook di
Slack, un modulo "Custom webhook" di Make.com che poi manda una mail, o
un servizio di monitoraggio. Il campo `text` è precompilato in modo che
Slack lo mostri leggibile senza configurazione aggiuntiva.
"""
from __future__ import annotations

import json
import logging
import os

from .redaction import redact_secrets

logger = logging.getLogger(__name__)

LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"

_LEVEL_ORDER = {LEVEL_WARNING: 10, LEVEL_ERROR: 20}

DEFAULT_TIMEOUT_S = 5.0

# Tetto sulla lunghezza del dettaglio: un traceback o un body di errore di
# un'API esterna può essere lunghissimo, e un webhook che rifiuta il payload
# perché troppo grande è un allarme che non arriva.
_MAX_DETAIL_CHARS = 1500


def _min_level() -> str:
    raw = (os.getenv("ALERT_MIN_LEVEL") or LEVEL_WARNING).strip().lower()
    return raw if raw in _LEVEL_ORDER else LEVEL_WARNING


def _timeout_s() -> float:
    raw = os.getenv("ALERT_TIMEOUT_S")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def safe_trip_context(trip: object) -> dict:
    """Estrae dal Trip SOLO i campi non personali, per l'allarme.

    Deliberatamente NON include email, nome o note libere: l'allarme esce
    verso un servizio esterno, e per capire cosa è rotto basta sapere dove
    e quanto dura il viaggio. Accetta un `Trip`, un dict o None e non
    solleva mai.
    """
    if trip is None:
        return {}
    getter = trip.get if isinstance(trip, dict) else lambda k, d=None: getattr(trip, k, d)
    context = {}
    for field in ("destination", "duration_days", "objective_function", "budget_mode"):
        try:
            value = getter(field, None)
        except Exception:  # noqa: BLE001 — un Trip esotico non deve rompere l'allarme
            value = None
        if value is not None:
            context[field] = value
    return context


def build_alert_payload(kind: str, detail: str, context: dict | None, level: str) -> dict:
    """Funzione pura — costruisce il corpo dell'allarme (testabile senza rete)."""
    safe_detail = redact_secrets(str(detail))
    if len(safe_detail) > _MAX_DETAIL_CHARS:
        safe_detail = safe_detail[:_MAX_DETAIL_CHARS] + " […troncato]"
    safe_context = {}
    for key, value in (context or {}).items():
        safe_context[str(key)] = (
            redact_secrets(value) if isinstance(value, str) else value
        )
    prefix = "ERRORE" if level == LEVEL_ERROR else "AVVISO"
    return {
        "service": "ai-travel-agency",
        "level": level,
        "kind": str(kind),
        "detail": safe_detail,
        "context": safe_context,
        # Campo di cortesia per Slack/Discord, che mostrano `text` così com'è.
        "text": f"[{prefix}] ai-travel-agency — {kind}: {safe_detail}",
    }


def notify(kind: str, detail: str, context: dict | None = None, level: str = LEVEL_ERROR) -> bool:
    """Manda l'allarme. Ritorna True se è stato spedito, False altrimenti.

    Il valore di ritorno serve ai test e ai log: NESSUN chiamante deve
    cambiare comportamento in base ad esso, men che meno sollevare.
    """
    try:
        level = level if level in _LEVEL_ORDER else LEVEL_ERROR
        if _LEVEL_ORDER[level] < _LEVEL_ORDER[_min_level()]:
            return False
        url = (os.getenv("ALERT_WEBHOOK_URL") or "").strip()
        if not url:
            # Comportamento di default: nessun webhook configurato → inerte.
            # L'evento resta comunque nei log del servizio.
            logger.warning("[alert:%s] %s — %s", level, kind, redact_secrets(str(detail)))
            return False
        payload = build_alert_payload(kind, detail, context, level)
        logger.warning("[alert:%s] %s — %s", level, kind, payload["detail"])

        import requests  # import locale: il modulo resta importabile senza rete

        requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=_timeout_s(),
        )
        return True
    except Exception as e:  # noqa: BLE001 — vedi regola 1 nel docstring del modulo
        try:
            logger.warning("Invio dell'allarme fallito (ignorato): %s", redact_secrets(str(e)))
        except Exception:  # pragma: no cover — logger rotto: non resta nulla da fare
            pass
        return False


def notify_degraded_pdf(counters: dict, context: dict | None = None) -> bool:
    """Allarme di livello `warning` quando un PDF esce con delle sezioni vuote.

    Ogni sezione del PDF è best-effort per scelta (una chiave Google scaduta
    costa al cliente le cartine, non il documento) — ma "il cliente riceve
    comunque qualcosa" vale solo se qualcuno si accorge che quel qualcosa è
    incompleto. Qui si traduce quel silenzio in una notifica.

    `counters` è lo stesso dizionario di contatori già restituito da
    /v1/pdf: nessuna logica nuova da tenere allineata, si legge quella che
    il servizio dichiara al chiamante.
    """
    missing = []
    if counters.get("guides_requested") and not counters.get("guides_generated"):
        missing.append("guide turistiche")
    if counters.get("guides_requested") and 0 < counters.get("guides_generated", 0) < counters["guides_requested"]:
        missing.append(
            f"guide turistiche parziali "
            f"({counters['guides_generated']}/{counters['guides_requested']})"
        )
    if not counters.get("day_maps_included"):
        missing.append("cartine delle giornate")
    if not counters.get("directions_included"):
        missing.append("come arrivare")
    if not counters.get("costs_included"):
        missing.append("stima dei costi")
    if not counters.get("tips_included"):
        missing.append("consigli dell'architetto")
    if not counters.get("place_cards_included"):
        missing.append("schede dei luoghi")
    if not counters.get("feedback_included"):
        missing.append("richiesta di recensione")
    if not missing:
        return False
    return notify(
        "pdf_degradato",
        "Il PDF è stato consegnato SENZA queste sezioni: " + ", ".join(missing),
        context=context,
        level=LEVEL_WARNING,
    )
