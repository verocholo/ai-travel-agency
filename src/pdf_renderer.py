"""
NODO 10A (versione reale) — Rendering documento PDF.

[NUOVO 2026-07-11 — richiesta di Lorenzo: "facciamo tutto ciò che è
necessario per avere un prodotto ottimo, prima di andare su Make.com"]

Finora `src/renderer.py` produceva solo Markdown grezzo — sufficiente per
revisionare la qualità del CONTENUTO (executive summary, day-by-day,
grounding RAG), ma non rappresentativo di cosa riceverà davvero il
cliente finale: un documento impaginato. `HTTP_MODULES_REALI.md` §Nodo 10
raccomanda esplicitamente PDFMonkey con "template HTML/CSS con loop
Liquid" per il sistema reale su Make.com. Questo modulo costruisce
esattamente quel tipo di template — HTML/CSS autosufficiente, senza
dipendenze esterne (nessun CDN, nessun font remoto) — e lo converte in PDF
con `wkhtmltopdf`, uno strumento a riga di comando (non una libreria
Python) già presente in questo ambiente sandbox.

Doppio scopo deliberato:
1. Dare a Lorenzo un vero PDF da giudicare (non più un surrogato Markdown)
   prima di investire tempo nel wiring Make.com.
2. L'HTML prodotto qui è, di fatto, un riferimento di design diretto per
   il futuro template PDFMonkey (stesso loop day-by-day, stessa struttura
   a blocchi) — non solo un artefatto del prototipo, ma un documento di
   lavoro per la Fase 4.

**Nota di onestà, stesso principio già seguito altrove nel progetto**:
`wkhtmltopdf` è verificato presente e funzionante in QUESTO ambiente
sandbox (Linux) — non è mai stato verificato sul PC Windows di Lorenzo.
A differenza delle librerie Python del resto del prototipo (installabili
via `pip` in modo identico su qualunque sistema operativo), `wkhtmltopdf`
è un binario esterno che richiede un installer separato su Windows
(https://wkhtmltopdf.org/downloads.html). `render_pdf()` solleva un errore
esplicito e leggibile (non un crash criptico) se il binario non è
presente, con l'istruzione di installazione inclusa nel messaggio.
Lorenzo dovrà installarlo e verificare dal vivo sul suo PC prima di
considerare questa funzionalità "pronta", non solo "scritta".
"""
from __future__ import annotations

import base64
import html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .affiliate_links import build_search_links
from .price_display import price_level_symbol


class PdfRendererError(Exception):
    """Sollevata quando la generazione del PDF fallisce — sia per binario
    mancante (messaggio con istruzioni di installazione) sia per un
    fallimento reale di wkhtmltopdf (stderr incluso nel messaggio, non
    inghiottito)."""


# [AGGIUNTO 2026-07-11 — secondo audit adversariale, richiesta di Lorenzo
# "rendiamolo perfetto"] `wkhtmltopdf` usa un motore WebKit datato (~2014,
# pre-emoji-a-colori) che NON supporta i meccanismi Unicode più recenti per
# comporre emoji multi-codepoint. Verificato dal vivo in questo ambiente
# (rendering reale, non solo lettura di changelog di wkhtmltopdf): anche
# installando un font a colori (Noto Color Emoji, già presente in questo
# sandbox), le bandiere (coppie di "regional indicator symbol", es. 🇮🇹)
# vengono mostrate come due lettere in riquadro, e i modificatori di tono
# della pelle (es. 👍🏽) producono un glifo "tofu" (quadrato vuoto/pieno di
# puntini) visibilmente rotto accanto all'emoji base. Le emoji semplici a
# singolo codepoint (es. ⚠, ✅, 📄 — le uniche effettivamente usate nel
# template statico di questo modulo) restano invece leggibili (in stile
# monocromatico, non a colori, ma non rotte).
#
# Non è un bug risolvibile installando un font diverso — è un limite
# dell'engine di rendering stesso. La mitigazione realistica non è "farlo
# funzionare" ma "degradare in modo pulito": se testo generato da Claude
# (executive_summary, tips, note libere) dovesse mai contenere una di
# queste sequenze problematiche, rimuoviamo qui il modificatore/l'indicatore
# regionale PRIMA del rendering, così l'emoji base resta leggibile invece
# di mostrare un riquadro vuoto/rotto accanto. Non tenta di "riparare" la
# bandiera o la sequenza ZWJ (impossibile senza un motore di rendering
# diverso) — rimuove solo l'elemento che produce l'artefatto visibile.
_SKIN_TONE_MODIFIERS = re.compile("[\U0001F3FB-\U0001F3FF]")
_REGIONAL_INDICATORS = re.compile("[\U0001F1E6-\U0001F1FF]")


def _strip_broken_emoji_sequences(text: str) -> str:
    """Rimuove i soli codepoint Unicode che, verificato dal vivo, producono
    un glifo visibilmente rotto in wkhtmltopdf (modificatori di tono della
    pelle, indicatori regionali usati nelle bandiere). Le emoji semplici a
    singolo codepoint non vengono toccate — già leggibili."""
    text = _SKIN_TONE_MODIFIERS.sub("", text)
    text = _REGIONAL_INDICATORS.sub("", text)
    return text


