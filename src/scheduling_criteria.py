"""
Il CRITERIO con cui e' costruita una giornata — dichiarato al cliente e
verificato in Python.

[AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «dare un criterio alla
programmazione delle cose da vedere (minimizzare gli spostamenti, tenendo
conto degli orari di apertura delle strutture e le varie pause durante la
giornata)»]

Perche' questo modulo esiste, e perche' non basta una regola in piu' nel
prompt.

La richiesta ha due meta' che sembrano una sola. La prima e' che l'itinerario
SIA costruito con un criterio: quella si chiede al modello, ed e' finita nel
prompt ([HARD_CONSTRAINTS] punto 10). La seconda e' che il criterio si VEDA, e
soprattutto che si possa verificare — perche' un criterio che nessuno controlla
e' una promessa, e una promessa stampata su un documento pagato che poi non
regge e' peggio del silenzio.

Il pezzo che mancava davvero era piu' a monte di entrambe: gli orari di
apertura non arrivavano fin qui. Google li restituisce dentro
`regularOpeningHours`, campo che chiediamo (e paghiamo) a ogni ricerca di POI,
ma di quella risposta tenevamo solo l'insieme dei GIORNI e buttavamo via le
ore. Chiedere al modello di "tenere conto degli orari" era quindi chiedergli di
tenere conto di un dato che non aveva mai visto. Da oggi gli orari arrivano
(vedi `POI.open_hours`), e qui c'e' il controllo che li usa.

Cosa NON fa questo modulo: non riordina la giornata e non sposta i blocchi.
Riscrivere l'orario di una tappa dopo che il modello l'ha deciso significa
rompere gli incastri (spostamenti, pasti, prenotazioni) senza avere sotto mano
le ragioni per cui erano stati messi cosi'. Quando trova una tappa a porta
chiusa, il documento lo DICE accanto a quella tappa. Il cliente vede il
problema mentre puo' ancora rimediare, che e' l'unica cosa che gli serve
davvero.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta

# Vocabolario canonico dei giorni: lo stesso di `places_client._DOW_MAP` e di
# `temporal_filter._DOW_ORDER`. Tenerne tre copie diverse sarebbe il modo
# classico per far combaciare i lunedi' con i martedi'.
GIORNI = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Le tre righe che il documento stampa. Sono qui e non dentro il renderer
# perche' sono le stesse tre cose che il prompt chiede al modello: se un
# giorno divergessero, il documento dichiarerebbe un criterio diverso da
# quello applicato. Il test `test_criterio_2026_08_03.py` confronta questa
# costante con il testo del prompt e fallisce se si separano.
#
# ATTENZIONE alle lettere accentate. Nel resto di questo file — commenti,
# docstring, nomi — si scrive "perche'" con l'apostrofo, che e' la
# convenzione del progetto per il codice. Qui NO: queste stringhe non sono
# codice, sono testo che finisce stampato dentro un documento che il cliente
# paga 4,90 €, e "e' collocata" su una pagina venduta si legge come un
# refuso. [CORRETTO 2026-08-03, stesso giorno, guardando il campione
# rigenerato: le tre righe erano uscite con gli apostrofi.]
CRITERIO = (
    (
        "Meno spostamenti possibile",
        "le tappe di una giornata sono raggruppate per zona e messe in fila "
        "nell'ordine che accorcia il cammino, non nell'ordine in cui sono "
        "famose.",
    ),
    (
        "Orari di apertura veri",
        "ogni tappa è collocata in una fascia in cui il luogo risulta "
        "aperto secondo il suo orario dichiarato; dove l'orario non ci è "
        "stato fornito il documento lo scrive, invece di dare per scontato "
        "che sia aperto.",
    ),
    (
        "Le pause sono tappe anche loro",
        "pranzo, cena e il fiato tra un museo e l'altro sono blocchi "
        "programmati con un orario, non quello che avanza.",
    ),
)


def giorno_settimana(date_start, day_number) -> str | None:
    """"Mon".."Sun" della giornata N, oppure None se la data non c'e'.

    Stessa convenzione senza "+1" di `pdf_renderer._day_calendar_label()` e di
    `triage._date_difference_days()`: il giorno 1 E' `date_start`. Un modulo
    che contasse i giorni in modo diverso dagli altri due sposterebbe tutti
    gli orari di apertura di 24 ore, e sarebbe un errore invisibile — gli
    orari di un martedi' sono plausibilissimi anche di lunedi'.
    """
    if not date_start or day_number is None:
        return None
    try:
        base = _date.fromisoformat(str(date_start).strip()[:10])
        offset = int(day_number) - 1
    except (ValueError, TypeError):
        return None
    if offset < 0 or offset > 400:
        return None
    return GIORNI[(base + _timedelta(days=offset)).weekday()]


def _minuti(orario) -> int | None:
    """"HH:MM" -> minuti dalla mezzanotte. None se non e' un orario."""
    if not isinstance(orario, str):
        return None
    testo = orario.strip()[:5]
    if len(testo) != 5 or testo[2] != ":":
        return None
    try:
        ore, minuti = int(testo[:2]), int(testo[3:])
    except ValueError:
        return None
    if not (0 <= ore <= 23 and 0 <= minuti <= 59):
        return None
    return ore * 60 + minuti


