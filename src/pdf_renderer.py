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
# [AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore"] Testi legali
# rivolti al cliente, tenuti in un solo posto: vedi src/legal_notices.py.
from . import legal_notices


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
    /* [CORRETTO 2026-07-31 — difetto grafico reale trovato ispezionando il
       PDF di esempio: `page-break-inside: avoid` QUI obbligava l'intero
       programma di una giornata (cartina + 6-8 blocchi + "Come arrivare")
       a stare tutto su una pagina sola. Quando non ci stava, wkhtmltopdf
       spostava il blocco intero alla pagina successiva lasciando ~metà
       pagina bianca dopo ogni cartina: 3 pagine su 14 sprecate. La regola
       "non spezzare" serve al singolo blocco orario (quello sì illeggibile
       se tagliato a metà fra due pagine), non alla giornata intera — per
       questo si sposta su `.block`. Il titolo della giornata non si perde:
       `_MAX_BLOCKS_PER_DAY_CARD` spezza le giornate lunghe in più card e
       ripete l'intestazione su ognuna, marcandola come continuazione.
       NB: la parola esatta usata per quel suffisso NON va scritta qui — i
       test di regressione la cercano nell'HTML prodotto e un commento la
       farebbe passare per una card di continuazione vera. */
    .day-card {
      border: 1px solid #e2e8ef;
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 14px;
    }
    .day-title { font-size: 15px; font-weight: bold; color: #1a3b5c; margin-bottom: 10px; }
    .block { padding: 8px 0; border-top: 1px solid #eef2f6; page-break-inside: avoid; }
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
    /* [AGGIUNTO 2026-08-01] Riquadro del link di risposta. E' una TABELLA,
       non un div, perche' page-break-inside: avoid regge sulle righe di
       tabella e non su un contenitore alto. La URL puo' essere lunga:
       word-wrap la spezza invece di farla uscire dal margine destro. */
    .cta-box {
      width: 100%;
      border-collapse: collapse;
      background: #f4f1e8;
      border: 2px solid #b08d3f;
      border-radius: 4px;
      margin: 14px 0;
      page-break-inside: avoid;
    }
    .cta-box td { padding: 14px 18px; }
    .cta-title {
      font-size: 14px;
      font-weight: bold;
      color: #7a5c14;
      margin-bottom: 6px;
    }
    .cta-link { font-size: 12px; word-wrap: break-word; }
    .cta-link a { color: #1a5f8f; }
    .cta-note { font-size: 11px; color: #555555; margin-top: 6px; }
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
       applicato ai blocchi orari qui sopra, non un'invenzione nuova.] */
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
    /* [CORRETTO 2026-07-31 — richiesta di Lorenzo: "migliorare la parte
       grafica, il pdf in sé deve essere accattivante"] Il layout a scatola
       flessibile NON è supportato dal motore Qt WebKit (~2014) di
       wkhtmltopdf: i riquadri di sintesi si impilavano uno sotto l'altro a
       piena larghezza invece di affiancarsi, cioè esattamente il contrario
       dell'effetto "cruscotto" voluto. Stesso identico genere di bug già
       chiuso per le sfumature di sfondo e per le trasparenze (vedi la nota
       in cima al file). Sostituito con una tabella — brutta come tecnica,
       ma è l'unico layout multi-colonna che quel motore renderizza in modo
       identico ovunque (verificato dal vivo, non dedotto).
       NB: i nomi delle proprietà vietate non vanno MAI scritti per esteso
       qui dentro: i test di regressione cercano quelle parole nell'HTML
       prodotto e un commento le farebbe passare per uso reale. */
    .stat-grid { width: 100%; border-collapse: separate; border-spacing: 6px 0; margin: 14px 0; }
    .stat-grid td { vertical-align: top; padding: 0; }
    .stat-tile {
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

    /* =====================================================================
       [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "migliorare la parte
       grafica, il pdf in sé deve essere accattivante, bello da vedere e
       facile da comprendere. la parte da migliorare maggiormente è quella
       delle cartine"]
       Vincoli non negoziabili di questo blocco (motore wkhtmltopdf datato):
       niente scatole flessibili, niente sfumature di sfondo, niente
       trasparenze in nessuna forma (né la proprietà dedicata né il canale
       alpha nei colori). Tutto è ottenuto con colori pieni, bordi, tabelle e
       `inline-block` — verificato dal vivo, non dedotto dalla documentazione.
       I nomi esatti di quelle proprietà non compaiono qui apposta: i test di
       regressione li cercano nell'HTML prodotto.
       ===================================================================== */

    /* --- Copertina ---------------------------------------------------- */
    .cover { page-break-after: always; padding-top: 40px; }
    .cover-kicker {
      font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
      color: #2f6690; margin-bottom: 10px;
    }
    .cover-title { font-size: 40px; line-height: 1.15; color: #1a3b5c; margin: 0 0 6px 0; }
    .cover-sub { font-size: 15px; color: #6b7a89; margin-bottom: 26px; }
    .cover-rule { border-top: 3px solid #c9762f; width: 70px; margin: 0 0 26px 0; }
    .cover-facts { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px; }
    .cover-facts td { padding: 8px 0; border-bottom: 1px solid #e2e8ef; }
    .cover-facts td.k { color: #6b7a89; width: 34%; text-transform: uppercase; font-size: 10px; letter-spacing: .05em; }
    .cover-facts td.v { color: #1a3b5c; font-weight: bold; }
    /* [AGGIUNTO 2026-07-31 — difetto grafico reale trovato ispezionando il
       PDF di esempio: la copertina riempiva circa un terzo della pagina e i
       due terzi sotto restavano bianchi. È la PRIMA cosa che vede chi ha
       appena pagato, e "mezza pagina vuota" comunica bozza, non prodotto.
       Questa striscia riempie lo spazio con l'unica informazione che a quel
       punto interessa davvero: che cosa contiene il documento che ha in
       mano. Impaginata a due colonne con una tabella, non con la scatola
       flessibile, che il motore Qt WebKit di wkhtmltopdf non supporta. */
    .cover-toc { margin-top: 30px; border-top: 1px solid #e2e8ef; padding-top: 16px; }
    .cover-toc-title {
      font-size: 10px; letter-spacing: .12em; text-transform: uppercase;
      color: #2f6690; margin-bottom: 12px;
    }
    .cover-toc table { width: 100%; border-collapse: collapse; }
    .cover-toc td { width: 50%; vertical-align: top; padding: 0 12px 0 0; }
    .cover-toc-item { font-size: 12px; color: #1a3b5c; padding: 5px 0; }
    .cover-toc-num { color: #c9762f; font-weight: bold; margin-right: 7px; }
    .cover-note { font-size: 10px; color: #9aa6b1; margin-top: 30px; }

    /* --- Indice cliccabile -------------------------------------------- */
    .toc { page-break-after: always; }
    .toc-item { font-size: 13px; padding: 7px 0; border-bottom: 1px solid #eef2f6; }
    .toc-item a { color: #1a3b5c; text-decoration: none; }
    .toc-item .toc-num {
      display: inline-block; width: 26px; color: #2f6690; font-weight: bold; font-size: 11px;
    }
    .toc-sub { padding-left: 26px; font-size: 12px; color: #4a5b6b; }

    /* --- Cartina del giorno ------------------------------------------- */
    .day-map { margin: 12px 0 6px 0; page-break-inside: avoid; }
    .day-map img { max-width: 100%; border-radius: 8px; border: 1px solid #dbe3ec; }
    /* Cartina a sinistra, legenda numerata a destra: vedi la nota in
       `_render_day_map()` per il perché (il blocco impilato occupava più di
       metà pagina e sprecava tre pagine su quattordici). */
    .day-map-grid { width: 100%; border-collapse: collapse; }
    .day-map-grid td { vertical-align: top; padding: 0; }
    .day-map-figure { width: 62%; padding-right: 14px !important; }
    .day-map-key { width: 38%; }
    .map-legend { margin: 8px 0 0 0; font-size: 11px; }
    .day-map-key .map-legend { margin-top: 0; }
    .map-legend-row { padding: 3px 0; }
    .map-pin {
      display: inline-block; width: 17px; height: 17px; line-height: 17px;
      text-align: center; border-radius: 9px; color: #ffffff;
      font-size: 10px; font-weight: bold; margin-right: 7px; vertical-align: middle;
    }
    .map-pin.pin-red { background: #b23a3a; }
    .map-pin.pin-orange { background: #c9762f; }
    .map-pin.pin-green { background: #3f8f5f; }
    .map-pin.pin-blue { background: #2f6690; }
    .map-pin.pin-purple { background: #6b4a8f; }
    .map-pin.pin-yellow { background: #a8871f; }
    .map-legend-type { color: #6b7a89; font-size: 10px; }

    /* --- Cartina e come arrivare -------------------------------------- */
    .legs { font-size: 12px; margin: 6px 0 2px 0; }
    .leg-row { padding: 7px 0; border-top: 1px solid #eef2f6; page-break-inside: avoid; }
    .leg-row:first-child { border-top: none; }
    .leg-arrow { color: #2f6690; font-weight: bold; }
    .leg-meta { font-size: 11px; color: #6b7a89; margin-top: 2px; }
    .leg-meta a { color: #2f6690; text-decoration: none; }
    .leg-unknown { color: #8a97a3; font-style: italic; }

    /* --- Costi e budget ------------------------------------------------ */
    .cost-table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }
    .cost-table th {
      text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .05em;
      color: #6b7a89; border-bottom: 2px solid #dfe7ee; padding: 6px 4px;
    }
    .cost-table td { padding: 6px 4px; border-bottom: 1px solid #eef2f6; vertical-align: top; }
    .cost-table td.num { text-align: right; white-space: nowrap; }
    .cost-table tr.total td {
      border-top: 2px solid #1a3b5c; border-bottom: none;
      font-weight: bold; color: #1a3b5c; font-size: 13px; padding-top: 8px;
    }
    .cost-detail { font-size: 10px; color: #8a97a3; }
    .verdict {
      display: inline-block; font-size: 11px; font-weight: bold; color: #ffffff;
      padding: 3px 10px; border-radius: 10px; margin-top: 6px;
    }
    .verdict.v-within { background: #3f8f5f; }
    .verdict.v-tight { background: #c9762f; }
    .verdict.v-over { background: #b23a3a; }

    /* --- Consigli dell'Architetto -------------------------------------- */
    .tip-group { margin-bottom: 14px; page-break-inside: avoid; }
    .tip-group-title {
      font-size: 13px; font-weight: bold; color: #1a3b5c;
      border-left: 4px solid #c9762f; padding-left: 10px; margin-bottom: 6px;
    }
    .tip-group ul { margin: 0; padding-left: 20px; font-size: 12px; }
    .tip-group li { margin-bottom: 4px; }

    /* --- Piani B se piove ---------------------------------------------- */
    .rain-card {
      border: 1px solid #dbe3ec; border-left: 4px solid #2f6690; border-radius: 6px;
      padding: 12px 16px; margin-bottom: 10px; font-size: 12px; page-break-inside: avoid;
    }
    .rain-day { font-weight: bold; color: #1a3b5c; margin-bottom: 4px; }
    .rain-swap { padding: 4px 0; border-top: 1px solid #eef2f6; }
    .rain-swap:first-child { border-top: none; }
    .rain-arrow { color: #2f6690; font-weight: bold; }

    /* --- Schede luogo (menù / info ristoranti) ------------------------- */
    .place-links { font-size: 11px; margin-top: 3px; }
    .place-links a {
      display: inline-block; color: #2f6690; text-decoration: none;
      border: 1px solid #cfdae5; border-radius: 10px;
      padding: 1px 9px; margin: 2px 5px 0 0;
    }
    .place-meta { font-size: 10px; color: #8a97a3; margin-top: 2px; }

    /* --- Guida turistica tascabile ------------------------------------- */
    .guide-link { font-size: 11px; margin-top: 3px; }
    .guide-link a {
      display: inline-block; color: #ffffff; background: #1a3b5c; text-decoration: none;
      border-radius: 10px; padding: 2px 10px;
    }
    /* La regola "non spezzare a metà" resta quella condivisa `.page-break`
       (vedi sopra): la guida la applica aggiungendo quella classe, così
       esiste un solo posto dove cambiare quel comportamento. */
    .guide-card {
      border: 1px solid #dbe3ec; border-radius: 8px; padding: 16px 20px;
      margin-bottom: 14px;
    }
    .guide-card h3 { font-size: 15px; color: #1a3b5c; margin: 0 0 4px 0; }
    .guide-eyebrow { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #c9762f; }
    .guide-body { font-size: 12px; margin-top: 8px; }
    .guide-facts { font-size: 11px; color: #4a5b6b; margin-top: 8px; }
    .guide-back { font-size: 10px; margin-top: 8px; }
    .guide-back a { color: #2f6690; text-decoration: none; }
    .highlight-row { padding: 4px 0; border-top: 1px solid #eef2f6; font-size: 12px; }
    .highlight-row:first-child { border-top: none; }
    .highlight-name { font-weight: bold; color: #1a3b5c; }

    /* --- Varie --------------------------------------------------------- */
    .anchor { font-size: 1px; color: #ffffff; }
    .section-intro { font-size: 11px; color: #6b7a89; margin: -4px 0 10px 0; }
    .day-open { page-break-inside: avoid; }
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
def _render_guide_section(guide: dict, anchor: str | None = None) -> str:
    """Rende una guida turistica per un singolo POI (schema completo in
    guide_generator.py: title, poi_name, history_summary, practical_tips,
    best_time_to_visit, estimated_visit_duration, consiglio_personalizzato,
    disclaimer) come sezione del PDF.

    [AGGIORNATO 2026-07-31 — richiesta di Lorenzo: "reindirizzi il cliente
    alla fine del pdf dove è presente la guida turistica, portandolo
    DIRETTAMENTE sull'attrazione richiesta"] La sezione porta ora un `id`
    HTML: è il bersaglio del link "Guida turistica tascabile" stampato
    accanto al blocco nel giorno-per-giorno. Senza ancora, il cliente
    atterrava all'inizio del capitolo guide e doveva cercare la sua a mano —
    su un viaggio da dieci tappe, inutilizzabile.

    [AGGIUNTO 2026-07-31] `highlights` (campo OPZIONALE, vedi
    guide_generator.py): le opere/punti principali da vedere DENTRO il
    luogo — la parte che Lorenzo chiedeva esplicitamente ("piccola guida per
    un museo che spiega le opere principali al suo interno"). Opzionale di
    proposito: una guida generata prima di questa modifica, o per una piazza
    dove l'elenco non ha senso, resta valida e viene stampata senza."""
    tips = "".join(f"<li>{_esc(t)}</li>" for t in guide.get("practical_tips", []) or [])
    title = guide.get("title") or guide.get("poi_name", "")
    anchor_attr = f" id='{_esc(anchor)}'" if anchor else ""
    parts = [
        f"<div class='guide-card page-break'{anchor_attr}>",
        "<div class='guide-eyebrow'>Guida turistica tascabile</div>",
        f"<h3>{_esc(title)}</h3>",
        f"<div class='guide-body'>{_esc(guide.get('history_summary', ''))}</div>",
    ]

    highlights = guide.get("highlights")
    if isinstance(highlights, list) and highlights:
        parts.append(
            "<div class='guide-body'><strong>Cosa cercare, una volta dentro</strong></div>"
        )
        for item in highlights:
            if isinstance(item, dict):
                name, why = item.get("name") or "", item.get("why") or ""
            else:
                name, why = str(item), ""
            if not name:
                continue
            parts.append(
                f"<div class='highlight-row'><span class='highlight-name'>{_esc(name)}</span>"
                + (f" — {_esc(why)}" if why else "")
                + "</div>"
            )

    if tips:
        parts.append(
            f"<div class='tips-box'><strong>Consigli pratici</strong><ul>{tips}</ul></div>"
        )
    parts.append(
        f"<div class='guide-facts'><strong>Quando visitare:</strong> "
        f"{_esc(guide.get('best_time_to_visit', ''))}<br>"
        f"<strong>Durata consigliata della visita:</strong> "
        f"{_esc(guide.get('estimated_visit_duration', ''))}</div>"
    )
    if guide.get("consiglio_personalizzato"):
        parts.append(
            f"<div class='guide-facts'><strong>Su misura per te:</strong> "
            f"{_esc(guide['consiglio_personalizzato'])}</div>"
        )
    if guide.get("disclaimer"):
        parts.append(f"<div class='disclaimer'>{_esc(guide['disclaimer'])}</div>")
    parts.append(
        "<div class='guide-back'>"
        "<a href='#giorno-per-giorno'>Torna al programma giorno per giorno</a></div>"
    )
    parts.append("</div>")
    return "".join(parts)


def _render_feedback_section(feedback: dict | None, feedback_link: dict | None = None) -> str:
    """Rende il messaggio di feedback post-viaggio (schema completo in
    feedback_generator.py: intro_message, questions, testimonial_request,
    closing_message) come sezione finale del PDF.

    [AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore"] Alle
    domande personalizzate generate dal modello si affiancano ora due cose
    che prima mancavano del tutto: un POSTO DOVE RISPONDERE (il link al
    modulo, con il codice della consegna già dentro la URL) e un set di
    DOMANDE UGUALI PER TUTTI (`feedback_link.CORE_QUESTIONS`). Le prime
    fanno parlare la persona, le seconde producono numeri confrontabili fra
    clienti diversi: senza le seconde, cento risposte restano cento aneddoti.

    `feedback_link` è `{"ref": ..., "url": ..., "core_questions": [...]}` —
    tutto opzionale: se il modulo non è configurato (FEEDBACK_FORM_URL
    assente) la sezione esce come prima, senza link morti.
    """
    feedback = feedback or {}
    link = feedback_link or {}
    parts = [
        "<div class='page-break'>",
        "<div class='section-title'>Facci sapere com'è andata</div>",
    ]
    if feedback.get("intro_message"):
        parts.append(f"<div class='summary-box'>{_esc(feedback['intro_message'])}</div>")

    questions = "".join(f"<li>{_esc(q)}</li>" for q in feedback.get("questions", []))
    if questions:
        parts.append(f"<div class='tips-box'><ul>{questions}</ul></div>")

    core = link.get("core_questions") or []
    if core:
        parts.append(
            "<div class='section-intro'>E poi qualche minuto su queste, che facciamo a "
            "tutti: sono il modo in cui capiamo se il prossimo itinerario può essere "
            "migliore di questo.</div>"
        )
        core_items = []
        for question in core:
            text = _esc(question.get("text", ""))
            options = question.get("options") or []
            if options:
                text += " <em>(" + _esc(" / ".join(str(o) for o in options)) + ")</em>"
            core_items.append(f"<li>{text}</li>")
        parts.append(f"<div class='tips-box'><ul>{''.join(core_items)}</ul></div>")

    url = link.get("url")
    ref = link.get("ref")
    if url:
        # Il link porta già con sé il codice della consegna: il cliente non
        # deve ricordarsi né trascrivere niente. Il codice è ripetuto in
        # chiaro solo come rete di sicurezza per chi stampa il documento.
        # Tabella e non div: `page-break-inside: avoid` è affidabile sulle
        # righe di tabella, non su un contenitore alto (vedi il commento in
        # cima al foglio di stile).
        parts.append(
            "<table class='cta-box'><tr><td>"
            "<div class='cta-title'>Rispondi qui</div>"
            f"<div class='cta-link'><a href='{_esc(url)}'>{_esc(url)}</a></div>"
            + (
                f"<div class='cta-note'>Se apri il modulo a mano, il codice del tuo "
                f"viaggio è <strong>{_esc(ref)}</strong>.</div>" if ref else ""
            )
            + "</td></tr></table>"
        )

    if feedback.get("testimonial_request"):
        parts.append(f"<div class='summary-box'>{_esc(feedback['testimonial_request'])}</div>")
    if feedback.get("closing_message"):
        parts.append(f"<div class='summary-box'>{_esc(feedback['closing_message'])}</div>")
    parts.append("</div>")
    return "".join(parts)


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
    # [CORRETTO 2026-07-31] I riquadri erano `<div>` dentro un contenitore a
    # scatola flessibile: su wkhtmltopdf si impilavano a piena larghezza uno
    # sotto l'altro, cioè il contrario del "cruscotto" voluto. Ora sono celle
    # di una vera tabella, l'unico layout multi-colonna che quel motore
    # renderizza in modo affidabile. Tre per riga: con quattro o cinque voci
    # una riga da quattro schiaccia i valori lunghi (nome dell'hotel) su più
    # capoversi e la pagina perde leggibilità.
    per_row = 3
    parts.append("<table class='stat-grid'>")
    for start in range(0, len(tiles), per_row):
        row = tiles[start:start + per_row]
        parts.append("<tr>")
        for label, value in row:
            parts.append(
                f"<td style='width:{100 // per_row}%'>"
                f"<div class='stat-tile'><div class='stat-label'>{_esc(label)}</div>"
                f"<div class='stat-value'>{_esc(value)}</div></div></td>"
            )
        # Celle vuote di riempimento: senza, l'ultima cella di una riga
        # incompleta si allarga e i riquadri non risultano più allineati in
        # colonna con quelli della riga sopra.
        parts.extend(["<td></td>"] * (per_row - len(row)))
        parts.append("</tr>")
    parts.append("</table>")

    days = [d for d in (itinerary.get("days") or []) if isinstance(d, dict)]
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
    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            pid = block.get("poi_id")
            tag = poi_energy.get(pid) if isinstance(pid, str) else None
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


def _render_maps_link(
    poi_id: str | None,
    location_lookup: dict[str, tuple[float, float]],
    place_cards: dict | None = None,
) -> str:
    """Link 'apri su Google Maps' per UN blocco, se le sue coordinate
    reali sono note. Nessun link per blocchi senza `poi_id` (check-in
    generico, `[SLOT LIBERO]`) o il cui id non è tra gli hotel/POI
    realmente forniti al renderer."""
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento] un `poi_id` non
    # hashable (lista, forma inattesa di Claude) faceva `location_lookup.get`
    # → TypeError unhashable, crashando il rendering del PDF. Un id non-str non
    # è comunque una chiave valida: nessun link, mai crash.
    if not isinstance(poi_id, str) or not poi_id:
        return ""
    # [CORRETTO 2026-07-31 — difetto grafico reale trovato ispezionando il PDF
    # di esempio] La scheda luogo (`_render_place_links`) emette già il proprio
    # link a Google Maps — `info_link`, che oltre alla posizione porta orari,
    # foto e recensioni, quindi è STRETTAMENTE migliore di queste sole
    # coordinate. Stampandoli entrambi ogni blocco mostrava due pulsanti quasi
    # identici uno sotto l'altro ("Apri in Google Maps" / "🗺️ Apri su Google
    # Maps"): rumore che fa sembrare il documento generato a macchina e
    # costringe il cliente a chiedersi quale dei due sia quello giusto. Se la
    # scheda c'è, vince lei; questo resta il ripiego per i POI senza scheda.
    if isinstance(place_cards, dict):
        card = place_cards.get(poi_id)
        if isinstance(card, dict):
            info = card.get("info_link")
            if isinstance(info, dict) and info.get("url"):
                return ""
    coords = location_lookup.get(poi_id)
    if coords is None:
        return ""
    lat, lng = coords
    url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    return f"<div class='block-maps-link'><a href='{_esc(url)}'>🗺️ Apri su Google Maps</a></div>"


# =========================================================================
# [AGGIUNTO 2026-07-31 — blocco di richieste di Lorenzo dopo aver testato
# dal vivo il PDF del proprio Interrail]
#
# Sette sezioni nuove, tutte con lo stesso vincolo di fondo già in vigore
# nel resto del progetto: **si stampa solo ciò che è stato calcolato o
# recuperato da dati reali**. Una sezione che non ha dati non viene
# stampata mezza vuota — semplicemente non compare, e l'indice non la
# elenca. Questo è il motivo per cui ogni `_render_*` qui sotto ritorna
# stringa vuota invece di un titolo con sotto il nulla.
# =========================================================================

# Colori dei marker Google Static Maps -> classi CSS dei pallini in legenda.
# La legenda DEVE usare lo stesso colore del marker sulla cartina, altrimenti
# è peggio di nessuna legenda: il cliente cercherebbe un pallino verde che
# sulla cartina è arancione.
_PIN_CLASS_BY_COLOR = {
    "red": "pin-red", "orange": "pin-orange", "green": "pin-green",
    "blue": "pin-blue", "purple": "pin-purple", "yellow": "pin-yellow",
}
_SLUG_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(value) -> str:
    """Id HTML sicuro per un'ancora interna. I `poi_id` reali sono già
    alfanumerici, ma un id inatteso (spazi, accenti, apici) produrrebbe un
    `href='#...'` rotto — e un link interno rotto in un PDF è invisibile
    finché il cliente non ci clicca sopra."""
    return _SLUG_UNSAFE.sub("-", str(value or "")).strip("-").lower()


def _fmt_eur(value) -> str:
    """Importo in euro senza decimali inutili: 360 invece di 360.0 (il
    cliente legge un budget, non un estratto conto)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:,.0f}".replace(",", ".") + " €"


# --- Copertina e indice --------------------------------------------------
def _render_cover(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None,
    sections: list[str] | None = None,
) -> str:
    """Prima pagina dedicata: il documento che il cliente riceve dopo aver
    pagato deve *sembrare* un prodotto, non l'output di uno script. È
    l'unica sezione con `page-break-after: always` — qui il salto pagina è
    voluto, non uno spreco (vedi la nota su `.page-break` nel CSS).

    `sections` sono i titoli delle sezioni REALMENTE generate (le stesse
    dell'indice, passate dal chiamante): la copertina non deve mai promettere
    un capitolo che poi non c'è."""
    destination = itinerary.get("destination") or trip.get("destination") or ""
    budget_str = (
        "Illimitato" if trip.get("budget_mode") == "UNLIMITED"
        else (_fmt_eur(trip.get("budget_eur")) or _esc(trip.get("budget_eur")))
    )
    rows = [
        ("Date", f"{trip.get('date_start')} → {trip.get('date_end')}"),
        ("Durata", f"{trip.get('duration_days')} giorni"),
        ("Budget indicato", budget_str),
    ]
    if hotels:
        rows.append(("Base", hotels[0].get("name") or "[Da Verificare]"))
    days = [d for d in (itinerary.get("days") or []) if isinstance(d, dict)]
    if days:
        rows.append(("Giornate progettate", str(len(days))))

    parts = [
        "<div class='cover'>",
        "<div class='cover-kicker'>Itinerario su misura</div>",
        f"<h1 class='cover-title'>{_esc(destination)}</h1>",
        "<div class='cover-rule'></div>",
        "<div class='cover-sub'>Progettato attorno al tuo ritmo, ai tuoi orari e al tuo budget.</div>",
        "<table class='cover-facts'>",
    ]
    for key, value in rows:
        parts.append(
            f"<tr><td class='k'>{_esc(key)}</td><td class='v'>{_esc(value)}</td></tr>"
        )
    parts.append("</table>")

    # "Cosa troverai dentro": due colonne bilanciate, la prima metà a
    # sinistra. Con una sola voce la tabella a due colonne sarebbe sbilanciata
    # e peggiorerebbe l'impaginazione invece di migliorarla: sotto le due voci
    # la striscia non si stampa proprio.
    titles = [t for t in (sections or []) if isinstance(t, str) and t.strip()]
    if len(titles) >= 2:
        half = (len(titles) + 1) // 2
        columns = (titles[:half], titles[half:])
        parts.append(
            "<div class='cover-toc'>"
            "<div class='cover-toc-title'>Cosa troverai dentro</div>"
            "<table><tr>"
        )
        offset = 0
        for column in columns:
            parts.append("<td>")
            for index, title in enumerate(column):
                parts.append(
                    f"<div class='cover-toc-item'>"
                    f"<span class='cover-toc-num'>{offset + index + 1:02d}</span>"
                    f"{_esc(title)}</div>"
                )
            parts.append("</td>")
            offset += len(column)
        parts.append("</tr></table></div>")

    parts.append(
        "<div class='cover-note'>Ogni luogo, coordinata e prezzo in questo documento proviene "
        "da dati reali raccolti al momento della generazione. Dove un dato non era disponibile "
        "lo troverai marcato come da verificare, mai sostituito da una stima inventata.</div>"
    )
    parts.append("</div>")
    return "".join(parts)


def _render_toc(entries: list[tuple[str, str]], day_entries: list[tuple[str, str]]) -> str:
    """Indice cliccabile. `entries` sono le sezioni di primo livello già
    filtrate dal chiamante: se una sezione non è stata generata, non
    compare qui — un indice che rimanda a una pagina inesistente è un bug
    visibile al cliente."""
    if not entries:
        return ""
    parts = ["<div class='toc'>", "<div class='section-title'>Indice</div>"]
    number = 0
    for anchor, title in entries:
        number += 1
        parts.append(
            f"<div class='toc-item'><span class='toc-num'>{number}.</span>"
            f"<a href='#{_esc(anchor)}'>{_esc(title)}</a></div>"
        )
        if anchor == "giorno-per-giorno":
            for day_anchor, day_title in day_entries:
                parts.append(
                    f"<div class='toc-item toc-sub'>"
                    f"<a href='#{_esc(day_anchor)}'>{_esc(day_title)}</a></div>"
                )
    parts.append("</div>")
    return "".join(parts)


# --- Cartina del giorno + legenda ---------------------------------------
def _render_day_map(day_map: dict | None, title_html: str = "") -> str:
    """
    [richiesta di Lorenzo: "nelle mappe varie che generi non si capisce cosa
    siano gli indicatori, sarebbe opportuno indicare vicino ad ogni
    indicatore cosa sono e il numero (1=prima attività del giorno...)"]

    La legenda è la vera risposta a quella richiesta, non l'immagine: il
    numero sul marker acquista significato solo se accanto c'è scritto
    "1 — Galleria degli Uffizi". Per questo la legenda viene stampata anche
    quando il PNG non è arrivato (quota Google esaurita, rete): il cliente
    perde la figura ma non l'informazione.

    [CORRETTO 2026-07-31 — difetto misurato sul PDF di esempio] Prima la
    legenda stava SOTTO la cartina: cartina (~41 % di pagina) + legenda
    (~13 %) = oltre metà pagina indivisibile. Risultato: il blocco non
    entrava quasi mai nello spazio rimasto e slittava alla pagina dopo,
    lasciandone metà bianca (pagine 4, 6 e 8 su 14) e separando perfino il
    titolo del giorno dalla propria cartina. Affiancandole in due colonne
    l'altezza totale scende a circa un terzo di pagina e il blocco entra
    quasi sempre. Due colonne fatte con una tabella, non con la scatola
    flessibile: quel layout il motore Qt WebKit di wkhtmltopdf non lo
    supporta (vedi la nota in cima al CSS).

    `title_html` viaggia DENTRO la stessa cella della cartina apposta:
    titolo e figura finiscono nella stessa riga di tabella e il motore non
    può più separarli fra due pagine, cosa che invece faceva quando erano
    due `div` fratelli sotto un contenitore con la regola "non spezzare".
    """
    if not day_map:
        return ""
    stops = day_map.get("stops") or []
    png = day_map.get("png")
    if not stops and not png:
        # Nessun dato cartografico: il titolo NON viene stampato qui, lo
        # stampa comunque la `.day-card` del programma subito sotto. Fosse
        # stampato in entrambi i posti il cliente lo leggerebbe due volte.
        return ""
    img_html = ""
    if png:
        b64 = base64.b64encode(png).decode("ascii")
        img_html = (
            f"<img src='data:image/png;base64,{b64}' "
            f"alt='Cartina del giorno con le tappe numerate'>"
        )

    # Senza immagine non c'è nulla da affiancare: la legenda da sola prende
    # tutta la larghezza, che è anche il modo in cui si legge meglio.
    side_by_side = bool(img_html and stops)
    parts = ["<div class='day-map'>"]
    if side_by_side:
        parts.append(
            f"<table class='day-map-grid'><tr><td class='day-map-figure'>"
            f"{title_html}{img_html}</td><td class='day-map-key'>"
        )
    else:
        parts.append(title_html)
        parts.append(img_html)
    if stops:
        parts.append("<div class='map-legend'>")
        parts.append(
            "<div class='map-legend-row'><span class='map-pin pin-red'>H</span>"
            "<strong>Punto di partenza e rientro</strong> "
            "<span class='map-legend-type'>— il tuo alloggio</span></div>"
        )
        for stop in stops:
            pin_class = _PIN_CLASS_BY_COLOR.get(stop.get("color"), "pin-blue")
            label = stop.get("label") or "•"
            name = stop.get("location") or stop.get("activity") or ""
            time = stop.get("time") or ""
            type_label = stop.get("type_label") or ""
            meta = " · ".join(x for x in (time, type_label) if x)
            parts.append(
                f"<div class='map-legend-row'>"
                f"<span class='map-pin {pin_class}'>{_esc(label)}</span>"
                f"<strong>{_esc(name)}</strong>"
                + (f" <span class='map-legend-type'>— {_esc(meta)}</span>" if meta else "")
                + "</div>"
            )
        parts.append("</div>")
    if side_by_side:
        parts.append("</td></tr></table>")
    parts.append("</div>")
    return "".join(parts)


# --- Cartina e come arrivare --------------------------------------------
def _render_directions(day_directions: dict | None) -> str:
    """
    [richiesta di Lorenzo: "manca anche la parte 'cartina e come arrivare' in
    cui spieghi spostamento per spostamento come arrivare"]

    Un tragitto per riga, nell'ordine reale della giornata, con il link
    Google Maps già impostato su origine e destinazione: il cliente in
    strada non deve ridigitare nulla. I minuti compaiono SOLO se provengono
    da una misura reale della Distance Matrix già in payload — altrimenti
    la riga dice esplicitamente che il tempo va verificato, invece di
    stampare una stima plausibile e sbagliata.
    """
    if not day_directions:
        return ""
    legs = day_directions.get("legs") or []
    if not legs:
        return ""
    parts = ["<div class='legs'>"]
    for leg in legs:
        from_label = leg.get("from_label") or ""
        to_label = leg.get("to_label") or ""
        line = (
            f"<span class='leg-arrow'>{_esc(from_label)} → {_esc(to_label)}</span> "
            f"{_esc(leg.get('from_name'))} → <strong>{_esc(leg.get('to_name'))}</strong>"
        )
        minutes = leg.get("minutes")
        mode = leg.get("mode_label") or leg.get("mode") or ""
        if isinstance(minutes, int):
            meta = f"circa {minutes} min {mode}".strip()
        else:
            meta = (
                "<span class='leg-unknown'>tempo di percorrenza da verificare sul momento</span>"
            )
        arrival = leg.get("arrival_time")
        if arrival:
            meta += f" · arrivo previsto {_esc(arrival)}"
        url = leg.get("url")
        if url:
            meta += f" · <a href='{_esc(url)}'>apri il percorso</a>"
        parts.append(
            f"<div class='leg-row'>{line}<div class='leg-meta'>{meta}</div></div>"
        )
    parts.append("</div>")
    return "".join(parts)


# --- Stima dei costi e dettaglio budget ---------------------------------
_VERDICT_TEXT = {
    "within": ("v-within", "Rientra nel budget indicato"),
    "tight": ("v-tight", "Al limite del budget indicato"),
    "over": ("v-over", "Sopra il budget indicato"),
}


def _render_costs(cost_summary: dict | None) -> str:
    """
    [richiesta di Lorenzo: "manca la parte della stima dei costi e dettaglio
    budget"]

    Ogni riga è calcolata in Python da prezzi/fasce reali (vedi
    src/cost_estimator.py), mai generata dal modello: è il numero su cui il
    cliente decide quanto contante portare. Le voci senza un dato reale
    restano in tabella marcate `[Da Verificare]` ma FUORI dal totale —
    ometterle nasconderebbe una spesa, includerle a stima inventerebbe un
    prezzo. Entrambe le cose sarebbero peggio del dirlo.
    """
    if not cost_summary or not (cost_summary.get("lines") or []):
        return ""
    parts = [
        "<table class='cost-table'>",
        "<tr><th>Voce</th><th>Dettaglio</th><th class='num'>Stima</th></tr>",
    ]
    for line in cost_summary["lines"]:
        if line.get("known"):
            low, high = line.get("min_eur"), line.get("max_eur")
            amount = _fmt_eur(low) if low == high else f"{_fmt_eur(low)} – {_fmt_eur(high)}"
        else:
            amount = "<span class='cost-detail'>[Da Verificare]</span>"
        parts.append(
            f"<tr><td><strong>{_esc(line.get('label'))}</strong></td>"
            f"<td class='cost-detail'>{_esc(line.get('detail'))}</td>"
            f"<td class='num'>{amount}</td></tr>"
        )
    total_min = cost_summary.get("total_min_eur")
    total_max = cost_summary.get("total_max_eur")
    total = _fmt_eur(total_min) if total_min == total_max else f"{_fmt_eur(total_min)} – {_fmt_eur(total_max)}"
    parts.append(
        f"<tr class='total'><td colspan='2'>Totale stimato "
        f"({_esc(cost_summary.get('travellers', 1))} "
        f"{'persona' if cost_summary.get('travellers', 1) == 1 else 'persone'})</td>"
        f"<td class='num'>{total}</td></tr>"
    )
    parts.append("</table>")

    verdict = cost_summary.get("budget_verdict")
    if verdict in _VERDICT_TEXT:
        css_class, text = _VERDICT_TEXT[verdict]
        budget = _fmt_eur(cost_summary.get("budget_eur"))
        parts.append(
            f"<div><span class='verdict {css_class}'>{_esc(text)}</span>"
            + (f" <span class='cost-detail'>budget indicato: {budget}</span>" if budget else "")
            + "</div>"
        )
    if cost_summary.get("unknown_count"):
        parts.append(
            f"<div class='cost-detail' style='margin-top:6px'>"
            f"{_esc(cost_summary['unknown_count'])} voce/i senza un prezzo pubblicato al momento "
            f"della generazione: sono elencate qui sopra ma NON incluse nel totale, per non "
            f"gonfiarlo con una cifra inventata.</div>"
        )
    if cost_summary.get("excluded_note"):
        parts.append(f"<div class='cost-detail'>{_esc(cost_summary['excluded_note'])}</div>")
    return "".join(parts)


# --- Consigli dell'Architetto + piani B se piove -------------------------
def _render_tips(tips: dict | None, legacy_tips: list | None = None) -> str:
    """
    [richiesta di Lorenzo: "architect's tips molto più articolato secondo
    direttrici ben precise: biglietti e prenotazioni, bagagli e logistica,
    risparmio e pagamenti, meteo luce e stagione, pratico e sicurezza, vita
    notturna, ecc..."]

    Una sotto-sezione per direttrice (vedi src/tips_generator.py::
    TIP_CATEGORIES). `legacy_tips` è la vecchia lista piatta
    `itinerary["architect_tips"]`: resta come ripiego per gli itinerari
    generati prima di questa modifica e per il caso in cui la chiamata
    dedicata fallisca — meglio quattro consigli generici che nessuno.
    """
    sections = [s for s in ((tips or {}).get("sections") or []) if (s.get("tips") or [])]
    if sections:
        parts = []
        for section in sections:
            parts.append("<div class='tip-group'>")
            parts.append(f"<div class='tip-group-title'>{_esc(section.get('title'))}</div>")
            parts.append("<ul>")
            for tip in section.get("tips") or []:
                parts.append(f"<li>{_esc(tip)}</li>")
            parts.append("</ul></div>")
        return "".join(parts)
    if legacy_tips:
        items = "".join(f"<li>{_esc(t)}</li>" for t in legacy_tips)
        return f"<div class='tips-box'><ul>{items}</ul></div>"
    return ""


def _render_rain_plans(tips: dict | None) -> str:
    """
    [richiesta di Lorenzo: "manca la parte dei piani b se piove"]

    Le alternative al chiuso sono scelte esclusivamente tra i POI reali già
    in `DATI_API_FORNITI` (filtro applicato in
    `tips_generator.normalize_tips()`, non qui): un piano B che manda il
    cliente in un museo inesistente sotto la pioggia è il peggior fallimento
    possibile di questa sezione.
    """
    plans = [p for p in ((tips or {}).get("rain_plans") or []) if (p.get("swaps") or p.get("summary"))]
    if not plans:
        return ""
    parts = []
    for plan in plans:
        parts.append("<div class='rain-card'>")
        day = plan.get("day")
        parts.append(
            f"<div class='rain-day'>Giorno {_esc(day)}</div>" if day is not None
            else "<div class='rain-day'>Se piove</div>"
        )
        if plan.get("summary"):
            parts.append(f"<div>{_esc(plan['summary'])}</div>")
        for swap in plan.get("swaps") or []:
            parts.append(
                f"<div class='rain-swap'>{_esc(swap.get('replaces'))} "
                f"<span class='rain-arrow'>→</span> <strong>{_esc(swap.get('name'))}</strong>"
                + (f"<div class='cost-detail'>{_esc(swap.get('why'))}</div>" if swap.get("why") else "")
                + "</div>"
            )
        parts.append("</div>")
    return "".join(parts)


# --- Schede ristorante (menù + info) e guide tascabili -------------------
def _render_place_links(poi_id, place_cards: dict | None) -> str:
    """
    [richiesta di Lorenzo: "per i ristoranti è utile che crei un collegamento
    con il menù del ristorante ... ed un altro collegamento con le info utili
    sul ristorante (indirizzo, numero, ecc...)"]

    Il link "menù" è il sito ufficiale quando Google Places lo restituisce,
    altrimenti una ricerca DICHIARATA come tale — mai un `sito.it/menu`
    indovinato (vedi il test `test_niente_url_di_menu_indovinato`).
    """
    if not place_cards or not isinstance(poi_id, str):
        return ""
    card = place_cards.get(poi_id)
    if not card:
        return ""
    links = []
    for key in ("menu_link", "info_link"):
        link = card.get(key)
        if link and link.get("url"):
            links.append(f"<a href='{_esc(link['url'])}'>{_esc(link.get('label') or 'Apri')}</a>")
    meta = " · ".join(x for x in (card.get("address"), card.get("phone")) if x)
    if not links and not meta:
        return ""
    parts = []
    if links:
        parts.append(f"<div class='place-links'>{''.join(links)}</div>")
    if meta:
        parts.append(f"<div class='place-meta'>{_esc(meta)}</div>")
    return "".join(parts)


def _render_guide_link(poi_id, guide_anchors: dict | None) -> str:
    """
    [richiesta di Lorenzo: "aggiungi magari un collegamento 'guida turistica
    tascabile' per ogni cosa che lo richieda ... e reindirizzi il cliente
    alla fine del pdf dove è presente la guida turistica, portandolo
    direttamente sull'attrazione richiesta"]

    Link interno al PDF (`href='#guida-...'`), non un URL esterno: funziona
    offline, in aereo, senza rete — che è precisamente quando serve. Perché
    sia cliccabile, `render_pdf()` passa `--enable-internal-links` a
    wkhtmltopdf (senza quel flag il link viene disegnato ma è inerte).
    """
    if not guide_anchors or not isinstance(poi_id, str):
        return ""
    anchor = guide_anchors.get(poi_id)
    if not anchor:
        return ""
    return (
        f"<div class='guide-link'><a href='#{_esc(anchor)}'>"
        f"Guida turistica tascabile</a></div>"
    )


def render_html(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None = None,
    guides: list[dict] | None = None,
    feedback: dict | None = None,
    poi: list[dict] | None = None,
    map_png_bytes: bytes | None = None,
    day_maps: list[dict] | None = None,
    directions: list[dict] | None = None,
    cost_summary: dict | None = None,
    tips: dict | None = None,
    place_cards: dict | None = None,
    feedback_link: dict | None = None,
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
    funzionante, semplicemente senza le sezioni corrispondenti.

    [AGGIUNTI 2026-07-31 — blocco di richieste di Lorenzo dopo il test dal
    vivo del PDF del suo Interrail] Cinque nuovi ingressi, tutti opzionali
    per la stessa ragione degli altri (un chiamante che non li passa ottiene
    il documento di prima, non un errore):
      - `day_maps`: una cartina + legenda PER GIORNO
        (`maps_static.build_day_maps_for_itinerary()`) — sostituisce di
        fatto l'unica cartina d'insieme come strumento di orientamento
        quotidiano ("puntini con coordinate che non aiutano minimamente il
        cliente ad orientarsi durante la giornata");
      - `directions`: i tragitti spostamento-per-spostamento
        (`directions.build_directions_by_day()`);
      - `cost_summary`: la stima costi calcolata
        (`cost_estimator.estimate_costs()`);
      - `tips`: consigli per direttrice + piani B se piove
        (`tips_generator.generate_architect_tips()`);
      - `place_cards`: menù/info/telefono/indirizzo per POI
        (`place_links.build_place_cards_by_id()`).

    **Indice e ancore.** Ogni sezione realmente presente riceve un `id` e
    compare nell'indice cliccabile di pagina 2. Le sezioni assenti non
    vengono elencate: un indice che rimanda al vuoto è un difetto visibile,
    e questo documento viene pagato.
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

    days = [d for d in (itinerary.get("days") or []) if isinstance(d, dict)]

    # Indicizzazione per numero di giorno: `day_maps`/`directions` arrivano
    # come liste, ma il day-by-day itera sui giorni dell'itinerario — un
    # accoppiamento posizionale si romperebbe al primo giorno saltato.
    day_maps_by_day = {
        dm.get("day"): dm for dm in (day_maps or []) if isinstance(dm, dict)
    }
    directions_by_day = {
        d.get("day"): d for d in (directions or []) if isinstance(d, dict)
    }

    # Ancore delle guide: costruite PRIMA del day-by-day, perché i link
    # "Guida turistica tascabile" dentro i blocchi puntano qui.
    guide_anchors: dict[str, str] = {}
    guide_list = [g for g in (guides or []) if isinstance(g, dict)]
    for index, guide in enumerate(guide_list):
        key = guide.get("poi_id") or guide.get("poi_name") or f"guida-{index}"
        anchor = f"guida-{_slug(key)}" or f"guida-{index}"
        guide.setdefault("_anchor", anchor)
        if guide.get("poi_id"):
            guide_anchors[guide["poi_id"]] = anchor

    costs_html = _render_costs(cost_summary)
    tips_html = _render_tips(tips, itinerary.get("architect_tips"))
    rain_html = _render_rain_plans(tips)
    curated_html = _render_curated_sections(poi)

    # --- Indice: solo le sezioni che esistono davvero --------------------
    toc_entries: list[tuple[str, str]] = [("colpo-docchio", "Il tuo viaggio, a colpo d'occhio")]
    if hotels:
        toc_entries.append(("alloggio", "Il tuo alloggio"))
    if curated_html:
        toc_entries.append(("selezione", "La selezione: dove mangiare, cosa fare"))
    if days:
        toc_entries.append(("giorno-per-giorno", "Il programma, giorno per giorno"))
    if costs_html:
        toc_entries.append(("costi", "Stima dei costi e dettaglio budget"))
    if tips_html:
        toc_entries.append(("consigli", "Architect's Tips — i consigli dell'Architetto"))
    if rain_html:
        toc_entries.append(("piani-b", "Piani B: se piove"))
    if guide_list:
        toc_entries.append(("guide", "Guide turistiche tascabili"))
    if feedback or feedback_link:
        toc_entries.append(("recensione", "Facci sapere com'è andata"))

    day_toc = [
        (f"giorno-{_esc(day.get('day'))}",
         f"Giorno {day.get('day')} — {day.get('title', '')}")
        for day in days
    ]

    parts = [
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>",
        f"<title>Itinerario — {destination}</title>",
        f"<style>{_CSS}</style></head><body>",
        _render_cover(itinerary, trip, hotels, [title for _anchor, title in toc_entries]),
        _render_toc(toc_entries, day_toc),
        "<div class='header'>",
        f"<h1>Itinerario Ottimizzato: {destination}</h1>",
        f"<div class='meta'>{meta}</div>",
        "</div>",
        "<div id='colpo-docchio'></div>",
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
        parts.append("<div class='section-title' id='alloggio'>Il tuo alloggio</div>")
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
        # [ESTESO 2026-08-01 — punto 6 del feedback "da investitore"] La frase
        # sui link di ricerca c'era già; quello che mancava era la conseguenza
        # legale, ed è proprio qui che serve. Un elenco di link a piattaforme di
        # prenotazione stampato sotto un itinerario è il punto del documento in
        # cui qualcuno potrebbe leggere il tutto come un'offerta combinata di
        # servizi turistici — attività regolata, con obblighi che questo
        # servizio non ha e non vuole avere. Il testo sta in src/legal_notices.py
        # perché la stessa frase deve comparire identica nei Termini, nel modulo
        # d'ordine e nell'email: tre copie a mano divergono, una sola no.
        parts.append(
            "<div class='disclaimer'>Confronta anche su altre piattaforme — link di ricerca "
            "pubblica (non dati live/prezzi verificati di queste piattaforme). "
            f"{_esc(legal_notices.BOOKING_LINKS_NOTICE)}</div>"
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

    if curated_html:
        parts.append("<div id='selezione'></div>")
        parts.append(curated_html)

    poi_energy = _build_poi_energy_lookup(poi)
    if poi_energy and _itinerary_has_any_energy_info(itinerary, poi_energy):
        parts.append(_render_energy_legend())

    location_lookup = _build_location_lookup(hotels, poi)

    if days:
        parts.append(
            "<div class='section-title' id='giorno-per-giorno'>"
            "Il programma, giorno per giorno</div>"
        )
        parts.append(
            "<div class='section-intro'>Ogni giornata ha la sua cartina con le tappe numerate "
            "nell'ordine di visita, la legenda che spiega ogni indicatore, e i tragitti "
            "spostamento per spostamento con il percorso già pronto da aprire.</div>"
        )

    for day in days:
        # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
        # il rendering PDF NON è gated sull'esito PASS del Nodo 9 (main.py e
        # /v1/pdf possono renderizzare un itinerario non ancora validato), quindi
        # deve tollerare le stesse forme inattese del validator: `days`/`day`/
        # `blocks`/`block` = None o non-dict.
        blocks = day.get("blocks") or []
        if not isinstance(blocks, list):
            blocks = []
        blocks = [b for b in blocks if isinstance(b, dict)]
        day_number = day.get("day")

        # [AGGIUNTO 2026-07-31] Cartina del giorno + legenda PRIMA dei
        # blocchi: si guarda la mappa per capire la forma della giornata, poi
        # si legge il dettaglio. L'ordine inverso costringeva a tornare
        # indietro (comportamento osservato da Lorenzo sul proprio viaggio).
        day_title_html = (
            f"<div class='day-title'>Giorno {_esc(day_number)} — "
            f"{_esc(day.get('title', ''))}</div>"
        )
        day_map_html = _render_day_map(day_maps_by_day.get(day_number), day_title_html)
        if day_map_html:
            parts.append(
                f"<div class='day-open' id='giorno-{_esc(day_number)}'>"
                f"{day_map_html}</div>"
            )

        # [FIX 2026-07-11 — secondo audit adversariale; nota aggiornata
        # 2026-07-31] Da quando `page-break-inside: avoid` vive sul singolo
        # `.block` e non più sull'intera `.day-card` (vedi CSS), una giornata
        # lunga fluisce naturalmente su più pagine. Questo spezzettamento resta
        # comunque necessario: garantisce che ogni tronco riporti il proprio
        # titolo con " (continua)", così il cliente che gira pagina sa ancora
        # di quale giorno sta leggendo il programma.
        _MAX_BLOCKS_PER_DAY_CARD = 20
        chunks = [
            blocks[i : i + _MAX_BLOCKS_PER_DAY_CARD]
            for i in range(0, len(blocks), _MAX_BLOCKS_PER_DAY_CARD)
        ] or [[]]

        for chunk_index, chunk in enumerate(chunks):
            parts.append("<div class='day-card'>")
            suffix = " (continua)" if chunk_index > 0 else ""
            id_attr = "" if day_map_html or chunk_index > 0 else f" id='giorno-{_esc(day_number)}'"
            # [CORRETTO 2026-07-31] Quando la cartina c'è, il titolo del
            # giorno è già stampato accanto ad essa poche righe sopra:
            # ripeterlo qui lo faceva leggere due volte di fila a distanza di
            # un centimetro. Nei tronchi di continuazione invece va sempre
            # ripetuto — è tutto il motivo per cui esiste lo spezzettamento.
            if not (day_map_html and chunk_index == 0):
                parts.append(
                    f"<div class='day-title'{id_attr}>Giorno {_esc(day_number)} — "
                    f"{_esc(day.get('title', ''))}{suffix}</div>"
                )
            for block in chunk:
                # [DELIBERATO] Il `poi_id` (mostrato come `[POI1]` in
                # renderer.py) è un marcatore interno di audit/grounding per la
                # revisione qualità (Nodo 9) — non ha senso in un documento
                # cliente premium, quindi qui NON viene mostrato.
                poi_id = block.get("poi_id")
                energy_chip = _render_energy_chip(poi_id, poi_energy) if poi_energy else ""
                parts.append(
                    "<div class='block'>"
                    f"<span class='block-time'>{_esc(block.get('time'))}</span> "
                    f"<span class='block-activity'>{_esc(block.get('activity'))} "
                    f"({_esc(block.get('location', ''))})</span>"
                    f"{energy_chip}"
                )
                if block.get("logistics"):
                    parts.append(f"<div class='block-logistics'>{_esc(block['logistics'])}</div>")
                parts.append(_render_place_links(poi_id, place_cards))
                parts.append(_render_guide_link(poi_id, guide_anchors))
                parts.append(_render_maps_link(poi_id, location_lookup, place_cards))
                parts.append("</div>")
            parts.append("</div>")

        # [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "manca anche la parte
        # 'cartina e come arrivare'"] Subito dopo il programma della
        # giornata, non in un capitolo separato in fondo: serve mentre si
        # legge quella giornata, non a fine documento.
        legs_html = _render_directions(directions_by_day.get(day_number))
        if legs_html:
            parts.append("<div class='day-card'>")
            parts.append(
                f"<div class='day-title'>Come arrivare — giorno {_esc(day_number)}</div>"
            )
            parts.append(legs_html)
            parts.append("</div>")

    if costs_html:
        parts.append("<div class='section-title' id='costi'>Stima dei costi e dettaglio budget</div>")
        parts.append(
            "<div class='section-intro'>Calcolata sui prezzi e sulle fasce di prezzo reali dei "
            "luoghi selezionati, non su una media generica della destinazione.</div>"
        )
        parts.append(costs_html)

    if tips_html:
        # Il nome "Architect's Tips" è un elemento di marca del prodotto (lo
        # usa anche src/renderer.py per l'output markdown): resta, con la
        # traduzione accanto perché il documento è per un cliente italiano.
        parts.append(
            "<div class='section-title' id='consigli'>"
            "Architect's Tips — i consigli dell'Architetto</div>"
        )
        parts.append(
            "<div class='section-intro'>Consigli legati a questo itinerario e a queste date — "
            "non consigli di viaggio validi ovunque.</div>"
        )
        parts.append(tips_html)

    if rain_html:
        parts.append("<div class='section-title' id='piani-b'>Piani B: se piove</div>")
        parts.append(
            "<div class='section-intro'>Alternative al chiuso scelte tra i luoghi reali già "
            "verificati per la tua destinazione, con lo stesso criterio del programma "
            "principale.</div>"
        )
        parts.append(rain_html)

    if guide_list:
        parts.append(
            "<div class='section-title' id='guide'>Guide turistiche tascabili</div>"
        )
        parts.append(
            "<div class='section-intro'>Una scheda per ogni luogo del programma: cosa stai "
            "guardando, cosa cercare una volta dentro, quanto tempo serve davvero. "
            "Dal programma puoi saltare direttamente alla scheda che ti serve.</div>"
        )
        for guide in guide_list:
            parts.append(_render_guide_section(guide, guide.get("_anchor")))

    # [AGGIORNATO 2026-08-01] La sezione esce anche se la generazione del
    # messaggio personalizzato e' fallita, purche' ci sia un link a cui
    # rispondere: il ciclo di dati non deve dipendere da una chiamata al
    # modello andata storta.
    if feedback or feedback_link:
        parts.append("<div id='recensione'></div>")
        parts.append(_render_feedback_section(feedback, feedback_link))

    # [ESTESO 2026-08-01 — punto 6 del feedback "da investitore"] Il piede
    # diceva solo "verifica gli orari". La natura del servizio — informazione,
    # non pacchetto turistico — non compariva in nessun punto del documento che
    # il cliente porta con sé, e il PDF è l'unico artefatto che gli resta in
    # mano e che eventualmente gira. Va scritto qui, non solo nei Termini.
    parts.append(
        "<div class='footer'>Documento generato automaticamente — verificare sempre orari "
        "di apertura e disponibilità prima della partenza.<br>"
        f"{_esc(legal_notices.NATURE_SHORT)}</div>"
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
    day_maps: list[dict] | None = None,
    directions: list[dict] | None = None,
    cost_summary: dict | None = None,
    tips: dict | None = None,
    place_cards: dict | None = None,
    feedback_link: dict | None = None,
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
        poi=poi, map_png_bytes=map_png_bytes, day_maps=day_maps,
        directions=directions, cost_summary=cost_summary, tips=tips,
        place_cards=place_cards, feedback_link=feedback_link,
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
        # [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "reindirizzi il cliente
        # alla fine del pdf dove è presente la guida turistica" + "il pdf in sé
        # deve essere ... facile da comprendere"]
        # - `--enable-internal-links`: senza questo flag wkhtmltopdf stampa gli
        #   `<a href='#ancora'>` come testo morto. I link "Guida turistica
        #   tascabile" e l'indice cliccabile sono l'unico modo per navigare un
        #   documento da 30+ pagine, e funzionano anche offline/in aereo —
        #   che è esattamente quando il cliente li usa.
        # - `--outline`: genera i segnalibri PDF nativi (il pannello laterale
        #   dei lettori), navigazione che non costa una pagina di carta.
        # - `--footer-center`: numeri di pagina. Un documento che il cliente
        #   stampa senza numeri di pagina è ingestibile se cade per terra.
        result = subprocess.run(
            [
                "wkhtmltopdf", "--quiet",
                "--enable-internal-links",
                "--outline",
                "--footer-center", "[page] / [topage]",
                "--footer-font-size", "8",
                "--footer-spacing", "5",
                tmp_html_path, tmp_pdf_path,
            ],
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