def _esc(text) -> str:
    """Escape HTML di base per qualunque testo proveniente da dati
    esterni (destinazione, nomi hotel/POI, note del cliente, testo
    generato da Claude) — stesso principio già applicato in
    renderer.py per l'escaping Markdown: mai fidarsi di stringhe esterne
    iniettate direttamente in un formato con sintassi propria. Applica
    anche `_strip_broken_emoji_sequences()` per lo stesso motivo (testo
    esterno, mai fidarsi che sia "sicuro" per il motore di rendering di
    destinazione)."""
    if text is None:
        return ""
    return html.escape(_strip_broken_emoji_sequences(str(text)), quote=True)


# [CORRETTO 2026-07-12 — bug reale trovato ED ESEGUITO da Lorenzo, terzo
# giro sull'header del PDF] La causa REALE dei due round precedenti (testo
# "fantasma" con `opacity`, poi sparito del tutto col fix a `rgba()`) non
# era mai stata il colore del testo: il `linear-gradient` di `.header` non
# si renderizzava affatto sulla build wkhtmltopdf del PC Windows di
# Lorenzo, lasciando lo sfondo bianco (confermato con uno screenshot
# reale — testo chiaro quasi invisibile su bianco, non su blu scuro).
# Fix: sfondo a colore pieno e solido, niente più gradiente CSS —
# universalmente supportato anche dai motori di rendering più datati.
# Questo commento resta fuori dalla stringa `_CSS` qui sotto perché
# `test_header_uses_solid_background_color_no_gradient` verifica che le
# PAROLE "linear-gradient"/"opacity" non compaiano nell'HTML generato.
_CSS = """
    @page { size: A4; margin: 2cm 1.8cm; }
    * { box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #22303f;
      line-height: 1.5;
      margin: 0;
    }
    .header {
      background-color: #1a3b5c;
      color: #ffffff;
      padding: 28px 32px;
      border-radius: 10px;
      margin-bottom: 24px;
    }
    .header h1 { margin: 0 0 8px 0; font-size: 26px; }
    .header .meta { font-size: 13px; color: #d7e6f5; }
    .section-title {
      font-size: 16px;
      font-weight: bold;
      color: #1a3b5c;
      border-bottom: 2px solid #dfe7ee;
      padding-bottom: 6px;
      margin: 26px 0 12px 0;
    }
    .summary-box {
      background: #f4f7fa;
      border-left: 4px solid #2f6690;
      padding: 14px 18px;
      border-radius: 4px;
      font-size: 13px;
    }
    .budget-alert {
      background: #fdf1e8;
      border-left: 4px solid #c9762f;
      padding: 14px 18px;
      border-radius: 4px;
      font-size: 13px;
      margin-bottom: 8px;
    }
    .day-card {
      border: 1px solid #e2e8ef;
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 14px;
      page-break-inside: avoid;
    }
    .day-title { font-size: 15px; font-weight: bold; color: #1a3b5c; margin-bottom: 10px; }
    .block { padding: 8px 0; border-top: 1px solid #eef2f6; }
    .block:first-child { border-top: none; }
    .block-time { font-weight: bold; color: #2f6690; font-size: 12px; display: inline-block; min-width: 52px; }
    .block-activity { font-size: 13px; }
    .block-logistics { font-size: 11px; color: #6b7a89; font-style: italic; margin-top: 2px; }
    /* [AGGIUNTO 2026-07-13 (ter) — vedi _render_maps_link()] Link diretto
       alle coordinate reali del blocco, stile compatto coerente con
       .block-logistics (stessa gerarchia visiva: informazione di
       contorno, non il testo principale del blocco). */
    .block-maps-link { font-size: 11px; margin-top: 2px; }
    .block-maps-link a { color: #2f6690; text-decoration: none; }
    .tips-box {
      background: #eef6f0;
      border-left: 4px solid #3f8f5f;
      padding: 14px 18px;
      border-radius: 4px;
      font-size: 13px;
    }
    .tips-box ul { margin: 4px 0 0 0; padding-left: 18px; }
    .platforms-box { font-size: 12px; }
    .platforms-box .hotel-row { margin-bottom: 8px; }
    .platforms-box a {
      display: inline-block;
      font-size: 11px;
      color: #ffffff;
      background: #2f6690;
      padding: 3px 10px;
      border-radius: 4px;
      text-decoration: none;
      margin-right: 6px;
    }
    .disclaimer { font-size: 10px; color: #8a97a3; margin-top: 4px; }
    .footer { margin-top: 28px; font-size: 10px; color: #9aa6b1; text-align: center; }
    /* [CORRETTO 2026-07-13 (ter) — bug reale segnalato da Lorenzo su un
       PDF vero: "elimina ogni spazio a mo di capitolo di libro". Prima,
       `page-break-before: always` forzava OGNI guida turistica e il
       messaggio di feedback (vedi `_render_guide_section()`/
       `_render_feedback_section()`) a iniziare sempre su una pagina
       nuova, anche quando il contenuto della pagina precedente si
       fermava a metà — risultato: pagine quasi vuote in mezzo al
       documento, un "capitolo di libro" percepito come spreco di spazio
       più che come organizzazione. `page-break-inside: avoid` ottiene
       l'unico obiettivo che contava davvero (non spezzare a metà una
       guida/il feedback tra due pagine) senza sprecare spazio forzando
       comunque un salto pagina quando non serve — stesso principio già
       applicato a `.day-card` più sotto, non un'invenzione nuova.] */
    .page-break { page-break-inside: avoid; }
    /* [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "layout migliore/
       infografica, riassumere in una/due pagine"] Pagina di apertura
       "colpo d'occhio": stat tiles + mini-strip giorno-per-giorno +
       cartina. [CORRETTO 2026-07-13 (ter) — stesso fix di `.page-break`
       sopra: `page-break-after: always` forzava un salto pagina anche
       quando il contenuto di apertura era corto, lasciando spazio vuoto
       prima del day-by-day. `page-break-inside: avoid` evita solo che
       QUESTA sezione venga spezzata a metà, senza riservare comunque una
       pagina intera se non necessario.] */
    .at-a-glance-page { page-break-inside: avoid; }
    .stat-grid { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0; }
    .stat-tile {
      flex: 1 1 150px;
      background: #f4f7fa;
      border-left: 4px solid #2f6690;
      border-radius: 4px;
      padding: 10px 14px;
    }
    .stat-label { font-size: 10px; color: #6b7a89; text-transform: uppercase; letter-spacing: .04em; }
    .stat-value { font-size: 15px; font-weight: bold; color: #1a3b5c; margin-top: 2px; }
    .day-strip-item { padding: 5px 0; border-top: 1px solid #eef2f6; font-size: 12px; }
    .day-strip-item:first-child { border-top: none; }
    .map-image { text-align: center; margin: 16px 0 4px 0; }
    .map-image img { max-width: 100%; border-radius: 8px; border: 1px solid #e2e8ef; }
    /* [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "ristoranti/hotel/
       intrattenimento", "segnare ogni costo"] */
    .curated-item { padding: 6px 0; border-top: 1px solid #eef2f6; font-size: 13px; }
    .curated-item:first-child { border-top: none; }
    .price-badge { color: #2f6690; font-weight: bold; margin-left: 6px; font-size: 11px; }
    /* [AGGIUNTO 2026-07-13 — audit di revisione completa, miglioramento
       di prodotto richiesto esplicitamente da Lorenzo: "grafico di
       contenuto... per rendere il lavoro ancor più completo"]
       [SOSTITUITO 2026-07-13 (bis) — bug reale trovato da Lorenzo su un
       PDF vero: la versione originale codificava l'unica informazione
       leggibile (l'orario e il livello) SOLO nell'attributo HTML `title`
       di ogni pallino — un tooltip che appare al passaggio del mouse in
       un browser, ma che NON esiste in un documento PDF statico. Il
       cliente vedeva pallini colorati muti, senza alcun modo di sapere a
       quale blocco si riferisse ciascuno. Sostituito con un "chip"
       testuale visibile, agganciato direttamente al blocco a cui si
       riferisce — nessuna informazione nascosta in un attributo che il
       formato di output finale non può mostrare. Vedi
       `_render_energy_chip()` sotto.] */
    .energy-chip {
      display: inline-block;
      font-size: 10px;
      font-weight: bold;
      color: #ffffff;
      padding: 1px 8px;
      border-radius: 9px;
      margin-left: 6px;
      vertical-align: middle;
    }
    .energy-chip.energy-high { background: #b23a3a; }
    .energy-chip.energy-medium { background: #c9762f; }
    .energy-chip.energy-low { background: #3f8f5f; }
    .energy-legend { font-size: 10px; color: #6b7a89; margin: -6px 0 16px 0; }
    .energy-legend .energy-chip { margin-left: 0; margin-right: 10px; }
"""


