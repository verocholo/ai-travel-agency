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
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

from .affiliate_links import build_search_links
from . import impaginazione
from .directions import describe_leg_duration, summarize_day_travel
from .price_display import price_level_symbol
# [AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore"] Testi legali
# rivolti al cliente, tenuti in un solo posto: vedi src/legal_notices.py.
from . import compositore, foto
from . import legal_notices
# [AGGIUNTO 2026-08-05 — task #190] La cucitura dei capitoli staccati dentro
# un unico file, e i nomi delle ancore di ritorno. Il modulo non importa
# `pdf_renderer` di rimando, di proposito: sarebbe un giro chiuso che farebbe
# fallire l'avvio del servizio.
from . import fascicolo
from . import pdf_links
# [AGGIUNTO 2026-08-02 — task #166] Aritmetica del ritmo della giornata,
# tenuta fuori dal renderer perché è logica pura e va testata da sola.
from . import pacing
# [AGGIUNTO 2026-08-03 — task #180] Il criterio con cui è costruita una
# giornata (meno spostamenti, orari di apertura veri, pause programmate) e il
# controllo che lo verifica. Sta fuori dal renderer per la stessa ragione di
# `pacing`: il renderer stampa, non decide.
from . import scheduling_criteria


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


def _paragraphs(text, css_class: str = "guide-para") -> str:
    """Un testo a più paragrafi diventa più paragrafi anche nel documento.

    [AGGIUNTO 2026-08-02] Sembra ovvio ed è esattamente il motivo per cui è
    rimasto rotto per settimane. I prompt chiedono da sempre "paragrafi
    separati da due ritorni a capo", il modello li produce onestamente, e poi
    il renderer li passava a `_esc()` dentro un solo `<div>`: in HTML il
    ritorno a capo è spazio bianco, quindi tre paragrafi arrivavano al cliente
    come un unico blocco compatto. Nessun errore, nessun log, solo un
    documento più faticoso da leggere — e tanto più faticoso quanto più il
    testo era ricco, cioè il difetto peggiorava proprio dove il prodotto
    migliorava.

    Tollera sia `\\n\\n` sia il ritorno a capo singolo che alcuni modelli
    usano al suo posto: un paragrafo perso vale più di una regola pura."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if len(blocks) <= 1:
        # Nessun doppio a capo: si prova con quello singolo, ma solo se ce
        # n'è più d'uno — altrimenti si spezzerebbe a metà una frase mandata
        # a capo per larghezza.
        singles = [b.strip() for b in raw.split("\n") if b.strip()]
        blocks = singles if len(singles) > 1 else blocks
    if not blocks:
        return ""
    return "".join(f"<p class='{css_class}'>{_esc(b)}</p>" for b in blocks)


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
_CSS_MODELLO = """
    @page { size: A4; margin: 2cm 1.8cm; }
    * { box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #22303f;
      line-height: 1.5;
      margin: 0;
    }
    .header {
      background-color: {{scuro}};
      color: #ffffff;
      padding: 28px 32px;
      border-radius: 0;
      margin-bottom: 24px;
    }
    .header h1 { margin: 0 0 8px 0; font-size: 26px; }
    .header .meta { font-size: 13px; color: {{chiaro_su_scuro}}; }
    /* [RIFATTO 2026-08-05 — task #195] Con le grazie e piu' grande, sopra
       un filetto da un pixel invece che da due. Il carattere con le grazie
       e' quello dei libri: dice «questo si legge». Il filetto sottile
       separa senza gridare — un bordo spesso e' il modo in cui un documento
       ammette di non fidarsi della propria gerarchia. */
    .section-title {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 21px;
      font-weight: normal;
      color: #16212f;
      border-bottom: 1px solid {{bordo_caldo}};
      padding-bottom: 8px;
      margin: 26px 0 12px 0;
    }
    .summary-box {
      background: {{sfondo_caldo}};
      border-left: 4px solid {{primario}};
      padding: 14px 18px;
      border-radius: 0;
      font-size: 13px;
    }
    .budget-alert {
      background: #fdf1e8;
      border-left: 4px solid {{accento}};
      padding: 14px 18px;
      border-radius: 0;
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
    /* [RIFATTO 2026-08-05 — task #195] La scatola attorno alla giornata e'
       sparita: restava un rettangolo dentro un rettangolo dentro la pagina.
       Un filetto in alto basta a dire «qui comincia un giorno», e libera
       quattro centimetri di larghezza per il testo. */
    .day-card {
      border: none;
      border-top: 2px solid #16212f;
      padding: 14px 0 0 0;
      margin-bottom: 20px;
    }
    .day-title {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 19px; font-weight: normal; color: #16212f;
      margin-bottom: 12px;
    }
    .block { padding: 8px 0; border-top: 1px solid {{sfondo_tenue}}; page-break-inside: avoid; }
    .block:first-child { border-top: none; }
    .block-time { font-weight: bold; color: {{primario}}; font-size: 12px; display: inline-block; min-width: 52px; }
    .block-activity { font-size: 13px; }
    .block-logistics { font-size: 11px; color: #6b7a89; font-style: italic; margin-top: 2px; }
    /* [AGGIUNTO 2026-08-02 — task #166] La riga del margine. Colore e bordo
       sinistro la distinguono dalla logistica senza aggiungere un riquadro:
       e' un'informazione di ritmo, non un avviso. Solo tinte piatte e
       bordi solidi: il motore di stampa e' Qt WebKit del 2014 e ignora
       tutto il resto (i test lo verificano cercando i token vietati nel
       CSS, per questo qui non si possono nemmeno nominare). */
    .block-margin {
      font-size: 11px;
      color: {{accento_testo}};
      background: {{sfondo_caldo}};
      border-left: 3px solid {{accento}};
      padding: 3px 8px;
      margin-top: 3px;
    }
    /* [AGGIUNTO 2026-08-03 — task #180] La segnalazione "porta chiusa".
       Rossa e non gialla di proposito: il margine di ritmo e' un'informazione
       sul come impiegare il tempo, questa e' una cosa da sistemare prima di
       partire. Se avessero lo stesso colore il cliente imparerebbe a saltarle
       entrambe, e quella che conta e' questa. */
    .block-chiuso {
      font-size: 11px;
      color: #8c2f26;
      background: #fbeeec;
      border-left: 3px solid #c0392b;
      padding: 3px 8px;
      margin-top: 3px;
    }
    /* [AGGIUNTO 2026-08-03 — task #180] Il riquadro che dichiara il criterio:
       tre righe in tutto, una sola volta nel documento, sotto l'occhiello del
       programma. Deliberatamente piu' piccolo e piu' spento del testo del
       programma: e' la regola del gioco, non il gioco. */
    .criterio { margin: 0 0 10px 0; }
    .criterio-riga { font-size: 11px; color: #55636f; margin-bottom: 3px; }
    .criterio-nome { color: #24303a; font-weight: bold; }
    /* [AGGIUNTO 2026-07-13 (ter) — vedi _render_maps_link()] Link diretto
       alle coordinate reali del blocco, stile compatto coerente con
       .block-logistics (stessa gerarchia visiva: informazione di
       contorno, non il testo principale del blocco). */
    .block-maps-link { font-size: 11px; margin-top: 2px; }
    .block-maps-link a { color: {{primario}}; text-decoration: none; }
    .tips-box {
      background: #eef6f0;
      border-left: 4px solid #3f8f5f;
      padding: 14px 18px;
      border-radius: 0;
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
      background: {{sfondo_caldo}};
      border: 2px solid {{accento}};
      border-radius: 0;
      margin: 14px 0;
      page-break-inside: avoid;
    }
    .cta-box td { padding: 14px 18px; }
    .cta-title {
      font-size: 14px;
      font-weight: bold;
      color: {{accento_testo}};
      margin-bottom: 6px;
    }
    .cta-link { font-size: 12px; word-wrap: break-word; }
    .cta-link a { color: {{primario}}; }
    .cta-note { font-size: 11px; color: #555555; margin-top: 6px; }
    .platforms-box { font-size: 12px; }
    .platforms-box .hotel-row { margin-bottom: 6px; }
    /* Il nome davanti ai pulsanti quando le strutture sono due: senza, le due
       righe sono indistinguibili. Vedi la nota nel punto in cui si stampa. */
    .platforms-for {
      display: inline-block; min-width: 120px;
      font-size: 11px; color: #4a5b6b; font-weight: bold;
    }
    .platforms-box a {
      display: inline-block;
      font-size: 11px;
      color: #ffffff;
      background: {{primario}};
      padding: 3px 10px;
      border-radius: 0;
      text-decoration: none;
      margin-right: 6px;
    }
    .disclaimer { font-size: 10px; color: #8a97a3; margin-top: 4px; }
    /* [RIDOTTO 2026-08-02 — task #168] Il piede prendeva 28px di stacco.
       Su un documento che finiva al 97,7% dell'ultima pagina piena, quei 28px
       erano esattamente ciò che spingeva DUE righe di piede su una pagina
       tutta sua: una pagina intera per una riga di avvertenza. Lo stacco che
       serve a separare il piede dal contenuto è la metà. */
    .footer { margin-top: 14px; font-size: 10px; color: #9aa6b1; text-align: center; }
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
       la sintesi d'apertura: cartina d'insieme + quadro delle giornate. [CORRETTO 2026-07-13 (ter) — stesso fix di `.page-break`
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
    /* --- Il quadro delle giornate ----------------------------------------
       [SOSTITUISCE 2026-08-02 (ter) — task #168 i riquadri "stat-tile" e la
       striscia "day-strip-item"] I riquadri ripetevano destinazione, date,
       durata, budget e alloggio, cioe' esattamente cio' che la copertina
       dice UNA PAGINA PRIMA; la striscia ripeteva i titoli dei giorni, che
       l'indice di copertina gia' elenca. Erano due elenchi contigui che
       dicevano la stessa cosa: lo stesso difetto che aveva gia' imposto la
       fusione di copertina e indice. Al loro posto una tabella che dice
       qualcosa di NUOVO: per ogni giornata la data vera con il giorno della
       settimana, la finestra oraria in cui si muove e quante tappe contiene.
       E' la forma del viaggio, non la sua ripetizione. */
    .glance-days { width: 100%; border-collapse: collapse; margin: 12px 0 0 0; }
    .glance-days td {
      border-top: 1px solid {{bordo}};
      padding: 8px 8px 8px 0;
      vertical-align: top;
      font-size: 11.5px;
      color: #4a5b6b;
    }
    .glance-days tr:first-child td { border-top: none; }
    .glance-n { width: 92px; color: {{scuro}}; font-weight: bold; white-space: nowrap; }
    .glance-date {
      font-size: 9px; font-weight: normal; color: #7b8896;
      letter-spacing: .1em; text-transform: uppercase; margin-top: 3px;
    }
    .glance-t { color: {{scuro}}; }
    .glance-m {
      width: 126px; text-align: right; white-space: nowrap;
      font-size: 10.5px; color: #6b7a89;
    }
    .glance-m b { color: {{scuro}}; font-weight: bold; }
    .map-image { text-align: center; margin: 16px 0 4px 0; }
    .map-image img { max-width: 100%; border-radius: 0; border: 1px solid {{bordo_caldo}}; }
    /* [AGGIUNTO 2026-08-03 - richiesta di Lorenzo: "la cartina deve essere
       interattiva, ci puoi cliccare e li trovi tutto quello inerente a
       quello ... come se fosse uno zoom out dal macro al micro"]
       Sopra la cartina appoggiamo delle zone cliccabili invisibili, una per
       pallino. Il guscio deve essere `inline-block` e non un blocco pieno:
       un blocco largo quanto la pagina renderebbe le percentuali dei figli
       relative alla PAGINA e non all'immagine, e le zone finirebbero
       spostate. `inline-block` fa aderire il guscio all'immagine.
       Niente colore di sfondo, niente bordo, niente trasparenza: il motore
       Qt di wkhtmltopdf non sa fare la trasparenza (vedi la nota in cima al
       CSS), quindi l'unico modo di rendere invisibile una zona e' non
       disegnarci NULLA dentro. Il carattere da un pixel serve a impedire
       che lo spazio unificatore dentro l'ancora venga disegnato. */
    .map-clickable { position: relative; display: inline-block; }
    .map-hit {
      position: absolute; display: block; text-decoration: none;
      color: #ffffff; font-size: 1px; line-height: 1px; overflow: hidden;
    }
    /* La riga di legenda cliccabile e' la rete di sicurezza della cartina
       interattiva: centrare il dito su un pallino di sei millimetri e'
       difficile su un telefono, e su una stampa di carta e' impossibile.
       Il colore resta quello del testo: un link che si vede e' rumore in
       una legenda gia' fitta, e la riga si capisce che e' cliccabile
       perche' il documento lo dice una volta sola, nella didascalia. */
    .map-legend-row a.legend-link { color: #1f2b38; text-decoration: none; }
    /* [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "ristoranti/hotel/
       intrattenimento", "segnare ogni costo"] */
    .curated-grid { width: 100%; border-collapse: collapse; }
    .curated-grid td { width: 50%; vertical-align: top; padding: 0 14px 0 0; }
    .curated-item { padding: 5px 0; border-bottom: 1px solid {{sfondo_tenue}}; font-size: 12.5px; }
    .price-badge { color: {{primario}}; font-weight: bold; margin-left: 6px; font-size: 11px; }
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
    /* [RIFATTO 2026-08-05 — task #195] Erano tre pastiglie piene, rosso
       verde e arancio: le uniche macchie di colore acceso di tutto il
       documento, e finivano per gridare piu' del nome del luogo a cui erano
       attaccate. Adesso sono etichette in maiuscoletto con un filetto
       sotto: si leggono quando le cerchi e spariscono quando leggi il
       programma. Il colore resta — dice una cosa vera sul ritmo — ma sul
       TESTO e sul filetto, non su un fondo pieno. */
    .energy-chip {
      display: inline-block;
      font-size: 8.5px;
      font-weight: bold;
      letter-spacing: .10em;
      text-transform: uppercase;
      background: none;
      padding: 0 0 1px 0;
      margin-left: 10px;
      vertical-align: middle;
    }
    .energy-chip.energy-high { color: #a3423a; border-bottom: 2px solid #a3423a; }
    .energy-chip.energy-medium { color: {{accento_testo}}; border-bottom: 2px solid {{accento}}; }
    .energy-chip.energy-low { color: #55705f; border-bottom: 2px solid #55705f; }
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

    /* --- Copertina + indice, sulla STESSA pagina ------------------------
       [RIFATTO 2026-08-02 — task #168, segnalazione di Lorenzo:
       «l'impaginazione: troppi spazi vuoti dispersivi» e «il design deve
       essere estremamente figo da vedere»]

       Prima erano due pagine consecutive, e nessuna delle due era piena: la
       copertina si fermava a circa il 40% dell'altezza, l'indice al 28%. Ma il
       difetto peggiore non era il bianco: era che le DUE pagine elencavano gli
       STESSI undici capitoli. Il cliente pagante girava la prima pagina e
       trovava, di nuovo, la stessa lista. Due pagine quasi vuote che si
       ripetono a vicenda sono il caso da manuale di "spazio disperso".

       Ora la pagina è una sola e fa entrambi i lavori: la fascia scura in alto
       dà il colpo d'occhio, la griglia dei dati dice i fatti, l'indice
       cliccabile — quello vero, con i giorni annidati — riempie la metà
       inferiore. Una pagina piena al posto di due mezze vuote.

       Vincoli del motore, non scelte di gusto: i fondali sono tinte piatte e i
       bordi sono solidi, perché wkhtmltopdf non renderizza le sfumature né la
       trasparenza; le colonne sono TABELLE, perché la scatola flessibile lì non
       esiste. I nomi esatti di quelle proprietà non compaiono qui apposta: i
       test di regressione li cercano nell'intero HTML prodotto, commenti
       compresi. */
    .cover { page-break-after: always; }
    /* [RIVISTO 2026-08-02 (bis) — task #168] La copertina rifatta occupava
       ancora solo il 45% dell'altezza: piena a metà è comunque una pagina
       dispersiva, e per giunta è LA pagina che il cliente vede per prima.
       Le proporzioni qui sotto sono tarate per arrivare in fondo al foglio
       senza traboccare sulla seconda pagina: fascia scura alta, griglia dei
       fatti con più respiro, striscia "come si legge", indice, e la nota
       sui dati appoggiata in basso come un piede di pagina. */
    /* [RIFATTO 2026-08-05 — task #195, richiesta di Lorenzo: «migliora in
       maniera professionale, accattivante e definitiva il design e lo stile
       di tutto il pdf, deve essere facilmente riconoscibile, e si deve
       distinguere dal resto del mercato per la sua qualita' grafica», con
       la sua scelta esplicita: stile «editoriale di lusso»]

       La copertina era un pannello blu con gli angoli tondi: la stessa cosa
       che fa qualunque prodotto software. Adesso e' CARTA — fondo bianco,
       il nome della citta' grande, con le grazie, in inchiostro, e un solo
       filetto d'oro sopra. E' il modo in cui si apre una guida di citta',
       non un cruscotto.

       Il bianco non e' pigrizia: e' la scelta piu' costosa che ci sia in
       tipografia, perche' non lascia niente dietro cui nascondersi. Se il
       contenuto e' scarso, su fondo bianco si vede. */
    .cover-hero {
      background-color: #ffffff;
      color: #16212f;
      padding: 26px 0 34px 0;
      border-top: 3px solid {{accento}};
      margin-bottom: 26px;
    }
    .cover-kicker {
      font-size: 10px; letter-spacing: .22em; text-transform: uppercase;
      color: {{accento_testo}}; margin-bottom: 30px; font-weight: bold;
    }
    .cover-title {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 66px; line-height: 1.02; color: #16212f;
      margin: 0 0 20px 0; font-weight: normal;
    }
    .cover-rule { border-top: 3px solid {{accento}}; margin: 0 0 14px 0; width: 90px; }}; width: 100%; margin: 0 0 18px 0; }
    .cover-sub {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 15.5px; font-style: italic; color: #6c7683;
      margin: 0 0 30px 0;
    }

    /* --- Il blocco della copertina (task #218) -------------------------
       [AGGIUNTO 2026-08-15] Fotografia tonda, titolo, bollo della durata,
       tutti dentro un blocco di colore pieno.

       Tre note su cose che con questo motore di stampa NON si possono fare,
       e che qui sono state aggirate invece che scoperte sulla carta:

       1. la fotografia tonda NON si ottiene arrotondando gli angoli col
          foglio di stile — viene una figura mezza tonda e mezza quadrata. Si
          ritaglia sui pixel prima (`foto.ritaglia_tondo`), e qui arriva gia'
          rotonda;
       2. il bollo invece SI', perche' e' un riquadro di colore vuoto: un
          quadrato con il raggio pari a meta' del lato diventa un cerchio
          vero. E' l'unica forma tonda che questo motore disegna;
       3. affiancare si fa con le tabelle e basta. */
    .cover-blocco {
      background: {{primario}};
      padding: 22px 26px 24px 26px;
      margin-bottom: 8px;
    }
    .cover-blocco-t { width: 100%; border-collapse: collapse; }
    .cover-blocco-t td { padding: 0; border: none; vertical-align: middle; }
    .cover-tonda { width: 112px; padding-right: 22px !important; }
    .cover-tonda img { width: 100px; display: block; }
    .cover-blocco-testo .cover-kicker {
      color: {{accento_su_scuro}}; margin-bottom: 8px;
    }
    .cover-blocco-testo .cover-title {
      color: #ffffff; font-size: 52px; margin: 0 0 12px 0;
    }
    .cover-blocco-testo .cover-rule {
      border-top: 3px solid {{accento_su_scuro}}; margin: 0 0 10px 0;
    }
    .cover-blocco-testo .cover-sub {
      color: {{chiaro_su_scuro}}; font-size: 13.5px; margin: 0;
    }
    .cover-bollo-cella { width: 96px; padding-left: 18px !important; }
    .cover-bollo {
      width: 78px; height: 78px; border-radius: 39px;
      background: {{accento}}; color: #ffffff; text-align: center;
    }
    .cover-bollo-n {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 34px; line-height: 1; padding-top: 18px;
    }
    .cover-bollo-t {
      font-size: 9px; letter-spacing: .18em; text-transform: uppercase;
    }
    /* La striscia chiara dentro la fascia scura: ripete le due informazioni
       che il cliente cerca per prime (quando parte, quanto dura) in un punto
       dove non può sfuggirgli. Sfondo a tinta piatta, mai trasparenze. */
    .cover-hero-strip { width: 100%; border-collapse: separate; border-spacing: 0; }
    .cover-hero-strip td {
      border-top: 1px solid {{bordo_caldo}};
      padding: 16px 0 0 0; vertical-align: top; width: 50%;
    }
    .cover-hero-k {
      font-size: 9px; letter-spacing: .16em; text-transform: uppercase;
      color: #6c7683; margin-bottom: 5px;
    }
    .cover-hero-v {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px; color: #16212f;
    }
    /* La griglia dei fatti: riquadri secchi, un dato per casella, ma
       in chiaro e su tre colonne. Il bordo a sinistra in arancio è l'unico
       accento di colore, e serve a far leggere la griglia come una riga sola
       invece che come sei caselle scollegate. */
    .cover-facts { width: 100%; border-collapse: separate; border-spacing: 7px; margin: 0 -7px; }
    .cover-facts td { vertical-align: top; padding: 0; width: 33%; }
    /* Niente angoli arrotondati QUI: il motore di stampa, quando un riquadro
       ha insieme l'angolo tondo e un bordo colorato su un lato solo,
       "srotola" quel bordo lungo il fondo del riquadro dell'ultima riga —
       nel PDF vero si vedeva una codina arancione sotto ogni casella in
       basso. Angoli vivi, difetto sparito. Vedi il resto della copertina:
       l'angolo tondo resta dove non c'e' bordo laterale. */
    /* [RIFATTO 2026-08-05 — task #195] Erano sei caselle colorate con il
       bordo a sinistra: una griglia di widget. Adesso sono sei dati sotto
       un filetto, come le didascalie di una rivista. Meno inchiostro, piu'
       aria, e i numeri si leggono meglio proprio perche' non c'e' piu' una
       scatola attorno a chiedere attenzione. */
    .cover-fact {
      background-color: #ffffff;
      border-top: 1px solid {{bordo_caldo}};
      padding: 12px 0 4px 0;
    }
    .cover-fact-k {
      font-size: 9px; letter-spacing: .12em; text-transform: uppercase;
      color: #6b7a89; margin-bottom: 5px;
    }
    .cover-fact-v {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px; color: #16212f; line-height: 1.25;
    }
    /* --- "Come si legge questo documento" -------------------------------
       [AGGIUNTO 2026-08-02 (bis) — task #168] Tre righe che spiegano le tre
       cose che il cliente non scoprirebbe da solo: che il PDF è cliccabile,
       che le tappe sulla cartina della giornata sono pulsanti, e che i dati
       mancanti sono marcati invece che inventati. Riempiono la copertina con qualcosa che
       serve, non con decorazione: è la differenza fra una pagina piena e una
       pagina gonfiata. */
    .cover-how { margin-top: 26px; }
    .cover-how-title {
      font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
      color: {{primario}}; margin-bottom: 9px;
    }
    .cover-how table { width: 100%; border-collapse: separate; border-spacing: 7px; margin: 0 -7px; }
    .cover-how td { width: 33%; vertical-align: top; padding: 0; }
    .cover-how-cell {
      background-color: #ffffff;
      border: 1px solid {{bordo_caldo}};
      border-radius: 0;
      padding: 14px 14px;
      font-size: 10.5px;
      color: #4a5b6b;
      line-height: 1.4;
    }
    .cover-how-cell b { color: {{scuro}}; }
    .cover-toc { margin-top: 26px; border-top: 2px solid {{bordo_caldo}}; padding-top: 18px; }
    .cover-toc-title {
      font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
      color: {{primario}}; margin-bottom: 10px;
    }
    .cover-toc table { width: 100%; border-collapse: collapse; }
    .cover-toc td.col { width: 50%; vertical-align: top; padding: 0 14px 0 0; }
    .cover-toc-item {
      font-size: 12px; color: {{scuro}}; padding: 9px 0;
      border-bottom: 1px solid {{sfondo_tenue}};
    }
    /* Le voci di copertina sono link, ma non devono SEMBRARE link: la
       copertina e' l'unica pagina in cui la grafica viene prima della
       segnaletica. Restano cliccabili, in nero come il resto. */
    .cover-toc-item a { color: {{scuro}}; text-decoration: none; }
    .cover-toc-num {
      display: inline-block; width: 22px;
      color: {{accento_testo}}; font-weight: bold; font-size: 11px;
    }
    /* I giorni annidati sotto "Il programma": rientrati, più piccoli, senza
       numero proprio — sono un dettaglio del capitolo 4, non un capitolo. */
    .cover-toc-sub {
      font-size: 11px; color: #4a5b6b; padding: 7px 0 7px 22px;
      border-bottom: 1px solid {{sfondo_caldo}};
    }
    .cover-toc-sub a { color: #4a5b6b; text-decoration: none; }
    .cover-note {
      /* [AGGIUNTO 2026-08-11] Se proprio non ci sta, si sposta INTERA.
         Spezzata lascia una riga orfana in cima alla pagina dopo, che e'
         esattamente il difetto segnalato. `page-break-inside` il motore di
         stampa lo rispetta sulle tabelle e sui blocchi semplici come questo. */
      page-break-inside: avoid;
      font-size: 9.5px; color: #6b7a89; margin-top: 26px;
      background-color: {{sfondo_caldo}};
      border-left: 3px solid {{primario}};
      border-radius: 0;
      padding: 15px 16px;
      line-height: 1.45;
    }

    /* --- I due livelli di respiro della copertina -------------------------
       [AGGIUNTO 2026-08-02 (bis) — task #168] Vedi la nota in `_render_cover()`
       per il perché ce ne sono tre. Qui ci sono solo i due livelli PIÙ larghi:
       il terzo è il valore base scritto sopra, quello che non sborda mai.
       I numeri sono tarati misurando il PDF prodotto, pagina per pagina. */
    .cover-roomy .cover-hero { padding: 74px 40px 66px 40px; }
    .cover-roomy .cover-title { font-size: 62px; }
    .cover-roomy .cover-fact { padding: 19px 15px; }
    .cover-roomy .cover-toc { margin-top: 30px; padding-top: 21px; }
    .cover-roomy .cover-toc-item { padding: 11px 0; }
    .cover-roomy .cover-toc-sub { padding: 8px 0 8px 22px; }
    .cover-roomy .cover-how { margin-top: 30px; }
    .cover-roomy .cover-how-cell { padding: 17px 14px; }
    .cover-roomy .cover-note { margin-top: 30px; padding: 17px 16px; }

    .cover-airy .cover-hero { padding: 92px 40px 84px 40px; }
    .cover-airy .cover-title { font-size: 66px; }
    .cover-airy .cover-sub { margin-bottom: 30px; }
    .cover-airy .cover-fact { padding: 22px 15px; }
    .cover-airy .cover-toc { margin-top: 36px; padding-top: 24px; }
    .cover-airy .cover-toc-item { padding: 13px 0; }
    .cover-airy .cover-toc-sub { padding: 10px 0 10px 22px; }
    .cover-airy .cover-how { margin-top: 36px; }
    .cover-airy .cover-how-cell { padding: 20px 14px; }
    .cover-airy .cover-note { margin-top: 36px; padding: 20px 16px; }

    /* --- Titoli che non restano soli in fondo alla pagina ---------------
       [AGGIUNTO 2026-08-02 — task #168] Nel campione, "Il programma, giorno
       per giorno" cadeva sull'ultima riga della pagina 3 e il suo contenuto
       cominciava sulla 4: un titolo orfano, con sotto due centimetri di
       bianco. Il motore non onora la richiesta di "non spezzare DOPO" un
       elemento; onora invece "non spezzare DENTRO" una tabella. Quindi il
       titolo e il primo pezzo del suo contenuto viaggiano dentro una
       tabella-guscio: o entrano insieme in questa pagina, o vanno insieme
       nella prossima. */
    .keep { width: 100%; border-collapse: collapse; page-break-inside: avoid; }
    .keep td { padding: 0; border: none; }

    /* [AGGIUNTO 2026-08-03 — task #183] Lo stesso guscio, ma messo dalla
       passata finale di impaginazione attorno a ogni paragrafo di prosa
       abbastanza corto (vedi `_tieni_uniti_i_paragrafi`). Ha una classe
       propria e non riusa `.keep` per una ragione pratica: sono due cose che
       si toccano spesso — un paragrafo dentro una testa gia' tenuta insieme
       finisce in un guscio dentro l'altro — e con due nomi diversi si capisce
       leggendo l'HTML quale dei due ha creato un vuoto, invece di doverlo
       indovinare. Nessun margine e nessun bordo: il guscio non deve
       aggiungere nulla a quello che avvolge, altrimenti l'impaginazione
       cambia dove non e' stato chiesto. */
    .keep-prosa {
      width: 100%; border-collapse: collapse; page-break-inside: avoid;
      margin: 0; border: none;
    }
    .keep-prosa td { padding: 0; border: none; }

    /* --- Cartina del giorno ------------------------------------------- */
    .day-map { margin: 12px 0 6px 0; page-break-inside: avoid; }
    .day-map img { max-width: 100%; border-radius: 0; border: 1px solid {{bordo}}; }
    /* Cartina a sinistra, legenda numerata a destra: vedi la nota in
       `_render_day_map()` per il perché (il blocco impilato occupava più di
       metà pagina e sprecava tre pagine su quattordici). */
    .day-map-grid { width: 100%; border-collapse: collapse; }
    .day-map-grid td { vertical-align: top; padding: 0; }
    .day-map-figure { width: 62%; padding-right: 14px !important; }
    .day-map-key { width: 38%; }
    .map-caption {
      font-size: 8.5px; color: #7c8a99; line-height: 1.35;
      margin: 4px 0 0 0; padding: 0 2px;
    }
    .map-legend { margin: 8px 0 0 0; font-size: 11px; }
    .day-map-key .map-legend { margin-top: 0; }
    .map-legend-row { padding: 3px 0; }
    .map-pin {
      display: inline-block; width: 17px; height: 17px; line-height: 17px;
      text-align: center; border-radius: 0; color: #ffffff;
      font-size: 10px; font-weight: bold; margin-right: 7px; vertical-align: middle;
    }
    .map-pin.pin-red { background: #b23a3a; }
    .map-pin.pin-orange { background: {{accento}}; }
    .map-pin.pin-green { background: #3f8f5f; }
    .map-pin.pin-blue { background: {{primario}}; }
    .map-pin.pin-purple { background: #6b4a8f; }
    .map-pin.pin-yellow { background: #a8871f; }
    .map-legend-type { color: #6b7a89; font-size: 10px; }
    /* [AGGIUNTO 2026-08-02] Il ruolo della struttura (base / alternativa):
       stessa riga, peso visivo minore del nome — è una didascalia, non una
       seconda informazione da leggere. */
    .hotel-role { color: #6b7a89; font-size: 10px; font-style: italic; }

    /* --- Cartina e come arrivare -------------------------------------- */
    .legs { font-size: 12px; margin: 6px 0 2px 0; }
    .leg-row { padding: 7px 0; border-top: 1px solid {{sfondo_tenue}}; page-break-inside: avoid; }
    .leg-row:first-child { border-top: none; }
    .leg-arrow { color: {{primario}}; font-weight: bold; }
    .leg-meta { font-size: 11px; color: #6b7a89; margin-top: 2px; }
    .leg-meta a { color: {{primario}}; text-decoration: none; }
    .leg-unknown { color: #8a97a3; font-style: italic; }
    /* [AGGIUNTO 2026-08-01] L'ora di uscita e' l'unica riga azionabile della
       sezione: deve staccarsi dal grigio dei metadati. */
    .leg-depart { color: {{scuro}}; }

    /* [AGGIUNTO 2026-08-03 — task #179] Lo spostamento dentro il programma.
       Grigio e piccolo di proposito: e' la riga che si legge alzandosi dal
       tavolo, non il titolo della tappa. Sta DENTRO .block, che ha gia'
       page-break-inside: avoid, quindi non puo' separarsi dalla tappa a cui
       si riferisce. */
    .leg-inline { font-size: 10.5px; color: #6b7a89; margin: 0 0 3px 0; }
    .leg-inline a { color: {{primario}}; text-decoration: none; }
    .leg-inline-head { color: #8a97a3; }
    /* [AGGIUNTO 2026-08-03 — task #179] I chilometri della giornata, sotto al
       titolo del giorno. Non e' un metadato: e' il numero che dice se quella
       giornata e' fattibile con le scarpe che uno ha messo. */
    .day-total { font-size: 11px; color: {{primario}}; font-weight: bold;
                 margin: -6px 0 8px 0; }

    /* [AGGIUNTO 2026-08-03 — task #181, richiesta di Lorenzo: «inserisci
       alcune immagini con senso», «meno testo piu' immagini, non deve essere
       noioso»] Una fotografia per giornata, in apertura. UNA: il documento
       principale e' la vista da lontano, e una pagina piena di miniature
       sarebbe l'opposto dello "zoom out dal macro al micro" — le altre foto
       stanno dentro la guida della singola attrazione, cioe' dietro al
       pallino, dove chi le vuole vedere e' gia' andato a cercarle.
       L'altezza e' tagliata a una fascia: una foto verticale a piena pagina
       spingerebbe il programma della giornata alla pagina dopo, che e'
       esattamente il difetto che Lorenzo ha segnalato sull'impaginazione. */
    /* [CORRETTO 2026-08-11 — segnalazione di Lorenzo: «le foto sono
       stretchate».] C'era `width: 100%` INSIEME a `max-height: 150px`. Sono
       due ordini che si contraddicono: il primo dice «larga quanto la
       pagina», il secondo «alta al massimo cosi'», e il motore obbedisce a
       tutti e due schiacciando la fotografia. Una torre diventava tozza, un
       viale diventava una fessura.

       La regola giusta e' dire solo i LIMITI e lasciare che sia l'immagine a
       scegliere le proprie proporzioni dentro quei limiti. Una foto
       orizzontale riempie la fascia; una verticale resta stretta e centrata,
       con del bianco ai lati — che in una pagina impaginata bene non e' un
       difetto, e' respiro.

       `object-fit: cover`, che risolverebbe ritagliando, non esiste nel
       motore di stampa: e' una di quelle proprieta' che funzionano benissimo
       nell'anteprima del browser e vengono ignorate in silenzio nel PDF
       venduto. */
    /* La fila di fotografie in chiusura di giornata — vedi
       `_render_striscia_foto()` per il perche' delle tre scelte. */
    .day-striscia {
      width: 100%; border-collapse: separate; border-spacing: 6px;
      margin: 10px -6px 4px -6px; page-break-inside: avoid;
    }
    .day-striscia td { vertical-align: top; padding: 0; text-align: center; }
    .day-striscia img { max-width: 100%; max-height: 120px; }
    .day-striscia .didascalia {
      font-size: 8px; color: #98a4b0; margin-top: 3px; line-height: 1.3;
    }
    .day-foto { margin: 0 0 10px 0; text-align: center; }
    .day-foto img { max-width: 100%; max-height: 250px; }
    .day-foto .didascalia { font-size: 9px; color: #8a97a5; margin-top: 2px; }

    /* [AGGIUNTO 2026-08-03 — task #181] L'immagine in testa alla scheda di
       una guida. E' piu' bassa di quella della giornata (110 px contro 150)
       per una ragione di impaginazione, non di gusto: la testa della scheda
       viene tenuta insieme a forza da `_keep_together()`, e un blocco
       inscindibile troppo alto non entra in fondo a nessuna pagina — si
       trascina dietro mezza pagina bianca, che e' esattamente il difetto
       segnalato («troppi spazi vuoti dispersivi»).
       Qui, a differenza della giornata, passa ANCHE la grafica disegnata in
       casa: la scheda della guida e' il posto dove il documento dichiara di
       raccontare il luogo, e una copertina disegnata con su scritto che non
       e' una fotografia non inganna nessuno. In cima a una giornata sarebbe
       un'altra cosa. */
    .guide-foto { margin: 0 0 8px 0; text-align: center; }
    .guide-foto img { max-width: 100%; max-height: 150px; }
    .guide-foto .didascalia { font-size: 8px; color: #98a4b0; margin-top: 2px; }

    /* --- Prima di partire ---------------------------------------------- */
    /* [AGGIUNTO 2026-08-01] Stessa impaginazione della copertina (tabella a
       due colonne, chiave in maiuscoletto grigio, valore in blu grassetto):
       la scheda del paese e i fatti di copertina sono la stessa cosa — dati
       secchi da leggere in un colpo d'occhio — e devono sembrarlo. */
    .pre-facts { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0 18px 0; }
    .pre-facts td { padding: 7px 4px; border-bottom: 1px solid {{sfondo_tenue}}; vertical-align: top; }
    .pre-facts td.k {
      color: #6b7a89; width: 34%; text-transform: uppercase;
      font-size: 10px; letter-spacing: .05em;
    }
    .pre-facts td.v { color: {{scuro}}; font-weight: bold; }
    .pre-facts tr.emergency td.v { color: #b23a3a; font-size: 14px; }
    /* Una tabella PER RIGA e non una tabella sola: `page-break-inside` in
       questo motore vale sulle righe di tabella, quindi una voce con il suo
       dettaglio non si spezza mai a metà tra due pagine. */
    .check-row { width: 100%; border-collapse: collapse; page-break-inside: avoid; }
    .check-row td { padding: 8px 4px; border-bottom: 1px solid {{sfondo_tenue}}; vertical-align: top; }
    .check-row td.check-mark { width: 24px; }
    /* Una casella davvero vuota, disegnata col bordo: i caratteri di casella
       Unicode non esistono nei font di sistema del renderer e uscirebbero
       come rettangoli vuoti — cioè come un errore di stampa. */
    .check-box {
      display: inline-block; width: 11px; height: 11px;
      border: 2px solid {{accento}}; border-radius: 0;
    }
    .check-text { font-size: 12px; color: {{scuro}}; }
    .check-detail { font-size: 11px; color: #6b7a89; margin-top: 3px; }

    /* --- Vademecum: clima, valigia, bagagli ---------------------------- */
    /* [AGGIUNTO 2026-08-02 — task #167]
       Tre regole valgono per tutto quello che segue, e sono le stesse che
       reggono il resto del foglio: solo tinte piatte e bordi solidi (il motore
       di stampa è WebKit del 2014 e ignora in silenzio tutto il resto — i test
       cercano i token proibiti in TUTTO l'HTML prodotto, commenti compresi,
       quindi qui non si possono nemmeno nominare); l'impaginazione a colonne si
       fa con le TABELLE, che sono l'unica cosa che questo motore allinea
       davvero; e ogni riquadro che deve restare intero porta
       `page-break-inside: avoid` su una tabella o su una riga, mai su un div
       alto — su quelli non ha effetto. */

    /* La scheda del clima: una fascia scura con il mese, e dentro tre numeri
       grandi affiancati. È la prima cosa che si vede della sezione e deve
       rispondere alla domanda in un secondo: quanto fa caldo, quanto fa
       freddo, quanto piove. */
    .vad-climate {
      width: 100%; border-collapse: collapse; margin: 6px 0 12px 0;
      page-break-inside: avoid;
    }
    .vad-climate-head {
      background: {{scuro}}; color: #ffffff; padding: 5px 14px;
      font-size: 11px; text-transform: uppercase; letter-spacing: .08em;
    }
    .vad-climate-head .vad-zone { color: {{accento_su_scuro}}; }
    .vad-climate-body {
      border: 1px solid {{bordo}}; border-top: none; padding: 0;
    }
    .vad-nums { width: 100%; border-collapse: collapse; }
    .vad-nums td {
      width: 33%; text-align: center; padding: 7px 6px;
      border-right: 1px solid {{sfondo_tenue}}; vertical-align: middle;
    }
    .vad-nums td:last-child { border-right: none; }
    .vad-num { font-size: 22px; font-weight: bold; color: {{scuro}}; line-height: 1.1; }
    .vad-num-hot { color: #b23a3a; }
    .vad-num-cold { color: {{primario}}; }
    .vad-num-label {
      font-size: 9px; text-transform: uppercase; letter-spacing: .07em;
      color: #8a97a3; margin-top: 2px;
    }
    .vad-num-small { font-size: 13px; font-weight: bold; color: {{scuro}}; line-height: 1.2; }
    .vad-note {
      font-size: 11px; color: #4a5b6b; padding: 6px 14px;
      border-top: 1px solid {{sfondo_tenue}}; text-align: justify;
    }
    .vad-forecast { font-size: 11px; padding: 6px 14px; border-top: 1px solid {{sfondo_tenue}}; }
    .vad-forecast a {
      display: inline-block; color: #ffffff; background: {{primario}};
      text-decoration: none; border-radius: 0; padding: 1px 10px;
    }
    .vad-forecast-when { color: #8a97a3; margin-left: 6px; }

    /* Il verdetto sul bagaglio: la parola sola, grande, colorata come i
       verdetti di budget — è la risposta secca alla domanda di Lorenzo
       "quale tipologia di bagaglio conviene prendere". */
    .vad-choice {
      width: 100%; border-collapse: collapse; margin: 4px 0 10px 0;
      page-break-inside: avoid;
    }
    .vad-choice td { vertical-align: top; padding: 0; }
    .vad-choice td.vad-choice-badge { width: 132px; padding-right: 14px; }
    .vad-badge {
      display: block; text-align: center; color: #ffffff; background: {{primario}};
      border-radius: 0; padding: 7px 6px; font-size: 15px; font-weight: bold;
      text-transform: uppercase; letter-spacing: .04em;
    }
    .vad-badge-hold { background: {{accento}}; }
    .vad-badge-sub {
      display: block; font-size: 9px; font-weight: normal; letter-spacing: .06em;
      text-transform: uppercase; margin-top: 1px; color: {{chiaro_su_scuro}};
    }
    .vad-reason { font-size: 12px; color: {{scuro}}; text-align: justify; }
    .vad-total {
      font-size: 12px; color: {{accento_testo}}; background: {{sfondo_caldo}};
      border-left: 3px solid {{accento}}; padding: 4px 10px; margin-top: 4px;
    }

    /* Il listino delle compagnie: una tabella vera, perché sono numeri da
       confrontare in colonna e qualunque altra forma li renderebbe illeggibili. */
    /* [CORRETTO 2026-08-13 — task #220, difetto ISOLATO col misuratore.]
       Il listino sbordava di due-tre righe sulla pagina dopo, che restava
       vuota per l'80%: era la pagina 9 che il misuratore segnalava al 19,8%.
       E' lo stesso difetto delle schede di guida — un blocco lungo che non ci
       sta e trascina un pezzetto sul foglio successivo — cioe' esattamente
       cio' che Lorenzo ha segnalato («poche righe e poi bianco»).
       `page-break-inside: avoid` da solo non basterebbe: se la tabella fosse
       piu' alta di una pagina il motore lo ignora e spezza lo stesso. Quindi
       si fa stare: righe piu' strette e corpo leggermente minore. I numeri
       restano perfettamente leggibili — erano larghi, non necessari. */
    .vad-fares { width: 100%; border-collapse: collapse; font-size: 10px;
                 margin: 6px 0; page-break-inside: avoid; }
    .vad-fares th {
      text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: .05em;
      color: #6b7a89; border-bottom: 2px solid {{bordo_caldo}}; padding: 2px 4px;
    }
    .vad-fares td { padding: 2px 4px; border-bottom: 1px solid {{sfondo_tenue}}; vertical-align: top; }
    .vad-fares td.vad-carrier { font-weight: bold; color: {{scuro}}; white-space: nowrap; }
    .vad-fares td.num { text-align: right; white-space: nowrap; }
    .vad-caveat { font-size: 9.5px; line-height: 1.3; color: #8a97a3; text-align: justify; margin-bottom: 6px; }
    .vad-notes { font-size: 10.5px; line-height: 1.35; margin: 0 0 8px 0; padding-left: 18px; color: #4a5b6b; }
    .vad-notes li { margin-bottom: 2px; }

    /* La lista della valigia su DUE colonne: la stessa quantità di voci su
       metà delle pagine. È il rimedio diretto ai "troppi spazi vuoti
       dispersivi" — una lista di spunte a colonna singola sprecava due terzi
       della larghezza del foglio. */
    .vad-group { margin-bottom: 7px; page-break-inside: avoid; }
    .vad-group-title {
      font-size: 12px; font-weight: bold; color: {{scuro}};
      border-left: 4px solid {{accento}}; padding-left: 10px; margin-bottom: 4px;
    }
    .vad-items { width: 100%; border-collapse: collapse; }
    .vad-items td {
      width: 50%; vertical-align: top; padding: 2px 10px 3px 0;
      font-size: 11px; color: {{scuro}};
    }
    .vad-tick { color: {{accento_testo}}; font-weight: bold; }

    /* I passi di come si riempie: numerati, perché è una sequenza e l'ordine
       è metà dell'informazione. */
    .vad-step { width: 100%; border-collapse: collapse; page-break-inside: avoid; }
    .vad-step td { padding: 4px 4px; border-bottom: 1px solid {{sfondo_tenue}}; vertical-align: top; }
    .vad-step td.vad-step-n { width: 26px; }
    .vad-step-num {
      display: inline-block; width: 20px; height: 20px; line-height: 20px;
      text-align: center; border-radius: 0; background: {{scuro}};
      color: #ffffff; font-size: 11px; font-weight: bold;
    }
    .vad-step-title { font-size: 12px; font-weight: bold; color: {{scuro}}; }
    .vad-step-detail { font-size: 11px; color: #6b7a89; margin-top: 1px; text-align: justify; }
    .vad-sub {
      font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
      color: {{accento_testo}}; margin: 14px 0 5px 0; font-weight: bold;
    }

    /* Il riquadro del foglio da spuntare. Tabella e non div: deve restare
       tutto sulla stessa pagina, e `page-break-inside: avoid` su un div alto
       il motore di stampa lo ignora. Niente `border-radius` insieme al bordo
       colorato di un lato solo: nel PDF vero quel bordo viene "srotolato"
       lungo il fondo (difetto gia' visto e gia' corretto altrove). */
    .vad-sheet {
      width: 100%; border-collapse: collapse; margin: 10px 0 6px 0;
      page-break-inside: avoid;
      background: {{sfondo_tenue}}; border-left: 4px solid {{scuro}};
    }
    .vad-sheet td { padding: 7px 12px; vertical-align: top; }
    .vad-sheet-title {
      font-size: 12px; font-weight: bold; color: {{scuro}}; margin-bottom: 3px;
    }
    .vad-sheet-body { font-size: 11px; color: #4a5b6b; text-align: justify; }
    .vad-sheet-how {
      font-size: 10px; color: #6b7a89; margin-top: 4px;
      border-top: 1px solid {{bordo_caldo}}; padding-top: 5px;
    }
    .vad-sheet-file {
      font-family: 'DejaVu Sans Mono', monospace; font-size: 10px;
      color: {{scuro}}; font-weight: bold;
    }

    /* --- Costi e budget ------------------------------------------------ */
    .cost-table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }
    .cost-table th {
      text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: .05em;
      color: #6b7a89; border-bottom: 2px solid {{bordo_caldo}}; padding: 6px 4px;
    }
    .cost-table td { padding: 6px 4px; border-bottom: 1px solid {{sfondo_tenue}}; vertical-align: top; }
    .cost-table td.num { text-align: right; white-space: nowrap; }
    .cost-table tr.total td {
      border-top: 2px solid {{scuro}}; border-bottom: none;
      font-weight: bold; color: {{scuro}}; font-size: 13px; padding-top: 8px;
    }
    .cost-detail { font-size: 10px; color: #8a97a3; }
    .verdict {
      display: inline-block; font-size: 11px; font-weight: bold; color: #ffffff;
      padding: 3px 10px; border-radius: 0; margin-top: 6px;
    }
    .verdict.v-within { background: #3f8f5f; }
    .verdict.v-tight { background: {{accento}}; }
    .verdict.v-over { background: #b23a3a; }

    /* --- Consigli dell'Architetto -------------------------------------- */
    .tip-group { margin-bottom: 14px; page-break-inside: avoid; }
    .tip-group-title {
      font-size: 13px; font-weight: bold; color: {{scuro}};
      border-left: 4px solid {{accento}}; padding-left: 10px; margin-bottom: 6px;
    }
    .tip-group ul { margin: 0; padding-left: 20px; font-size: 12px; }
    .tip-group li { margin-bottom: 4px; }

    /* --- Piani B se piove ---------------------------------------------- */
    .rain-card {
      border: 1px solid {{bordo}}; border-left: 4px solid {{primario}}; border-radius: 0;
      padding: 12px 16px; margin-bottom: 10px; font-size: 12px; page-break-inside: avoid;
    }
    .rain-day { font-weight: bold; color: {{scuro}}; margin-bottom: 4px; }
    .rain-swap { padding: 4px 0; border-top: 1px solid {{sfondo_tenue}}; }
    .rain-swap:first-child { border-top: none; }
    .rain-arrow { color: {{primario}}; font-weight: bold; }

    /* --- Schede luogo (menù / info ristoranti) ------------------------- */
    .place-links { font-size: 11px; margin-top: 3px; }
    .place-links a {
      display: inline-block; color: {{primario}}; text-decoration: none;
      border: 1px solid {{bordo}}; border-radius: 0;
      padding: 1px 9px; margin: 2px 5px 0 0;
    }
    .place-meta { font-size: 10px; color: #8a97a3; margin-top: 2px; }

    /* --- Guida turistica tascabile ------------------------------------- */
    .guide-link { font-size: 11px; margin-top: 3px; }
    .guide-link a {
      display: inline-block; color: #ffffff; background: {{scuro}}; text-decoration: none;
      border-radius: 0; padding: 2px 10px;
    }
    /* [CAMBIATO 2026-08-02 (quinquies)] La scheda NON porta più `.page-break`.
       La regola "non spezzare a metà" è giusta per un riquadro alto un quarto
       di pagina; su una scheda alta quasi mezza pagina produce il difetto che
       doveva evitare. Nove schede da ~48% non si dividono mai 2+2+2+2+1 sulla
       pagina in cui il capitolo si apre: lì sopra ci sono già i piani B e il
       titolo, resta posto per una sola scheda, e la seconda scende — con il
       40% del foglio lasciato bianco. Misurato: pagina 8 al 58% di riempimento,
       documento a 13 pagine.

       Lasciando scorrere la scheda, il taglio cade dentro un elenco (che si
       legge benissimo a cavallo di due pagine, come in qualsiasi libro) e il
       bianco sparisce: stessa pagina al 99%, documento a 12 pagine, non una
       parola in meno. Quello che NON deve spezzarsi è il poco che, diviso,
       diventa illeggibile: l'intestazione della scheda (occhiello + nome +
       primo paragrafo) sta in un guscio `_keep_together()`, e i due riquadri
       colorati hanno la loro regola qui sotto. */
    /* [COMPATTATA 2026-08-02 (quater)] Le misure di questo blocco NON sono
       una questione di gusto: decidono quante schede stanno in una pagina.
       Con la scheda completa (nove sezioni, come le scrive davvero il
       prodotto) l'altezza arrivava al 51-57% dello specchio di stampa: due
       schede non ci stavano, e il capitolo usciva a UNA scheda per pagina
       con quasi metà foglio bianco per sette pagine di fila — di nuovo i
       "troppi spazi vuoti dispersivi". Sotto il 48% due schede entrano e
       il capitolo si accorcia di tre pagine a parità di parole. Chi ritocca
       questi valori verso l'alto rimette il bianco: `tests/
       test_standard_qualita.py` misura la densità e lo dice. */
    .guide-card {
      border: 1px solid {{bordo}}; border-radius: 0; padding: 10px 14px;
      margin-bottom: 8px;
      /* L'interlinea generale del documento è 1.5, giusta per un testo che
         si legge di seguito. Dentro la scheda il testo è fatto di righe
         brevi ed elenchi, dove 1.5 diventa distanza fra le voci invece che
         respiro: 1.38 toglie l'8% dell'altezza senza che si veda. */
      line-height: 1.38;
    }
    .guide-card h3 { font-size: 15px; color: {{scuro}}; margin: 0 0 3px 0; }
    .guide-eyebrow { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: {{accento_testo}}; }
    .guide-body { font-size: 12px; margin-top: 5px; }
    .guide-facts { font-size: 11px; color: #4a5b6b; margin-top: 5px; }
    .guide-back { font-size: 10px; margin-top: 5px; }
    .guide-back a { color: {{primario}}; text-decoration: none; }
    /* Gli elenchi puntati dentro la scheda: il margine verticale di 1em e il
       rientro di 40px sono i valori con cui WebKit disegna un `<ul>` quando
       nessuno glieli dice. Su una scheda con due elenchi sono quasi tre
       centimetri di aria e mezza colonna di rientro sprecato. */
    .guide-card ul { margin: 3px 0 0 0; padding-left: 16px; }
    .guide-card li { margin-bottom: 2px; }
    /* I due riquadri colorati della scheda restano interi anche ora che la
       scheda scorre: sono corti (tre o quattro righe), e spezzati mostrano
       una cornice aperta sopra e una chiusa sotto, che sulla carta si legge
       come un errore di stampa. Su blocchi bassi come questi la regola il
       motore la onora; è sui blocchi alti che non è affidabile — ed è
       esattamente per questo che non sta più sulla scheda intera. */
    .guide-card .tips-box {
      padding: 8px 12px; margin: 7px 0 0 0; page-break-inside: avoid;
    }
    .guide-card .guide-warn { page-break-inside: avoid; }
    .guide-card .highlight-row { padding: 2px 0; }
    .highlight-row { padding: 4px 0; border-top: 1px solid {{sfondo_tenue}}; font-size: 12px; }
    .highlight-row:first-child { border-top: none; }
    .highlight-name { font-weight: bold; color: {{scuro}}; }
    /* [AGGIUNTI 2026-08-02] Sottotitoli interni alla scheda e i due blocchi
       nuovi. Nessun gradiente, nessuna trasparenza: il motore di stampa è
       WebKit del 2014 e li ignora in silenzio, che è il modo peggiore di
       sbagliare — vedi la nota in cima a questo foglio di stile. */
    .guide-sub {
      font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
      color: {{accento_testo}}; margin-top: 8px; font-weight: bold;
    }
    /* Margini scritti per esteso e non lasciati al default: il `<p>` di
       WebKit porta un margine verticale di 1em sopra E sotto, che fra due
       paragrafi diventa una riga vuota abbondante. Su una scheda di quattro
       paragrafi sono quasi due centimetri di nulla — esattamente i "troppi
       spazi vuoti dispersivi" segnalati da Lorenzo. */
    .guide-para { font-size: 12px; margin: 0 0 6px 0; text-align: justify; }
    .guide-para:last-child { margin-bottom: 0; }
    .guide-warn {
      font-size: 12px; margin-top: 7px; padding: 6px 10px;
      border-left: 3px solid {{accento}}; background: {{sfondo_caldo}};
    }

    /* --- Varie --------------------------------------------------------- */
    .anchor { font-size: 1px; color: #ffffff; }
    /* Sonda d'ancoraggio: vedi `_anchor()` qui sotto e src/pdf_links.py. Deve
       occupare un'area — un elemento a dimensione zero non produce nessuna
       annotazione nel PDF e la sezione resterebbe irraggiungibile — ma deve
       essere invisibile sulla pagina stampata: bianco su bianco, due pixel. */
    .anchor-probe { font-size: 2px; line-height: 2px; color: #ffffff; }
    /* [CORRETTO 2026-08-05 — difetto visto sul campione, non nel codice]
       Da quando il segnaposto del ritorno si semina DENTRO `.guide-link`
       (task #191), il suo `<a>` ereditava lo stile del pulsante: fondo blu,
       riempimento, blocco in linea. Nel PDF vero, accanto a ognuno dei nove
       pulsanti «Apri la guida», compariva un mozzicone blu largo mezzo
       centimetro. Nessun controllo poteva vederlo — l'HTML era corretto e i
       collegamenti funzionavano tutti — si vedeva solo guardando la pagina.
       Queste tre righe rimettono il segnaposto a essere invisibile ovunque
       lo si metta, e vengono DOPO le regole dei pulsanti perche' devono
       vincere loro. */
    .anchor-probe a {
      color: #ffffff; text-decoration: none;
      display: inline; background: none; padding: 0; border: none;
      font-size: 2px; line-height: 2px;
    }
    .section-intro { font-size: 11px; color: #6b7a89; margin: -4px 0 10px 0; }

    /* --- Testate dei capitoli (task #216) --------------------------------
       [AGGIUNTE 2026-08-15] Fino a ieri tutti e undici i capitoli si aprivano
       con la stessa riga: carattere con le grazie e un filetto sotto. Su un
       documento di ventisei pagine sono undici aperture identiche, ed e' il
       difetto che Lorenzo ha nominato per primo guardando i provini: non
       «brutto», ma «sempre uguale».

       Quale delle quattro tocchi a un capitolo lo decide `compositore.testata()`,
       che garantisce due cose: mai due di fila uguali, e lo stesso viaggio
       rigenerato da' lo stesso documento.

       REGOLA COMUNE A TUTTE E QUATTRO: la testata non si spezza (sta dentro
       `page-break-inside: avoid`) ma NON si incolla al testo che segue. La
       differenza e' costata cara il 13 agosto — legare il titolo al suo
       seguito toglieva un titolo orfano e apriva due centimetri di vuoto
       altrove, e il misuratore delle pagine e' diventato rosso. Qui si
       decora l'apertura, non si tocca il flusso. */
    .cap { page-break-inside: avoid; margin: 17px 0 10px 0; }
    /* [AGGIUNTA 2026-08-15 — task #221] Il capitolo comincia su una pagina
       nuova. La classe la mette la seconda stampa, e solo sui capitoli la cui
       testata, alla prima, era caduta in fondo al foglio: `page-break-before`
       questo motore lo onora, `page-break-after: avoid` no — misurato. */
    .cap-a-capo { page-break-before: always; margin-top: 0; }
    .cap .section-title { margin: 0; }
    /* L'occhiello: due parole in maiuscoletto sopra il titolo. Serve a dare
       alla testata una seconda riga su cui variare — senza, "fascia" e
       "laterale" si distinguerebbero solo per un bordo. */
    .cap-occhiello {
      font-size: 9px; letter-spacing: 1.6px; text-transform: uppercase;
      color: {{accento_testo}}; margin-bottom: 3px;
    }

    /* FASCIA — la banda piena che esce dai margini del foglio. E' l'apertura
       piu' forte, riservata ai capitoli di racconto.
       I due margini negativi valgono ESATTAMENTE quanto i margini laterali di
       `@page`, e il riempimento li restituisce: cosi' il colore arriva al
       bordo della carta ma il titolo resta incolonnato con tutto il resto del
       documento. Se un domani cambiano i margini di pagina vanno cambiati
       anche qui — c'e' un controllo che lo verifica, perche' e' il tipo di
       disallineamento che non da' nessun errore e si vede solo sulla carta. */
    .cap-fascia {
      background: {{primario}};
      margin-left: -1.8cm; margin-right: -1.8cm;
      padding: 9px 1.8cm 10px 1.8cm;
    }
    .cap-fascia .section-title {
      color: #ffffff; border-bottom: none; padding-bottom: 0;
    }
    .cap-fascia .cap-occhiello { color: {{accento_su_scuro}}; }

    /* LATERALE — sbarra verticale spessa a sinistra, niente filetto sotto.
       E' la piu' sobria delle quattro: sta bene sui capitoli di consultazione,
       dove il titolo deve farsi trovare sfogliando ma non rubare la scena
       alla tabella che ha sotto. */
    .cap-laterale {
      border-left: 7px solid {{primario}};
      padding: 1px 0 1px 15px;
    }
    .cap-laterale .section-title { border-bottom: none; padding-bottom: 0; }

    /* BLOCCO — riquadro pieno sul fondo caldo, con una linguetta di colore
       sopra il titolo. La linguetta e' un div solido: nessun gradiente,
       nessuna trasparenza, cioe' le uniche cose che questo motore di stampa
       disegna davvero. */
    .cap-blocco {
      background: {{sfondo_caldo}};
      border-left: 3px solid {{accento}};
      padding: 9px 18px 10px 18px;
    }
    .cap-blocco .cap-linguetta {
      width: 44px; height: 6px; background: {{accento}};
      margin-bottom: 7px; font-size: 1px; line-height: 1px;
    }
    .cap-blocco .section-title { border-bottom: none; padding-bottom: 0; }

    /* NUMERO — la cifra grande in chiaro accanto al titolo, con un filetto
       SOPRA invece che sotto. E' una tabella e non due div affiancati perche'
       affiancare qui si fa solo con le tabelle: `float` e `flex` questo motore
       li ignora in silenzio, e il risultato sarebbe la cifra sopra il titolo
       invece che accanto. */
    .cap-numero { width: 100%; border-collapse: collapse; }
    .cap-numero td { padding: 0; border: none; vertical-align: middle; }
    .cap-numero .cap-cifra {
      width: 62px;
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 40px; line-height: 1; color: {{bordo_caldo}};
    }
    .cap-numero .section-title {
      border-bottom: none; border-top: 2px solid {{bordo_caldo}};
      padding: 7px 0 0 0;
    }
    /* [AGGIUNTA 2026-08-02 (quater)] Stessa riga di raccordo, ma quando sta
       IN MEZZO a due riquadri invece che sotto a un titolo. Il margine
       negativo di `.section-intro` serve a incollare l'occhiello al titolo
       che lo precede; sotto a un riquadro fa l'opposto, e la riga finiva
       sopra il bordo inferiore del riquadro — nel campione si leggeva la
       frase tagliata a metà dalla cornice verde. Qui il margine è positivo
       da entrambi i lati: la riga respira sopra e sotto. */
    .mid-intro { font-size: 11px; color: #6b7a89; margin: 10px 0 8px 0; }
    .day-open { page-break-inside: avoid; }
    /* [AGGIUNTO 2026-08-13 — task #209] La fascia fotografica in cima alla
       copertina. Niente `object-fit` (il motore la ignora) e niente altezza
       forzata: solo un tetto, cosi' l'immagine sceglie le proprie proporzioni
       dentro il limite e nessuna fotografia esce schiacciata — e' la stessa
       lezione che era costata le foto stirate dell'11 agosto. */
    .cover-foto { text-align: center; margin: 0 0 18px 0; page-break-inside: avoid; }
    .cover-foto img { width: 100%; }
    .cover-foto .didascalia { font-size: 8px; color: #98a4b0; margin-top: 3px; }
    /* [AGGIUNTO 2026-08-13 — task #214] La fotografia che esce dai margini e
       arriva al bordo del foglio: e' la mossa che distingue una rivista da una
       relazione. E' anche l'unica forma che il motore accetta — `@page {
       margin: 0 }` sposterebbe anche tutto il testo.
       Questi due numeri valgono ESATTAMENTE quanto i margini di `@page` in
       cima al foglio: se un domani cambiano li', vanno cambiati anche qui,
       altrimenti la fotografia sborda dal foglio o si ferma prima del bordo.
       C'e' un controllo che lo verifica, perche' e' il tipo di disallineamento
       che non da' nessun errore e si vede solo sulla carta. */
    /* --- Le due aperture a colonne (task #219) -------------------------
       [AGGIUNTE 2026-08-15] Dividono in colonne l'APERTURA della giornata,
       non la giornata: sotto, titolo, cartina e programma restano impilati.
       Le larghezze sono dichiarate sulle celle perche' senza, con una
       fotografia sola, la cella rimasta si prende tutta la riga. */
    .day-eroe, .day-numerone {
      width: 100%; border-collapse: separate; border-spacing: 7px;
      margin: 0 -7px 8px -7px; page-break-inside: avoid;
    }
    .day-eroe td, .day-numerone td { padding: 0; vertical-align: middle; }
    .day-eroe-grande { width: 61%; }
    .day-eroe-lato { width: 39%; }
    /* Il numerone: grande abbastanza da essere un elemento grafico, non un
       numero scritto grosso. In grigio chiaro perche' deve fare da fondale
       alla fotografia accanto, non contenderle l'occhio. */
    .day-numerone-cifra {
      width: 27%; text-align: center;
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 76px; line-height: .9; color: {{bordo_caldo}};
    }
    .day-numerone-e {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      font-size: 9px; letter-spacing: .2em; text-transform: uppercase;
      color: {{accento_testo}}; margin-top: 6px;
    }
    .day-numerone-foto { width: 73%; }

    .day-banda { margin-left: -1.8cm; margin-right: -1.8cm; margin-bottom: 10px;
                 page-break-inside: avoid; }
    .day-banda .didascalia { font-size: 8px; color: #98a4b0;
                             margin-top: 2px; margin-left: 1.8cm; }
    /* [AGGIUNTO 2026-08-13 — task #215] Gli ornamenti della giornata.
       Colori pieni e nessuna sfumatura: il motore non le sa fare e le stampa
       piatte o non le stampa affatto. Il tondo del bollo si ottiene con
       `border-radius` su un blocco COLORATO, che il motore regge — e' solo
       sulle IMMAGINI che si rompe (misurato: mezzo tondo, mezzo quadrato). */
    .day-bollo { width: 74px; height: 74px; border-radius: 37px;
                 background: {{accento}}; color: #ffffff; text-align: center;
                 float: right; margin: 0 0 6px 10px; page-break-inside: avoid; }
    .day-bollo .n { font-family: Georgia, 'Times New Roman', serif;
                    font-size: 26px; line-height: 1; padding-top: 16px; }
    .day-bollo .e { font-size: 7px; letter-spacing: 0.13em;
                    text-transform: uppercase; }
    .day-capolettera { font-family: Georgia, 'Times New Roman', serif;
                       font-size: 72px; line-height: 0.8; color: {{sfondo_tenue}};
                       float: right; margin: 0 0 4px 12px; }
    /* Il nastro storto. Uno per pagina: due lo fanno sembrare un volantino di
       sconti, e questo documento si vende a 4,90 non a 0,90. */
    .day-nastro { -webkit-transform: rotate(-2deg); background: {{scuro}};
                  color: #ffffff; display: inline-block; padding: 4px 14px;
                  font-size: 9px; letter-spacing: 0.15em;
                  text-transform: uppercase; margin: 4px 0 8px 0; }
    .day-tonda { text-align: center; margin: 8px 0; page-break-inside: avoid; }
    .day-tonda img { width: 190px; }
    .day-tonda .didascalia { font-size: 8px; color: #98a4b0; margin-top: 2px; }
    /* L'apertura a colonna piena: niente `max-height` di proposito. Le
       proporzioni le decide il ritaglio in Python, e width + max-height
       insieme sono la coppia che l'11 agosto ha prodotto le fotografie
       schiacciate. */
    .day-larga { margin: 4px 0 10px 0; page-break-inside: avoid; }
    .day-larga .didascalia { font-size: 8px; color: #98a4b0; margin-top: 2px; }
"""


def _css(tavolozza: dict | None = None) -> str:
    """Il foglio di stile con dentro i colori del posto (task #209).

    [CAMBIATO 2026-08-13 — richiesta di Lorenzo: «mi piacerebbe che l'estetica
    si adattasse al posto in cui il cliente vuole andare».]

    Prima i colori stavano scritti dentro il foglio di stile, uno per uno: lo
    stesso blu navy e lo stesso oro per Bologna, per Santorini e per
    Marrakech. Adesso il foglio e' un MODELLO con dei segnaposto, e i colori
    arrivano da `src/tavolozza.py`, che sceglie la tavolozza guardando le
    fotografie vere del luogo.

    Cambia solo la parte cromatica: i grigi del testo, il nero e le distanze
    restano identici in ogni tavolozza. Un documento di trenta pagine si legge
    grazie ai neutri, e farli girare insieme al colore vorrebbe dire rimettere
    in gioco la leggibilita' a ogni destinazione.

    Restano fissi anche i colori che vogliono dire QUALCOSA: il rosso degli
    avvisi, il verde delle conferme, i colori dei pallini che distinguono le
    giornate sulla cartina. Quelli non sono decorazione — se cambiassero col
    posto cambierebbe il significato, che e' un difetto peggiore del grigiore.
    """
    from src import tavolozza as _tav

    piena = _tav.completa(tavolozza) if tavolozza else _tav.completa(_tav.PREDEFINITA)
    foglio = _CSS_MODELLO
    for ruolo, colore in piena.items():
        if isinstance(colore, str) and colore.startswith("#"):
            foglio = foglio.replace("{{" + ruolo + "}}", colore)
    return foglio


# Il foglio di stile di sempre: il modello con la tavolozza predefinita.
#
# Resta esposto con questo nome perche' meta' dei controlli di questo progetto
# lo leggono da qui — e soprattutto perche' un documento senza fotografie deve
# continuare a uscire ESATTAMENTE come usciva prima. Il ripiego dev'essere una
# cosa gia' vista funzionare, non una cosa nuova.
_CSS = _css()

# Prefisso delle sonde d'ancoraggio (vedi `_anchor()`). La costante vive in
# src/pdf_links.py perche' e' un contratto fra chi scrive l'HTML e chi ripara
# il PDF: due definizioni separate si sarebbero disallineate al primo
# refactoring, e il sintomo sarebbe stato — di nuovo — un collegamento che non
# fa niente e non dice niente.
_ANCHOR_PROBE_PREFIX = pdf_links.PROBE_PREFIX

# Quanto e' larga la fascia fotografica di copertina rispetto alla sua
# altezza. Non e' un gusto: e' altezza di pagina. A 2,6 la copertina del
# campione sfondava sul foglio dopo; a 3,2 ci sta, e come banda sta pure
# meglio — una striscia larga si legge come un'apertura, un rettangolo alto
# si legge come una figura messa li'.
_RAPPORTO_FASCIA = 3.2


# Il comando esatto con cui si stampa. UNA definizione sola, e il motivo e'
# preciso.
#
# [ESTRATTO 2026-08-13] Serve a `src/prova_stampa.py`, la prova che chiede al
# motore di stampa VERO — quello di produzione, con le patch — che cosa fa dei
# rimandi interni. Se quella prova costruisse un comando suo, misurerebbe il
# comportamento di un comando che nessuno esegue: risposta precisa alla
# domanda sbagliata, cioe' il modo piu' elegante di prendersi in giro. Da qui
# in poi chi misura e chi stampa eseguono le stesse identiche parole.
#
# `--enable-internal-links` resta acceso di proposito anche adesso che i
# rimandi interni non passano piu' di li': toglierlo cambierebbe il
# comportamento del motore su un documento che gia' funziona, e non abbiamo
# modo di provare qui che cosa succede. Si tocca una cosa alla volta.
#
# [TOLTO IL PIEDE 2026-08-15 — task #217] Qui c'era
# `--footer-center "[page] / [topage]"`, e scriveva una cosa falsa: il motore
# di stampa vede UN file per volta, quindi su un fascicolo di ventisei pagine
# stampava «1 / 12» — il totale dell'itinerario da solo, prima che le guide
# gli venissero cucite dietro. E le pagine delle guide, stampate a parte,
# restavano senza numero.
#
# I numeri li mette adesso `fascicolo.numera()`, sul documento finito, quando
# il totale e' finalmente quello vero.
COMANDO_STAMPA = (
    "wkhtmltopdf", "--quiet",
    "--enable-internal-links",
    "--outline",
)


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
def _anchor(name: str) -> str:
    """Punto di atterraggio di un collegamento interno.

    [RIFATTO 2026-08-02 — segnalazione di Lorenzo: «i collegamenti non
    funzionano: quello per la guida turistica che porta in fondo al documento
    non funziona, non funziona nemmeno il collegamento per le recensioni»]

    Prima qui c'era solo un `id` HTML. Bastava in un browser; nel PDF no.
    wkhtmltopdf, con il Qt non patchato, traduce ogni `href="#x"` in un link al
    FILE TEMPORANEO da cui ha stampato — `file:///tmp/tmpXXXX.html#x` — che sul
    computer del cliente non esiste. Misurato sul campione: 26 collegamenti
    interni, 26 morti, e nessun errore da nessuna parte.

    L'ancora porta ora con se' una "sonda": un link invisibile verso uno schema
    inventato. wkhtmltopdf lo tratta come un link esterno qualunque e gli
    assegna un'annotazione — ed e' l'unico modo per sapere, dall'esterno, su
    quale PAGINA e a quale ALTEZZA e' finita questa ancora. `src/pdf_links.py`
    legge quelle annotazioni dopo la stampa, riscrive i link interni in veri
    salti `/GoTo` e cancella le sonde.

    L'`id` resta: non serve al PDF ma serve all'HTML, che e' lo stesso file su
    cui si fanno i collaudi a occhio nel browser."""
    safe = _esc(name)
    return (
        f"<span id='{safe}' class='anchor-probe'>"
        f"<a href='{_ANCHOR_PROBE_PREFIX}{safe}'>&#160;</a></span>"
    )


# --------------------------------------------------------------------------
# LE TESTATE DEI CAPITOLI (task #216)
#
# I capitoli di RACCONTO — quelli per cui il cliente ha pagato: il colpo
# d'occhio, la selezione, il programma, le guide — chiedono l'apertura piu'
# decisa. Gli altri raccontano meno e si consultano di piu' (i costi si
# confrontano col proprio budget, la valigia si spunta la sera prima): li'
# una testata spettacolare non aggiunge, toglie spazio alla tabella.
#
# La distinzione sta QUI e non dentro `compositore.py` di proposito: il
# compositore sa comporre pagine, non sa quali capitoli abbia questo prodotto.
# --------------------------------------------------------------------------
# Tutti i capitoli del documento, nell'ordine in cui possono comparire. Serve
# alla seconda stampa per sapere quali ancore sono testate di capitolo e quali
# no (vedi `src/impaginazione.py`).
CAPITOLI_DEL_DOCUMENTO = (
    "colpo-docchio", "alloggio", "selezione", "giorno-per-giorno", "costi",
    "consigli", "piani-b", "guide", "prima-di-partire", "vademecum",
    "numeri-utili", "recensione",
)

CAPITOLI_DI_RACCONTO = frozenset(
    {"colpo-docchio", "selezione", "giorno-per-giorno", "guide"}
)


def _titolo_capitolo(nome: str, testo: str, con_ancora: bool = True) -> str:
    """Il titolo di un capitolo, marcato perche' la passata finale lo trovi.

    Il marcatore e' un attributo e non una classe in piu' per una ragione
    misurata: mezza dozzina di prove cercano nell'HTML la stringa esatta
    `class='section-title'`, e una classe aggiunta le avrebbe fatte diventare
    verdi senza piu' guardare niente — che e' il modo peggiore in cui una
    prova puo' rompersi, perche' non lo dice.

    `con_ancora=False` per i due capitoli la cui ancora e' gia' stampata
    poco sopra, fuori dal titolo: due ancore con lo stesso nome sarebbero due
    `id` uguali nella stessa pagina, e il salto interno finirebbe su quella
    sbagliata.
    """
    ancora = _anchor(nome) if con_ancora else ""
    return f"<div class='section-title' data-capitolo='{_esc(nome)}'>{ancora}{testo}</div>"


# Un titolo di capitolo marcato da `_titolo_capitolo()`. Non puo' pescare i
# titoli di sezione normali (Shopping, Cosa fare, Come arrivare): quelli
# l'attributo non ce l'hanno, ed e' esattamente la distinzione che serve.
_RE_TITOLO_DI_CAPITOLO = re.compile(
    r"<div class='section-title' data-capitolo='([^']*)'>(.*?)</div>", re.S
)


def _disegna_testata(modo: str, nome: str, dentro: str, numero: int,
                     a_capo: bool = False) -> str:
    """Il vestito di UNA testata. Quattro modi, tutti fatti degli stessi pezzi.

    Non c'e' un `else` che ricade su un modo qualunque: se il compositore
    inventasse un nome nuovo si vedrebbe subito, mentre una ricaduta muta lo
    nasconderebbe e il documento uscirebbe con dieci testate uguali senza che
    nessuna prova diventi rossa.
    """
    # [AGGIUNTO 2026-08-15 — task #221] Il capitolo comincia su una pagina
    # nuova SOLO quando la prima stampa ha mostrato che la sua testata cadeva
    # in fondo al foglio. Vedi `src/impaginazione.py`: non e' una regola per
    # tutti i capitoli, e' una riparazione per quelli che ne hanno bisogno.
    salto = " cap-a-capo" if a_capo else ""
    occhiello = f"<div class='cap-occhiello'>Capitolo {numero}</div>"
    titolo = f"<div class='section-title' data-capitolo='{_esc(nome)}'>{dentro}</div>"
    if modo == "fascia":
        return f"<div class='cap{salto} cap-fascia'>{occhiello}{titolo}</div>"
    if modo == "laterale":
        return f"<div class='cap{salto} cap-laterale'>{occhiello}{titolo}</div>"
    if modo == "blocco":
        return (f"<div class='cap{salto} cap-blocco'><div class='cap-linguetta'></div>"
                f"{titolo}</div>")
    if modo == "numero":
        return (f"<table class='cap{salto} cap-numero'><tr>"
                f"<td class='cap-cifra'>{numero:02d}</td>"
                f"<td>{titolo}</td></tr></table>")
    raise ValueError(f"testata sconosciuta: {modo!r}")


def _testate_dei_capitoli(documento: str, chiave: str, a_capo=()) -> str:
    """Passata finale: veste ogni capitolo, mai due di fila allo stesso modo.

    [AGGIUNTA 2026-08-15 — task #216.]

    PERCHE' UNA PASSATA SUL DOCUMENTO FINITO e non una decorazione scritta in
    ognuno degli undici punti che stampano un titolo: perche' la scelta
    dipende dal capitolo PRECEDENTE, e il capitolo precedente non e' una cosa
    che un punto del codice conosce — dipende da quali sezioni sono uscite,
    che cambia da viaggio a viaggio (senza alberghi non c'e' "Il tuo
    alloggio", senza guide stampate non c'e' "Guide turistiche"). Passando di
    qui i capitoli si contano nell'ordine vero in cui stanno sulla carta, che
    e' anche l'unico ordine in cui «mai due di fila uguali» vuol dire
    qualcosa.

    E' lo stesso rimedio gia' usato per i paragrafi (`_tieni_uniti_i_paragrafi`):
    vale anche per i capitoli che verranno aggiunti domani, senza doversene
    ricordare.
    """
    stato = {"numero": 0, "precedente": None}

    def _sostituisci(m: "re.Match[str]") -> str:
        nome, dentro = m.group(1), m.group(2)
        stato["numero"] += 1
        modo = compositore.testata(
            chiave, nome, stato["precedente"],
            forte=nome in CAPITOLI_DI_RACCONTO,
        )
        stato["precedente"] = modo
        return _disegna_testata(modo, nome, dentro, stato["numero"],
                                a_capo=nome in (a_capo or ()))

    return _RE_TITOLO_DI_CAPITOLO.sub(_sostituisci, documento)


def _render_guide_foto(guide: dict, photos: dict | None) -> str:
    """L'immagine in testa alla scheda di una guida, oppure "".

    [AGGIUNTO 2026-08-03 — task #181, richiesta di Lorenzo: «meno testo piu'
    immagini, non deve essere noioso»]

    Qui passa qualunque immagine ci sia per quel luogo: la fotografia vera se
    l'abbiamo, altrimenti la copertina disegnata in casa. La differenza fra le
    due non e' nascosta, e' scritta nella didascalia — `foto.py` mette in
    chiaro «non e' una fotografia del luogo» sulla grafica interna. E' la
    ragione per cui questa funzione, a differenza di `_render_day_photo()`,
    non guarda `reale`: nel capitolo che racconta il posto una copertina
    dichiarata e' un'illustrazione, in cima al programma della giornata
    sarebbe uno scambio.

    Come in tutto il resto del progetto, senza credito non si stampa nulla.
    """
    if not isinstance(photos, dict) or not photos:
        return ""
    chiave = guide.get("poi_id")
    if not isinstance(chiave, str) or not chiave:
        return ""
    scatto = photos.get(chiave)
    if not isinstance(scatto, dict):
        return ""
    png, credito = scatto.get("png"), scatto.get("credito")
    if not png or not isinstance(credito, str) or not credito.strip():
        return ""
    try:
        b64 = base64.b64encode(png).decode("ascii")
    except (TypeError, ValueError):
        return ""
    nome = str(guide.get("poi_name") or guide.get("title") or "").strip()
    return (
        "<div class='guide-foto'>"
        f"<img src='data:{foto.mime_immagine(png)};base64,{b64}' alt='{_esc(nome)}'>"
        f"<div class='didascalia'>{_esc(credito)}</div></div>"
    )


def _render_guide_section(
    guide: dict, anchor: str | None = None, photos: dict | None = None,
) -> str:
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
    dove l'elenco non ha senso, resta valida e viene stampata senza.

    [AGGIUNTI 2026-08-02 — richiesta di Lorenzo: "non aver paura di sembrare
    prolisso"] `curiosita`, `errore_da_evitare` e `dintorni`, opzionali con lo
    stesso criterio di `highlights`.

    E un difetto vero, trovato mentre si scriveva questa parte:
    `history_summary` è specificato da sempre come "paragrafi separati da due
    ritorni a capo", ma veniva stampato con un solo `_esc()` dentro un solo
    `<div>` — e in HTML un ritorno a capo è spazio bianco. Il cliente riceveva
    quindi i paragrafi fusi in un muro di testo unico, e il difetto peggiorava
    ESATTAMENTE in proporzione a quanto il testo era ricco. Chiedere al
    modello di scrivere di più senza correggere prima questo avrebbe reso il
    documento peggiore, non migliore."""
    tips = "".join(f"<li>{_esc(t)}</li>" for t in guide.get("practical_tips", []) or [])
    title = guide.get("title") or guide.get("poi_name", "")
    probe = _anchor(anchor) if anchor else ""
    # [CAMBIATO 2026-08-02 (quinquies)] La scheda scorre fra una pagina e
    # l'altra (vedi la nota su `.guide-card` nel CSS), quindi l'unica cosa da
    # tenere insieme è la testa: occhiello, nome del luogo e primo paragrafo.
    # Se si separassero, il cliente si troverebbe il nome in fondo a una
    # pagina e la guida sulla successiva — che è il difetto che
    # `_keep_together()` esiste per evitare. La sonda dell'ancora sta DENTRO
    # il guscio, non prima: se restasse fuori atterrerebbe in fondo alla
    # pagina precedente e il rimando dal programma arriverebbe una pagina
    # troppo in su.
    # [AGGIUNTO 2026-08-03 — task #181] L'immagine sta DENTRO la testa tenuta
    # insieme, sopra l'occhiello: staccata, wkhtmltopdf potrebbe lasciarla in
    # fondo alla pagina precedente e far cominciare la scheda in quella dopo,
    # cioe' una figura orfana sopra il nome di un'altra guida.
    foto_html = _render_guide_foto(guide, photos)
    parts = [
        "<div class='guide-card'>",
        _keep_together(
            probe
            + foto_html
            + "<div class='guide-eyebrow'>Guida turistica tascabile</div>"
            + f"<h3>{_esc(title)}</h3>"
            + f"<div class='guide-body'>{_paragraphs(guide.get('history_summary', ''))}</div>"
        ),
    ]

    def _named_rows(items, heading: str) -> None:
        rows = []
        for item in items or []:
            if isinstance(item, dict):
                name, why = item.get("name") or "", item.get("why") or ""
            else:
                name, why = str(item), ""
            if not name:
                continue
            rows.append(
                f"<div class='highlight-row'><span class='highlight-name'>{_esc(name)}</span>"
                + (f" — {_esc(why)}" if why else "")
                + "</div>"
            )
        if rows:
            parts.append(f"<div class='guide-sub'>{heading}</div>")
            parts.extend(rows)

    _named_rows(guide.get("highlights"), "Cosa cercare, una volta dentro")

    curiosita = [str(c).strip() for c in (guide.get("curiosita") or []) if str(c).strip()]
    if curiosita:
        parts.append("<div class='guide-sub'>Da sapere</div>")
        parts.append(
            "<ul class='guide-body'>"
            + "".join(f"<li>{_esc(c)}</li>" for c in curiosita)
            + "</ul>"
        )

    if tips:
        parts.append(
            f"<div class='tips-box'><strong>Consigli pratici</strong><ul>{tips}</ul></div>"
        )

    errore = str(guide.get("errore_da_evitare") or "").strip()
    if errore:
        parts.append(
            f"<div class='guide-warn'><strong>L'errore che fanno quasi tutti:</strong> "
            f"{_esc(errore)}</div>"
        )

    _named_rows(guide.get("dintorni"), "A due passi da qui")
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
        "<a href='" + pdf_links.LINK_PREFIX + "giorno-per-giorno'>Torna al programma giorno per giorno</a></div>"
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

    `feedback_link` è `{"ref": ..., "url": ..., "core_questions": [...]}`.

    [CORRETTO 2026-08-03] Se non c'è una URL a cui rispondere, questa
    sezione NON esce affatto. Prima usciva lo stesso: titolo, introduzione e
    due o tre domande personalizzate, e nessun posto dove scrivere la
    risposta. Un capitolo che fa domande senza offrire un modo di
    rispondere non è una degradazione elegante, è una promessa rotta
    stampata su un documento che il cliente ha pagato — e per lui è
    indistinguibile da un link che non funziona. Meglio tacere.
    """
    feedback = feedback or {}
    link = feedback_link or {}
    if not link.get("url"):
        return ""
    parts = [
        "<div class='page-break'>",
        _titolo_capitolo("recensione", "Facci sapere com'è andata",
                         con_ancora=False),
    ]
    if feedback.get("intro_message"):
        parts.append(f"<div class='summary-box'>{_esc(feedback['intro_message'])}</div>")

    questions = "".join(f"<li>{_esc(q)}</li>" for q in feedback.get("questions", []))
    if questions:
        parts.append(f"<div class='tips-box'><ul>{questions}</ul></div>")

    core = link.get("core_questions") or []
    if core:
        parts.append(
            "<div class='mid-intro'>E poi qualche minuto su queste, che facciamo a "
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


_GIORNI_SETTIMANA = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


def _day_calendar_label(date_start, day_number) -> str:
    """
    Data vera della giornata N, nella forma "lun 14 set".

    Il giorno N-esimo cade a `date_start + (N - 1)` giorni: e' la stessa
    convenzione senza "+1" usata da `src/triage.py::_date_difference_days()`,
    e va tenuta allineata a quella — un documento che dice "3 giorni" in
    copertina e poi elenca quattro date si contraddice da solo.

    Restituisce stringa vuota, mai un'approssimazione, se la data di
    partenza manca o non e' leggibile: nel resto del documento vale la
    stessa regola, un dato che non abbiamo non viene inventato.
    """
    if not date_start or day_number is None:
        return ""
    try:
        base = _date.fromisoformat(str(date_start).strip()[:10])
        offset = int(day_number) - 1
    except (ValueError, TypeError):
        return ""
    if offset < 0 or offset > 400:
        return ""
    giorno = base + _timedelta(days=offset)
    mesi = ("gen", "feb", "mar", "apr", "mag", "giu",
            "lug", "ago", "set", "ott", "nov", "dic")
    return f"{_GIORNI_SETTIMANA[giorno.weekday()]} {giorno.day} {mesi[giorno.month - 1]}"


def _day_time_window(blocks: list) -> str:
    """
    Finestra oraria della giornata: dal primo orario stampato all'ultimo.

    Legge gli orari cosi' come sono scritti nei blocchi (formato "HH:MM"),
    senza convertirli: qui non serve fare aritmetica sulle ore, serve dire
    al cliente a che ora si comincia e a che ora, indicativamente, si
    chiude. Se gli orari non ci sono, la colonna resta vuota invece di
    riportare un intervallo inventato.
    """
    orari = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        raw = str(block.get("time") or "").strip()
        if len(raw) >= 4 and raw[:2].isdigit() and ":" in raw[:3]:
            orari.append(raw[:5])
    if not orari:
        return ""
    primo, ultimo = min(orari), max(orari)
    return primo if primo == ultimo else f"{primo}\u2013{ultimo}"


# Quanto e' piu' largo il bersaglio cliccabile rispetto al pallino disegnato.
# 1.0 sarebbe il pallino esatto: troppo preciso per un dito su un telefono, e
# il PDF si legge quasi sempre da telefono. Oltre 1.6 due pallini vicini si
# sovrappongono e si finisce sulla scheda sbagliata, che e' peggio del non
# poter cliccare: il cliente crede che il documento sbagli luogo.
_PIN_HIT_FACTOR = 1.4


def _png_dimensioni(blob) -> tuple[int, int] | None:
    """Larghezza e altezza di un PNG, lette dai suoi primi 24 byte.

    Serve una cosa sola: il rapporto fra i due lati. La posizione dei pallini
    arriva in percentuale della LARGHEZZA (vedi `map_render._geometria_dei_pin`),
    mentre l'altezza di un riquadro in percentuale, nel motore di stampa, si
    misura sull'ALTEZZA del contenitore. Senza il rapporto fra i lati il
    bersaglio verrebbe fuori ovale e spostato.

    Niente Pillow qui di proposito: l'intestazione di un PNG e' fissa e
    leggerla costa quattro righe, mentre importare una libreria di immagini
    dentro il renderer significherebbe farla diventare un requisito del
    documento — e il documento deve uscire anche quando qualcosa manca.
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 24:
        return None
    if bytes(blob[:8]) != b"\x89PNG\r\n\x1a\n":
        return None
    larghezza = int.from_bytes(bytes(blob[16:20]), "big")
    altezza = int.from_bytes(bytes(blob[20:24]), "big")
    if larghezza <= 0 or altezza <= 0:
        return None
    return larghezza, altezza


def _render_map_hits(plan: dict, png, pin_targets: dict | None) -> str:
    """Le zone cliccabili invisibili appoggiate sopra i pallini della cartina.

    [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: «la cartina deve essere
    interattiva, ci puoi cliccare e li trovi tutto quello inerente a quello
    […] come se fosse uno zoom out dal macro al micro»]

    Dentro un PNG non si clicca niente: l'immagine e' piatta. Quello che si
    fa qui e' appoggiarci sopra dei collegamenti trasparenti, uno per
    pallino, nella posizione esatta in cui il pallino e' stato disegnato —
    posizione che `src/map_render.py` ci consegna in `plan["pins"]` proprio
    per questo. Il risultato, per chi legge, e' una cartina in cui si tocca
    un posto e si arriva alla sua scheda.

    Un pallino senza destinazione NON diventa cliccabile. Un collegamento che
    non porta da nessuna parte e' peggio di nessun collegamento: il cliente
    ci prova, non succede niente, e da quel momento non si fida piu' del
    resto del documento.
    """
    pins = [x for x in (plan.get("pins") or []) if isinstance(x, dict)]
    if not pins or not pin_targets:
        return ""
    misure = _png_dimensioni(png)
    if misure is None:
        return ""
    larghezza, altezza = misure
    pezzi = []
    for pin in pins:
        poi_id = pin.get("poi_id")
        bersaglio = pin_targets.get(poi_id) if poi_id else None
        if not isinstance(bersaglio, dict) or not bersaglio.get("href"):
            continue
        try:
            x = float(pin.get("x_pct"))
            y = float(pin.get("y_pct"))
            r = float(pin.get("r_pct"))
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        larg_pct = 2 * r * _PIN_HIT_FACTOR
        # Stessa dimensione REALE in orizzontale e in verticale: la
        # percentuale verticale va riscalata sul rapporto fra i lati.
        alt_pct = larg_pct * larghezza / altezza
        if larg_pct >= 100 or alt_pct >= 100:
            continue
        sinistra = max(0.0, min(100.0 - larg_pct, x - larg_pct / 2))
        alto = max(0.0, min(100.0 - alt_pct, y - alt_pct / 2))
        titolo = bersaglio.get("titolo") or ""
        pezzi.append(
            f"<a class='map-hit' href='{_esc(bersaglio['href'])}'"
            + (f" title='{_esc(titolo)}'" if titolo else "")
            + f" style='left:{sinistra:.2f}%;top:{alto:.2f}%;"
            f"width:{larg_pct:.2f}%;height:{alt_pct:.2f}%'>&nbsp;</a>"
        )
    return "".join(pezzi)


def _figura_cliccabile(img_tag: str, hits_html: str) -> str:
    """Mette l'immagine e le sue zone cliccabili nello stesso riquadro.

    Il riquadro e' `inline-block` e non ha dimensioni proprie: si stringe
    esattamente attorno all'immagine. E' questa la ragione per cui le
    percentuali dei pallini cadono al posto giusto — se il contenitore fosse
    largo quanto la pagina, i pallini finirebbero tutti a sinistra.
    """
    if not hits_html:
        return img_tag
    return f"<span class='map-clickable'>{img_tag}{hits_html}</span>"


def _costruisci_pin_targets(
    guide_anchors: dict | None,
    poi_by_id: dict | None,
    guide_urls: dict | None = None,
    capitoli: dict | None = None,
) -> dict:
    """Dove porta il pallino quando ci clicchi sopra.

    [AGGIUNTO 2026-08-03 - richiesta di Lorenzo: «la cartina deve essere
    interattiva, ci puoi cliccare e li trovi tutto quello inerente a quello
    (orari, biglietti, info, guida turistica, come arrivare) cosi' il
    documento principale appare piu' pulito piu' scarno ... come se fosse uno
    zoom out dal macro al micro»]

    Qui si decide UNA cosa sola, ed e' la ragione per cui questa funzione
    esiste separata invece di essere due righe dentro il renderer: la
    destinazione di un pallino ha due modi possibili e non devono convivere
    per caso.

      1. `capitoli` - la guida e' un documento a se' PERO' cucito dentro
         questo stesso file (vedi `src/fascicolo.py`). Il link e' un rimando
         interno `#capitolo-...` che attraversa il confine fra i due
         documenti;
      2. `guide_urls` - la guida e' un documento ospitato su Render e il link
         e' un indirizzo `https://`;
      3. `guide_anchors` - la guida e' un capitolo stampato dentro il
         documento principale e il link e' un rimando interno `#guida-...`.

    [MODIFICATO 2026-08-05 - task #190] Il primo modo e' nuovo ed e' il
    migliore dei tre, per questo viene per primo: e' un documento staccato
    come il secondo — quindi il principale resta scarno, che era la richiesta
    di Lorenzo — ma sta nello stesso file, quindi funziona in aereo come il
    terzo, e in piu' e' l'unico che permette il ritorno al punto esatto di
    partenza. Non e' una preferenza di stile: e' l'unico che soddisfa tutte e
    tre le cose che Lorenzo ha chiesto insieme.

    Se non esiste NESSUNO dei tre, il pallino NON diventa cliccabile - meglio
    un pallino muto di un link che porta a una pagina che non c'e'. E' la
    stessa regola che vale per il resto del documento: si promette solo cio'
    che si puo' mantenere.
    """
    bersagli: dict = {}
    per_id = poi_by_id if isinstance(poi_by_id, dict) else {}

    def _titolo(poi_id):
        posto = per_id.get(poi_id)
        if isinstance(posto, dict):
            return str(posto.get("name") or "").strip()
        return ""

    for poi_id, ancora in (capitoli or {}).items():
        nome = str(ancora or "").strip().lstrip("#")
        if not isinstance(poi_id, str) or not nome:
            continue
        bersagli[poi_id] = {
            "href": f"{pdf_links.LINK_PREFIX}{nome}", "titolo": _titolo(poi_id), "modo": "capitolo",
        }

    for poi_id, url in (guide_urls or {}).items():
        testo = str(url or "").strip()
        # Solo `https://`: un `http://` finirebbe stampato dentro un PDF che
        # viaggia per posta elettronica, e un test del progetto lo vieta.
        if not isinstance(poi_id, str) or not testo.startswith("https://"):
            continue
        if poi_id in bersagli:
            continue
        bersagli[poi_id] = {"href": testo, "titolo": _titolo(poi_id), "modo": "documento"}

    for poi_id, anchor in (guide_anchors or {}).items():
        if not isinstance(poi_id, str) or not anchor or poi_id in bersagli:
            continue
        bersagli[poi_id] = {
            "href": f"{pdf_links.LINK_PREFIX}{anchor}", "titolo": _titolo(poi_id), "modo": "interno",
        }
    return bersagli


def _render_at_a_glance(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None,
    map_png_bytes: bytes | None,
    overview_map: dict | None = None,
    pin_targets: dict | None = None,
) -> str:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "layout migliore/
    infografica, riassumere tutto in una/due pagine"] Pagina di apertura
    "a colpo d'occhio". Il day-by-day completo che segue resta identico,
    invariato — questa e' una sintesi in apertura, non una sostituzione
    del dettaglio.

    [RIFATTA 2026-08-02 (ter) — task #168] Vedi la nota nel CSS
    (`.glance-days`) per il difetto che questa riscrittura chiude: la
    pagina ripeteva, una pagina dopo, cio' che la copertina aveva appena
    detto. Ora contiene due cose e nessuna delle due sta altrove: la
    cartina d'insieme, e il quadro delle giornate con data reale, finestra
    oraria e numero di tappe.

    L'ordine — prima la cartina, poi il quadro — e' lo stesso gia' adottato
    dentro ogni singola giornata: si guarda la mappa per capire la forma,
    poi si legge il dettaglio. L'ordine inverso costringeva a tornare
    indietro (comportamento osservato da Lorenzo sul proprio viaggio).

    Restituisce stringa vuota se non c'e' ne' la cartina ne' una giornata
    da elencare: un capitolo con il solo titolo e sotto il nulla e' peggio
    di un capitolo assente, e il chiamante toglie anche la voce d'indice.
    """
    # [RIFATTA 2026-08-03 — segnalazione del cliente: «risolvi il problema
    # delle cartine che non si vedono»] Fino a ieri qui arrivavano solo dei
    # byte: `map_png_bytes`, una figura gia' finita scaricata da Google con i
    # pallini disegnati da loro. Aveva due difetti che si vedevano entrambi
    # nel documento. Primo: senza chiave o senza rete quei byte non
    # esistevano e la cartina d'insieme spariva — senza che nessuno lo
    # dicesse, il capitolo perdeva la sua meta'. Secondo: essendo un'immagine
    # piatta non sapevamo dove fosse finito ciascun pallino, quindi non
    # potevamo renderli cliccabili.
    #
    # Ora arriva `overview_map`, che ha la stessa identica forma dei piani
    # per giornata: dentro c'e' il PNG, da dove viene (`map_source`) e la
    # geometria dei pallini. Cosi' la cartina d'insieme ha la stessa rete di
    # sicurezza delle altre — se Google non risponde si disegna lo schema in
    # casa — e la stessa didascalia onesta.
    #
    # `map_png_bytes` resta accettato: e' la strada da cui passano ancora i
    # chiamanti vecchi, e toglierla romperebbe chi la usa senza dare nulla in
    # cambio al cliente.
    days = [d for d in (itinerary.get("days") or []) if isinstance(d, dict)]
    piano = overview_map if isinstance(overview_map, dict) else {}
    png = piano.get("png") or map_png_bytes
    if not days and not png:
        return ""

    parts = ["<div class='at-a-glance-page'>"]
    parts.append(_titolo_capitolo("colpo-docchio",
                                  "Il tuo viaggio, a colpo d'occhio",
                                  con_ancora=False))

    if png:
        b64 = base64.b64encode(png).decode("ascii")
        parts.append(
            "<div class='section-intro'>Tutto il viaggio su una cartina sola: "
            "l'alloggio e ogni tappa in programma, cosi' come sono distribuiti "
            "davvero sul territorio. Il numero dentro il pallino dice in che "
            "giorno ci vai.</div>"
        )
        # [2026-08-03] Le zone cliccabili si appoggiano sopra la figura solo
        # se il piano sa DOVE sta ogni pallino (`pins`) e se quel pallino ha
        # davvero una destinazione. Se manca una delle due cose esce
        # l'immagine di prima, identica: la cartina interattiva e' un
        # miglioramento, non una condizione per vedere la cartina.
        img_tag = (
            f"<img src='data:{foto.mime_immagine(png)};base64,{b64}' "
            f"alt='Cartina con hotel, tappe e percorsi'>"
        )
        hits = _render_map_hits(piano, png, pin_targets)
        parts.append(
            f"<div class='map-image'>{_figura_cliccabile(img_tag, hits)}</div>"
        )
        # La didascalia dice CHE COSA si sta guardando. E' la stessa regola
        # gia' applicata alle cartine delle singole giornate: chi scambia lo
        # schema disegnato in casa per una mappa stradale e prova a seguirlo
        # si perde, e chi non sa che le linee sono tratte dritte crede di
        # avere davanti un percorso di navigazione.
        fonte = piano.get("map_source")
        if fonte == "schema":
            didascalia = (
                "Schema in scala di tutto il viaggio: posizioni, distanze e "
                "orientamento sono reali, le strade no. La cartina stradale "
                "vera la trovi dentro ogni singola giornata."
            )
        else:
            didascalia = (
                "Cartina stradale di tutto il viaggio: ogni pallino e' una "
                "tappa e il numero e' il giorno in cui la vedi. Le linee "
                "collegano i punti in linea d'aria — non sono un percorso di "
                "navigazione: orari e modo di spostarsi sono nel dettaglio "
                "giorno per giorno."
            )
        if piano.get("map_declustered"):
            didascalia += (
                " Alcune tappe sono a pochi passi l'una dall'altra: i pallini "
                "sono stati leggermente distanziati per renderli tutti leggibili."
            )
        # Una funzione che nessuno sa che esiste e' una funzione che non
        # esiste: se i pallini sono cliccabili il documento deve dirlo, una
        # volta, qui sotto la cartina.
        if hits:
            didascalia += (
                " Su schermo i pallini sono cliccabili: tocca una tappa per "
                "andare direttamente alla sua guida."
            )
        parts.append(f"<div class='disclaimer'>{didascalia}</div>")

    if days:
        # Il titoletto "Il ritmo delle giornate" serve solo se sopra c'e' la
        # cartina: senza, sarebbe un titolo di sezione appiccicato subito sotto
        # un altro titolo di sezione — due righe di inchiostro per annunciare
        # una cosa sola. Quando la cartina manca, il titolo del capitolo
        # copre gia' quello che segue.
        if png:
            parts.append("<div class='section-title'>Il ritmo delle giornate</div>")
        parts.append(
            "<div class='section-intro'>Quando si esce, fin quando si va avanti e "
            "quante tappe contiene ogni giornata. Il dettaglio di ciascuna, con "
            "orari, indirizzi e spostamenti, e' nel capitolo dedicato.</div>"
        )
        parts.append("<table class='glance-days'>")
        for day in days:
            blocchi = [b for b in (day.get("blocks") or []) if isinstance(b, dict)]
            data = _day_calendar_label(trip.get("date_start"), day.get("day"))
            finestra = _day_time_window(blocchi)
            misure = []
            if finestra:
                misure.append(f"<b>{_esc(finestra)}</b>")
            if blocchi:
                misure.append(
                    "1 tappa" if len(blocchi) == 1 else f"{len(blocchi)} tappe"
                )
            parts.append(
                "<tr>"
                f"<td class='glance-n'>Giorno {_esc(day.get('day'))}"
                + (f"<div class='glance-date'>{_esc(data)}</div>" if data else "")
                + "</td>"
                f"<td class='glance-t'>{_esc(day.get('title', ''))}</td>"
                f"<td class='glance-m'>{' &middot; '.join(misure)}</td>"
                "</tr>"
            )
        parts.append("</table>")

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

    # [RIFATTO 2026-08-02 — task #168] Erano tre elenchi a una colonna di righe
    # da tre parole l'una, con due terzi della larghezza di pagina lasciati
    # bianchi a destra di ogni nome. Su un viaggio breve la sezione occupava
    # mezza pagina per dire nove nomi. Ora ogni elenco è su due colonne — con
    # una tabella, che è l'unico layout multi-colonna affidabile su questo
    # motore — e la stessa informazione occupa la metà dello spazio.
    def _render_list(items: list[dict]) -> str:
        cells = []
        for p in items:
            symbol = price_level_symbol(p.get("price_level"))
            badge = f"<span class='price-badge'>{_esc(symbol)}</span>" if symbol else ""
            cells.append(f"<div class='curated-item'>{_esc(p.get('name'))}{badge}</div>")
        rows = ["<table class='curated-grid'>"]
        for start in range(0, len(cells), 2):
            pair = cells[start:start + 2]
            rows.append("<tr>")
            for cell in pair:
                rows.append(f"<td>{cell}</td>")
            # Con un numero dispari di voci l'ultima cella si allargherebbe a
            # tutta la riga e il nome finale risulterebbe fuori colonna.
            if len(pair) == 1:
                rows.append("<td></td>")
            rows.append("</tr>")
        rows.append("</table>")
        return "".join(rows)

    parts = []
    for title, items in (
        ("Dove mangiare", restaurants),
        ("Shopping", shopping),
        ("Cosa fare", other),
    ):
        if not items:
            continue
        # Il titolo scende insieme alla PRIMA riga del suo elenco: un "Cosa
        # fare" da solo in fondo alla pagina è lo stesso difetto del titolo
        # orfano del programma.
        parts.append(_keep_together(
            f"<div class='section-title'>{_esc(title)}</div>"
            + _render_list(items[:2])
        ))
        if len(items) > 2:
            parts.append(_render_list(items[2:]))
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


_MESI_IT = ("", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _periodo_leggibile(inizio, fine) -> str:
    """«14 → 16 settembre 2026», non «2026-09-14 → 2026-09-16».

    [AGGIUNTO 2026-08-05 — task #195] La data in forma tecnica era, su tutta
    la copertina, l'unico punto in cui si vedeva che il documento l'ha
    scritto un programma. Nessuno scrive «2026-09-14» a un cliente: quella
    forma esiste per gli ordinamenti, e in copertina dice soltanto che
    nessuno ha guardato la pagina prima di venderla.

    Il mese si scrive una volta sola quando i due estremi cadono nello
    stesso mese, che e' il caso della quasi totalita' dei viaggi brevi.
    Se le date non si leggono, si torna alla forma tecnica: meglio brutto
    che assente.
    """
    try:
        a = _date.fromisoformat(str(inizio)[:10])
        b = _date.fromisoformat(str(fine)[:10])
    except (ValueError, TypeError):
        return f"{inizio} \u2192 {fine}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} \u2192 {b.day} {_MESI_IT[b.month]} {b.year}"
    if a.year == b.year:
        return (f"{a.day} {_MESI_IT[a.month]} \u2192 "
                f"{b.day} {_MESI_IT[b.month]} {b.year}")
    return (f"{a.day} {_MESI_IT[a.month]} {a.year} \u2192 "
            f"{b.day} {_MESI_IT[b.month]} {b.year}")


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
    day_entries: list[tuple[str, str]] | None = None,
    guide_count: int = 0,
    leg_count: int = 0,
    # [AGGIUNTO 2026-08-13 — task #209] La fotografia vera del posto, in cima
    # alla copertina. `None` = copertina come prima: un documento senza
    # immagini non deve peggiorare, deve solo restare quello di ieri.
    foto_copertina: tuple[bytes, str] | None = None,
) -> str:
    """Prima pagina dedicata: il documento che il cliente riceve dopo aver
    pagato deve *sembrare* un prodotto, non l'output di uno script. È
    l'unica sezione con `page-break-after: always` — qui il salto pagina è
    voluto, non uno spreco (vedi la nota su `.page-break` nel CSS).

    `sections` sono le sezioni REALMENTE generate (le stesse dell'indice,
    passate dal chiamante): la copertina non deve mai promettere un capitolo
    che poi non c'è.

    [ESTESO 2026-08-01 — "migliorare la parte grafica ... facile da
    comprendere"] Accetta sia `["Titolo", ...]` (forma storica) sia
    `[("ancora", "Titolo"), ...]`: nella seconda forma ogni voce della
    copertina diventa CLICCABILE. Era l'unica lista di capitoli del documento
    che non lo era — il cliente la leggeva per prima, ci provava sopra, e non
    succedeva nulla.

    [RIFATTO 2026-08-02 — task #168, «troppi spazi vuoti dispersivi»] Questa
    pagina ha inglobato l'indice, che prima stava da solo sulla pagina
    successiva. Non è una compressione fatta per risparmiare carta: le due
    pagine elencavano LO STESSO indice, e nessuna delle due arrivava a metà
    altezza. Il cliente girava la copertina e ritrovava, identica, la lista che
    aveva appena letto. Ora `day_entries` porta qui anche i giorni annidati —
    l'unica cosa che la pagina separata aveva in più — e la pagina è una,
    piena, e cliccabile per intero."""
    destination = itinerary.get("destination") or trip.get("destination") or ""
    budget_str = (
        "Illimitato" if trip.get("budget_mode") == "UNLIMITED"
        else (_fmt_eur(trip.get("budget_eur")) or _esc(trip.get("budget_eur")))
    )
    days = [d for d in (itinerary.get("days") or []) if isinstance(d, dict)]
    # [RIVISTO 2026-08-02 (bis) — task #168] Date e durata NON stanno più qui:
    # da quando la fascia scura le mostra in grande, ripeterle nei riquadri
    # sottostanti era lo stesso difetto che aveva fatto fondere copertina e
    # indice — due elenchi contigui che dicono la stessa cosa. I riquadri ora
    # dicono cose che la fascia non dice, e tre di esse sono numeri di
    # consegna: quante giornate, quante tappe, quante schede. È l'unico punto
    # del documento in cui il cliente vede, in cifre, cosa ha ricevuto.
    rows = [("Budget indicato", budget_str)]
    if hotels:
        rows.append(("Base", hotels[0].get("name") or "[Da Verificare]"))
    if days:
        rows.append(("Giornate progettate", str(len(days))))
    stops = sum(
        len([b for b in (d.get("blocks") or []) if isinstance(b, dict)])
        for d in days
    )
    if stops:
        rows.append(("Tappe in programma", str(stops)))
    if leg_count:
        rows.append((
            "Spostamenti mappati",
            "1 tratta" if leg_count == 1 else f"{leg_count} tratte",
        ))
    if guide_count:
        rows.append((
            "Guide incluse",
            "1 scheda" if guide_count == 1 else f"{guide_count} schede",
        ))

    # La striscia dentro la fascia scura ripete le due informazioni che si
    # cercano per prime. Se una delle due manca la cella non si stampa: una
    # etichetta con sotto il vuoto è peggio dell'etichetta assente.
    strip = []
    if trip.get("date_start") and trip.get("date_end"):
        strip.append(("Quando", _periodo_leggibile(
            trip.get("date_start"), trip.get("date_end"))))
    # [TOLTA DA QUI 2026-08-15 — task #218] La durata la dice il bollo tondo
    # dentro il blocco della copertina, sei centimetri piu' in alto. La stessa
    # informazione due volte sulla stessa pagina non rassicura: fa venire il
    # dubbio che siano due cose diverse lette male.

    # --- Indice: colonne e bilanciamento, calcolati PRIMA di stampare ------
    # Servono qui in cima perché la loro altezza decide quanto respiro può
    # permettersi il resto della pagina (vedi `density` poco sotto).
    # Normalizzazione delle due forme accettate in `(ancora|None, titolo)`.
    entries: list[tuple[str | None, str]] = []
    for item in sections or []:
        if isinstance(item, str) and item.strip():
            entries.append((None, item))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            anchor, title = item
            if isinstance(title, str) and title.strip():
                entries.append((anchor if isinstance(anchor, str) and anchor else None, title))
    subs = list(day_entries or [])
    columns: tuple[list, list] | None = None
    tallest = 0
    if len(entries) >= 2:
        # Il bilanciamento conta le RIGHE stampate, non i capitoli: i giorni
        # annidati sotto "Il programma" occupano una riga ciascuno, e ignorarli
        # produceva una colonna sinistra lunga il doppio della destra su ogni
        # viaggio di più di due giorni.
        weights = [
            1 + (len(subs) if anchor == "giorno-per-giorno" else 0)
            for anchor, _ in entries
        ]
        target = (sum(weights) + 1) // 2
        split, running = len(entries), 0
        for index, weight in enumerate(weights):
            running += weight
            if running >= target:
                split = index + 1
                break
        split = max(1, min(split, len(entries) - 1))
        columns = (entries[:split], entries[split:])
        tallest = max(sum(weights[:split]), sum(weights[split:]))

    # --- Quanto respiro può permettersi la copertina ----------------------
    # [AGGIUNTO 2026-08-02 (bis) — task #168] La copertina deve arrivare in
    # fondo al foglio SENZA traboccare sulla seconda pagina, e la sua altezza
    # non è fissa: dipende dai giorni di viaggio, perché ogni giornata è una
    # riga annidata nell'indice. Un'unica spaziatura generosa riempie bene un
    # weekend e fa sbordare una vacanza di due settimane; un'unica spaziatura
    # stretta non sborda mai ma lascia un terzo di pagina bianco sui viaggi
    # corti — che sono la maggioranza. Quindi la spaziatura è a tre livelli,
    # scelti sulla colonna PIÙ ALTA dell'indice, che è ciò che detta davvero
    # l'altezza. Le soglie sono misurate sul PDF vero, non stimate.
    # [STRETTE 2026-08-11 — segnalazione di Lorenzo: «l'impaginazione della
    # prima e seconda pagina fa schifo, non voglio una pagina iniziata per due
    # righe e poi lasciata bianca».]
    #
    # Le soglie erano 8 e 11 ed erano tarate su un campione COSTRUITO A MANO.
    # Sul primo documento uscito davvero dalla catena completa — Bologna, due
    # giorni, indice alto 6 — la copertina prendeva il respiro massimo e la
    # nota di chiusura sbordava di due righe sulla pagina dopo, lasciandola
    # bianca per il resto. Due righe su una pagina intera sono la cosa che, in
    # un documento venduto, si nota per prima.
    #
    # Ora sono 4 e 7. La regola dietro il numero: **fra una copertina un po'
    # piu' compatta e una seconda pagina quasi vuota, vince sempre la prima.**
    # Il bianco in fondo a una pagina e' respiro; il bianco sotto due righe e'
    # un errore.
    # [CORRETTO 2026-08-13 — task #209, e il difetto e' stato visto sulla
    # pagina prima di essere riparato.] Le soglie qui sotto erano tarate su
    # una copertina SENZA fotografia. Appena la fascia in cima e' comparsa, la
    # copertina del campione ha sfondato sulla seconda pagina lasciandola
    # bianca per nove decimi: esattamente cio' che Lorenzo aveva segnalato
    # l'11 agosto («non voglio una pagina iniziata per due righe e poi
    # lasciata bianca»), ricomparso da un'altra porta.
    #
    # La fascia occupa piu' o meno quanto tre voci d'indice. Quindi, quando
    # c'e', il respiro scala di un livello: e' l'unico modo di aggiungere
    # un'immagine senza rimettere in gioco l'impaginazione.
    limite_arioso, limite_comodo = (2, 4) if foto_copertina else (4, 7)
    if tallest <= limite_arioso:
        density = " cover-airy"
    elif tallest <= limite_comodo:
        density = " cover-roomy"
    else:
        density = ""

    apertura = ""
    if foto_copertina:
        try:
            byte_foto, credito = foto_copertina
            byte_foto = foto.ritaglia_panoramica(byte_foto, _RAPPORTO_FASCIA) or byte_foto
            b64 = base64.b64encode(byte_foto).decode("ascii")
            tipo = foto.mime_immagine(byte_foto)
            didascalia = (f"<div class='didascalia'>Foto: {_esc(credito)}</div>"
                          if str(credito or "").strip() else "")
            apertura = (f"<div class='cover-foto'>"
                        f"<img src='data:{tipo};base64,{b64}' alt=''/>"
                        f"{didascalia}</div>")
        except (TypeError, ValueError, AttributeError):
            # Una fotografia illeggibile non deve costare il documento: al
            # massimo costa la fotografia. Vale per tutte le immagini di
            # questo progetto, e vale a maggior ragione per la prima pagina.
            apertura = ""

    # [RIFATTA 2026-08-15 — task #218] La testata della copertina: un blocco
    # di colore pieno, la fotografia tonda del posto a sinistra, il bollo con
    # la durata a destra. E' il pezzo del prototipo che Lorenzo aveva
    # approvato e che il documento vero non aveva mai avuto.
    #
    # SOSTITUISCE il titolo che c'era, non si aggiunge: il blocco e' alto piu'
    # o meno quanto le quattro righe di prima, quindi la copertina resta di
    # UNA pagina. Non e' un dettaglio — la copertina che sborda sulla seconda
    # pagina e' un difetto gia' visto due volte in questo progetto, e la
    # seconda volta e' comparso proprio aggiungendo un'immagine.
    tonda = ""
    if foto_copertina:
        try:
            ritagliata = foto.ritaglia_tondo(foto_copertina[0])
            if ritagliata:
                b64_tonda = base64.b64encode(ritagliata).decode("ascii")
                tonda = ("<td class='cover-tonda'>"
                         f"<img src='data:{foto.mime_immagine(ritagliata)};"
                         f"base64,{b64_tonda}' alt=''/></td>")
        except (TypeError, ValueError, AttributeError):
            # Il ritaglio tondo si fa sui PIXEL e non con gli angoli
            # arrotondati del foglio di stile: quelli, con questo motore di
            # stampa, danno una figura mezza tonda e mezza quadrata. Se anche
            # il ritaglio vero non riesce, si resta senza — mai con la figura
            # sbagliata.
            tonda = ""
    giorni = str(trip.get("duration_days") or "").strip()
    bollo = ""
    if giorni:
        bollo = ("<td class='cover-bollo-cella'><div class='cover-bollo'>"
                 f"<div class='cover-bollo-n'>{_esc(giorni)}</div>"
                 f"<div class='cover-bollo-t'>giorni</div></div></td>")

    parts = [
        f"<div class='cover{density}'>",
        apertura,
        "<div class='cover-hero'>",
        "<div class='cover-blocco'><table class='cover-blocco-t'><tr>",
        tonda,
        "<td class='cover-blocco-testo'>",
        "<div class='cover-kicker'>Itinerario su misura</div>",
        f"<h1 class='cover-title'>{_esc(destination)}</h1>",
        "<div class='cover-rule'></div>",
        "<div class='cover-sub'>Progettato attorno al tuo ritmo, ai tuoi orari "
        "e al tuo budget.</div>",
        "</td>",
        bollo,
        "</tr></table></div>",
    ]
    if strip:
        parts.append("<table class='cover-hero-strip'><tr>")
        for key, value in strip:
            parts.append(
                f"<td><div class='cover-hero-k'>{_esc(key)}</div>"
                f"<div class='cover-hero-v'>{_esc(value)}</div></td>"
            )
        parts.append("</tr></table>")
    parts += [
        "</div>",
        "<table class='cover-facts'>",
    ]
    # Tre celle per riga. L'ultima riga, se incompleta, NON viene riempita con
    # celle vuote: i riquadri si allargano fino a chiudere la riga.
    # [CORRETTO 2026-08-02 (bis) — task #168] Prima si riempiva con celle
    # vuote per tenere i riquadri incolonnati. Guardando il PDF vero, il
    # risultato era peggiore del difetto che evitava: due riquadri e un buco
    # bianco della stessa forma accanto, che si legge come un riquadro che non
    # e' stato stampato. Una riga chiusa da riquadri piu' larghi si legge come
    # una scelta; un buco si legge come un errore.
    per_row = 3
    for start in range(0, len(rows), per_row):
        parts.append("<tr>")
        for key, value in rows[start:start + per_row]:
            parts.append(
                f"<td><div class='cover-fact'>"
                f"<div class='cover-fact-k'>{_esc(key)}</div>"
                f"<div class='cover-fact-v'>{_esc(value)}</div></div></td>"
            )
        parts.append("</tr>")
    parts.append("</table>")

    # "Cosa troverai dentro": due colonne bilanciate, la prima metà a
    # sinistra. Con una sola voce la tabella a due colonne sarebbe sbilanciata
    # e peggiorerebbe l'impaginazione invece di migliorarla: sotto le due voci
    # la striscia non si stampa proprio.
    if columns:
        parts.append(
            "<div class='cover-toc'>"
            "<div class='cover-toc-title'>Cosa troverai dentro</div>"
            "<table><tr>"
        )
        offset = 0
        for column in columns:
            parts.append("<td class='col'>")
            for index, (anchor, title) in enumerate(column):
                label = (
                    f"<a href='{pdf_links.LINK_PREFIX}{_esc(anchor)}'>{_esc(title)}</a>" if anchor
                    else _esc(title)
                )
                parts.append(
                    f"<div class='cover-toc-item'>"
                    f"<span class='cover-toc-num'>{offset + index + 1:02d}</span>"
                    f"{label}</div>"
                )
                if anchor == "giorno-per-giorno":
                    for day_anchor, day_title in subs:
                        parts.append(
                            f"<div class='cover-toc-sub'>"
                            f"<a href='{pdf_links.LINK_PREFIX}{_esc(day_anchor)}'>{_esc(day_title)}</a></div>"
                        )
            parts.append("</td>")
            offset += len(column)
        parts.append("</tr></table></div>")

    # "Come si legge": tre istruzioni brevi. Vanno DOPO l'indice, perché
    # spiegano come usare quello che l'indice elenca — e perché in fondo alla
    # pagina reggono il peso visivo della fascia scura in alto.
    parts.append(
        "<div class='cover-how'>"
        "<div class='cover-how-title'>Come si legge</div>"
        "<table><tr>"
        "<td><div class='cover-how-cell'><b>È cliccabile.</b> Dall'indice qui sopra "
        "salti al capitolo; dal programma salti alla guida del luogo, ai menù dei "
        "ristoranti e al percorso già pronto su Maps.</div></td>"
        # La cartina cliccabile e' il meccanismo nuovo del documento, ed e'
        # anche l'unico che il cliente non puo' scoprire da solo: su carta non
        # esiste il cursore che cambia forma sopra un collegamento. Una
        # funzione che nessuno sa di avere non e' una funzione: qui si dice.
        "<td><div class='cover-how-cell'><b>La cartina si tocca.</b> Ogni tappa "
        "numerata sulla cartina della giornata è un pulsante: toccala e apri la "
        "sua guida, con orari, biglietti e come arrivarci.</div></td>"
        "<td><div class='cover-how-cell'><b>Quello che non sapevamo è marcato.</b> "
        "Nessun orario, prezzo o indirizzo è stato inventato per riempire un vuoto: "
        "se manca, lo dice.</div></td>"
        "</tr></table></div>"
    )

    parts.append(
        "<div class='cover-note'>Ogni luogo, coordinata e prezzo in questo documento proviene "
        "da dati reali raccolti al momento della generazione. Dove un dato non era disponibile "
        "lo troverai marcato come da verificare, mai sostituito da una stima inventata.</div>"
    )
    parts.append("</div>")
    return "".join(parts)


def _keep_together(html: str) -> str:
    """Guscio che impedisce a un titolo di restare solo in fondo alla pagina.

    [AGGIUNTO 2026-08-02 — task #168] Il motore di stampa ignora la richiesta
    di "non spezzare DOPO" un elemento: è una proprietà che Qt WebKit non ha
    mai implementato. Onora invece "non spezzare DENTRO" una tabella. Quindi
    il titolo e il primo pezzo del suo contenuto entrano in una tabella a una
    cella: o ci stanno insieme in questa pagina, o scendono insieme alla
    prossima. Senza, il campione stampava "Il programma, giorno per giorno"
    sull'ultima riga della pagina 3 e il programma vero sulla 4.

    Va usato con PICCOLE quantità di contenuto (titolo + occhiello, titolo +
    prima riga). Su un blocco alto quanto una pagina la stessa regola produce
    il difetto opposto: il motore, non riuscendo a farlo stare, lo butta tutto
    sulla pagina dopo e lascia bianco il fondo di questa."""
    return f"<table class='keep'><tr><td>{html}</td></tr></table>"


# --- Impaginazione: un paragrafo non si spezza fra due pagine ------------
#
# [AGGIUNTO 2026-08-03 — task #183, richiesta di Lorenzo: «migliorare
# l'impaginazione per evitare di spezzare lo stesso paragrafo»]
#
# Oltre questa soglia di caratteri VISIBILI un blocco non viene piu' tenuto
# insieme. Non e' prudenza generica, e' il difetto opposto e simmetrico:
# `page-break-inside: avoid` su un blocco che non entra nello spazio rimasto
# lo fa scendere INTERO alla pagina dopo, e quello che resta e' bianco. Su un
# blocco di tre righe si perdono al massimo due righe; su un blocco di venti
# se ne perdono diciannove, ed e' esattamente «troppi spazi vuoti dispersivi»,
# il reclamo precedente di Lorenzo. Le due richieste sono in tensione e il
# numero e' il punto in cui si incontrano.
#
# 900 caratteri sono circa nove righe stampate (il corpo del testo gira sui
# 100 caratteri per riga a questa larghezza e a questo corpo). I paragrafi
# veri delle guide misurati sul campione stanno fra 340 e 530 caratteri,
# cioe' quattro-sei righe: la soglia li copre tutti con margine, e taglia
# fuori solo i blocchi anomali — quelli per cui spezzare e' davvero il male
# minore.
LIMITE_PROSA_UNITA = 900

# I blocchi di prosa che questa regola protegge. Sono elencati per classe e
# non riconosciuti "a naso" perche' la regola deve valere per quello che il
# documento contiene DAVVERO, non per qualunque cosa somigli a un paragrafo:
# le righe di una tabella, le tappe di una giornata e i riquadri hanno gia'
# le loro protezioni, e avvolgerli una seconda volta creerebbe tabelle
# annidate senza motivo.
_CLASSI_PROSA = ("guide-para", "corpo", "section-intro", "disclaimer")

_RE_PROSA = re.compile(
    r"<(p|div) class='(" + "|".join(_CLASSI_PROSA) + r")'>"
    r"((?:(?!</?(?:p|div)\b).)*?)"
    r"</\1>",
    re.DOTALL,
)

_RE_SOLO_TESTO = re.compile(r"<[^>]+>")


def _lunghezza_visibile(html_interno: str) -> int:
    """Quanti caratteri di questo pezzo di HTML finiscono sulla carta.

    I marcatori non si stampano e le entita' (`&#x27;`, `&#160;`, `&amp;`)
    valgono un carattere sola, non sei: contarli per esteso gonfierebbe la
    misura di un buon dieci per cento sui testi italiani, pieni di apostrofi,
    e la soglia scatterebbe su paragrafi che in realta' sono corti.
    """
    testo = _RE_SOLO_TESTO.sub("", html_interno)
    return len(html.unescape(testo))


# Un titolo di sezione seguito subito dalla sua riga di presentazione. Sono
# due elementi semplici e mai annidati, quindi qui l'espressione regolare e'
# sicura — cosa che NON sarebbe se provasse a inghiottire il primo blocco
# qualunque, che puo' contenerne altri dentro.
_RE_TITOLO_CON_INIZIO = re.compile(
    r"(<div class='section-title'>.*?</div>)\s*"
    r"(<div class='section-intro'>.*?</div>)",
    re.S,
)


def _tieni_il_titolo_col_suo_inizio(documento: str) -> str:
    """Un titolo non resta mai da solo in fondo alla pagina.

    [AGGIUNTO 2026-08-13 — segnalazione di Lorenzo: «non voglio che ci sia una
    pagina iniziata per due righe e poi lasciata bianca», e prima ancora
    «evitando di spezzare i paragrafi o di iniziare una pagina con tre
    righe».]

    Il motore di stampa non conosce «non spezzare DOPO questo elemento»: la
    proprieta' esiste nello standard e qui viene ignorata in silenzio. Conosce
    invece «non spezzare DENTRO una tabella». Quindi il titolo e la sua riga
    di presentazione viaggiano dentro la stessa tabella-guscio: o entrano
    insieme in questa pagina, o vanno insieme nella prossima.

    E' lo stesso identico rimedio gia' usato per i paragrafi corti, applicato
    allo stesso modo — una passata sola sul documento finito invece di una
    regola da ricordarsi in quindici punti diversi. Vale anche per le sezioni
    che ancora non esistono, che e' l'unico modo perche' non si debba
    richiedere la stessa cosa fra un mese.
    """
    return _RE_TITOLO_CON_INIZIO.sub(
        lambda m: f"<table class='keep'><tr><td>{m.group(1)}{m.group(2)}</td></tr></table>",
        documento,
    )


def _tieni_uniti_i_paragrafi(documento: str) -> str:
    """Passata finale di impaginazione sull'intero documento.

    [AGGIUNTO 2026-08-03 — task #183]

    Perche' qui e non nei singoli punti che scrivono i paragrafi: perche' i
    punti che scrivono paragrafi sono una quindicina sparsi su quattromila
    righe, e domani saranno sedici. Una regola applicata a mano in quindici
    posti e' una regola che il sedicesimo non avra'. Applicata una volta sola
    sul documento finito, vale anche per i capitoli che ancora non esistono —
    che e' l'unico modo perche' Lorenzo non debba chiedere di nuovo la stessa
    cosa fra un mese.

    La regola: ogni blocco di prosa abbastanza corto entra in una tabella a
    una cella, l'unica cosa su cui il motore di stampa onora davvero il
    "non spezzare dentro" (vedi `_keep_together`). I blocchi lunghi restano
    come sono e possono spezzarsi: e' voluto, la ragione sta su
    `LIMITE_PROSA_UNITA`.

    L'espressione regolare salta i blocchi che contengono altri `<p>` o
    `<div>` annidati: quelli sono contenitori, non paragrafi, e avvolgerli
    intero significherebbe rendere inscindibile mezza pagina.
    """

    def _sostituisci(m: "re.Match[str]") -> str:
        intero, interno = m.group(0), m.group(3)
        if _lunghezza_visibile(interno) > LIMITE_PROSA_UNITA:
            return intero
        return f"<table class='keep-prosa'><tr><td>{intero}</td></tr></table>"

    return _RE_PROSA.sub(_sostituisci, documento)


# --- Cartina del giorno + legenda ---------------------------------------
def _render_day_map(
    day_map: dict | None,
    title_html: str = "",
    pin_targets: dict | None = None,
) -> str:
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
    hits = ""
    if png:
        b64 = base64.b64encode(png).decode("ascii")
        # [2026-08-03 - «la cartina deve essere interattiva»] Stessa
        # meccanica della cartina d'insieme: zone cliccabili invisibili
        # appoggiate sopra i pallini. Se il piano non porta la geometria dei
        # pallini, o se nessuna tappa ha una destinazione, resta l'immagine
        # di prima senza differenze.
        img_tag = (
            f"<img src='data:{foto.mime_immagine(png)};base64,{b64}' "
            f"alt='Cartina del giorno con le tappe numerate'>"
        )
        hits = _render_map_hits(day_map, png, pin_targets)
        img_html = _figura_cliccabile(img_tag, hits)
        # [2026-08-02] La didascalia dice al cliente CHE COSA sta guardando.
        # Quando la figura è lo schema disegnato in casa (niente strade, niente
        # edifici) tacerlo sarebbe una piccola bugia per omissione: chi la
        # scambia per una mappa stradale e prova a seguirla si perde. Le
        # posizioni relative, le distanze e la scala sono però reali e misurate,
        # e questo va detto con la stessa chiarezza — altrimenti la figura
        # sembra un disegnino ornamentale e il cliente la ignora.
        if day_map.get("map_source") == "schema":
            caption = (
                "Schema in scala delle tappe: posizioni, distanze e orientamento "
                "sono reali, le strade no. Per il percorso vero usa i collegamenti "
                "«Apri in Maps» qui sotto."
            )
        else:
            # [2026-08-02] Cartina stradale vera con i NOSTRI pallini disegnati
            # sopra (vedi maps_static.build_day_base_map_url). Anche qui la
            # didascalia dice cosa si sta guardando, e soprattutto cosa NON si
            # sta guardando: le linee restano tratte dritte fra una tappa e
            # l'altra, non un itinerario calcolato sulle strade. Tacerlo
            # sarebbe peggio qui che sullo schema, perché con le strade sotto
            # la linea SEMBRA un percorso di navigazione.
            caption = (
                "Cartina stradale della giornata: i numeri seguono l'ordine di "
                "visita, la linea continua è il giro e quella tratteggiata il "
                "rientro. Le linee sono indicative — collegano le tappe in linea "
                "d'aria, non sono un percorso di navigazione: per quello usa i "
                "collegamenti «Apri in Maps» qui sotto."
            )
        if day_map.get("map_declustered"):
            # Se due pallini sono stati allontanati per non coprirsi, va
            # detto: chi misura col righello deve sapere perché due tappe a
            # venti metri sull'immagine ne sembrano cinquanta.
            caption += (
                " Alcune tappe sono a pochi passi l'una dall'altra: i pallini "
                "sono stati leggermente distanziati per renderli tutti leggibili."
            )
        if hits:
            caption += (
                " Su schermo pallini e voci della legenda sono cliccabili: "
                "portano alla guida della singola tappa."
            )
        img_html += f"<div class='map-caption'>{caption}</div>"

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
        # [CORRETTO 2026-08-02] La riga «H» si stampava SEMPRE, anche quando la
        # cartina non aveva nessun pallino H — succede se l'alloggio non è
        # geolocalizzato. La legenda prometteva un simbolo che sulla figura non
        # c'era, ed è il tipo di dettaglio che fa dubitare di tutto il resto.
        if day_map.get("hotel_point"):
            parts.append(
                "<div class='map-legend-row'><span class='map-pin pin-red'>H</span>"
                "<strong>Punto di partenza e rientro</strong> "
                "<span class='map-legend-type'>— il tuo alloggio</span></div>"
            )
        for stop in stops:
            pin_class = _PIN_CLASS_BY_COLOR.get(stop.get("color"), "pin-blue")
            label = stop.get("label") or "•"
            # [CORRETTO 2026-08-02 — difetto visto rigenerando il campione con
            # un payload completo, non dedotto a tavolino] Prima si stampava
            # `location`, cioè il campo indirizzo del blocco: in legenda usciva
            # «1 Siena — 10:30 · Attività» e «3 Via Giovanni Duprè 132». Ma la
            # legenda esiste per rispondere a UNA domanda — "il puntino 1 cos'è?"
            # — e un indirizzo non risponde: il cliente ha la cartina davanti e
            # cerca il NOME. L'indirizzo resta stampato nel programma, due
            # centimetri più sotto.
            # [RAFFINATO poche ore dopo] Prima veniva `activity`, che è una
            # FRASE: «2 Pranzo alla Taverna di San Giuseppe — 12:30 · Dove
            # mangiare» dice due volte la stessa cosa e non è quello che il
            # cliente legge sull'insegna. `stop["name"]` (aggiunto in
            # `maps_static.build_day_map_plans()`) è il nome proprio del posto
            # secondo Google. I ripieghi restano nell'ordine giusto: meglio una
            # frase di un indirizzo, meglio un indirizzo di un puntino muto.
            name = stop.get("name") or stop.get("activity") or stop.get("location") or ""
            time = stop.get("time") or ""
            type_label = stop.get("type_label") or ""
            meta = " · ".join(x for x in (time, type_label) if x)
            # [AGGIUNTO 2026-08-03 - «la cartina deve essere interattiva»]
            # La riga di legenda cliccabile non e' un doppione del pallino
            # cliccabile: e' la versione che funziona davvero. Un pallino
            # stampato misura pochi millimetri e centrarci sopra un dito su
            # un telefono e' una lotteria; il nome scritto per esteso e' un
            # bersaglio largo quanto la colonna. Il pallino resta perche' e'
            # il gesto naturale ("clicco su quello che vedo sulla cartina"),
            # la riga perche' e' quello che riesce.
            bersaglio = (pin_targets or {}).get(stop.get("poi_id"))
            nome_html = f"<strong>{_esc(name)}</strong>"
            if isinstance(bersaglio, dict) and bersaglio.get("href"):
                nome_html = (
                    f"<a class='legend-link' href='{_esc(bersaglio['href'])}'>"
                    f"{nome_html}</a>"
                )
            parts.append(
                f"<div class='map-legend-row'>"
                f"<span class='map-pin {pin_class}'>{_esc(label)}</span>"
                f"{nome_html}"
                + (f" <span class='map-legend-type'>— {_esc(meta)}</span>" if meta else "")
                + "</div>"
            )
        parts.append("</div>")
    if side_by_side:
        parts.append("</td></tr></table>")
    parts.append("</div>")
    return "".join(parts)


# --- Cartina e come arrivare --------------------------------------------
def _render_leg_inline(leg: dict | None) -> str:
    """Uno spostamento, dentro il programma della giornata.

    [RIFATTO 2026-08-03 — richiesta di Lorenzo: «la parte del "come arrivare"
    appare ridondante, uniscila al programma del giorno»]

    Fino a ieri gli stessi spostamenti comparivano DUE volte: una nel
    programma (come riga di logistica) e una in un riquadro "Come arrivare"
    subito sotto, che ripeteva le stesse tappe nello stesso ordine. Chi
    leggeva doveva confrontare due elenchi per capire che dicevano la stessa
    cosa. Ora la riga sta dove serve: attaccata alla tappa a cui porta, letta
    un attimo prima di alzarsi dal tavolo.

    La riga e' volutamente compatta — una freccia, il tempo, i chilometri, il
    link. Tutto quello che era decorazione (etichette della cartina ripetute
    per esteso, ora di arrivo gia' scritta due righe sotto) e' stato tolto:
    e' la stessa richiesta di Lorenzo di "meno testo".
    """
    if not isinstance(leg, dict):
        return ""
    pezzi = []
    mode = leg.get("mode_label") or leg.get("mode") or ""
    durata = leg.get("duration_text") or describe_leg_duration(leg.get("minutes"), mode)
    if durata:
        pezzi.append(_esc(durata))
    else:
        pezzi.append(
            "<span class='leg-unknown'>tempo da verificare sul momento</span>"
        )
    distanza = leg.get("distance_text")
    if distanza:
        # "circa" solo quando i metri sono una stima nostra e non una misura
        # di Google: il cliente deve poter distinguere i due casi senza
        # doverci credere sulla parola.
        prefisso = "circa " if leg.get("metres_estimated") else ""
        pezzi.append(f"{_esc(prefisso)}{_esc(distanza)}")
    parti_da = str(leg.get("depart_by") or "").strip()
    if parti_da:
        pezzi.append(
            f"<strong class='leg-depart'>parti entro le {_esc(parti_da)}</strong>"
        )
    url = leg.get("url")
    if url:
        pezzi.append(f"<a href='{_esc(url)}'>percorso</a>")
    alt_url = leg.get("alt_url")
    if alt_url:
        alt = leg.get("alt_mode_label") or "alternativa"
        pezzi.append(f"<a href='{_esc(alt_url)}'>oppure {_esc(alt)}</a>")
    provenienza = str(leg.get("from_name") or "").strip()
    testa = f"da {_esc(provenienza)}" if provenienza else "spostamento"
    return (
        # Il separatore dopo la testa non e' decorazione: senza, la riga si
        # legge "da Palazzo Ravizza tempo da verificare" come se fosse una
        # frase sola. Con il punto elenco si legge come un elenco, che e' cio'
        # che e'.
        f"<div class='leg-inline'><span class='leg-inline-head'>&#8594; {testa}</span> · "
        + " · ".join(pezzi)
        + "</div>"
    )


def _render_day_travel_total(legs) -> str:
    """La riga dei chilometri di giornata, sotto al titolo del giorno.

    [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: «inserire nel programma del
    giorno il totale di chilometri/percorrenze a piedi»]

    E' il numero che decide le scarpe. Compare solo quando c'e' davvero
    qualcosa da dire (vedi `directions.summarize_day_travel`): su una
    giornata passata dentro un museo una riga "0 m" sarebbe rumore, e su una
    giornata di cui non conosciamo le distanze sarebbe una bugia.
    """
    sintesi = summarize_day_travel(legs)
    if not sintesi:
        return ""
    prefisso = "circa " if sintesi.get("estimated") else ""
    testo = f"In movimento: {prefisso}{sintesi['metres_text']}"
    if sintesi.get("walking_text"):
        testo += f", di cui {sintesi['walking_text']} a piedi"
        if sintesi.get("walking_minutes"):
            testo += f" (~{sintesi['walking_minutes']} min di cammino)"
    return f"<div class='day-total'>{_esc(testo)}</div>"


def _foto_di_apertura(days, photos: dict | None) -> tuple[bytes, str] | None:
    """La fotografia che apre il documento: la prima tappa vera del viaggio.

    [AGGIUNTO 2026-08-13 — task #209] La copertina era l'unica pagina del
    documento senza una sola immagine: il cliente pagava, apriva, e trovava
    del testo. Adesso apre e vede il posto dove sta andando.

    Si sceglie la PRIMA tappa in ordine di visita, non «la piu' bella»: non
    abbiamo modo di sapere quale sia la piu' bella, e qualunque criterio ce lo
    facesse credere sarebbe un dato inventato. La prima tappa ha per giunta un
    senso narrativo — e' da li' che il viaggio comincia davvero.

    Deterministica di proposito: lo stesso viaggio, rigenerato, deve dare la
    stessa copertina. Una prima pagina che cambia fra due esecuzioni identiche
    e' un difetto che nessuno riesce a riprodurre.
    """
    for giorno in days or []:
        if not isinstance(giorno, dict):
            continue
        candidate = _foto_vere_della_giornata(giorno.get("blocks"), photos)
        for _poi_id, scatto, _nome in candidate:
            dati = scatto.get("png")
            if isinstance(dati, (bytes, bytearray)) and dati:
                return bytes(dati), str(scatto.get("credito") or "")
    return None


def _foto_vere_della_giornata(blocks, photos: dict | None) -> list:
    """Le fotografie VERE delle tappe di una giornata, nell'ordine di visita.

    Una tappa sola per luogo: se il cliente torna in Piazza Maggiore due
    volte, la sua fotografia si stampa una volta.
    """
    if not isinstance(photos, dict) or not photos:
        return []
    viste, uscita = set(), []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        poi_id = block.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id or poi_id in viste:
            continue
        scatto = photos.get(poi_id)
        if not isinstance(scatto, dict) or not scatto.get("reale"):
            continue
        credito = scatto.get("credito")
        if not scatto.get("png") or not isinstance(credito, str) or not credito.strip():
            continue
        viste.add(poi_id)
        uscita.append((poi_id, scatto, str(block.get("location") or "").strip()))
    return uscita


def _render_striscia_foto(blocks, photos: dict | None, gia_usata: str = "") -> str:
    """Fino a tre fotografie in fila, in chiusura di giornata.

    [AGGIUNTO 2026-08-13 — richiesta di Lorenzo: «inserisci piu' foto,
    soprattutto negli spazi bianchi; a pagina 5 e 7 ce ne stanno almeno 3».]

    Una fotografia per giornata lasciava mezze pagine vuote e raccontava un
    luogo su sei. Qui se ne mettono altre due o tre, in fondo alla giornata:
    e' il punto in cui lo spazio avanza davvero, ed e' anche il posto giusto
    per un colpo d'occhio su cio' che si e' appena letto.

    Tre scelte, tutte per lo stesso motivo — che il documento non peggiori
    quando i dati sono pochi:

      - la fila si stampa **solo se ci sono almeno due** fotografie nuove. Una
        sola, larga un terzo di pagina e sola in una riga da tre, sembra un
        errore di impaginazione;
      - le colonne si fanno con una TABELLA, l'unico modo che questo motore
        di stampa conosce davvero;
      - `page-break-inside: avoid` sulla tabella: se la fila non ci sta,
        scende intera invece di spezzarsi in due pagine — la stessa regola
        della nota di copertina, e per lo stesso motivo.
    """
    candidate = [c for c in _foto_vere_della_giornata(blocks, photos)
                 if c[0] != gia_usata][:3]
    if len(candidate) < 2:
        return ""
    larghezza = 100 // len(candidate)
    celle = []
    for _poi_id, scatto, nome in candidate:
        try:
            b64 = base64.b64encode(scatto["png"]).decode("ascii")
        except (TypeError, ValueError, KeyError):
            continue
        tipo = foto.mime_immagine(scatto.get("png"))
        celle.append(
            f"<td style='width:{larghezza}%'>"
            f"<img src='data:{tipo};base64,{b64}' alt='{_esc(nome)}'>"
            f"<div class='didascalia'>{_esc(scatto.get('credito') or '')}</div>"
            "</td>"
        )
    if len(celle) < 2:
        return ""
    return ("<table class='day-striscia'><tr>" + "".join(celle) + "</tr></table>")


def _apertura_di_giornata(chiave, giorno_numero, blocks, photos,
                          riserva_viaggio, apertura_precedente):
    """Come si apre questa giornata: l'HTML e il nome dell'apertura scelta.

    [AGGIUNTO 2026-08-13 — task #214, primo pezzo del compositore che entra
    davvero nel documento venduto.]

    Prima ogni giornata si apriva allo stesso identico modo: una fotografia
    centrata sotto il titolo. Con un viaggio di cinque giorni erano cinque
    pagine gemelle, ed e' la richiesta di Lorenzo: «non devono essere una
    uguale all'altra».

    Qui cambia UN pezzo di HTML, nello stesso punto in cui prima ce n'era uno
    solo: le tre aperture si impilano tutte allo stesso modo, quindi la
    struttura della giornata — titolo, cartina, programma, legenda — resta
    intatta e con lei i controlli di impaginazione che la difendono. Gli
    impianti a colonne arrivano dopo, quando questa parte e' collaudata in
    produzione. Questa settimana ha gia' mostrato due volte cosa succede a
    cambiare tutto insieme: una singola immagine in piu' fa sfondare una
    pagina.

    Torna anche il nome dell'apertura perche' chi chiama deve poterlo passare
    alla giornata dopo: senza, «mai due volte di fila» non e' verificabile.
    """
    proprie = [(scatto, nome) for _poi, scatto, nome
               in _foto_vere_della_giornata(blocks, photos)]
    disponibili, _provenienza = compositore.foto_della_giornata(
        proprie, riserva_viaggio, None, giorno_numero)
    apertura = compositore.scegli_apertura(
        chiave, giorno_numero, len(disponibili), apertura_precedente)
    if not apertura or not disponibili:
        return "", ""

    # [ESTESO 2026-08-13 — task #215, e nasce da una bocciatura.]
    # La prima versione portava dentro SOLO l'apertura e lasciava fuori tutto
    # cio' che nei provini faceva il lavoro. Lorenzo, confrontando il
    # documento vero col prototipo: «ci sono meno foto e anche la grafica e'
    # diversa [...] PIU' DINAMISMO E FOTO».
    #
    # Aveva ragione: un'apertura che cambia e tutto il resto identico non e'
    # una pagina diversa, e' la stessa pagina con un cappello diverso. Qui
    # entrano anche gli ORNAMENTI — bollo, nastro, capolettera, foto tonda —
    # scelti dal compositore con i suoi vincoli, e le fotografie in piu'.
    ricetta = compositore.componi(
        chiave, giorno_numero, len(disponibili),
        {"impianto": {"nome": apertura_precedente or ""}, "ornamenti": []})
    ornamenti = ricetta["ornamenti"]

    def _figura(scatto, larghezza_html, rapporto, sfumata=False):
        png = scatto.get("png") if isinstance(scatto, dict) else None
        credito = str((scatto or {}).get("credito") or "").strip()
        if not png or not credito:
            return ""
        ritagliata = foto.ritaglia_panoramica(png, rapporto) or png
        if sfumata:
            ritagliata = foto.sfuma_in_basso(ritagliata) or ritagliata
        try:
            b64 = base64.b64encode(ritagliata).decode("ascii")
        except (TypeError, ValueError):
            return ""
        tipo = foto.mime_immagine(ritagliata)
        return (f"<img src='data:{tipo};base64,{b64}' alt='' {larghezza_html}>"
                f"<div class='didascalia'>Foto: {_esc(credito)}</div>")

    def _tonda(scatto):
        png = scatto.get("png") if isinstance(scatto, dict) else None
        credito = str((scatto or {}).get("credito") or "").strip()
        if not png or not credito:
            return ""
        # Il ritaglio tondo si fa sui PIXEL: in CSS esce mezzo tondo e mezzo
        # quadrato, misurato sul motore di stampa.
        ritagliata = foto.ritaglia_tondo(png, 380)
        if not ritagliata:
            return ""
        try:
            b64 = base64.b64encode(ritagliata).decode("ascii")
        except (TypeError, ValueError):
            return ""
        return (f"<div class='day-tonda'><img src='data:image/png;base64,{b64}' "
                f"alt=''><div class='didascalia'>Foto: {_esc(credito)}</div></div>")

    pezzi = []

    # --- il segno che apre: bollo tondo col numero, oppure capolettera ----
    # Sono alternativi per regola (due numeroni si contendono l'occhio) e il
    # compositore non li mette mai insieme: qui si stampa quello scelto.
    if "bollo" in ornamenti:
        pezzi.append(f"<div class='day-bollo'><div class='n'>{_esc(giorno_numero)}</div>"
                     "<div class='e'>giorno</div></div>")
    elif "capolettera" in ornamenti:
        try:
            numero = f"{int(giorno_numero):02d}"
        except (TypeError, ValueError):
            numero = str(giorno_numero or "")
        pezzi.append(f"<div class='day-capolettera'>{numero}</div>")

    # --- l'apertura fotografica -------------------------------------------
    scelta = apertura
    if apertura == "mosaico":
        celle = []
        for scatto, _nome in disponibili[:3]:
            figura = _figura(scatto, "style='width:100%; display:block;'", 1.35)
            if figura:
                celle.append(f"<td style='width:33%'>{figura}</td>")
        if len(celle) >= 3:
            pezzi.append("<table class='day-striscia'><tr>" + "".join(celle)
                         + "</tr></table>")
        else:
            scelta = "banda"

    # --- le due aperture a COLONNE (task #219) ----------------------------
    # Dividono in colonne l'apertura, non la giornata: sotto, titolo, cartina
    # e programma restano impilati come sempre. Affiancare, con questo motore
    # di stampa, si fa solo con le tabelle — `float` e `flex` li ignora in
    # silenzio, e il risultato sarebbe la colonna stretta SOTTO quella larga.
    if scelta == "eroe-laterale":
        grande = _figura(disponibili[0][0],
                         "style='width:100%; display:block;'", 1.25)
        piccola = (_figura(disponibili[1][0],
                           "style='width:100%; display:block;'", 1.0)
                   if len(disponibili) >= 2 else "")
        if grande and piccola:
            pezzi.append(
                "<table class='day-eroe'><tr>"
                f"<td class='day-eroe-grande'>{grande}</td>"
                f"<td class='day-eroe-lato'>{piccola}</td>"
                "</tr></table>")
        else:
            scelta = "banda"

    if scelta == "numero-gigante":
        figura = _figura(disponibili[0][0],
                         "style='width:100%; display:block;'", 1.7)
        if figura:
            try:
                cifra = f"{int(giorno_numero):02d}"
            except (TypeError, ValueError):
                cifra = str(giorno_numero or "")
            pezzi.append(
                "<table class='day-numerone'><tr>"
                f"<td class='day-numerone-cifra'>{_esc(cifra)}"
                "<div class='day-numerone-e'>giorno</div></td>"
                f"<td class='day-numerone-foto'>{figura}</td>"
                "</tr></table>")
        else:
            scelta = "banda"

    if scelta == "banda":
        figura = _figura(disponibili[0][0], "style='width:100%; display:block;'", 3.1)
        if figura:
            pezzi.append(f"<div class='day-banda'>{figura}</div>")
        else:
            scelta = "foto-sola"

    if scelta == "foto-sola":
        # [CORRETTO 2026-08-13 — task #219, segnalato DUE volte da Lorenzo:
        # «filla gli spazi bianchi» e poi «a pagina 5 c'e' sempre una sola
        # foto centrale che non mi piace».]
        #
        # La fotografia era centrata dentro la colonna con margini bianchi ai
        # lati: non un'apertura, un francobollo in mezzo alla pagina.
        #
        # La riparazione NON e' togliere questa apertura — provato, e con due
        # sole aperture piu' la regola «mai due volte di fila» la sequenza
        # diventa un'alternanza fissa: due viaggi diversi finiscono con la
        # stessa identica sequenza di pagine. L'ha preso una prova.
        #
        # La riparazione e' toglierle i margini: la stessa fotografia,
        # ritagliata piu' larga, che occupa la colonna per intero. Il ritaglio
        # governa le proporzioni, quindi il foglio di stile puo' dire solo
        # `width` e non serve nessun `max-height` — cioe' non si ricrea la
        # coppia che l'11 agosto aveva schiacciato le immagini.
        figura = _figura(disponibili[0][0],
                         "style='width:100%; display:block;'", 2.9)
        if figura:
            pezzi.append(f"<div class='day-larga'>{figura}</div>")

    # --- il nastro coi numeri della giornata ------------------------------
    if "nastro" in ornamenti and blocks:
        quante = len(blocks)
        pezzi.append(f"<span class='day-nastro'>{quante} "
                     f"{'tappa' if quante == 1 else 'tappe'}</span>")

    # --- una fotografia in piu', tonda ------------------------------------
    # E' l'ornamento che alza di piu' la densita' di immagini, ed e' anche il
    # motivo per cui il compositore lo esclude quando le fotografie sono meno
    # di due: se se la prendesse lui, l'apertura resterebbe senza.
    if "tonda" in ornamenti and len(disponibili) >= 2:
        pezzi.append(_tonda(disponibili[1][0]))

    return "".join(x for x in pezzi if x), scelta


def _render_day_photo(blocks, photos: dict | None) -> str:
    """La fotografia di apertura della giornata, oppure "".

    Sceglie la PRIMA tappa della giornata che ha una fotografia vera. Non la
    piu' famosa e non la piu' bella: la prima, perche' e' quella che il
    cliente vedra' per prima quel giorno, e una foto in cima alla pagina che
    mostra la seconda tappa e' una figura che racconta un'altra storia.

    Solo fotografie vere. La grafica disegnata in casa
    (`foto.copertina_interna`) resta fuori da qui di proposito: nel documento
    principale un'immagine vale se mostra un luogo che il cliente
    riconoscera', altrimenti e' un rettangolo colorato che occupa lo spazio
    del programma. Nelle guide della singola attrazione, invece, ha senso e
    infatti c'e'.

    [CAMBIATO 2026-08-03, stesso giorno] Il filtro sul "vera" sta QUI dentro e
    non piu' a monte in chi chiama. Prima il servizio passava al renderer solo
    le fotografie vere (`foto.solo_reali()`) e il renderer si fidava: bastava
    che un domani qualcuno passasse l'insieme completo — cosa che serve, ed e'
    successa subito, perche' i capitoli delle guide dentro il documento le
    vogliono TUTTE — perche' la grafica disegnata in casa finisse in cima a una
    giornata spacciandosi per una fotografia del posto. Un controllo che
    dipende dalla buona memoria di chi chiama non e' un controllo. Ora il canale
    e' uno solo, porta tutte le immagini, e chi le stampa decide: qui passano
    solo quelle con `reale` vero.

    Il credito e' obbligatorio come nelle guide: senza il nome di chi ha
    scattato la foto, la foto non si stampa.
    """
    if not isinstance(photos, dict) or not photos:
        return ""
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        poi_id = block.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        scatto = photos.get(poi_id)
        if not isinstance(scatto, dict):
            continue
        if not scatto.get("reale"):
            continue
        png, credito = scatto.get("png"), scatto.get("credito")
        if not png or not isinstance(credito, str) or not credito.strip():
            continue
        try:
            b64 = base64.b64encode(png).decode("ascii")
        except (TypeError, ValueError):
            continue
        nome = str(block.get("location") or "").strip()
        return (
            "<div class='day-foto'>"
            f"<img src='data:{foto.mime_immagine(png)};base64,{b64}' alt='{_esc(nome)}'>"
            f"<div class='didascalia'>{_esc(credito)}</div></div>"
        )
    return ""


def _render_criterio() -> str:
    """Le tre righe che dichiarano COME e' stata costruita la giornata.

    [AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «dare un criterio
    alla programmazione delle cose da vedere (minimizzare gli spostamenti,
    tenendo conto degli orari di apertura delle strutture e le varie pause
    durante la giornata)»]

    Tre righe, una volta sola in tutto il documento, sotto l'occhiello del
    programma. Non e' un capitolo: la richiesta della stessa tornata era
    «meno testo piu' immagini», e un criterio spiegato in mezza pagina e' un
    criterio che nessuno legge — quindi vale zero, esattamente come non
    averlo.

    Il testo NON e' scritto qui: arriva da `scheduling_criteria.CRITERIO`, la
    stessa costante che il prompt del modello ricopia. Se un giorno il
    documento e il prompt divergessero, il cliente leggerebbe una regola e
    riceverebbe una giornata costruita con un'altra. Un test confronta le due
    cose e fallisce se si separano.
    """
    righe = [
        f"<div class='criterio-riga'><span class='criterio-nome'>{_esc(nome)}</span> — "
        f"{_esc(spiegazione)}</div>"
        for nome, spiegazione in scheduling_criteria.CRITERIO
    ]
    return "<div class='criterio'>" + "".join(righe) + "</div>"


def _render_blocco_chiuso(segnalazione: dict | None) -> str:
    """La riga "risulta chiuso a quest'ora", accanto alla tappa interessata.

    [AGGIUNTO 2026-08-03 — task #180]

    Qui il documento fa una cosa che gli costa: ammette che una riga del
    programma che ha appena stampato non torna. La tentazione opposta —
    spostare in silenzio la tappa a un orario aperto — e' peggiore di quanto
    sembri: sposteremmo un blocco senza sapere perche' era li' (una
    prenotazione? il treno? il pranzo con qualcuno?), rompendo gli incastri
    che non vediamo e senza dirlo a nessuno. Meglio una riga scomoda letta a
    casa che una porta chiusa trovata sul posto.
    """
    if not segnalazione:
        return ""
    orario = segnalazione.get("orario") or ""
    finestre = segnalazione.get("finestre") or ""
    testo = f"Attenzione: alle {orario} questo luogo risulta chiuso"
    if finestre:
        testo += f". Orario dichiarato per quel giorno: {finestre}"
    testo += ". Conferma prima di andarci, oppure spostala dentro l'orario di apertura."
    return f"<div class='block-chiuso'>{_esc(testo)}</div>"


# [RIMOSSO 2026-08-03 — task #179, richiesta di Lorenzo: «la parte del
# "come arrivare" appare ridondante, uniscila al programma del giorno»]
#
# Qui viveva `_render_directions()`, che stampava il riquadro "Come arrivare —
# giorno N": gli stessi spostamenti gia' presenti nel programma, ripetuti di
# seguito in un secondo elenco. Ora esiste una sola riga per spostamento, ed
# e' `_render_leg_inline()`, attaccata alla tappa a cui porta.
#
# La funzione e' stata TOLTA e non solo scollegata, di proposito: lasciarla
# definita e mai chiamata l'avrebbe fatta sembrare ancora viva al prossimo che
# legge questo file, e il modo classico per far tornare un doppione e'
# ritrovare la funzione che lo produceva e ricollegarla "perche' c'era gia'".
# Il divieto e' verificato in tests/test_pdf_renderer.py
# (TestComeArrivareNonTornaDueVolte).


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
        # [CORRETTO 2026-08-02] Il plurale con la barra ("voce/i") è il modo
        # pigro di non deciderlo, e in un documento a pagamento si legge come
        # un modulo prestampato. Il numero ce l'abbiamo già in mano.
        unknown_n = cost_summary["unknown_count"]
        try:
            singolare = int(unknown_n) == 1
        except (TypeError, ValueError):
            singolare = False
        etichetta = (
            "Una voce è senza" if singolare
            else f"{_esc(unknown_n)} voci sono senza"
        )
        parts.append(
            f"<div class='cost-detail' style='margin-top:6px'>"
            f"{etichetta} un prezzo pubblicato al momento "
            f"della generazione: {'è elencata' if singolare else 'sono elencate'} qui sopra "
            f"ma NON {'inclusa' if singolare else 'incluse'} nel totale, per non "
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


def _render_predeparture(predeparture: dict | None) -> str:
    """
    [AGGIUNTO 2026-08-01 — sotto la voce di Lorenzo "stupiscimi"]

    Due blocchi, in quest'ordine: la scheda del paese (numero di emergenza,
    valuta, prese, acqua, mancia) e la lista di controllo della sera prima.

    Il numero di emergenza è l'unico dato del documento stampato in rosso e
    più grande del resto: non è decorazione, è la sola riga che qualcuno
    cercherà con le mani che tremano. Tutto quello che c'è qui arriva da
    `src/predeparture.py`, che a sua volta legge la tabella scritta a mano di
    `src/local_info.py`: nessuna riga di questa sezione è mai passata per un
    modello linguistico, ed è deliberato.

    Ritorna "" quando non c'è né scheda né lista: il paese non in tabella
    produce l'omissione, mai un numero plausibile.
    """
    data = predeparture if isinstance(predeparture, dict) else {}
    country = data.get("country") if isinstance(data.get("country"), dict) else None
    checklist = [
        c for c in (data.get("checklist") or [])
        if isinstance(c, dict) and c.get("title")
    ]
    if not country and not checklist:
        return ""

    # [SPOSTATA 2026-08-15 — task #220] La scheda del paese stava qui dentro,
    # in coda a un capitolo che si legge LA SERA PRIMA. Ma il numero di
    # emergenza, la valuta e le prese si cercano DURANTE il viaggio, e
    # cercarli dentro «Prima di partire» vuol dire non trovarli: nessuno apre
    # la lista della sera prima mentre e' in giro con un problema.
    #
    # Adesso hanno un capitolo loro (`_render_numeri_utili`), in fondo al
    # documento, dove si arriva aprendo il fascicolo dall'ultima pagina — che
    # e' il gesto naturale quando si cerca un numero.
    parts: list[str] = []
    for item in checklist:
        detail = item.get("detail")
        parts.append(
            "<table class='check-row'><tr>"
            "<td class='check-mark'><span class='check-box'></span></td>"
            f"<td class='check-text'><strong>{_esc(item['title'])}</strong>"
            + (f"<div class='check-detail'>{_esc(detail)}</div>" if detail else "")
            + "</td></tr></table>"
        )
    return "".join(parts)


def _camminate_in_due_colonne(voci) -> str:
    """Le giornate a due a due, invece che una per riga.

    [MISURATO, 2026-08-15.] In colonna sola l'elenco era alto quanto mezza
    pagina: non ci stava in fondo al capitolo, scendeva tutto intero sulla
    pagina dopo (viaggia dentro un guscio, quindi o entra o scende) e quella
    pagina restava piena all'undici per cento. A due a due ci sta, e un
    elenco di numeri corti su due colonne si legge anche meglio.
    """
    righe = []
    for i in range(0, len(voci), 2):
        coppia = voci[i:i + 2]
        celle = "".join(f"<td class='k'>{k}</td><td class='v'>{v}</td>"
                        for k, v in coppia)
        if len(coppia) == 1:
            # Senza le celle vuote l'ultima voce si allargherebbe a tutta la
            # riga e sembrerebbe piu' importante delle altre.
            celle += "<td></td><td></td>"
        righe.append(f"<tr>{celle}</tr>")
    return "<table class='pre-facts'>" + "".join(righe) + "</table>"


def _render_numeri_utili(predeparture: dict | None, hotels=None,
                        directions_by_day: dict | None = None,
                        days=None) -> str:
    """Il capitolo che si cerca quando qualcosa va storto (task #220).

    [AGGIUNTO 2026-08-15. Lorenzo: «manca ancora qualcosa».]

    ## Perche' esiste un capitolo suo

    Il numero di emergenza, la valuta e le prese erano gia' nel documento, in
    coda a «Prima di partire». Ma quello e' il capitolo che si legge la sera
    prima di partire, e queste righe servono DURANTE il viaggio: nessuno apre
    la lista della valigia mentre e' in giro con un problema. Un dato messo
    dove non lo si cerca e' un dato che non c'e'.

    In fondo al documento, per giunta, si arriva sfogliando dall'ultima
    pagina — che e' il gesto naturale quando si cerca un numero.

    ## Da dove arriva ogni riga, e cosa NON c'e' dentro

    Tutto qui e' deterministico: **nessuna riga di questo capitolo e' mai
    passata per un modello linguistico**, ed e' deliberato. Il numero di
    emergenza e' il dato in cui un errore fa il danno piu' grave e piu'
    veloce, quindi viene stampato tale e quale dalla tabella scritta a mano
    di `src/local_info.py`; se il paese non e' in tabella, la riga non esce —
    mai un numero plausibile.

    I chilometri a piedi sono quelli gia' misurati sui tragitti veri del
    programma, non una stima.

    ## Cosa manca di proposito: i biglietti dei mezzi

    Sarebbe il pezzo piu' utile di un capitolo intitolato «come muoversi», e
    non c'e'. I prezzi dei trasporti cambiano, non abbiamo una fonte che si
    aggiorni, e un modello che li ricorda a memoria li sbaglia. Un cliente
    che arriva al tornello con il prezzo sbagliato e' peggio di un cliente
    che non ha letto niente: la seconda volta non si fida piu' nemmeno delle
    parti giuste. Quando ci sara' una fonte vera, entrera' qui.
    """
    dati = predeparture if isinstance(predeparture, dict) else {}
    paese = dati.get("country") if isinstance(dati.get("country"), dict) else None

    righe_paese = []
    if paese:
        for classe, etichetta, valore in (
            ("emergency", "Numero di emergenza", paese.get("emergency")),
            ("", "Valuta", paese.get("currency")),
            ("", "Prese elettriche", paese.get("plug")),
            ("", "Acqua del rubinetto", paese.get("tap_water")),
            ("", "Mancia", paese.get("tipping")),
        ):
            if valore:
                righe_paese.append((classe, etichetta, valore))

    # --- dove si dorme, in chiaro -----------------------------------------
    # E' la riga che si mostra a un tassista, o che si legge al telefono a
    # qualcuno che ti viene a prendere. Vale la pena averla senza doverla
    # cercare in mezzo al capitolo dell'alloggio.
    base = next((h for h in (hotels or []) if isinstance(h, dict)), None)
    indirizzo = str((base or {}).get("address") or "").strip()
    nome_base = str((base or {}).get("name") or "").strip()

    # --- quanto si cammina davvero ----------------------------------------
    # E' la meta' onesta di «come muoversi»: non i biglietti, che non
    # sappiamo, ma i metri, che abbiamo misurato tragitto per tragitto.
    camminate = []
    for giorno in (days or []):
        if not isinstance(giorno, dict):
            continue
        numero = giorno.get("day")
        tratte = ((directions_by_day or {}).get(numero) or {}).get("legs") or []
        sintesi = summarize_day_travel(tratte)
        if not sintesi or not sintesi.get("walking_text"):
            continue
        minuti = sintesi.get("walking_minutes")
        camminate.append((
            f"Giorno {_esc(numero)}",
            f"{sintesi['walking_text']}"
            + (f" (~{minuti} min)" if minuti else ""),
        ))

    if not righe_paese and not indirizzo and not camminate:
        return ""

    pezzi: list[str] = []
    if righe_paese:
        # [COMPATTATA 2026-08-15, MISURANDO.] Una riga per voce faceva un
        # capitolo alto mezza pagina che non stava mai in fondo a quella
        # prima: scendeva intero e lasciava la pagina piena al nove per cento.
        # A due a due ci sta, e le voci sono corte — si leggono anche meglio.
        #
        # Il numero di emergenza resta da solo sulla sua riga, sempre: e' la
        # riga che qualcuno cerchera' con le mani che tremano, e non deve
        # dividere l'occhio con la valuta.
        emergenza = [r for r in righe_paese if r[0] == "emergency"]
        altre = [r for r in righe_paese if r[0] != "emergency"]
        righe = []
        if paese.get("country"):
            altre = [("", "Paese", paese["country"])] + altre
        for classe, etichetta, valore in emergenza:
            righe.append(f"<tr class='{classe}'><td class='k'>{_esc(etichetta)}</td>"
                         f"<td class='v' colspan='3'>{_esc(valore)}</td></tr>")
        for i in range(0, len(altre), 2):
            coppia = altre[i:i + 2]
            celle = "".join(f"<td class='k'>{_esc(e)}</td>"
                            f"<td class='v'>{_esc(v)}</td>"
                            for _c, e, v in coppia)
            if len(coppia) == 1:
                celle += "<td></td><td></td>"
            righe.append(f"<tr>{celle}</tr>")
        pezzi.append(_keep_together(
            "<table class='pre-facts'>" + "".join(righe) + "</table>"))

    if indirizzo:
        # Su una riga sola, dentro lo stesso guscio del resto: e' la riga che
        # si mostra a un tassista, non un capitolo a se'.
        pezzi.append(_keep_together(
            f"<div class='summary-box'><strong>Dove dormi:</strong> "
            f"{_esc(nome_base)} — {_esc(indirizzo)}</div>"))

    if camminate:
        # Dentro il guscio: senza, l'elenco si spezza fra due pagine e
        # l'ultima giornata resta da sola in cima al foglio dopo, con sotto
        # una pagina bianca. Misurato — la pagina si fermava al 6%.
        pezzi.append(_keep_together(
            "<div class='mid-intro'>Quanto si cammina, giorno per giorno — "
            "misurato sui tragitti veri del tuo programma, non stimato. "
            "E' il numero che decide le scarpe.</div>"
            + _camminate_in_due_colonne(camminate)
        ))
    return "".join(pezzi)


def _render_checklist_sheet_box(sheet: dict | None) -> str:
    """Il riquadro che collega la lista della valigia al foglio da spuntare.

    [NUOVO 2026-08-02 — task #173, richiesta di Lorenzo: "dopo l'elenco vorrei
    che creassi un collegamento per un foglio di calcolo google come quello
    che ti ho allegato"]

    Il riquadro dice tre cose e nient'altro: che il foglio esiste, dove
    trovarlo, e come aprirlo in Fogli Google. Deliberatamente NON ripete le
    voci: sono le stesse dell'elenco qui sopra, e una lista stampata due volte
    nello stesso capitolo e' il modo piu' rapido di far sembrare gonfio un
    documento.

    Due forme, decise da chi passa i dati e non da qui:
      - con `url`, il collegamento e' un indirizzo su cui si clicca;
      - senza, il collegamento e' il NOME dell'allegato nella stessa mail,
        scritto per esteso perche' e' cosi' che lo si ritrova.
    Mai un indirizzo inventato: e' la stessa regola dei menu' dei ristoranti.
    """
    if not isinstance(sheet, dict):
        return ""
    filename = str(sheet.get("filename") or "").strip()
    url = str(sheet.get("url") or "").strip()
    if not filename and not url:
        return ""
    try:
        righe = int(sheet.get("rows") or 0)
    except (TypeError, ValueError):
        righe = 0

    corpo = (
        "Questa lista esiste anche come foglio di calcolo, con una casella da "
        "spuntare accanto a ogni voce"
    )
    if righe:
        corpo = (
            f"Questa lista esiste anche come foglio di calcolo: {righe} voci, "
            "ognuna con la sua casella da spuntare"
        )
    corpo += (
        ", ordinate per quando vanno fatte e non per categoria — prima quello "
        "che, se manca, non si rimedia il giorno prima. Serve per spuntarla in "
        "due dal telefono mentre si prepara la valigia, che su carta non si "
        "puo\u2019 fare."
    )

    if url:
        collegamento = (
            "<div class='vad-sheet-how'>Aprilo qui: "
            f"<a href='{_esc(url)}'>{_esc(sheet.get('label') or 'Foglio della valigia')}</a>"
            " \u00b7 da Fogli Google fai \u00abFile \u203a Crea una copia\u00bb per averne "
            "una tua, modificabile e condivisibile.</div>"
        )
    else:
        collegamento = (
            "<div class='vad-sheet-how'>Lo trovi allegato alla stessa mail di "
            f"questo documento: <span class='vad-sheet-file'>{_esc(filename)}</span>"
            " \u00b7 per averlo su Fogli Google caricalo su Drive e apri "
            "\u00abApri con \u203a Fogli Google\u00bb; da l\u00ec si condivide con chi parte "
            "con te. Si apre anche con Excel, Numbers e LibreOffice.</div>"
        )

    return (
        "<table class='vad-sheet'><tr><td>"
        "<div class='vad-sheet-title'>Il foglio da spuntare</div>"
        f"<div class='vad-sheet-body'>{corpo}</div>"
        f"{collegamento}"
        "</td></tr></table>"
    )


def _render_vademecum(vademecum: dict | None, checklist_sheet: dict | None = None) -> str:
    """
    [AGGIUNTO 2026-08-02 — task #167, richiesta di Lorenzo: "aggiungi una parte
    di «vademecum di viaggio» e di suggerimenti di cosa portare in valigia su
    come strutturarla ... + per eventuali aerei low cost ... quale tipologia di
    bagaglio conviene prendere (stiva o cabina) e il costo di quest'ultimo"]

    Quattro blocchi, in quest'ordine, che non è estetico ma causale: il clima
    del mese DECIDE i vestiti, i vestiti DECIDONO il volume, il volume DECIDE
    se cabina o stiva. Chi legge dall'alto in basso non incontra mai una
    conclusione prima della ragione che la produce.

    Tutto arriva da `src/vademecum.py`: nessuna riga passa per un modello
    linguistico e nessuna riga costa una chiamata di rete. Ritorna "" se non
    c'è nemmeno un blocco — l'omissione, mai un riempitivo plausibile.
    """
    data = vademecum if isinstance(vademecum, dict) else {}
    climate = data.get("climate") if isinstance(data.get("climate"), dict) else None
    baggage = data.get("baggage") if isinstance(data.get("baggage"), dict) else None
    packing = [g for g in (data.get("packing") or []) if isinstance(g, dict) and g.get("items")]
    suitcase = [s for s in (data.get("suitcase") or []) if isinstance(s, dict) and s.get("title")]
    if not climate and not baggage and not packing and not suitcase:
        return ""

    parts: list[str] = []

    if climate:
        month = climate.get("month_label") or ""
        zone = climate.get("zone_label") or ""
        head = f"Il clima tipico di {_esc(month)}" if month else "Il clima tipico"
        if zone:
            head += f" <span class='vad-zone'>&middot; clima {_esc(zone)}</span>"
        cells: list[str] = []
        t_max, t_min = climate.get("temp_max"), climate.get("temp_min")
        if t_max is not None:
            cells.append(
                f"<td><div class='vad-num vad-num-hot'>{_esc(t_max)}&deg;</div>"
                "<div class='vad-num-label'>Massima di giorno</div></td>"
            )
        if t_min is not None:
            cells.append(
                f"<td><div class='vad-num vad-num-cold'>{_esc(t_min)}&deg;</div>"
                "<div class='vad-num-label'>Minima di notte</div></td>"
            )
        third = []
        if climate.get("rain"):
            third.append(
                f"<div class='vad-num-small'>Pioggia {_esc(climate['rain'])}</div>"
            )
        # [TOLTO 2026-08-11 — richiesta di Lorenzo: «12h e 45 di luce e'
        # un'informazione inutile e brutta da vedere, rimuovila».]
        #
        # Aveva ragione, e vale la pena scrivere perche': quel numero e' VERO
        # ma non serve a decidere niente. Nessuno cambia un programma perche'
        # la giornata dura dodici ore e quarantacinque invece di tredici. Cio'
        # che serve davvero — a che ora fa buio, quando e' l'ora d'oro per le
        # fotografie — e' gia' scritto altrove e in una forma che si usa.
        #
        # La durata resta calcolata in `src/sun_times.py`, che serve anche
        # all'ora d'oro: qui smette solo di essere stampata. Un documento non
        # migliora aggiungendo dati veri, migliora togliendo quelli che non
        # rispondono a nessuna domanda.
        if third:
            cells.append(
                "<td>" + "".join(third)
                + "<div class='vad-num-label'>Cosa aspettarsi</div></td>"
            )
        body = []
        if cells:
            body.append("<table class='vad-nums'><tr>" + "".join(cells) + "</tr></table>")
        if climate.get("note"):
            body.append(f"<div class='vad-note'>{_esc(climate['note'])}</div>")
        link = climate.get("forecast_link")
        if isinstance(link, dict) and link.get("url"):
            body.append(
                "<div class='vad-forecast'>"
                f"<a href='{_esc(link['url'])}'>{_esc(link.get('label') or 'Previsioni')}</a>"
                "<span class='vad-forecast-when'>Aprilo tre giorni prima di partire: "
                "prima di allora nessuna previsione al mondo è ancora una previsione.</span>"
                "</div>"
            )
        if body:
            parts.append(
                "<table class='vad-climate'>"
                f"<tr><td class='vad-climate-head'>{head}</td></tr>"
                f"<tr><td class='vad-climate-body'>{''.join(body)}</td></tr>"
                "</table>"
            )

    if packing:
        parts.append("<div class='vad-sub'>Cosa mettere in valigia</div>")
        for group in packing:
            items = [str(i) for i in group.get("items") or [] if str(i).strip()]
            if not items:
                continue
            rows = []
            # Due voci per riga: la lista occupa metà delle pagine e resta
            # leggibile, perché ogni voce è corta per costruzione.
            for i in range(0, len(items), 2):
                pair = items[i:i + 2]
                cell_a = (
                    f"<td><span class='vad-tick'>&#10003;</span> {_esc(pair[0])}</td>"
                )
                cell_b = (
                    f"<td><span class='vad-tick'>&#10003;</span> {_esc(pair[1])}</td>"
                    if len(pair) > 1 else "<td></td>"
                )
                rows.append(f"<tr>{cell_a}{cell_b}</tr>")
            parts.append(
                "<div class='vad-group'>"
                f"<div class='vad-group-title'>{_esc(group.get('group') or '')}</div>"
                f"<table class='vad-items'>{''.join(rows)}</table>"
                "</div>"
            )
        parts.append(_render_checklist_sheet_box(checklist_sheet))

    if suitcase:
        parts.append("<div class='vad-sub'>Come si riempie, nell'ordine</div>")
        for index, step in enumerate(suitcase, start=1):
            detail = step.get("detail")
            parts.append(
                "<table class='vad-step'><tr>"
                f"<td class='vad-step-n'><span class='vad-step-num'>{index}</span></td>"
                f"<td><div class='vad-step-title'>{_esc(step['title'])}</div>"
                + (f"<div class='vad-step-detail'>{_esc(detail)}</div>" if detail else "")
                + "</td></tr></table>"
            )

    if baggage:
        choice = str(baggage.get("choice") or "")
        parts.append("<div class='vad-sub'>Cabina o stiva, e quanto costa</div>")
        badge_class = "vad-badge vad-badge-hold" if choice.startswith("stiva") else "vad-badge"
        # La parola sola sul distintivo, il resto come sottotitolo: "cabina, ma
        # stretta" spezzato in "CABINA" + "ma stretta" si legge da lontano,
        # tutto su una riga no.
        head_word, _, tail_word = choice.partition(",")
        badge = f"<span class='{badge_class}'>{_esc(head_word.strip() or 'cabina')}"
        if tail_word.strip():
            badge += f"<span class='vad-badge-sub'>{_esc(tail_word.strip())}</span>"
        badge += "</span>"
        right = []
        if baggage.get("reason"):
            right.append(f"<div class='vad-reason'>{_esc(baggage['reason'])}</div>")
        if baggage.get("total"):
            right.append(f"<div class='vad-total'>{_esc(baggage['total'])}</div>")
        parts.append(
            "<table class='vad-choice'><tr>"
            f"<td class='vad-choice-badge'>{badge}</td>"
            f"<td>{''.join(right)}</td>"
            "</tr></table>"
        )
        carriers = [c for c in (baggage.get("carriers") or []) if isinstance(c, dict)]
        if carriers:
            rows = []
            for carrier in carriers:
                cabin = carrier.get("cabin") or []
                hold = carrier.get("hold") or []
                cabin_txt = f"{cabin[0]}–{cabin[1]} &euro;" if len(cabin) == 2 else "&mdash;"
                hold_txt = f"{hold[0]}–{hold[1]} &euro;" if len(hold) == 2 else "&mdash;"
                if carrier.get("hold_kg"):
                    hold_txt += f"<div class='cost-detail'>{_esc(carrier['hold_kg'])}</div>"
                rows.append(
                    f"<tr><td class='vad-carrier'>{_esc(carrier.get('name') or '')}</td>"
                    f"<td>{_esc(carrier.get('personal') or '')}</td>"
                    f"<td class='num'>{cabin_txt}</td>"
                    f"<td class='num'>{hold_txt}</td></tr>"
                )
            parts.append(
                "<table class='vad-fares'><tr>"
                "<th>Compagnia</th><th>Incluso nel biglietto</th>"
                "<th class='num'>Trolley in cabina</th><th class='num'>Stiva</th>"
                f"</tr>{''.join(rows)}</table>"
            )
        if baggage.get("caveat"):
            parts.append(f"<div class='vad-caveat'>{_esc(baggage['caveat'])}</div>")
        notes = [str(n) for n in (baggage.get("notes") or []) if str(n).strip()]
        if notes:
            parts.append(
                "<ul class='vad-notes'>"
                + "".join(f"<li>{_esc(n)}</li>" for n in notes)
                + "</ul>"
            )

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
    # [ESTESO 2026-08-01 — "togliergli più lavoro possibile"] `tickets_link`
    # (sito ufficiale di ciò che si visita) e `phone_link` (schema `tel:`: un
    # tap per prenotare un tavolo) si aggiungono ai due storici. L'ordine è
    # quello dell'uso reale: prima decido, poi mi informo, poi prenoto.
    for key in ("menu_link", "tickets_link", "info_link"):
        link = card.get(key)
        if isinstance(link, dict) and link.get("url"):
            links.append(f"<a href='{_esc(link['url'])}'>{_esc(link.get('label') or 'Apri')}</a>")
    phone_link = card.get("phone_link")
    has_phone_button = isinstance(phone_link, dict) and bool(phone_link.get("url"))
    if has_phone_button:
        label = phone_link.get("label") or card.get("phone") or "Chiama"
        links.append(f"<a href='{_esc(phone_link['url'])}'>&#9742; {_esc(label)}</a>")
    # Il numero resta come TESTO solo se non è già diventato un pulsante qui
    # sopra: stamparlo due volte di fila era rumore, non ridondanza utile.
    meta_bits = [card.get("address")]
    if not has_phone_button:
        meta_bits.append(card.get("phone"))
    meta = " · ".join(x for x in meta_bits if x)
    if not links and not meta:
        return ""
    parts = []
    if links:
        parts.append(f"<div class='place-links'>{''.join(links)}</div>")
    if meta:
        parts.append(f"<div class='place-meta'>{_esc(meta)}</div>")
    return "".join(parts)


def _sonde_cartina(ancore_di_ritorno: dict, day_number) -> str:
    """I segnaposti di ritorno che appartengono alla cartina di un giorno.

    [AGGIUNTO 2026-08-05 — task #191] Ne esce UNO solo per cartina: tutte le
    tappe di quel giorno tornano nello stesso punto, e infatti condividono lo
    stesso nome (vedi `fascicolo.ancora_cartina`).

    La precisione del ritorno, per la cartina, si ferma alla cartina e non
    arriva al singolo pallino. Il motivo è che i pallini sono elementi
    posizionati in modo assoluto sopra l'immagine: un segnaposto dentro un
    pallino avrebbe la stessa area del pallino e gli ruberebbe il clic. È una
    pagina di distanza, non un capitolo — il cliente si ritrova dove stava
    guardando.
    """
    # `dict.fromkeys` invece di `set`: toglie i doppioni ma tiene l'ordine,
    # così due stampe dello stesso documento escono identiche byte per byte.
    nomi = dict.fromkeys(
        nome
        for chiave, elenco in ancore_di_ritorno.items()
        if chiave and chiave[0] == "cartina" and chiave[1] == day_number
        for nome in elenco
    )
    # Ognuno dentro il suo `<div>`, e non è cosmesi.
    #
    # [MISURATO 2026-08-05] Il segnaposto della cartina finisce accanto a
    # quello del giorno: due `<span>` in fila, larghi due pixel l'uno.
    # Attaccati così, wkhtmltopdf assegna l'annotazione SOLO AL PRIMO — sul
    # campione vero restavano morti `ritorno-cartina-1` e `ritorno-cartina-2`,
    # e nel documento non si vedeva niente di storto: se ne accorgeva solo la
    # diagnostica della riparazione. Mandandoli a capo l'uno dall'altro, ne
    # escono due.
    return "".join(f"<div>{_anchor(nome)}</div>" for nome in nomi)


def _render_guide_link(poi_id, pin_targets: dict | None,
                       ancora_ritorno: str = "") -> str:
    """
    [richiesta di Lorenzo: "aggiungi magari un collegamento 'guida turistica
    tascabile' per ogni cosa che lo richieda ... e reindirizzi il cliente
    alla fine del pdf dove è presente la guida turistica, portandolo
    direttamente sull'attrazione richiesta"]

    [MODIFICATO 2026-08-03 — task #178] Prima riceveva solo le ancore interne
    e sapeva quindi fare una cosa sola: saltare a un capitolo di questo stesso
    documento. Ora riceve la stessa tabella di destinazioni che usano i
    pallini della cartina, e per lo stesso motivo: il collegamento alla guida
    di un posto deve portare ALLO STESSO POSTO ovunque compaia — dal pallino,
    dalla legenda o da qui. Due strade che divergono sono un difetto che
    nessun controllo di unità trova e che il cliente trova subito.

    Le due forme del collegamento non sono equivalenti e la differenza va
    detta al cliente, non nascosta: l'ancora interna funziona offline, in
    aereo, senza rete — che è precisamente quando serve; il documento
    ospitato no. Per questo la dicitura cambia. Perché l'ancora sia
    cliccabile, `render_pdf()` passa `--enable-internal-links` a wkhtmltopdf
    (senza quel flag il link viene disegnato ma è inerte).
    """
    if not pin_targets or not isinstance(poi_id, str):
        return ""
    bersaglio = pin_targets.get(poi_id)
    if not isinstance(bersaglio, dict) or not bersaglio.get("href"):
        return ""
    modo = bersaglio.get("modo")
    if modo == "documento":
        etichetta = "Apri la guida turistica"
    elif modo == "capitolo":
        etichetta = "Apri la guida &#8594;"
    else:
        etichetta = "Guida turistica tascabile"

    # [AGGIUNTO 2026-08-05 — task #191] Il segnaposto del ritorno si semina
    # QUI, accanto al collegamento che porta via, e non in cima al giorno.
    # È l'unico posto in cui «il punto esatto di dove si era arrivati
    # originariamente» significa qualcosa: il cliente stava leggendo questa
    # riga, non l'intestazione della giornata tre attività più su.
    sonda = _anchor(ancora_ritorno) if ancora_ritorno else ""
    return (
        f"<div class='guide-link'>{sonda}"
        f"<a href='{_esc(bersaglio['href'])}'>{etichetta}</a></div>"
    )


def render_html(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None = None,
    guides: list[dict] | None = None,
    # [AGGIUNTO 2026-08-03] Indirizzo pubblico della guida di ogni singola
    # attrazione, quando quella guida e' un documento a se' ospitato su
    # Render invece che un capitolo di questo stesso PDF (scelta di
    # Lorenzo). Chiave: `poi_id`. Vuoto o assente = si resta dentro il
    # documento, che e' il comportamento di sempre e funziona senza rete.
    guide_urls: dict | None = None,
    # [AGGIUNTO 2026-08-03 — task #181] `{poi_id: {"png", "credito", "reale"}}`,
    # TUTTE le immagini raccolte: le fotografie vere e le copertine disegnate
    # in casa, distinte dal campo `reale`. Chi stampa decide quali gli
    # servono — il programma della giornata prende solo le vere
    # (`_render_day_photo`), le schede delle guide le prendono tutte
    # (`_render_guide_foto`). Assente o vuoto = documento senza immagini,
    # identico a quello di ieri: e' il caso normale quando non c'e' una chiave
    # Google, e non deve essere un guasto.
    photos: dict | None = None,
    # [AGGIUNTO 2026-08-05 — task #190] `{poi_id: nome_ancora}` delle guide
    # stampate come CAPITOLI STACCATI, che verranno cucite in fondo a questo
    # stesso file (vedi `src/fascicolo.py`). È la migliore delle tre forme:
    # documento separato — quindi il principale resta scarno — nello stesso
    # file — quindi funziona in aereo — e con il ritorno al punto esatto.
    # Vuoto o assente = comportamento di prima, invariato.
    capitoli: dict | None = None,
    feedback: dict | None = None,
    poi: list[dict] | None = None,
    map_png_bytes: bytes | None = None,
    overview_map: dict | None = None,
    day_maps: list[dict] | None = None,
    directions: list[dict] | None = None,
    cost_summary: dict | None = None,
    tips: dict | None = None,
    place_cards: dict | None = None,
    feedback_link: dict | None = None,
    predeparture: dict | None = None,
    vademecum: dict | None = None,
    checklist_sheet: dict | None = None,
    # [AGGIUNTO 2026-08-15 — task #221] I capitoli che devono cominciare su una
    # pagina nuova, decisi MISURANDO la prima stampa (vedi
    # `src/impaginazione.py`). Vuoto = documento che scorre, cioe' il
    # comportamento di sempre.
    capitoli_a_capo=(),
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
    # [CORRETTO 2026-08-05 — task #195] Due difetti nella stessa riga, tutti
    # e due visibili in cima alla prima pagina di contenuto:
    #   - le date in forma tecnica («2026-09-14 → 2026-09-16»), l'unico
    #     punto del documento in cui si vedeva che l'ha scritto un
    #     programma;
    #   - quando `objective_function` manca — cioe' quasi sempre — la riga
    #     cominciava con un puntino separatore e uno spazio, appesi al
    #     nulla. Adesso i pezzi vuoti spariscono invece di lasciare la
    #     punteggiatura che li teneva insieme.
    pezzi_meta = [
        _esc(trip.get("objective_function")) if trip.get("objective_function") else "",
        _periodo_leggibile(trip.get("date_start"), trip.get("date_end"))
        if trip.get("date_start") and trip.get("date_end") else "",
        f"{_esc(trip.get('duration_days'))} giorni" if trip.get("duration_days") else "",
        f"Budget: {budget_str}",
    ]
    meta = " \u00b7 ".join(x for x in pezzi_meta if x)

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

    # [AGGIUNTO 2026-08-02 — task #166, "tra le varie attività mi sembra che
    # ci sia ancora troppo tempo"] Due indici che servono al calcolo del
    # ritmo (`src/pacing.py`): il tipo di ogni luogo, per sapere quanto dura
    # di norma la sosta, e i minuti misurati di ogni spostamento, per non
    # scambiare un trasferimento di mezz'ora per tempo libero.
    poi_by_id_for_pacing = {
        p.get("id"): p for p in (poi or []) if isinstance(p, dict) and p.get("id")
    }
    travel_minutes_by_pair: dict[tuple, int] = {}
    for entry in directions_by_day.values():
        for leg in entry.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            minutes = leg.get("minutes")
            if isinstance(minutes, (int, float)) and not isinstance(minutes, bool):
                travel_minutes_by_pair[(leg.get("from_poi_id"), leg.get("to_poi_id"))] = int(minutes)

    # Ancore delle guide: costruite PRIMA del day-by-day, perché i link
    # "Guida turistica tascabile" dentro i blocchi puntano qui.
    guide_list = [g for g in (guides or []) if isinstance(g, dict)]

    # [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: "cosi' il documento
    # principale appare piu' pulito piu' scarno andando a toglierli dal
    # documento principale, come se fosse uno zoom out dal macro al micro"]
    #
    # Un'attrazione la cui guida e' stata PUBBLICATA come documento a se' non
    # viene piu' ristampata qui dentro: sarebbe la stessa cosa due volte, e il
    # doppione e' precisamente il peso che rende noioso il documento
    # principale. Le altre restano, capitolo interno compreso — e non e' un
    # caso di scuola: la stampa di una guida puo' fallire per un timeout, e
    # quella guida deve continuare a esistere da qualche parte.
    #
    # Il filtro guarda la URL, non l'intenzione: solo un indirizzo cifrato
    # davvero presente toglie un capitolo. Un `guide_urls` mezzo vuoto o
    # malformato lascia il documento com'era.
    ospitate = {
        chiave for chiave, valore in (guide_urls or {}).items()
        if isinstance(chiave, str) and isinstance(valore, str)
        and valore.startswith("https://")
    }
    # [AGGIUNTO 2026-08-05 — task #190] Stessa identica logica per i capitoli
    # cuciti: una guida che esiste come capitolo staccato non viene ristampata
    # anche qui dentro. È tutto il punto della richiesta di Lorenzo — «i testi
    # cliccabili dalla cartina andrebbero rimossi dal documento» — e senza
    # questa riga il documento principale conterrebbe le guide DUE volte.
    staccate = {
        chiave for chiave, valore in (capitoli or {}).items()
        if isinstance(chiave, str) and isinstance(valore, str) and valore
    }
    ospitate = ospitate | staccate
    guide_stampate = [g for g in guide_list if g.get("poi_id") not in ospitate]

    guide_anchors: dict[str, str] = {}
    for index, guide in enumerate(guide_stampate):
        key = guide.get("poi_id") or guide.get("poi_name") or f"guida-{index}"
        anchor = f"guida-{_slug(key)}" or f"guida-{index}"
        guide.setdefault("_anchor", anchor)
        if guide.get("poi_id"):
            guide_anchors[guide["poi_id"]] = anchor

    # [AGGIUNTO 2026-08-03] Le destinazioni dei pallini: una sola tabella,
    # costruita qui e usata sia dalla cartina d'insieme sia da quelle delle
    # singole giornate, cosi' che lo stesso posto porti allo stesso posto in
    # tutto il documento.
    pin_targets = _costruisci_pin_targets(
        guide_anchors, poi_by_id_for_pacing, guide_urls=guide_urls,
        capitoli={c: a for c, a in (capitoli or {}).items() if c in staccate},
    )

    # [AGGIUNTO 2026-08-05 — task #191] Dove deve tornare il cliente da ogni
    # capitolo staccato. Si RICALCOLA qui invece di riceverlo: la stessa
    # funzione, gli stessi dati in ingresso, quindi per forza gli stessi nomi
    # di quelli che ha stampato `poi_pdf.costruisci_capitoli()`. Se il nome
    # arrivasse da fuori, una chiamata dimenticata lo lascerebbe vuoto e i
    # bottoni di ritorno punterebbero nel nulla — in silenzio.
    ritorni_per_poi = fascicolo.elenca_ritorni(
        itinerary, [{"poi_id": p} for p in sorted(staccate)],
        giorni_con_cartina=list(day_maps_by_day),
    )
    # Consumo per posizione: `("blocco", giorno, indice)` -> nomi delle ancore.
    #
    # [CORRETTO 2026-08-05, poche ore dopo averlo scritto] Il valore è una
    # LISTA e non una stringa, e la ragione è che una posizione può servire
    # più attrazioni. Un blocco del programma ne ha una sola, ma la cartina
    # di un giorno ne ha una per ogni pallino: `("cartina", 1)` è la stessa
    # chiave per tutte e nove le tappe. Con un valore solo, le prime otto
    # venivano sovrascritte dalla nona — e infatti il campione vero è uscito
    # con nove bottoni «torna alla cartina» e un solo bersaglio, cioè otto
    # collegamenti morti. Trovato rigenerando il documento, non leggendo il
    # codice: nessun controllo sui singoli pezzi poteva vederlo, perché ogni
    # pezzo, preso da solo, era giusto.
    ancore_di_ritorno: dict = {}
    for voci in ritorni_per_poi.values():
        for voce in voci:
            ancore_di_ritorno.setdefault(voce["origine"], []).append(voce["ancora"])

    costs_html = _render_costs(cost_summary)
    predeparture_html = _render_predeparture(predeparture)
    # [AGGIUNTO 2026-08-15 — task #220] Il capitolo che si cerca quando
    # qualcosa va storto: emergenze, valuta, prese, dove dormi, quanto si
    # cammina. Tutto da dati che abbiamo gia': non costa una chiamata.
    numeri_utili_html = _render_numeri_utili(
        predeparture, hotels, directions_by_day, days)
    vademecum_html = _render_vademecum(vademecum, checklist_sheet)
    tips_html = _render_tips(tips, itinerary.get("architect_tips"))
    rain_html = _render_rain_plans(tips)
    curated_html = _render_curated_sections(poi)
    glance_html = _render_at_a_glance(
        itinerary, trip, hotels, map_png_bytes, overview_map=overview_map,
        pin_targets=pin_targets,
    )

    # --- Indice: solo le sezioni che esistono davvero --------------------
    # [CORRETTO 2026-08-02 (ter) — task #168] Anche "a colpo d'occhio" ora
    # puo' non esserci: da quando non ripete piu' i dati di copertina, senza
    # cartina e senza giornate non le resta nulla da dire. Elencare in indice
    # un capitolo vuoto e' la versione peggiore del capitolo vuoto.
    toc_entries: list[tuple[str, str]] = []
    if glance_html:
        toc_entries.append(("colpo-docchio", "Il tuo viaggio, a colpo d'occhio"))
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
    # [CORRETTO 2026-08-03 — task #178] Sulle guide STAMPATE, non su tutte:
    # quando ogni guida e' diventata un documento a se' il capitolo interno
    # non esiste piu', e una voce d'indice che punta a un capitolo inesistente
    # e' un link morto in copertina — lo stesso difetto corretto due righe
    # sotto per la sezione recensione.
    if guide_stampate:
        toc_entries.append(("guide", "Guide turistiche tascabili"))
    # [SPOSTATE 2026-08-03 — task #182, richiesta di Lorenzo: «la parte del
    # "prima di partire" va messa in fondo al documento»] Qui, in coda,
    # perche' l'indice deve raccontare l'ordine vero delle pagine: un indice
    # che elenca "Prima di partire" fra i costi e i consigli, mentre la
    # sezione sta dodici pagine piu' in la', manda il cliente a cercare nel
    # posto sbagliato — ed e' un difetto che si nota solo su carta, dove non
    # si puo' cliccare. Le due voci restano una accanto all'altra: la lista
    # della sera prima e la valigia sono lo stesso gesto.
    if predeparture_html:
        toc_entries.append(("prima-di-partire", "Prima di partire"))
    if vademecum_html:
        toc_entries.append(("vademecum", "Vademecum: clima, valigia, bagagli"))
    if numeri_utili_html:
        toc_entries.append(("numeri-utili", "Numeri utili e quanto si cammina"))
    # [CORRETTO 2026-08-03] La voce d'indice segue la sezione: senza una URL
    # a cui rispondere la sezione non esce, e un indice che punta a un
    # capitolo inesistente è un link morto in copertina.
    if (feedback_link or {}).get("url"):
        toc_entries.append(("recensione", "Facci sapere com'è andata"))

    day_toc = [
        (f"giorno-{_esc(day.get('day'))}",
         f"Giorno {day.get('day')} — {day.get('title', '')}")
        for day in days
    ]

    # [AGGIUNTO 2026-08-13 — task #209] I colori del documento li sceglie il
    # POSTO, guardando le fotografie vere che abbiamo gia' scaricato per lui.
    # Senza fotografie si resta sulla tavolozza di sempre: un documento senza
    # immagini non ha nessuna informazione sul luogo, e inventargli un colore
    # sarebbe la stessa cosa che inventargli un prezzo.
    from src import tavolozza as _tav

    tinte = _tav.scegli(photos)

    parts = [
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>",
        f"<title>Itinerario — {destination}</title>",
        f"<style>{_css(tinte)}</style></head><body>",
        _render_cover(
            itinerary, trip, hotels, list(toc_entries), day_toc,
            len(guide_list),
            sum(
                len(e.get("legs") or [])
                for e in directions_by_day.values() if isinstance(e, dict)
            ),
            foto_copertina=_foto_di_apertura(days, photos),
        ),
        "<div class='header'>",
        f"<h1>Itinerario Ottimizzato: {destination}</h1>",
        f"<div class='meta'>{meta}</div>",
        "</div>",
        (f"<div>{_anchor('colpo-docchio')}</div>" if glance_html else ""),
        glance_html,
        # [TRADOTTO 2026-08-02] Era "Executive Summary": due parole inglesi
        # in un documento che per il resto e' tutto in italiano, e per giunta
        # in cima alla prima pagina di contenuto. Il campo dei dati continua a
        # chiamarsi `executive_summary` (lo scrive il modello, non il cliente);
        # qui cambia solo l'etichetta stampata.
        "<div class='section-title'>Il viaggio in breve</div>",
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
        parts.append(
            _titolo_capitolo("alloggio", "Il tuo alloggio")
        )
        # [AGGIUNTO 2026-08-02 — difetto visto rigenerando il campione] Qui si
        # stampavano due strutture una sotto l'altra, identiche nel peso
        # grafico e senza una parola su che rapporto avessero fra loro. Ma la
        # copertina ne indica UNA sotto "BASE", l'itinerario è costruito
        # attorno a quella, e la stima dei costi conta solo quella: chi legge
        # due righe uguali si chiede se debba prenotarle entrambe — e infatti
        # il conto, finché non l'ho corretto, gliele addebitava entrambe. La
        # riga di ruolo costa due parole e toglie l'ambiguità dal punto in cui
        # nasce.
        for index, h in enumerate(hotels):
            name = h.get("name") or "[Da Verificare]"
            ptype = h.get("property_type") or "alloggio"
            price = h.get("price_night_eur")
            # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni
            # costo"] Il prezzo/notte era già calcolato/disponibile da
            # LiteAPI ma non veniva mai mostrato al cliente finale prima
            # d'ora — solo il budget totale dichiarato compariva nel meta
            # dell'header.
            price_str = f" · {price}€/notte" if price is not None else ""
            if len(hotels) > 1:
                role = (
                    "base del viaggio — l'itinerario e la stima dei costi partono da qui"
                    if index == 0 else
                    "alternativa: stessa zona, stesse date — non si aggiunge alla base"
                )
                role_html = f" <span class='hotel-role'>{_esc(role)}</span>"
            else:
                role_html = ""
            parts.append(
                f"<div class='hotel-row'><strong>{_esc(name)}</strong> "
                f"({_esc(ptype)}{_esc(price_str)}){role_html}</div>"
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
        # [CORRETTO 2026-08-02 — task #168, difetto visto sul campione] Con due
        # strutture si stampavano due righe di pulsanti IDENTICHE nell'aspetto,
        # una sotto l'altra, senza nulla che dicesse a quale hotel appartenesse
        # ciascuna: il cliente vedeva "Cerca su Booking / Airbnb / Vrbo" due
        # volte di fila e non poteva sapere quale riga cercasse quale albergo.
        # Il nome davanti ai pulsanti costa una parola e toglie l'ambiguità; con
        # una struttura sola non serve e non si stampa.
        parts.append("<div class='platforms-box'>")
        for h in hotels:
            name = h.get("name") or "[Da Verificare]"
            links = build_search_links(destination_raw, date_start, date_end, hotel_name=name)
            which = (
                f"<span class='platforms-for'>{_esc(name)}</span>"
                if len(hotels) > 1 else ""
            )
            parts.append(
                f"<div class='hotel-row'>{which}"
                f"<a href='{links['booking']}'>Cerca su Booking</a>"
                f"<a href='{links['airbnb']}'>Airbnb</a>"
                f"<a href='{links['vrbo']}'>Vrbo</a></div>"
            )
        parts.append("</div>")

    if curated_html:
        # [CORRETTO 2026-08-15 — task #216] Qui c'era la sola ancora: il
        # capitolo esisteva in indice e sulla pagina no. Chi arrivava dal
        # sommario atterrava su "Dove mangiare" senza aver mai letto il titolo
        # del capitolo in cui era finito.
        parts.append(_titolo_capitolo(
            "selezione", "La selezione: dove mangiare, cosa fare"))
        parts.append(
            "<div class='section-intro'>Locali e luoghi scelti fra quelli davvero "
            "aperti e recensiti nella tua destinazione, non da una lista generica.</div>"
        )
        parts.append(curated_html)

    poi_energy = _build_poi_energy_lookup(poi)
    if poi_energy and _itinerary_has_any_energy_info(itinerary, poi_energy):
        parts.append(_render_energy_legend())

    location_lookup = _build_location_lookup(hotels, poi)

    if days:
        # Titolo e occhiello viaggiano insieme dentro il guscio: nel campione
        # questo titolo cadeva da solo sull'ultima riga di pagina 3.
        parts.append(_keep_together(
            _titolo_capitolo("giorno-per-giorno",
                             "Il programma, giorno per giorno")
            + "<div class='section-intro'>Ogni giornata ha la sua cartina con le tappe numerate "
            "nell'ordine di visita, la legenda che spiega ogni indicatore, e i tragitti "
            "spostamento per spostamento con il percorso già pronto da aprire.</div>"
            # [AGGIUNTO 2026-08-03 — task #180] Il criterio sta QUI, dentro lo
            # stesso guscio del titolo: e' la premessa del programma, e una
            # premessa che finisce sull'ultima riga della pagina precedente
            # non e' piu' una premessa.
            + _render_criterio()
        ))

    # [AGGIUNTO 2026-08-13 — task #214] Le due cose che il ciclo delle
    # giornate si deve ricordare da una all'altra.
    #
    # La RISERVA e' l'insieme delle fotografie vere di TUTTO il viaggio, ed
    # esiste per la richiesta di Lorenzo «ogni giornata deve avere le foto».
    # Quando per le tappe di una giornata Google non ha restituito niente si
    # prende in prestito da un'altra tappa dello stesso viaggio: stessa
    # citta', luogo dichiarato nella didascalia, nessuno ci legge una
    # promessa. Non si inventa niente — e' la regola su cui e' costruito
    # tutto questo prodotto.
    #
    # L'APERTURA PRECEDENTE serve a non ripetersi: senza, «mai due giornate
    # uguali di fila» non sarebbe nemmeno verificabile.
    _riserva_foto_viaggio = [
        (scatto, nome)
        for giorno_qualunque in days
        for _poi, scatto, nome in _foto_vere_della_giornata(
            (giorno_qualunque.get("blocks") or []), photos)
    ]
    _apertura_precedente = ""

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
        # [AGGIUNTO 2026-08-03 — task #179] Il totale della giornata entra nel
        # titolo, non in fondo: e' un dato che serve PRIMA di leggere il
        # programma, non dopo averlo letto.
        _totale_html = _render_day_travel_total(
            (directions_by_day.get(day_number) or {}).get("legs") or []
        )
        # [CORRETTO 2026-08-03, stesso giorno] La prima versione lo appendeva
        # solo a `day_title_html`, che pero' viene stampato SOLO se la cartina
        # del giorno esiste: bastava una chiamata a Google Static Maps andata
        # male — cioe' il caso piu' comune di guasto in questo progetto — per
        # far sparire in silenzio anche i chilometri, che con la cartina non
        # c'entrano niente. Ora il totale viene stampato una volta sola ma per
        # due strade indipendenti: dentro l'apertura del giorno se la cartina
        # c'e', subito sotto il titolo del primo tronco se non c'e'.
        _totale_gia_stampato = False
        day_title_html += _totale_html
        day_map_html = _render_day_map(
            day_maps_by_day.get(day_number), day_title_html, pin_targets=pin_targets,
        )
        if day_map_html:
            # [AGGIUNTO 2026-08-05 — task #191] I segnaposti di ritorno della
            # cartina. Sono TANTI quanti i pallini cliccabili di questa
            # giornata e stanno tutti nello stesso punto, subito sopra la
            # figura: ogni capitolo ha il suo nome di ritorno, ma il posto in
            # cui si torna è uno solo — la cartina.
            #
            # Il perché di questo compromesso, detto chiaramente: i pallini
            # sono elementi posizionati in modo assoluto sopra l'immagine, e
            # una sonda dentro un pallino avrebbe la stessa area del pallino,
            # rubandogli il clic. Quindi la precisione del ritorno, per la
            # cartina, si ferma alla cartina e non arriva al singolo pallino.
            # È una pagina intera di distanza, non un capitolo: il cliente si
            # ritrova dove stava guardando.
            parts.append(
                f"<div class='day-open'>{_anchor(f'giorno-{day_number}')}"
                f"{_sonde_cartina(ancore_di_ritorno, day_number)}"
                f"{day_map_html}</div>"
            )
            _totale_gia_stampato = bool(_totale_html)
        else:
            # La cartina di questo giorno era prevista ma non è uscita — la
            # chiamata a Google Static Maps che va male è il guasto più
            # frequente di questo progetto. I segnaposti si stampano lo
            # stesso: il bottone «torna alla cartina» esiste già dentro un
            # capitolo che è stato stampato prima, e senza il suo bersaglio
            # sarebbe un collegamento morto. Il cliente atterra all'inizio
            # della giornata, cioè dove la cartina sarebbe stata.
            parts.append(_sonde_cartina(ancore_di_ritorno, day_number))

        # [FIX 2026-07-11 — secondo audit adversariale; nota aggiornata
        # 2026-07-31] Da quando `page-break-inside: avoid` vive sul singolo
        # `.block` e non più sull'intera `.day-card` (vedi CSS), una giornata
        # lunga fluisce naturalmente su più pagine. Questo spezzettamento resta
        # comunque necessario: garantisce che ogni tronco riporti il proprio
        # titolo con " (continua)", così il cliente che gira pagina sa ancora
        # di quale giorno sta leggendo il programma.
        # [AGGIUNTO 2026-08-03 — task #181] La fotografia di apertura della
        # giornata. Calcolata qui, fuori dal ciclo dei tronchi, perche' va
        # stampata UNA volta: dentro il ciclo verrebbe ripetuta a ogni
        # "(continua)", cioe' tre volte nella stessa giornata lunga.
        _foto_html, _apertura_usata = _apertura_di_giornata(
            destination, day_number, blocks, photos,
            _riserva_foto_viaggio, _apertura_precedente)
        _apertura_precedente = _apertura_usata or _apertura_precedente
        # La fotografia in apertura ne usa una; la fila in chiusura prende le
        # altre. Passare qui quale e' gia' stata usata evita di stamparla due
        # volte nella stessa pagina, che e' il modo piu' rapido di far
        # sembrare automatico un documento.
        _foto_disponibili = _foto_vere_della_giornata(blocks, photos)
        _striscia_html = _render_striscia_foto(
            blocks, photos,
            gia_usata=(_foto_disponibili[0][0] if _foto_disponibili else ""))
        _MAX_BLOCKS_PER_DAY_CARD = 20
        chunks = [
            blocks[i : i + _MAX_BLOCKS_PER_DAY_CARD]
            for i in range(0, len(blocks), _MAX_BLOCKS_PER_DAY_CARD)
        ] or [[]]

        # [AGGIUNTO 2026-08-02 — task #166] Il ritmo si calcola sulla giornata
        # INTERA, non sul singolo tronco: lo spezzettamento in `chunks` è una
        # scelta di impaginazione e non deve poter cambiare il margine
        # stampato sull'ultimo blocco di una pagina.
        pacing_entries = pacing.analyze_day(
            blocks, poi_by_id_for_pacing, travel_minutes_by_pair
        )

        # [AGGIUNTO 2026-08-03 — task #180] Le tappe che cadono a porta
        # chiusa. Come il ritmo, si calcola sulla giornata intera: il giorno
        # della settimana non cambia perché il programma è stato spezzato su
        # due pagine. Se `date_start` manca, `giorno_settimana()` torna None e
        # `verifica_giornata()` non segnala niente — mai una segnalazione
        # basata su un giorno della settimana indovinato.
        _giorno_sett = scheduling_criteria.giorno_settimana(
            trip.get("date_start"), day_number
        )
        chiusure = scheduling_criteria.verifica_giornata(
            blocks, poi_by_id_for_pacing, _giorno_sett
        )

        # [AGGIUNTO 2026-08-03 — task #179, «la parte del "come arrivare"
        # appare ridondante, uniscila al programma del giorno»] Gli
        # spostamenti smettono di essere un capitolo e diventano righe dentro
        # il programma, ciascuna attaccata alla tappa a cui porta.
        # L'abbinamento e' per `to_poi_id` e non per posizione: i blocchi
        # senza luogo (pranzi liberi, tempo libero) non sono tappe della
        # cartina, quindi contarli spostererebbe tutte le righe di uno.
        # Vince la PRIMA occorrenza: se la stessa attrazione compare due
        # volte nella stessa giornata, il modo di arrivarci che interessa e'
        # quello della prima volta.
        day_legs = (directions_by_day.get(day_number) or {}).get("legs") or []
        day_legs = [l for l in day_legs if isinstance(l, dict)]
        legs_per_arrivo: dict[str, dict] = {}
        for _leg in day_legs:
            _dest = _leg.get("to_poi_id")
            if isinstance(_dest, str) and _dest and _dest not in legs_per_arrivo:
                legs_per_arrivo[_dest] = _leg
        legs_usati: set[int] = set()

        for chunk_index, chunk in enumerate(chunks):
            parts.append("<div class='day-card'>")
            suffix = " (continua)" if chunk_index > 0 else ""
            probe = "" if day_map_html or chunk_index > 0 else _anchor(f"giorno-{day_number}")
            # [CORRETTO 2026-07-31] Quando la cartina c'è, il titolo del
            # giorno è già stampato accanto ad essa poche righe sopra:
            # ripeterlo qui lo faceva leggere due volte di fila a distanza di
            # un centimetro. Nei tronchi di continuazione invece va sempre
            # ripetuto — è tutto il motivo per cui esiste lo spezzettamento.
            if not (day_map_html and chunk_index == 0):
                parts.append(
                    f"<div class='day-title'>{probe}Giorno {_esc(day_number)} — "
                    f"{_esc(day.get('title', ''))}{suffix}</div>"
                )
                if _totale_html and not _totale_gia_stampato:
                    parts.append(_totale_html)
                    _totale_gia_stampato = True
            # [AGGIUNTO 2026-08-03 — task #181] La foto sta DENTRO la
            # `.day-card`, non prima: fuori sarebbe un blocco a se' che
            # wkhtmltopdf puo' lasciare da solo in fondo alla pagina, con la
            # giornata che comincia in quella dopo. Una figura orfana e'
            # esattamente il difetto di impaginazione che Lorenzo ha
            # segnalato, e non ha senso introdurlo mentre si aggiungono le
            # immagini che dovrebbero rendere il documento piu' bello.
            if chunk_index == 0 and _foto_html:
                parts.append(_foto_html)
            for block_offset, block in enumerate(chunk):
                block_index = chunk_index * _MAX_BLOCKS_PER_DAY_CARD + block_offset
                # [DELIBERATO] Il `poi_id` (mostrato come `[POI1]` in
                # renderer.py) è un marcatore interno di audit/grounding per la
                # revisione qualità (Nodo 9) — non ha senso in un documento
                # cliente premium, quindi qui NON viene mostrato.
                poi_id = block.get("poi_id")
                energy_chip = _render_energy_chip(poi_id, poi_energy) if poi_energy else ""
                # [AGGIUNTO 2026-08-03 — task #179] Lo spostamento che porta
                # QUI, dentro lo stesso riquadro del blocco: il CSS tiene
                # unito il `.block`, quindi la riga "da X, 8 min a piedi" non
                # puo' finire in fondo a una pagina con la tappa a cui si
                # riferisce all'inizio della successiva.
                _leg_qui = legs_per_arrivo.get(poi_id) if isinstance(poi_id, str) else None
                _leg_html = ""
                if _leg_qui is not None and id(_leg_qui) not in legs_usati:
                    legs_usati.add(id(_leg_qui))
                    _leg_html = _render_leg_inline(_leg_qui)
                parts.append(
                    "<div class='block'>" + _leg_html +
                    f"<span class='block-time'>{_esc(block.get('time'))}</span> "
                    f"<span class='block-activity'>{_esc(block.get('activity'))} "
                    f"({_esc(block.get('location', ''))})</span>"
                    f"{energy_chip}"
                )
                if block.get("logistics"):
                    parts.append(f"<div class='block-logistics'>{_esc(block['logistics'])}</div>")
                # [AGGIUNTO 2026-08-03 — task #180] Prima del margine di
                # ritmo, non dopo: se una tappa è a porta chiusa, sapere
                # quanti minuti liberi restano dopo non serve a niente.
                parts.append(_render_blocco_chiuso(chiusure.get(block_index)))
                # [AGGIUNTO 2026-08-02 — task #166, "il rischio che la gente
                # ... finisca prima"] Il buco fra due tappe smette di essere
                # muto: quanto dura di norma questa sosta, a che ora ne uscirà,
                # quanto tempo gli resta e prima di cosa. Compare SOLO quando
                # il margine supera il buffer fisiologico (45 min), altrimenti
                # sarebbe una riga in più su ogni blocco del documento.
                margin_entry = (
                    pacing_entries[block_index]
                    if block_index < len(pacing_entries)
                    else None
                )
                if margin_entry is not None:
                    next_block = (
                        blocks[block_index + 1]
                        if block_index + 1 < len(blocks)
                        else {}
                    )
                    margin_text = pacing.describe_margin(
                        margin_entry, next_block.get("activity") or ""
                    )
                    if margin_text:
                        parts.append(
                            f"<div class='block-margin'>{_esc(margin_text)}</div>"
                        )
                parts.append(_render_place_links(poi_id, place_cards))
                parts.append(_render_guide_link(
                    poi_id, pin_targets,
                    # Un blocco del programma ha una sola attrazione: la
                    # lista, qui, non può che avere un elemento solo.
                    "".join(
                        ancore_di_ritorno.get(
                            ("blocco", day_number, block_index)) or []),
                ))
                parts.append(_render_maps_link(poi_id, location_lookup, place_cards))
                parts.append("</div>")
            parts.append("</div>")

        # [AGGIUNTO 2026-08-13] La fila di fotografie chiude la giornata,
        # dopo il programma e prima degli spostamenti residui: e' li' che lo
        # spazio avanza davvero.
        if _striscia_html:
            parts.append(_striscia_html)

        # [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "manca anche la parte
        # 'cartina e come arrivare'"] Subito dopo il programma della
        # giornata, non in un capitolo separato in fondo: serve mentre si
        # legge quella giornata, non a fine documento.
        # [RIFATTO 2026-08-03 — task #179] Il capitolo "Come arrivare" non
        # esiste piu': i suoi spostamenti sono gia' stampati sopra, ciascuno
        # attaccato alla tappa a cui porta. Qui restano solo quelli che non
        # hanno una tappa nel programma — in pratica il rientro serale
        # all'alloggio, che e' uno spostamento vero e sarebbe sbagliato
        # perdere proprio perche' e' quello fatto piu' stanchi.
        avanzati = [l for l in day_legs if id(l) not in legs_usati]
        if avanzati:
            parts.append("<div class='day-card'><div class='block'>")
            parts.append(
                "<span class='block-activity'>Rientro</span>"
            )
            for leg in avanzati:
                destinazione = str(leg.get("to_name") or "").strip()
                riga = _render_leg_inline(leg)
                if destinazione:
                    riga = riga.replace(
                        "</div>",
                        f" · verso {_esc(destinazione)}</div>", 1,
                    )
                parts.append(riga)
            parts.append("</div></div>")

    if costs_html:
        parts.append(
            _titolo_capitolo("costi", "Stima dei costi e dettaglio budget")
        )
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
            _titolo_capitolo(
                "consigli", "Architect's Tips — i consigli dell'Architetto")
        )
        parts.append(
            "<div class='section-intro'>Consigli legati a questo itinerario e a queste date — "
            "non consigli di viaggio validi ovunque.</div>"
        )
        parts.append(tips_html)

    if rain_html:
        parts.append(
            _titolo_capitolo("piani-b", "Piani B: se piove")
        )
        parts.append(
            "<div class='section-intro'>Alternative al chiuso scelte tra i luoghi reali già "
            "verificati per la tua destinazione, con lo stesso criterio del programma "
            "principale.</div>"
        )
        parts.append(rain_html)

    if guide_stampate:
        parts.append(
            _titolo_capitolo("guide", "Guide turistiche tascabili")
        )
        parts.append(
            "<div class='section-intro'>Una scheda per ogni luogo del programma: cosa stai "
            "guardando, cosa cercare una volta dentro, quanto tempo serve davvero. "
            "Dal programma puoi saltare direttamente alla scheda che ti serve.</div>"
        )
        for guide in guide_stampate:
            parts.append(
                _render_guide_section(guide, guide.get("_anchor"), photos)
            )

    # [SPOSTATE QUI 2026-08-03 — task #182, richiesta di Lorenzo: «la parte
    # del "prima di partire" va messa in fondo al documento»]
    #
    # Stavano fra i costi e i consigli, e la ragione scritta allora era buona:
    # «e' il punto in cui il documento smette di parlare del viaggio e comincia
    # a parlare di cosa fare ADESSO». Buona ma sbagliata sul momento della
    # lettura, che e' l'unica cosa che conta qui. Il documento si legge due
    # volte in due giorni diversi: la prima quando arriva, per vedere che
    # viaggio e' — e li' due capitoli di adempimenti piantati nel mezzo
    # interrompono proprio la parte per cui il cliente ha pagato; la seconda la
    # sera prima di partire, quando servono queste due liste e nient'altro. In
    # fondo servono entrambe le letture: la prima non le incontra, la seconda
    # le trova aprendo il documento dall'ultima pagina, che e' il gesto
    # naturale quando si cerca una lista.
    #
    # Restano nell'ordine di prima, una dietro l'altra: la lista della sera
    # prima e la valigia sono lo stesso gesto a un'ora di distanza. E restano
    # PRIMA della recensione, che e' l'unica cosa che ha senso trovare
    # sull'ultima pagina di tutte — la si legge a viaggio finito.
    if predeparture_html:
        parts.append(
            _titolo_capitolo("prima-di-partire", "Prima di partire")
        )
        parts.append(
            "<div class='section-intro'>La lista della sera prima: quello che, se manca, "
            "non si rimedia una volta arrivati. Ogni voce è legata a questo viaggio — "
            "all'alloggio prenotato, ai luoghi in programma, alla valuta del paese.</div>"
        )
        parts.append(predeparture_html)

    if vademecum_html:
        parts.append(
            _titolo_capitolo("vademecum",
                             "Vademecum: clima, valigia, bagagli")
        )
        parts.append(
            "<div class='section-intro'>Il clima tipico di queste date in questa destinazione, "
            "la valigia che ne consegue e — se si vola low cost — quale bagaglio conviene "
            "davvero, con il conto fatto. Il clima è un dato storico, non una previsione: "
            "la previsione vera esiste solo a pochi giorni dalla partenza, e qui sotto c'è "
            "il link per guardarla al momento giusto.</div>"
        )
        parts.append(vademecum_html)

    # [AGGIUNTO 2026-08-15 — task #220] Ultimo capitolo prima della
    # recensione, e la posizione e' il punto: e' quello che si cerca DURANTE
    # il viaggio, e in fondo ci si arriva aprendo il fascicolo dall'ultima
    # pagina — il gesto naturale di chi cerca un numero.
    if numeri_utili_html:
        parts.append(
            _titolo_capitolo("numeri-utili", "Numeri utili e quanto si cammina")
        )
        parts.append(
            "<div class='section-intro'>Il capitolo da cercare quando serve qualcosa "
            "subito: il numero di emergenza, come si paga, che prese servono, "
            "l'indirizzo di dove dormi e quanta strada fai a piedi ogni giorno. "
            "Niente qui è stato scritto da un'intelligenza artificiale: sono dati "
            "verificati a mano e misure prese sul tuo programma.</div>"
        )
        parts.append(numeri_utili_html)

    # [AGGIORNATO 2026-08-01] La sezione esce anche se la generazione del
    # messaggio personalizzato e' fallita, purche' ci sia un link a cui
    # rispondere: il ciclo di dati non deve dipendere da una chiamata al
    # modello andata storta.
    if (feedback_link or {}).get("url"):
        parts.append(f"<div>{_anchor('recensione')}</div>")
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

    # [AGGIUNTO 2026-08-03 - task #183] L'ultima cosa che succede al
    # documento: la passata di impaginazione che impedisce a un paragrafo di
    # spezzarsi fra due pagine. Sta qui, alla fine, e non dentro i singoli
    # capitoli, per la ragione scritta su `_tieni_uniti_i_paragrafi` - vale
    # anche per i capitoli che verranno aggiunti domani.
    # [PROVATO E TOLTO 2026-08-13] Qui era stata inserita una passata che
    # teneva il titolo di sezione attaccato alla sua riga di presentazione,
    # per rispondere a «non voglio una pagina iniziata per due righe».
    # Funzionava — e peggiorava il documento: il controllo misurato
    # `test_nessuna_pagina_si_ferma_a_meta_foglio` e' diventato rosso, con la
    # pagina 3 che si fermava al 68%. Togliere un titolo orfano creando due
    # centimetri di vuoto altrove non e' un miglioramento, e' uno scambio.
    # La funzione `_tieni_il_titolo_col_suo_inizio()` resta scritta e non
    # collegata: servira' quando si sapra' tenere insieme il titolo SOLO se
    # cade nell'ultimo quarto di pagina, che e' l'informazione che questo
    # motore di stampa non ci da'.
    # [AGGIUNTA 2026-08-15 — task #216] Le testate dei capitoli si vestono
    # PRIMA della passata sui paragrafi, e non dopo: quella avvolge in un
    # guscio ogni blocco di prosa corto, e una testata gia' vestita non e' piu'
    # un blocco di prosa. L'ordine inverso funzionerebbe lo stesso oggi e
    # smetterebbe di funzionare il giorno in cui una testata contiene una riga
    # di testo — cioe' senza che nessuno se ne accorga.
    return _tieni_uniti_i_paragrafi(
        _testate_dei_capitoli("".join(parts), str(destination or ""),
                              capitoli_a_capo)
    )


def render_pdf(
    itinerary: dict,
    trip: dict,
    hotels: list[dict] | None = None,
    guides: list[dict] | None = None,
    # [AGGIUNTO 2026-08-03] Indirizzo pubblico della guida di ogni singola
    # attrazione, quando quella guida e' un documento a se' ospitato su
    # Render invece che un capitolo di questo stesso PDF (scelta di
    # Lorenzo). Chiave: `poi_id`. Vuoto o assente = si resta dentro il
    # documento, che e' il comportamento di sempre e funziona senza rete.
    guide_urls: dict | None = None,
    # [AGGIUNTO 2026-08-03 — task #181] `{poi_id: {"png", "credito", "reale"}}`,
    # TUTTE le immagini raccolte: le fotografie vere e le copertine disegnate
    # in casa, distinte dal campo `reale`. Chi stampa decide quali gli
    # servono — il programma della giornata prende solo le vere
    # (`_render_day_photo`), le schede delle guide le prendono tutte
    # (`_render_guide_foto`). Assente o vuoto = documento senza immagini,
    # identico a quello di ieri: e' il caso normale quando non c'e' una chiave
    # Google, e non deve essere un guasto.
    photos: dict | None = None,
    feedback: dict | None = None,
    poi: list[dict] | None = None,
    map_png_bytes: bytes | None = None,
    overview_map: dict | None = None,
    output_path: str | None = None,
    day_maps: list[dict] | None = None,
    directions: list[dict] | None = None,
    cost_summary: dict | None = None,
    tips: dict | None = None,
    place_cards: dict | None = None,
    feedback_link: dict | None = None,
    predeparture: dict | None = None,
    vademecum: dict | None = None,
    checklist_sheet: dict | None = None,
    # [AGGIUNTO 2026-08-05 — task #190] I capitoli staccati da cucire in
    # fondo: la lista che esce da `poi_pdf.costruisci_capitoli()`, cioè
    # `[{"poi_id", "ancora", "pdf"}]`. Si passa QUESTA e non una mappa più i
    # byte a parte, di proposito: due argomenti separati potrebbero
    # disallinearsi — un capitolo elencato ma non cucito è un collegamento
    # morto — e non c'è modo di accorgersene guardando il PDF.
    capitoli_pdf: list | None = None,
    # File da infilare dentro il PDF come veri allegati: `{nome: byte}`.
    # Serve al foglio della valigia.
    allegati: dict | None = None,
    # [AGGIUNTO 2026-08-13] Un dizionario che chi chiama puo' passare per
    # RICEVERE il resoconto della riparazione dei collegamenti interni.
    #
    # Nasce da un difetto arrivato fino al cliente. Nel documento consegnato
    # l'11 agosto non c'era **nemmeno una** destinazione interna: i pulsanti
    # «Apri la guida» e le zone cliccabili sulle cartine erano tutti morti. Il
    # resoconto che lo diceva esisteva gia' — veniva stampato nei log di
    # Render — e non lo leggeva nessuno. E' la stessa lezione del 5xx che
    # nascondeva il messaggio: un'informazione che arriva dove nessuno guarda
    # non e' un'informazione.
    #
    # Passandolo qui, quel numero risale fino alla risposta di `/v1/pdf` e
    # quindi fino a Make, dove si vede senza aprire niente.
    resoconto_collegamenti: dict | None = None,
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

    # [AGGIUNTO 2026-08-05 — task #190] La mappa dei capitoli si RICAVA dai
    # capitoli davvero stampati, non si riceve a parte. Un capitolo che non è
    # riuscito a stamparsi non finisce qui dentro, e quindi il documento
    # principale non stampa nemmeno il collegamento che ci porterebbe: nessun
    # link morto, senza bisogno di ricordarselo.
    capitoli_pronti = [
        c for c in (capitoli_pdf or [])
        if isinstance(c, dict) and c.get("pdf") and c.get("ancora")
        and isinstance(c.get("poi_id"), str)
    ]
    mappa_capitoli = {c["poi_id"]: c["ancora"] for c in capitoli_pronti}

    def _componi(a_capo=()):
        return render_html(
            itinerary, trip, hotels=hotels, guides=guides, guide_urls=guide_urls,
            capitoli=mappa_capitoli,
            photos=photos, feedback=feedback,
            poi=poi, map_png_bytes=map_png_bytes, overview_map=overview_map,
            day_maps=day_maps,
            directions=directions, cost_summary=cost_summary, tips=tips,
            place_cards=place_cards, feedback_link=feedback_link,
            predeparture=predeparture, vademecum=vademecum,
            checklist_sheet=checklist_sheet,
            capitoli_a_capo=a_capo,
        )

    html_content = _componi()

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
            [*COMANDO_STAMPA, tmp_html_path, tmp_pdf_path],
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

        # [AGGIUNTO 2026-08-15 — task #221. Segnalazione di Lorenzo: «si
        # spezzano i capitoli. cerca di fare terminare i capitoli a fine
        # pagina».]
        #
        # LA SECONDA STAMPA. Il motore di stampa non sa dire, prima di
        # stampare, dove cadranno le cose — e `page-break-after: avoid`, che
        # servirebbe, lo ignora in silenzio. Quindi si stampa, si GUARDA dove
        # sono finite le testate (le sonde lo dicono gia', vedi
        # `src/impaginazione.py`), si mandano a capo SOLO quelle cadute in
        # fondo al foglio, e si ristampa.
        #
        # Solo quelle, e non tutte, e' l'intera differenza fra un
        # miglioramento e uno scambio: mandare a capo ogni capitolo su questo
        # prodotto e' gia' costato sette pagine con il 40% di bianco, ed e'
        # scritto nello standard di qualita'.
        #
        # Una passata sola in piu': se anche la seconda lasciasse una testata
        # in basso, ci si ferma. Un ciclo che insegue l'impaginazione perfetta
        # non converge — sposta il problema di un capitolo ogni volta — e
        # costerebbe secondi di stampa dentro un tetto di tempo che e' gia'
        # stretto.
        try:
            da_spostare = impaginazione.capitoli_da_mandare_a_capo(
                Path(tmp_pdf_path).read_bytes(), CAPITOLI_DEL_DOCUMENTO)
        except Exception:
            da_spostare = set()
        if da_spostare:
            with open(tmp_html_path, "w", encoding="utf-8") as rifatto:
                rifatto.write(_componi(da_spostare))
            seconda = subprocess.run(
                [*COMANDO_STAMPA, tmp_html_path, tmp_pdf_path],
                capture_output=True, text=True, timeout=60,
            )
            # Se la seconda stampa non riesce si tiene la prima: un documento
            # con un capitolo impaginato male e' molto meglio di nessun
            # documento.
            if seconda.returncode != 0 or not Path(tmp_pdf_path).stat().st_size:
                with open(tmp_html_path, "w", encoding="utf-8") as indietro:
                    indietro.write(html_content)
                subprocess.run([*COMANDO_STAMPA, tmp_html_path, tmp_pdf_path],
                               capture_output=True, text=True, timeout=60)

        # [AGGIUNTO 2026-08-02 — segnalazione di Lorenzo: «i collegamenti non
        # funzionano»] wkhtmltopdf, con il Qt non patchato, ignora in silenzio
        # `--enable-internal-links` e trasforma ogni `href="#x"` in un link al
        # file temporaneo da cui ha stampato. Qui il PDF finito viene ricucito:
        # vedi src/pdf_links.py. Si fa PRIMA di `os.replace()`, sul temporaneo,
        # così il file di destinazione compare già riparato — nessun lettore
        # può aprirlo a metà lavoro.
        #
        # `repair_internal_links` non solleva mai e, se non ce la fa, lascia il
        # file identico: la navigabilità è un di più, l'itinerario no.
        #
        # [MODIFICATO 2026-08-05 — task #190, richiesta di Lorenzo: «questi
        # documenti seppur diversi stiano in un unico file»] Da qui in poi il
        # file non è più il prodotto di un solo programma. I capitoli
        # staccati e il foglio della valigia entrano PRIMA della riparazione,
        # e l'ordine non è negoziabile:
        #
        #   1. cucitura dei capitoli   (pypdf riscrive tutto il file)
        #   2. allegati                (pypdf lo riscrive ancora)
        #   3. riparazione             (la nostra passata, che aggiunge in
        #                               fondo senza toccare il resto)
        #
        # Invertendo, i passaggi di pypdf cancellerebbero la riparazione:
        # riscrivendo il file da zero, i salti di pagina già risolti
        # tornerebbero collegamenti finti. Fatta per ultima, l'ultimo a
        # scrivere siamo noi.
        #
        # `fascicolo.cuci` non solleva mai: se la cucitura fallisce il cliente
        # riceve comunque l'itinerario, che è la parte che ha pagato.
        allegati_veri = {
            nome: blob for nome, blob in (allegati or {}).items()
            if isinstance(nome, str) and nome
            and isinstance(blob, bytes) and blob
        }
        if capitoli_pronti or allegati_veri:
            dati, resoconto = fascicolo.cuci(
                Path(tmp_pdf_path).read_bytes(),
                [c["pdf"] for c in capitoli_pronti],
                allegati_veri,
                # Le ancore, in fila con i capitoli: e' cio' che permette di
                # sapere dove atterra ogni collegamento senza doverlo dedurre
                # da un segnaposto invisibile che il motore di stampa di
                # produzione non disegna.
                ancore=[c.get("ancora") for c in capitoli_pronti],
            )
            Path(tmp_pdf_path).write_bytes(dati)
            link_report = resoconto.get("collegamenti") or {}
            if resoconto.get("errore") or (
                capitoli_pronti and not resoconto.get("unione_riuscita")
            ):
                print(
                    "[pdf_renderer] fascicolo: "
                    f"capitoli={resoconto.get('capitoli')} "
                    f"allegati={resoconto.get('allegati')} "
                    f"errore={resoconto.get('errore')}"
                )
        else:
            # [AGGIUNTO 2026-08-15 — task #217] Anche il documento senza
            # capitoli vuole i suoi numeri: senza questa riga, un itinerario
            # corto (nessuna guida stampata, nessun allegato) sarebbe l'unico
            # documento del prodotto a uscire senza numeri di pagina — e
            # sarebbe un difetto che compare solo su certi ordini, cioe' il
            # tipo che non si trova mai.
            Path(tmp_pdf_path).write_bytes(
                fascicolo.numera(Path(tmp_pdf_path).read_bytes()))
            link_report = pdf_links.repair_internal_links(tmp_pdf_path)

        if isinstance(resoconto_collegamenti, dict):
            resoconto_collegamenti.update(link_report or {})

        if link_report.get("errore") or link_report.get("non_risolte"):
            print(
                "[pdf_renderer] collegamenti interni: "
                f"riscritti={link_report.get('riscritti')} "
                f"sonde={link_report.get('sonde')} "
                f"non_risolte={link_report.get('non_risolte')} "
                f"errore={link_report.get('errore')}"
            )

        os.replace(tmp_pdf_path, output_path)
    finally:
        Path(tmp_html_path).unlink(missing_ok=True)
        # Se `os.replace()` è già avvenuto, il file temporaneo non esiste più
        # a questo path — `missing_ok=True` evita un errore spurio in quel
        # caso normale (successo), pulendo solo nei casi di fallimento.
        Path(tmp_pdf_path).unlink(missing_ok=True)

    return output_path
