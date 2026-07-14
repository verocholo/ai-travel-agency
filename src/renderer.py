"""
NODO 10A — Rendering documento (versione semplificata per il prototipo).
Nel sistema reale questo diventa PDFMonkey/Google Docs (HTTP_MODULES_REALI.md
§NODO 10). Qui produciamo Markdown pulito, sufficiente per una revisione
umana della qualità dell'output prima di investire nel template grafico.
"""
from __future__ import annotations
from .affiliate_links import build_search_links
from .price_display import price_level_symbol


def _escape_markdown_link_text(text: str) -> str:
    """
    [AGGIUNTO 2026-07-11 — audit mirato sulla feature link multi-piattaforma,
    richiesto da Lorenzo ("facciamo il massimo, la qualità migliore")]
    Sfugge i caratteri che romperebbero la sintassi `[testo](url)` di
    Markdown se comparissero nel TESTO del link (non nell'URL, già protetto
    da url-encoding) — es. una destinazione scritta dal cliente come
    "Roma] (evil.com)[click qui" chiuderebbe prematuramente il testo del
    link e inietterebbe una falsa parentesi/bracket accanto all'URL reale,
    corrompendo il link renderizzato. Bug reale trovato ed eseguito da un
    audit mirato (non teorico) — vedi CHANGELOG.md.
    """
    for ch in ("[", "]", "(", ")"):
        text = text.replace(ch, f"\\{ch}")
    return text