# [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "aggiungerli al pdf che si
# genera", chiarita con "Voglio tutti e tre nello stesso PDF"] Prima,
# guida turistica (`--guide`), affinamento (`--refine`) e feedback
# post-viaggio (`--feedback`) producevano solo file .md separati, mai
# incorporati nel PDF cliente vero e proprio (src/pdf_renderer.py). Queste
# due funzioni rendono guida/feedback come sezioni HTML autonome, ognuna
# su una nuova pagina (`.page-break`, vedi _CSS sopra) cosi non si
# mescolano visivamente con i day-card dell'itinerario — riusano le
# stesse classi CSS già definite per il resto del documento
# (`.section-title`, `.summary-box`, `.tips-box`, `.disclaimer`) invece
# di introdurne di nuove, per coerenza visiva con il resto del PDF.
def _render_guide_section(guide: dict) -> str:
    """Rende una guida turistica per un singolo POI (schema completo in
    guide_generator.py: title, poi_name, history_summary, practical_tips,
    best_time_to_visit, estimated_visit_duration, consiglio_personalizzato,
    disclaimer) come sezione del PDF."""
    tips = "".join(f"<li>{_esc(t)}</li>" for t in guide.get("practical_tips", []))
    title = guide.get("title") or guide.get("poi_name", "")
    return (
        "<div class='page-break'>"
        f"<div class='section-title'>Guida turistica: {_esc(title)}</div>"
        f"<div class='summary-box'>{_esc(guide.get('history_summary', ''))}</div>"
        f"<div class='tips-box'><strong>Consigli pratici</strong><ul>{tips}</ul></div>"
        f"<div class='summary-box'><strong>Quando visitare:</strong> "
        f"{_esc(guide.get('best_time_to_visit', ''))}<br>"
        f"<strong>Durata consigliata della visita:</strong> "
        f"{_esc(guide.get('estimated_visit_duration', ''))}</div>"
        f"<div class='summary-box'><strong>Consiglio su misura per te:</strong> "
        f"{_esc(guide.get('consiglio_personalizzato', ''))}</div>"
        f"<div class='disclaimer'>{_esc(guide.get('disclaimer', ''))}</div>"
        "</div>"
    )


