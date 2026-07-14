"""
NODO 2 — Triage & Normalizzazione. BLUEPRINT_MAKE.md §NODO 2.

Prende un JSON grezzo "stile Typeform" (vedi BLUEPRINT_MAKE.md §NODO 1 per
l'esempio) e produce un oggetto Trip pulito, deducendo objective_function
dallo "scopo" dichiarato dal cliente — stesso switch documentato, in
QUESTO ordine di priorità [RIORDINATO 2026-07-12 — vedi commento su
deduce_objective_function() per il bug reale che ha reso necessario
questo ordine]:

    "famiglia/bambini/anziani"      -> FRICTION_SAFETY (controllato per PRIMO: la sicurezza prevale)
    "torneo/allenamento/sport"      -> ENERGY_PACING
    "lavoro remoto/nomade digitale" -> WORK_CONNECTIVITY  [AGGIUNTO 2026-07-11]
    "anniversario/luxury"           -> EXCLUSIVITY_ZERO_FRICTION
    default                         -> BALANCED
"""
from __future__ import annotations
import re
from datetime import date
from .schemas import Trip

# [AGGIUNTO 2026-07-11 — revisione qualità pre-lancio] Bug reale trovato in
# audit: il matching precedente usava `keyword in s` (substring puro), che
# fa scattare falsi positivi quando la keyword è un prefisso di una parola
# non correlata — esempio concreto trovato: "gara" (keyword ENERGY_PACING)
# è una sottostringa di "garage" ("Cerco hotel con garage" veniva
# erroneamente dedotto come ENERGY_PACING). Fix: matching su confine di
# parola (`\b`) invece di substring puro. Alcune keyword sono PERÒ radici
# deliberate per intercettare più forme flesse (es. "bambin" per
# bambino/bambini/bambine, "anzian" per anziano/anziani/anziana,
# "sport" per sport/sportivo/sportiva/sportivi) — per queste il confine
# di parola è richiesto solo all'inizio, non alla fine, così il matching
# resta intenzionale e non si rompe la copertura esistente.
_STEM_KEYWORDS = {"bambin", "anzian", "infant", "sport"}


def _keyword_matches(text: str, keyword: str) -> bool:
    boundary_end = "" if keyword in _STEM_KEYWORDS else r"\b"
    pattern = r"\b" + re.escape(keyword) + boundary_end
    return re.search(pattern, text) is not None


def deduce_objective_function(scopo: str) -> str:
    s = (scopo or "").lower()
    # [CORRETTO 2026-07-12 — bug reale trovato in audit di qualità] Prima,
    # ENERGY_PACING veniva controllato PRIMA di FRICTION_SAFETY. Scenario
    # reale e plausibile per questo beachhead market (sport): "Vacanza
    # sportiva in famiglia con nonni anziani e bambini" contiene sia
    # "sport" sia "anzian"/"bambin" — con l'ordine precedente il primo
    # match vincente era "sport", quindi l'intero viaggio veniva
    # silenziosamente dedotto ENERGY_PACING, perdendo ogni protezione
    # FRICTION_SAFETY (finestre rigide, accessibilità, sicurezza
    # alimentare/motoria) per un viaggio con anziani/bambini a bordo.
    # `system_prompt_master.txt`, descrivendo il profilo FRICTION_SAFETY,
    # dice esplicitamente "La sicurezza ... prevale SEMPRE sull'ambizione
    # turistica": la priorità qui nel triage deve rispecchiare la stessa
    # gerarchia dichiarata nel prompt, non l'ordine in cui i rami erano
    # stati scritti in origine. Fix: FRICTION_SAFETY controllato per
    # primo, così un mix di parole chiave sport + famiglia/anziani/
    # bambini fa sempre vincere la sicurezza.
    if any(_keyword_matches(s, k) for k in ("famiglia", "bambin", "anzian", "mobilità ridotta", "infant")):
        return "FRICTION_SAFETY"
    # [AGGIUNTO 2026-07-11] "sport"/"sportiv-" mancava: una "Vacanza
    # sportiva" generica cadeva silenziosamente su BALANCED nonostante
    # ENERGY_PACING sia esattamente la lente di ottimizzazione per questo
    # caso (beachhead market).
    if any(_keyword_matches(s, k) for k in ("torneo", "allenamento", "training", "match", "gara", "sport")):
        return "ENERGY_PACING"
    # [AGGIUNTO 2026-07-11] Terzo modulo verticale (src/modules.py):
    # "lavoro_nomadi_digitali". A differenza di sport/famiglia, "lavoro"
    # prima non aveva NESSUN ramo dedicato — sarebbe finito silenziosamente
    # su BALANCED, senza una vera lente di ottimizzazione per chi deve
    # proteggere blocchi di lavoro fissi durante il viaggio.
    if any(_keyword_matches(s, k) for k in (
        "lavoro remoto", "smart working", "nomade digitale", "nomadi digitali",
        "coworking", "workation", "lavoro da remoto",
    )):
        return "WORK_CONNECTIVITY"
    # [AGGIUNTO 2026-07-11] "luna di miele" mancava: la frase italiana
    # standard per "honeymoon" (già presente solo in inglese) — un cliente
    # italiano che scrive "Viaggio di luna di miele" cadeva su BALANCED.
    if any(_keyword_matches(s, k) for k in ("anniversario", "luxury", "lusso", "honeymoon", "nozze", "luna di miele")):
        return "EXCLUSIVITY_ZERO_FRICTION"
    return "BALANCED"


def _date_difference_days(start: str, end: str) -> int:
    d1 = date.fromisoformat(start)
    d2 = date.fromisoformat(end)
    return (d2 - d1).days


def normalize_raw_input(raw: dict) -> Trip:
    """
    raw atteso nella forma semplificata (già estratta dal form_response
    Typeform, vedi fixtures/trip_happy_path.json per un esempio completo):

    {
      "email": "...",
      "scopo": "Torneo di tennis amatoriale",
      "destinazione": "Val d'Orcia, Toscana",
      "arrivo": "2026-09-12",
      "partenza": "2026-09-17",
      "budget": 0,
      "note": "privacy totale, niente folla"
    }
    """
    date_start = raw["arrivo"]
    date_end = raw["partenza"]
    budget = raw.get("budget", 0) or 0
    objective_function = deduce_objective_function(raw.get("scopo", ""))

    trip = Trip(
        email=raw["email"],
        destination=raw["destinazione"],
        date_start=date_start,
        date_end=date_end,
        duration_days=_date_difference_days(date_start, date_end),
        budget_eur=float(budget),
        budget_mode="UNLIMITED" if float(budget) == 0 else "LIMITED",
        objective_function=objective_function,
        raw_notes=raw.get("note", ""),
    )
    return trip