def render_markdown(
    itinerary: dict, trip: dict, hotels: list[dict] | None = None, poi: list[dict] | None = None,
) -> str:
    """
    [AGGIORNATO 2026-07-11 — richiesta di prodotto di Lorenzo: link di
    ricerca multi-piattaforma] `hotels` è opzionale (default None, nessuna
    modifica per chi chiama questa funzione senza passarlo — vedi
    test_renderer.py esistenti) — se fornito (i dict di `Hotel.to_dict()`),
    aggiunge una sezione "Confronta anche su altre piattaforme" con link
    di ricerca PUBBLICA (non dati live, vedi affiliate_links.py per il
    razionale completo) verso Booking/Airbnb/Vrbo. Deliberatamente
    costruita in CODICE, non passata a Claude per essere ricopiata nel suo
    output JSON: un URL è una stringa esatta che un LLM potrebbe alterare/
    troncare, stesso principio di "mai far generare a Claude un dato che
    deve restare esattamente fedele" già seguito per gli id RAG.

    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo",
    "ristoranti"/"intrattenimenti"] `poi` è opzionale (default None) — se
    fornito (i dict di `POI.to_dict()`, già filtrati dal chiamante ai soli
    id EFFETTIVAMENTE usati nell'itinerario, vedi src/itinerary_utils.py),
    aggiunge una sezione "Ristoranti e intrattenimento (usati
    nell'itinerario)" con la fascia di prezzo se disponibile — stesso
    scopo delle sezioni curate del PDF cliente (pdf_renderer.py), qui in
    forma testuale per la revisione interna che questo modulo serve.
    """
    lines = []
    lines.append(f"# Itinerario Ottimizzato: {itinerary.get('destination', trip.get('destination'))}")
    lines.append("")
    budget_str = (
        "illimitato"
        if trip.get("budget_mode") == "UNLIMITED"
        else f"{trip.get('budget_eur')}€"
    )
    lines.append(
        f"*Profilo: {trip.get('objective_function')} · "
        f"{trip.get('date_start')} → {trip.get('date_end')} "
        f"({trip.get('duration_days')} giorni) · "
        f"Budget: {budget_str}*"
    )
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(itinerary.get("executive_summary", "[mancante]"))
    lines.append("")

    if itinerary.get("budget_alert"):
        lines.append(f"> ⚠️ **Avviso Budget:** {itinerary['budget_alert']}")
        lines.append("")

    if hotels:
        destination = trip.get("destination", "")
        date_start = trip.get("date_start", "")
        date_end = trip.get("date_end", "")
        # [CORRETTO 2026-07-11 — audit mirato] testo del link separato
        # dall'URL: `_escape_markdown_link_text()` sfugge `[`/`]`/`(`/`)`
        # SOLO nel testo visibile (destinazione/nome/tipo), non nell'URL
        # (già protetto da url-encoding in affiliate_links.py) — vedi il
        # docstring della funzione per il bug reale che questo previene.
        destination_text = _escape_markdown_link_text(destination)
        lines.append("## Confronta anche su altre piattaforme")
        lines.append("")
        lines.append(
            "_Link di ricerca pubblica (non dati live/prezzi verificati di queste "
            "piattaforme — vedi affiliate_links.py) — utili per confrontare l'opzione "
            "proposta con altre disponibili._"
        )
        lines.append("")
        for h in hotels:
            # [CORRETTO 2026-07-11 — audit mirato] `h.get("name", "[Da
            # Verificare]")` applica il default SOLO se la chiave manca,
            # non se è presente con valore `None` (bug reale trovato ed
            # eseguito: un hotel con `name=None` esplicito renderizzava
            # letteralmente "None" invece del placeholder onesto).
            name = h.get("name") or "[Da Verificare]"
            ptype = h.get("property_type") or "alloggio"
            price = h.get("price_night_eur")
            # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni
            # costo"] Prima disponibile solo internamente (mai mostrato,
            # nemmeno in questo strumento di revisione).
            price_text = f" — {price}€/notte" if price is not None else ""
            links = build_search_links(destination, date_start, date_end, hotel_name=name)
            name_text = _escape_markdown_link_text(name)
            ptype_text = _escape_markdown_link_text(ptype)
            lines.append(
                f"- **{name_text}** ({ptype_text}){price_text}: [cerca su Booking]({links['booking']}) · "
                f"[Airbnb per {destination_text}]({links['airbnb']}) · "
                f"[Vrbo per {destination_text}]({links['vrbo']})"
            )
        lines.append("")

    if poi:
        # [AGGIUNTO 2026-07-12] Stessa logica di raggruppamento delle
        # sezioni curate del PDF cliente (vedi
        # pdf_renderer.py::_render_curated_sections()) — qui in forma
        # testuale, includendo anche l'id (utile per audit/revisione
        # interna, a differenza del PDF cliente che non lo mostra mai).
        # [ESTESO 2026-07-13 (ter) — categoria shopping, stesso terzo
        # bucket aggiunto in pdf_renderer.py, per non disallineare questo
        # strumento di revisione interna dal documento cliente reale.]
        restaurants = [p for p in poi if p.get("type") == "restaurant"]
        shopping = [p for p in poi if p.get("type") == "shopping"]
        other = [p for p in poi if p.get("type") not in ("restaurant", "shopping")]
        if restaurants or shopping or other:
            lines.append("## Ristoranti e intrattenimento (usati nell'itinerario)")
            lines.append("")
        for label, items in (("Dove mangiare", restaurants), ("Shopping", shopping), ("Cosa fare", other)):
            if not items:
                continue
            lines.append(f"**{label}**")
            lines.append("")
            for p in items:
                symbol = price_level_symbol(p.get("price_level"))
                price_suffix = f" ({symbol})" if symbol else ""
                lines.append(f"- {p.get('name')}{price_suffix} `[{p.get('id')}]`")
            lines.append("")

    for day in itinerary.get("days", []):
        lines.append(f"## Giorno {day.get('day')} — {day.get('title', '')}")
        lines.append("")
        for block in day.get("blocks", []):
            poi_id = block.get("poi_id")
            # [CORRETTO 2026-07-11 — audit qualità pre-lancio] `if poi_id`
            # (truthy) trattava un poi_id="" (stringa vuota) come
            # equivalente a None, renderizzando "[SLOT LIBERO]" — mentre
            # validator.py/scenario_checks.py in tutto il resto del
            # prototipo usano la convenzione "solo None è sempre ok",
            # quindi un poi_id="" verrebbe corretamente segnalato da loro
            # come id non riconosciuto/allucinazione nello STESSO run. Con
            # il controllo truthy, il documento cliente nascondeva
            # silenziosamente proprio il problema che il Nodo 9 segnalava.
            # Ora coerente: solo `poi_id is None` significa "nessun POI".
            grounding = " `[SLOT LIBERO]`" if poi_id is None else f" `[{poi_id}]`"
            lines.append(
                f"- **{block.get('time')}** — {block.get('activity')} "
                f"({block.get('location', '')}){grounding}"
            )
            if block.get("logistics"):
                lines.append(f"  *{block['logistics']}*")
        lines.append("")

    if itinerary.get("architect_tips"):
        lines.append("## The Architect's Tips")
        lines.append("")
        for tip in itinerary["architect_tips"]:
            lines.append(f"- {tip}")
        lines.append("")

    return "\n".join(lines)