def _render_feedback_section(feedback: dict) -> str:
    """Rende il messaggio di feedback post-viaggio (schema completo in
    feedback_generator.py: intro_message, questions, testimonial_request,
    closing_message) come sezione finale del PDF."""
    questions = "".join(f"<li>{_esc(q)}</li>" for q in feedback.get("questions", []))
    return (
        "<div class='page-break'>"
        "<div class='section-title'>Facci sapere com'è andata</div>"
        f"<div class='summary-box'>{_esc(feedback.get('intro_message', ''))}</div>"
        f"<div class='tips-box'><ul>{questions}</ul></div>"
        f"<div class='summary-box'>{_esc(feedback.get('testimonial_request', ''))}</div>"
        f"<div class='summary-box'>{_esc(feedback.get('closing_message', ''))}</div>"
        "</div>"
    )


def _render_at_a_glance(itinerary: dict, trip: dict, hotels: list[dict] | None, map_png_bytes: bytes | None) -> str:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "layout migliore/
    infografica, riassumere tutto in una/due pagine"] Pagina di apertura
    "a colpo d'occhio": stat tiles (destinazione/date/durata/budget/
    alloggio) + mini-strip giorno-per-giorno (solo il titolo di ogni
    giorno, non il dettaglio) + cartina (se disponibile). Il day-by-day
    completo che segue resta identico, invariato — questa è una sintesi
    aggiuntiva in apertura, non una sostituzione del dettaglio.

    Interpretazione scelta (dichiarata a Lorenzo in chat, non ovvia dalla
    richiesta originale): una pagina di sintesi PRIMA del giorno-per-
    giorno completo, non una compressione dell'intero documento a scapito
    del dettaglio già esistente.
    """
    budget_str = (
        "Illimitato"
        if trip.get("budget_mode") == "UNLIMITED"
        else f"{_esc(trip.get('budget_eur'))}€"
    )
    tiles = [
        ("Destinazione", itinerary.get("destination", trip.get("destination"))),
        ("Date", f"{trip.get('date_start')} → {trip.get('date_end')}"),
        ("Durata", f"{trip.get('duration_days')} giorni"),
        ("Budget", budget_str),
    ]
    if hotels:
        first_hotel_name = hotels[0].get("name") or "[Da Verificare]"
        tiles.append(("Alloggio", first_hotel_name))

    parts = ["<div class='at-a-glance-page'>"]
    parts.append("<div class='section-title'>Il tuo viaggio, a colpo d'occhio</div>")
    parts.append("<div class='stat-grid'>")
    for label, value in tiles:
        parts.append(
            f"<div class='stat-tile'><div class='stat-label'>{_esc(label)}</div>"
            f"<div class='stat-value'>{_esc(value)}</div></div>"
        )
    parts.append("</div>")

    days = itinerary.get("days", [])
    if days:
        parts.append("<div class='section-title'>In breve, giorno per giorno</div>")
        for day in days:
            parts.append(
                f"<div class='day-strip-item'><strong>Giorno {_esc(day.get('day'))}</strong> — "
                f"{_esc(day.get('title', ''))}</div>"
            )

    if map_png_bytes:
        b64 = base64.b64encode(map_png_bytes).decode("ascii")
        parts.append("<div class='section-title'>La tua mappa</div>")
        parts.append(
            f"<div class='map-image'><img src='data:image/png;base64,{b64}' "
            f"alt='Cartina con hotel, tappe e percorsi'></div>"
        )
        parts.append(
            "<div class='disclaimer'>I percorsi mostrati sono linee indicative tra le "
            "coordinate reali di alloggio e tappe — non un percorso di guida calcolato "
            "(orari/modalità di spostamento reali sono nel dettaglio giorno-per-giorno).</div>"
        )

    parts.append("</div>")
    return "".join(parts)


def _render_curated_sections(poi: list[dict] | None) -> str:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "ristoranti", "intrattenimenti
    vari (parchi a tema, musei) in funzione del tipo di vacanza"] Tre
    sezioni curate — "Dove mangiare" (type == "restaurant"), "Shopping"
    (type == "shopping", [AGGIUNTO 2026-07-13 (ter) — categoria shopping,
    confermata come miglioramento generale di prodotto via
    AskUserQuestion] vedi src/places_client.py::_SHOPPING_TYPES) e "Cosa
    fare" (tutto il resto: museum/activity) — costruite dai SOLI POI
    effettivamente usati nell'itinerario (`poi`, già filtrato dal
    chiamante con `src/itinerary_utils.py::extract_used_poi_ids()` — mai
    l'intero DATI_API_FORNITI, stessa Fedeltà RAG del resto del sistema:
    un elenco di "consigli" che include POI mai scelti da Claude per
    quell'itinerario sarebbe fuorviante). Mostra la fascia di prezzo
    (`price_level`, vedi src/price_display.py) quando disponibile — mai
    un simbolo inventato per un dato assente.
    """
    if not poi:
        return ""
    restaurants = [p for p in poi if p.get("type") == "restaurant"]
    shopping = [p for p in poi if p.get("type") == "shopping"]
    other = [p for p in poi if p.get("type") not in ("restaurant", "shopping")]

    def _render_list(items: list[dict]) -> str:
        rows = []
        for p in items:
            symbol = price_level_symbol(p.get("price_level"))
            badge = f"<span class='price-badge'>{_esc(symbol)}</span>" if symbol else ""
            rows.append(f"<div class='curated-item'>{_esc(p.get('name'))}{badge}</div>")
        return "".join(rows)

    parts = []
    if restaurants:
        parts.append("<div class='section-title'>Dove mangiare</div>")
        parts.append(_render_list(restaurants))
    if shopping:
        parts.append("<div class='section-title'>Shopping</div>")
        parts.append(_render_list(shopping))
    if other:
        parts.append("<div class='section-title'>Cosa fare</div>")
        parts.append(_render_list(other))
    return "".join(parts)