def finestre_del_giorno(open_hours, giorno) -> list[list[str]]:
    """Le finestre di apertura di quel giorno, ripulite. [] se non si sanno."""
    if not isinstance(open_hours, dict) or not giorno:
        return []
    grezze = open_hours.get(giorno)
    if not isinstance(grezze, (list, tuple)):
        return []
    valide = []
    for finestra in grezze:
        if not isinstance(finestra, (list, tuple)) or len(finestra) != 2:
            continue
        inizio, fine = _minuti(finestra[0]), _minuti(finestra[1])
        if inizio is None or fine is None or fine <= inizio:
            continue
        valide.append([str(finestra[0])[:5], str(finestra[1])[:5]])
    return sorted(valide)


def stato_apertura(open_hours, giorno, orario) -> str:
    """"aperto" | "chiuso" | "ignoto" per una tappa a quell'ora, quel giorno.

    "ignoto" e "chiuso" sono deliberatamente distinti e nessuno dei due e'
    trattato come l'altro. Dire "chiuso" di un luogo di cui non conosciamo gli
    orari manderebbe il cliente a saltare una tappa aperta; dire "aperto" di
    un luogo di cui non sappiamo nulla e' la bugia che questo intero progetto
    esiste per non dire.
    """
    finestre = finestre_del_giorno(open_hours, giorno)
    if not finestre:
        return "ignoto"
    quando = _minuti(orario)
    if quando is None:
        return "ignoto"
    for inizio, fine in finestre:
        if _minuti(inizio) <= quando <= _minuti(fine):
            return "aperto"
    return "chiuso"


def descrivi_finestre(open_hours, giorno) -> str:
    """"09:00–19:00" oppure "09:00–13:00 e 15:00–19:00". "" se non si sanno."""
    finestre = finestre_del_giorno(open_hours, giorno)
    if not finestre:
        return ""
    pezzi = [f"{inizio}–{fine}" for inizio, fine in finestre]
    if len(pezzi) == 1:
        return pezzi[0]
    return " e ".join([", ".join(pezzi[:-1]), pezzi[-1]])


def verifica_giornata(blocks, poi_by_id, giorno) -> dict:
    """Le tappe di una giornata che cadono fuori dall'orario di apertura.

    Ritorna `{"<indice del blocco>": {"orario", "finestre", "nome"}}` per le
    sole tappe da segnalare: quelle di cui conosciamo gli orari E che
    risultano a porta chiusa. Tutto il resto (orari ignoti, tappe senza
    `poi_id`, blocchi senza ora) non produce nulla — un documento che
    segnalasse un dubbio accanto a meta' delle tappe insegnerebbe al cliente a
    ignorare le segnalazioni, che e' il modo piu' efficace di rendere inutile
    proprio quella che conta.
    """
    fuori: dict[int, dict] = {}
    if not giorno or not isinstance(poi_by_id, dict):
        return fuori
    for indice, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            continue
        # [CORRETTO 2026-08-03, stesso giorno] `poi_id` viene da un JSON
        # scritto dal modello e passa di qui PRIMA della validazione: il
        # renderer non e' protetto dal Nodo 9. Con `poi_id` uguale a una
        # lista, `dict.get()` alza TypeError ("unhashable type") e il
        # documento intero non esce — cioe' un campo sbagliato in una riga
        # farebbe perdere al cliente tutto il resto. Il test
        # `test_html_renderer_tolerates_null_blocks_and_days` lo ha trovato
        # subito, ed e' la ragione per cui esiste.
        poi_id = block.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        poi = poi_by_id.get(poi_id)
        if not isinstance(poi, dict):
            continue
        orari = poi.get("open_hours")
        orario = block.get("time")
        if stato_apertura(orari, giorno, orario) != "chiuso":
            continue
        fuori[indice] = {
            "orario": str(orario)[:5],
            "finestre": descrivi_finestre(orari, giorno),
            "nome": poi.get("name") or block.get("location") or "",
        }
    return fuori