# [AGGIUNTO 2026-07-13 — audit di revisione completa, richiesta esplicita
# di Lorenzo: "aggiungi qualsiasi tipo di miglioramento: grafico di
# contenuto... per rendere il lavoro ancor più completo"] Indicatore
# visivo del ritmo energetico di ogni blocco (vedi CSS `.energy-chip`
# sopra). `ApiPayload.poi[].energy_tag` è un campo REALE già raccolto e
# già usato dal Nodo 9 per la validazione strutturale del pacing
# energetico (`validator.py::check_energy_pacing`) — finora esisteva solo
# come regola interna di qualità, MAI mostrato al cliente. Renderlo
# visibile chiude il cerchio tra la promessa di prodotto
# (objective_function=ENERGY_PACING, vedi SYSTEM_PROMPT_MASTER.md) e cosa
# il cliente vede davvero nel documento finale.
#
# [SOSTITUITO 2026-07-13 (bis) — bug reale trovato da Lorenzo leggendo un
# vero PDF generato: la prima versione mostrava un pallino per blocco in
# una barra separata in cima alla giornata, con l'unico testo leggibile
# (orario + livello) chiuso in un attributo `title` — un tooltip HTML che
# esiste solo in un browser interattivo. In un PDF statico (l'unico
# formato che il cliente riceve davvero) restava un pallino muto: colorato
# ma senza alcun modo di sapere a quale blocco si riferisse. Corretto
# eliminando la barra separata e mostrando un chip testuale (colore +
# etichetta "energia alta/media/bassa" sempre visibile, non in un
# attributo) attaccato direttamente al blocco che descrive — nessuna
# informazione che dipende da un'interazione (hover) impossibile su carta
# o PDF.
_ENERGY_CHIP_CLASS = {"HIGH": "energy-high", "MEDIUM": "energy-medium", "LOW": "energy-low"}
_ENERGY_CHIP_LABEL = {"HIGH": "energia alta", "MEDIUM": "energia media", "LOW": "energia bassa"}


def _build_poi_energy_lookup(poi: list[dict] | None) -> dict[str, str]:
    """Mappa poi_id -> energy_tag, costruita SOLO dai POI realmente
    forniti in `poi` (stessa fonte già usata da `_render_curated_sections()`)
    — mai un tag energetico inventato per un id non presente nei dati
    reali (stessa Fedeltà RAG del resto del progetto)."""
    if not poi:
        return {}
    return {p.get("id"): p.get("energy_tag") for p in poi if p.get("id")}


def _render_energy_chip(poi_id: str | None, poi_energy: dict[str, str]) -> str:
    """Chip testuale (colore + etichetta sempre visibile) per UN singolo
    blocco, se il suo `poi_id` ha un `energy_tag` reale e riconosciuto
    (HIGH/MEDIUM/LOW). Blocchi senza `poi_id` (check-in hotel,
    `[SLOT LIBERO]`) o con un id sconosciuto/tag non riconosciuto
    ricevono semplicemente NESSUN chip — mai un dato inventato per
    un'assenza (stesso principio già applicato in maps_static.py/
    renderer.py)."""
    tag = poi_energy.get(poi_id)
    css_class = _ENERGY_CHIP_CLASS.get(tag)
    if css_class is None:
        return ""
    label = _ENERGY_CHIP_LABEL[tag]
    return f"<span class='energy-chip {css_class}'>{_esc(label)}</span>"


def _itinerary_has_any_energy_info(itinerary: dict, poi_energy: dict[str, str]) -> bool:
    """Vero se ALMENO un blocco di QUALSIASI giorno mostrerà davvero un
    chip energetico — usato per decidere se mostrare la legenda una sola
    volta. Senza questo controllo, un `poi` con solo `energy_tag` non
    riconosciuti (valore inatteso, non HIGH/MEDIUM/LOW) farebbe comparire
    la legenda senza che nessun chip venga poi mostrato davvero da
    nessuna parte nel documento — una legenda "orfana"."""
    for day in itinerary.get("days", []) or []:
        for block in day.get("blocks", []) or []:
            tag = poi_energy.get(block.get("poi_id"))
            if _ENERGY_CHIP_CLASS.get(tag) is not None:
                return True
    return False


def _render_energy_legend() -> str:
    """Legenda compatta, mostrata una sola volta (prima del day-by-day)
    solo se almeno un chip comparirà davvero nel documento — vedi il
    controllo `if poi_energy` nel chiamante."""
    return (
        "<div class='energy-legend'>"
        "<span class='energy-chip energy-high'>energia alta</span>"
        "<span class='energy-chip energy-medium'>energia media</span>"
        "<span class='energy-chip energy-low'>energia bassa</span>"
        "— ritmo energetico di ciascuna attività"
        "</div>"
    )


# [AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "link maps risultano
# un po' dispersivi", confermata come miglioramento di prodotto generale
# (non specifico al suo viaggio) via AskUserQuestion] Prima, il documento
# non offriva alcun modo diretto di aprire la posizione di un blocco su
# una mappa — il cliente doveva copiare a mano il nome del luogo in
# Google Maps e sperare che il risultato corrispondesse davvero al POI
# scelto da Claude. Qui costruiamo un link diretto alle coordinate REALI
# già presenti in `DATI_API_FORNITI` (mai un indirizzo indovinato/
# geocodificato di nuovo) — stessa Fedeltà RAG di tutto il resto del
# documento: se le coordinate non sono disponibili per un dato poi_id
# (id sconosciuto, hotel/poi non passato al renderer), nessun link viene
# mostrato, mai un link costruito sul solo nome (che potrebbe risolvere
# su un luogo omonimo diverso). Non richiede alcuna chiave API: il
# formato pubblico `google.com/maps/search/?api=1&query=lat,lng` è
# documentato e stabile (Google Maps URLs API), utilizzabile anche senza
# Google Maps Static/Places configurato.
def _build_location_lookup(
    hotels: list[dict] | None, poi: list[dict] | None
) -> dict[str, tuple[float, float]]:
    """Mappa poi_id -> (lat, lng), costruita SOLO dagli hotel/POI
    realmente passati al renderer (stessa fonte già usata da
    `_build_poi_energy_lookup()`/`_render_curated_sections()`) — mai una
    coordinata inventata per un id non presente nei dati reali."""
    lookup: dict[str, tuple[float, float]] = {}
    for h in hotels or []:
        hid = h.get("id")
        lat, lng = h.get("lat"), h.get("lng")
        if hid and lat is not None and lng is not None:
            lookup[hid] = (lat, lng)
    for p in poi or []:
        pid = p.get("id")
        lat, lng = p.get("lat"), p.get("lng")
        if pid and lat is not None and lng is not None:
            lookup[pid] = (lat, lng)
    return lookup


def _render_maps_link(poi_id: str | None, location_lookup: dict[str, tuple[float, float]]) -> str:
    """Link 'apri su Google Maps' per UN blocco, se le sue coordinate
    reali sono note. Nessun link per blocchi senza `poi_id` (check-in
    generico, `[SLOT LIBERO]`) o il cui id non è tra gli hotel/POI
    realmente forniti al renderer."""
    if not poi_id:
        return ""
    coords = location_lookup.get(poi_id)
    if coords is None:
        return ""
    lat, lng = coords
    url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    return f"<div class='block-maps-link'><a href='{_esc(url)}'>🗺️ Apri su Google Maps</a></div>"


def render_html(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None = None,
    guides: list[dict] | None = None,
    feedback: dict | None = None,
    poi: list[dict] | None = None,
    map_png_bytes: bytes | None = None,
) -> str:
    """
    Funzione pura (nessuna chiamata di rete/subprocess) — costruisce
    l'HTML/CSS autosufficiente del documento cliente. Separata da
    `render_pdf()` così può essere testata (e ispezionata visivamente,
    es. aprendola in un browser) senza dover invocare wkhtmltopdf.

    [AGGIUNTO 2026-07-12] `guides` (lista di guide turistiche per singolo
    POI, vedi guide_generator.py) e `feedback` (messaggio di follow-up
    post-viaggio, vedi feedback_generator.py) sono entrambi opzionali
    (default None/[]): un PDF senza queste sezioni resta identico a prima
    di questa modifica — nessuna rottura per i chiamanti esistenti.

    [AGGIUNTI 2026-07-12 — richiesta di Lorenzo di potenziare il documento]
    `poi` (lista di POI EFFETTIVAMENTE usati nell'itinerario, già
    filtrati dal chiamante — vedi `_render_curated_sections()`) e
    `map_png_bytes` (PNG già scaricato da `src/maps_static.py`) sono
    entrambi opzionali (default None): un PDF senza questi dati resta
    funzionante, semplicemente senza le sezioni corrispondenti — nessuna
    rottura per i chiamanti esistenti (es. test_pdf_renderer.py esistenti
    che non li passano).
    """
    destination = _esc(itinerary.get("destination", trip.get("destination")))
    budget_str = (
        "illimitato"
        if trip.get("budget_mode") == "UNLIMITED"
        else f"{_esc(trip.get('budget_eur'))}€"
    )
    meta = (
        f"{_esc(trip.get('objective_function'))} · "
        f"{_esc(trip.get('date_start'))} → {_esc(trip.get('date_end'))} "
        f"({_esc(trip.get('duration_days'))} giorni) · Budget: {budget_str}"
    )

    parts = [
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>",
        f"<style>{_CSS}</style></head><body>",
        "<div class='header'>",
        f"<h1>Itinerario Ottimizzato: {destination}</h1>",
        f"<div class='meta'>{meta}</div>",
        "</div>",
        _render_at_a_glance(itinerary, trip, hotels, map_png_bytes),
        "<div class='section-title'>Executive Summary</div>",
        f"<div class='summary-box'>{_esc(itinerary.get('executive_summary', '[mancante]'))}</div>",
    ]

    if itinerary.get("budget_alert"):
        parts.append(
            f"<div class='budget-alert'><strong>⚠ Avviso Budget:</strong> "
            f"{_esc(itinerary['budget_alert'])}</div>"
        )

    if hotels:
        destination_raw = trip.get("destination", "")
        date_start = trip.get("date_start", "")
        date_end = trip.get("date_end", "")
        parts.append("<div class='section-title'>Il tuo alloggio</div>")
        for h in hotels:
            name = h.get("name") or "[Da Verificare]"
            ptype = h.get("property_type") or "alloggio"
            price = h.get("price_night_eur")
            # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni
            # costo"] Il prezzo/notte era già calcolato/disponibile da
            # LiteAPI ma non veniva mai mostrato al cliente finale prima
            # d'ora — solo il budget totale dichiarato compariva nel meta
            # dell'header.
            price_str = f" · {price}€/notte" if price is not None else ""
            parts.append(
                f"<div class='hotel-row'><strong>{_esc(name)}</strong> "
                f"({_esc(ptype)}{_esc(price_str)})</div>"
            )
        parts.append(
            "<div class='disclaimer'>Confronta anche su altre piattaforme — link di ricerca "
            "pubblica (non dati live/prezzi verificati di queste piattaforme):</div>"
        )
        parts.append("<div class='platforms-box'>")
        for h in hotels:
            name = h.get("name") or "[Da Verificare]"
            links = build_search_links(destination_raw, date_start, date_end, hotel_name=name)
            parts.append(
                f"<div class='hotel-row'>"
                f"<a href='{links['booking']}'>Cerca su Booking</a>"
                f"<a href='{links['airbnb']}'>Airbnb</a>"
                f"<a href='{links['vrbo']}'>Vrbo</a></div>"
            )
        parts.append("</div>")

    parts.append(_render_curated_sections(poi))

    poi_energy = _build_poi_energy_lookup(poi)
    if poi_energy and _itinerary_has_any_energy_info(itinerary, poi_energy):
        parts.append(_render_energy_legend())

    location_lookup = _build_location_lookup(hotels, poi)

    for day in itinerary.get("days", []):
        blocks = day.get("blocks", [])
        # [FIX 2026-07-11 — secondo audit adversariale, richiesta di
        # Lorenzo "rendiamolo perfetto"] Un `.day-card` con `page-break-
        # inside: avoid` funziona bene finché il contenuto sta in una
        # pagina A4 — verificato con gli itinerari reali testati finora
        # (fino a 30 giorni × 10 blocchi). Ma se un giorno anomalo avesse
        # MOLTI blocchi (es. ~60), il contenuto supera l'altezza di una
        # pagina e wkhtmltopdf non può più "evitare" l'interruzione: la
        # spezza a metà, e siccome il titolo del giorno è dentro la STESSA
        # card, non si ripete nella pagina di continuazione — un lettore
        # che apre quella pagina non sa più di che giorno si tratta.
        # Non esiste un modo puramente CSS di "ripetere un'intestazione ad
        # ogni pagina" affidabile nel motore di stampa datato di
        # wkhtmltopdf — la mitigazione reale è strutturale: se un giorno
        # supera questa soglia, lo spezziamo qui in più `.day-card`
        # consecutive, ciascuna con il proprio titolo (le successive
        # marcate "(continua)"), così ogni card resta ragionevolmente
        # piccola e il titolo compare comunque vicino a ogni gruppo di
        # blocchi, invece di sparire del tutto in un'unica card enorme.
        _MAX_BLOCKS_PER_DAY_CARD = 20
        chunks = [
            blocks[i : i + _MAX_BLOCKS_PER_DAY_CARD]
            for i in range(0, len(blocks), _MAX_BLOCKS_PER_DAY_CARD)
        ] or [[]]

        for chunk_index, chunk in enumerate(chunks):
            parts.append("<div class='day-card'>")
            suffix = " (continua)" if chunk_index > 0 else ""
            parts.append(
                f"<div class='day-title'>Giorno {_esc(day.get('day'))} — "
                f"{_esc(day.get('title', ''))}{suffix}</div>"
            )
            for block in chunk:
                # [DELIBERATO] Il `poi_id` (mostrato invece come `[POI1]`/
                # `[SLOT LIBERO]` in renderer.py) è un marcatore interno di
                # audit/grounding per la revisione qualità (Nodo 9) — non ha
                # senso in un documento cliente premium, quindi qui NON viene
                # mostrato. Questo PDF è il documento finale per il cliente,
                # non lo strumento di revisione interna che è invece
                # renderer.py (Markdown).
                energy_chip = _render_energy_chip(block.get("poi_id"), poi_energy) if poi_energy else ""
                parts.append(
                    "<div class='block'>"
                    f"<span class='block-time'>{_esc(block.get('time'))}</span> "
                    f"<span class='block-activity'>{_esc(block.get('activity'))} "
                    f"({_esc(block.get('location', ''))})</span>"
                    f"{energy_chip}"
                )
                if block.get("logistics"):
                    parts.append(f"<div class='block-logistics'>{_esc(block['logistics'])}</div>")
                parts.append(_render_maps_link(block.get("poi_id"), location_lookup))
                parts.append("</div>")
            parts.append("</div>")

    if itinerary.get("architect_tips"):
        parts.append("<div class='section-title'>The Architect's Tips</div>")
        parts.append("<div class='tips-box'><ul>")
        for tip in itinerary["architect_tips"]:
            parts.append(f"<li>{_esc(tip)}</li>")
        parts.append("</ul></div>")

    if guides:
        for guide in guides:
            parts.append(_render_guide_section(guide))

    if feedback:
        parts.append(_render_feedback_section(feedback))

    parts.append(
        "<div class='footer'>Documento generato automaticamente — verificare sempre orari "
        "di apertura e disponibilità prima della partenza.</div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def render_pdf(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None = None,
    guides: list[dict] | None = None,
    feedback: dict | None = None,
    poi: list[dict] | None = None,
    map_png_bytes: bytes | None = None,
    output_path: str | None = None,
) -> str:
    """
    Converte l'HTML di `render_html()` in un vero file PDF usando
    `wkhtmltopdf` (binario esterno, non una libreria Python — vedi la
    nota di onestà nel docstring del modulo). Ritorna il path del PDF
    generato.

    Solleva `PdfRendererError` con un messaggio ESPLICITO (non un
    traceback criptico di `subprocess`) se:
    - `itinerary` o `trip` sono `None` (guardia esplicita — senza questo
      controllo `render_html()` solleverebbe un `AttributeError` criptico
      su `.get()`, invece del messaggio chiaro previsto per ogni altro
      fallimento di questa funzione);
    - `wkhtmltopdf` non è installato (`FileNotFoundError` intercettato,
      messaggio con link all'installer per Windows/macOS/Linux);
    - `wkhtmltopdf` è installato ma fallisce davvero (returncode != 0 —
      lo stderr reale viene incluso nel messaggio, mai inghiottito in
      silenzio);
    - `wkhtmltopdf` ritorna successo (returncode 0) ma non ha effettivamente
      creato un file PDF non vuoto — [FIX 2026-07-11, trovato da audit
      adversariale] in alcuni scenari (es. directory di destinazione senza
      permessi di scrittura) wkhtmltopdf può terminare con exit code 0 senza
      aver scritto nulla, il che altrimenti si propagherebbe come un falso
      "successo" fino a `main.py`.

    **Scrittura atomica** [FIX 2026-07-11, trovato da audit adversariale]:
    la generazione avviene su un file temporaneo univoco nella stessa
    directory di `output_path`, poi viene spostata con `os.replace()` (atomica
    su POSIX e Windows) solo a generazione riuscita. Prima di questo fix,
    scritture concorrenti/rapide sullo stesso `output_path` (es. run ripetuti
    con lo stesso nome file) potevano corrompersi a vicenda — riprodotto con
    un vero stress test multiprocessing durante l'audit.
    """
    if itinerary is None or trip is None:
        raise PdfRendererError(
            "render_pdf() ha ricevuto itinerary=None o trip=None — impossibile "
            "generare un PDF senza un itinerario valido. Questo indica un bug "
            "a monte (es. una pipeline fallita il cui risultato viene comunque "
            "passato qui): verificare che il chiamante controlli l'esito della "
            "pipeline prima di invocare render_pdf()."
        )

    if shutil.which("wkhtmltopdf") is None:
        raise PdfRendererError(
            "wkhtmltopdf non è installato o non è nel PATH di sistema. "
            "È un programma esterno (non una libreria Python 'pip install'), "
            "va installato separatamente: https://wkhtmltopdf.org/downloads.html "
            "(su Windows: scarica l'installer .exe dalla pagina, poi riavvia il terminale)."
        )

    html_content = render_html(
        itinerary, trip, hotels=hotels, guides=guides, feedback=feedback,
        poi=poi, map_png_bytes=map_png_bytes,
    )

    if output_path is None:
        output_path = tempfile.mktemp(suffix=".pdf")

    output_dir = Path(output_path).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp_html:
        tmp_html.write(html_content)
        tmp_html_path = tmp_html.name

    # File temporaneo univoco (non `output_path` direttamente) nella STESSA
    # directory di destinazione: `os.replace()` è atomico solo se sorgente e
    # destinazione sono sullo stesso filesystem, quindi non basta usare
    # `tempfile.gettempdir()` se `output_path` è altrove.
    tmp_pdf_fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf.tmp", dir=str(output_dir))
    os.close(tmp_pdf_fd)

    try:
        result = subprocess.run(
            ["wkhtmltopdf", "--quiet", tmp_html_path, tmp_pdf_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise PdfRendererError(
                f"wkhtmltopdf ha fallito (exit code {result.returncode}): "
                f"{result.stderr.strip() or '[nessun dettaglio su stderr]'}"
            )

        generated = Path(tmp_pdf_path)
        if not generated.exists() or generated.stat().st_size == 0:
            raise PdfRendererError(
                "wkhtmltopdf ha terminato con successo (exit code 0) ma non ha "
                "prodotto un file PDF valido (file mancante o vuoto). Possibili "
                "cause: permessi di scrittura insufficienti sulla directory di "
                "destinazione, disco pieno, o un problema di rendering non "
                "segnalato su stderr. Verificare i permessi della directory "
                f"'{output_dir}'."
            )

        os.replace(tmp_pdf_path, output_path)
    finally:
        Path(tmp_html_path).unlink(missing_ok=True)
        # Se `os.replace()` è già avvenuto, il file temporaneo non esiste più
        # a questo path — `missing_ok=True` evita un errore spurio in quel
        # caso normale (successo), pulendo solo nei casi di fallimento.
        Path(tmp_pdf_path).unlink(missing_ok=True)

    return output_path
