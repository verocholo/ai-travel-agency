"""
Guide per attrazione, come documenti a sé — src/poi_pdf.py.

[AGGIUNTO 2026-08-03 — richiesta di Lorenzo: «migliorare la guida turistica
linkando un pdf per attrazione da te generato ad hoc per la guida con ogni
attrazione con immagini e tutto con bottone di torna all'itinerario alla
parte giusta», e più avanti la frase che tiene insieme tutto il giro:
«come se fosse uno zoom out dal macro al micro». Fra le due strade possibili
(un capitolo "micro" in fondo allo stesso PDF, oppure file separati) Lorenzo
ha scelto esplicitamente: «PDF separati, ospitati su Render».]

Che problema risolve, detto con le sue parole. Il documento principale era
diventato «noioso»: dentro c'era il programma della giornata e, subito
sotto, tutto quello che si poteva dire di ogni singola attrazione. Chi
voleva sapere a che ora si esce doveva sfogliare tre pagine di storia del
Duomo. Separando i due livelli, il principale torna a rispondere alla
domanda macro («che faccio oggi?») e ogni guida risponde alla domanda micro
(«cos'è questo posto, quanto costa, come ci arrivo?») a chi la fa davvero.

Il prezzo di questa scelta, scritto qui perché non venga dimenticato:

  1. **le guide separate NON funzionano senza rete.** Il documento
     principale sì (è un file che il cliente ha scaricato), le guide no:
     sono URL. In aereo, in metropolitana o all'estero senza dati il
     cliente ha l'itinerario e non ha le guide. Per questo il rimando
     INTERNO non viene buttato: quando l'ospitalità non è configurata —
     o quando anche una sola guida non riesce a essere pubblicata — quel
     luogo torna ad avere il suo capitolo dentro il documento principale
     (vedi `pdf_renderer._costruisci_pin_targets`, che sceglie fra le due
     strade una per volta e per singola attrazione);
  2. **sono documenti raggiungibili da chiunque abbia la URL.** Il modello
     di sicurezza è quello di `src/hosting.py` e va letto lì per intero.
     Le guide, a differenza del documento principale, non contengono dati
     personali: non c'è il nome del cliente, non ci sono le sue date, non
     c'è il suo albergo. È deliberato ed è il motivo per cui il
     `consiglio_personalizzato` — l'unico campo della guida che parla del
     cliente in seconda persona — resta dentro il PDF principale e non
     viene stampato qui.

Interfaccia pubblica:

    render_guide_pdf(...) -> bytes | None
    publish_guides(...)   -> dict[poi_id, url]

Nessuna delle due solleva mai. Quando qualcosa non va tornano `None` o un
dizionario vuoto, e il chiamante semplicemente non stampa il link: la
regola di tutto il progetto è che un collegamento morto stampato su un
documento pagato è peggio di un collegamento assente.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path

from src import fascicolo
from src import foto
from src import hosting
from src import scheduling_criteria
from src.pdf_links import PROBE_PREFIX
from src.pdf_renderer import (
    _esc, _paragraphs, _slug, _tieni_uniti_i_paragrafi,
)

# Quante guide al massimo si pubblicano per una consegna. Non è una paura
# astratta: ogni guida è una stampa di wkhtmltopdf da qualche centinaio di
# millisecondi, e l'esecuzione completa su Make ha un tetto duro di 300
# secondi che una misura reale ha già sfiorato (356 s). Meglio dieci guide
# pubblicate e le altre dentro il documento principale, che un itinerario
# che non arriva.
MAX_GUIDE = 12

# Tetto di sicurezza sulla singola stampa.
TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# Il foglio di stile. È una copia RIDOTTA di quello del documento
# principale, non un import: le guide sono documenti brevi (2-3 pagine) e
# la maggior parte di quelle regole — copertina, indice, cartine, tabelle
# dei costi — qui non serve. Copiare 40 righe è più onesto che trascinarsi
# dietro 900 righe di regole morte dentro ogni singolo file pubblicato,
# moltiplicate per il numero di attrazioni.
#
# I limiti del motore restano gli stessi del documento principale (Qt
# WebKit di wkhtmltopdf): niente sfumature, niente trasparenze, niente
# scatole flessibili. Le due colonne, dove servono, si fanno con le
# tabelle.
# ---------------------------------------------------------------------------
_CSS = """
    @page { size: A4; margin: 1.6cm 1.6cm; }
    * { box-sizing: border-box; }
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #22303f; line-height: 1.55; margin: 0; font-size: 13px;
    }
    /* [RIFATTO 2026-08-05 — task #195] Stessa identita' del documento
       principale (`src/identita.py`). Prima il capitolo si apriva con un
       pannello blu dagli angoli tondi e il principale con una pagina di
       carta: due documenti dentro lo stesso file con due facce diverse
       sono due documenti, non uno. Adesso si riconoscono come parenti. */
    .testata {
      background-color: #ffffff; color: #16212f;
      border-top: 3px solid #b08d4f;
      padding: 18px 0 16px 0; margin-bottom: 4px;
    }
    .testata .occhiello {
      font-size: 9px; letter-spacing: .20em; color: #b08d4f;
      text-transform: uppercase; margin-bottom: 14px; font-weight: bold;
    }
    .testata h1 {
      font-family: Georgia, 'Times New Roman', serif;
      margin: 0; font-size: 34px; line-height: 1.1; font-weight: normal;
    }
    .testata .dove {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 13px; font-style: italic; color: #6c7683; margin-top: 8px;
    }
    .foto { text-align: center; margin: 12px 0 4px 0; }
    .foto img { max-width: 100%; border-radius: 0; }
    .foto .credito { font-size: 9.5px; color: #8a97a5; margin-top: 3px; }
    .sottotitolo {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 17px; font-weight: normal; color: #16212f;
      border-bottom: 1px solid #e2ded6; padding-bottom: 6px;
      margin: 22px 0 10px 0;
    }
    .corpo { margin: 0 0 9px 0; }
    .riga-luogo { padding: 4px 0; border-bottom: 1px solid #efece5; }
    .nome-luogo { font-weight: bold; color: #16212f; }
    .riquadro {
      background: #faf7f1; border-left: 2px solid #b08d4f;
      padding: 11px 16px; margin: 12px 0;
    }
    .riquadro ul { margin: 6px 0 0 0; padding-left: 18px; }
    .avviso {
      background: #ffffff; border-left: 2px solid #a3423a;
      padding: 11px 16px; margin: 12px 0;
    }
    .fatti { font-size: 12.5px; margin: 8px 0; }
    .pratico { width: 100%; border-collapse: collapse; margin: 6px 0; }
    .pratico td { padding: 5px 10px 5px 0; vertical-align: top; }
    .pratico .voce { color: #6b7a89; width: 34%; font-size: 12px; }
    .bottone-torna { margin: 0 0 9px 0; }
    /* `inline-block` non e' cosmesi: un `<a>` in linea con del padding
       verticale NON alza la riga che lo contiene, quindi due bottoni uno
       sotto l'altro si sovrappongono — visto sul campione del 2026-08-05,
       il secondo mangiava il bordo del primo. Da quando i bottoni di
       ritorno sono piu' d'uno (uno per punto di partenza) la cosa si nota
       ogni volta. */
    .bottone-torna a {
      display: inline-block;
      background-color: #1a3b5c; color: #ffffff; text-decoration: none;
      padding: 10px 18px; border-radius: 0; font-weight: bold;
      font-size: 13px;
    }

    /* [AGGIUNTO 2026-08-05 — task #190] La sonda. Stesse identiche regole
       del documento principale, e per la stessa ragione: wkhtmltopdf assegna
       un'annotazione solo a un elemento che occupa dello spazio, quindi la
       sonda deve essere quasi invisibile ma NON di dimensione zero. Se
       sparisse del tutto, la riparazione dei collegamenti resterebbe cieca e
       tutti i rimandi del fascicolo morirebbero in silenzio. */
    .anchor-probe { font-size: 2px; line-height: 2px; color: #ffffff; }
    .anchor-probe a { color: #ffffff; text-decoration: none; }
    .nota { font-size: 10.5px; color: #6b7a89; margin-top: 12px; }
    a { color: #2f6690; }
    /* Il motore non sa tenere insieme una scatola alta, ma sa tenere
       insieme una riga di tabella: dove serve davvero si usa quella. */
    tr, img { page-break-inside: avoid; }

    /* [AGGIUNTO 2026-08-03 — task #183] Il guscio che la passata finale di
       impaginazione mette attorno a ogni paragrafo corto, perché non si
       spezzi fra due pagine. Il nome e la regola sono gli stessi del
       documento principale: è lo stesso codice a metterlo, e due fogli di
       stile che lo chiamano in due modi diversi sarebbero solo un modo per
       scoprire fra sei mesi che in uno dei due non ha mai funzionato. */
    .keep-prosa {
      width: 100%; border-collapse: collapse; page-break-inside: avoid;
      margin: 0; border: none;
    }
    .keep-prosa td { padding: 0; border: none; }
"""


def _righe_nominate(voci, titolo: str) -> str:
    """«Cosa cercare, una volta dentro» e «A due passi da qui»: nome in
    evidenza e, quando c'è, il perché di fianco."""
    righe = []
    for voce in voci or []:
        if isinstance(voce, dict):
            nome, perche = voce.get("name") or "", voce.get("why") or ""
        else:
            nome, perche = str(voce), ""
        if not nome:
            continue
        righe.append(
            f"<div class='riga-luogo'><span class='nome-luogo'>{_esc(nome)}</span>"
            + (f" — {_esc(perche)}" if perche else "")
            + "</div>"
        )
    if not righe:
        return ""
    return f"<div class='sottotitolo'>{_esc(titolo)}</div>" + "".join(righe)


def _riga_pratica(voce: str, contenuto: str) -> str:
    if not contenuto:
        return ""
    return f"<tr><td class='voce'>{_esc(voce)}</td><td>{contenuto}</td></tr>"


def _link(url, etichetta: str) -> str:
    """Un collegamento, ma solo se è cifrato.

    Un `http://` dentro un PDF che viaggia per posta elettronica è una
    segnalazione che i lettori moderni mostrano al cliente, ed è anche
    vietato da un test di regressione del progetto. Meglio niente riga.
    """
    testo = str(url or "").strip()
    if not testo.startswith("https://"):
        return ""
    return f"<a href='{_esc(testo)}'>{_esc(etichetta)}</a>"


_GIORNI_IT = (
    ("Mon", "Lun"), ("Tue", "Mar"), ("Wed", "Mer"), ("Thu", "Gio"),
    ("Fri", "Ven"), ("Sat", "Sab"), ("Sun", "Dom"),
)


def _orari_settimana(open_hours) -> str:
    """La settimana di apertura, in una riga per giorno.

    [AGGIUNTO 2026-08-03 — task #180, richiesta di Lorenzo: «tenendo conto
    degli orari di apertura delle strutture»]

    Questo e' il posto giusto per il dettaglio, ed e' la ragione per cui
    esiste lo "zoom out dal macro al micro": sette righe di orari nel
    documento principale, moltiplicate per venti attrazioni, sono
    centoquaranta righe che nessuno legge; qui dentro sono la prima cosa che
    serve a chi sta decidendo se uscire adesso.

    Un giorno assente dalle chiavi significa CHIUSO, e viene stampato come
    tale: lasciarlo fuori dall'elenco farebbe leggere "non lo sappiamo" a chi
    invece sta guardando l'unica informazione che gli evita un viaggio a
    vuoto. Se `open_hours` manca del tutto la riga non compare affatto — il
    silenzio e' meglio di sette "chiuso" inventati.
    """
    if not isinstance(open_hours, dict) or not open_hours:
        return ""
    righe = []
    for chiave, etichetta in _GIORNI_IT:
        finestre = scheduling_criteria.finestre_del_giorno(open_hours, chiave)
        if finestre:
            testo = " e ".join(f"{inizio}\u2013{fine}" for inizio, fine in finestre)
        else:
            testo = "chiuso"
        righe.append(f"{etichetta} {testo}")
    return "<br>".join(_esc(r) for r in righe)


def _sonda(nome: str) -> str:
    """Il punto di atterraggio di un rimando, dentro una guida.

    [AGGIUNTO 2026-08-05 — task #190] Identico a `pdf_renderer._anchor`: è
    lo stesso meccanismo, e deve restare lo stesso. Il carattere dentro il
    collegamento è uno spazio unificatore, non uno spazio normale: uno spazio
    normale verrebbe collassato dal motore e l'elemento resterebbe largo zero
    pixel — cioè senza annotazione, cioè invisibile alla riparazione.
    """
    sicuro = _esc(str(nome or "").strip())
    if not sicuro:
        return ""
    return (
        f"<span id='{sicuro}' class='anchor-probe'>"
        f"<a href='{PROBE_PREFIX}{sicuro}'>&#160;</a></span>"
    )


def build_guide_html(
    guide: dict,
    *,
    destination: str = "",
    place_card: dict | None = None,
    photo: dict | None = None,
    itinerary_url: str | None = None,
    come_arrivare: str = "",
    open_hours: dict | None = None,
    ancora_capitolo: str = "",
    ritorni=None,
) -> str:
    """L'HTML di UNA guida, completo e autonomo.

    `photo` è `{"png": bytes, "credito": str}` — la foto vera del luogo
    quando c'è; il credito è obbligatorio quando la foto arriva da Google
    Places, e infatti se manca il credito la foto NON viene stampata:
    pubblicare una foto altrui senza attribuzione su un documento venduto
    è un problema serio, non un dettaglio estetico.

    `itinerary_url` è la URL del documento principale: è il bottone «torna
    all'itinerario». Se manca, il bottone non c'è — e la guida lo dice, con
    una riga di spiegazione, invece di lasciare il cliente in un vicolo
    cieco senza capire perché.

    `ancora_capitolo` e `ritorni` servono alla modalità FASCICOLO, cioè
    quando questa guida non è un file ospitato ma un capitolo cucito dentro
    lo stesso PDF dell'itinerario (task #190-#191). In quel caso:

      - `ancora_capitolo` è il nome del punto di atterraggio stampato in
        cima, quello che il documento principale raggiunge da `#...`;
      - `ritorni` è l'elenco prodotto da `fascicolo.elenca_ritorni()` per
        QUESTA attrazione: un bottone per ogni punto da cui ci si arriva.

    Il secondo è il motivo per cui la lista non è una stringa sola. Lorenzo:
    «ogni collegamento esterno abbia un pulsante per ritornare al documento
    principale, NEL PUNTO ESATTO di dove si era arrivati originariamente».
    La stessa attrazione può comparire nel programma del Giorno 2 e sulla
    cartina del Giorno 2, e i due bottoni devono riportare in due posti
    diversi: un bottone solo, per forza di cose, ne sbaglierebbe uno.

    Quando `ritorni` c'è, il bottone verso la URL ospitata non viene
    stampato: nel fascicolo il documento principale è a due pagine di
    distanza, e mandare il cliente su internet per raggiungerlo sarebbe
    peggio in ogni situazione — soprattutto in aereo, che è esattamente il
    momento in cui questi documenti si leggono.
    """
    guide = guide if isinstance(guide, dict) else {}
    nome = str(guide.get("poi_name") or "").strip()
    titolo = str(guide.get("title") or nome).strip()
    card = place_card if isinstance(place_card, dict) else {}

    parti = [
        "<!DOCTYPE html><html lang='it'><head><meta charset='utf-8'>",
        f"<title>{_esc(titolo or 'Guida')}</title><style>{_CSS}</style></head><body>",
        # La sonda del capitolo sta PRIMA di tutto: è il punto in cui deve
        # atterrare chi arriva dall'itinerario, e deve essere la testata —
        # non il primo paragrafo — la prima cosa che vede.
        _sonda(ancora_capitolo),
        "<div class='testata'>",
        "<div class='occhiello'>Guida turistica tascabile</div>",
        f"<h1>{_esc(titolo)}</h1>",
    ]
    sottotesto = " · ".join(x for x in (nome if nome != titolo else "", destination) if x)
    if sottotesto:
        parti.append(f"<div class='dove'>{_esc(sottotesto)}</div>")
    parti.append("</div>")

    # La foto sta subito sotto la testata: è la risposta immediata a «meno
    # testo più immagini, non deve essere noioso». Prima del testo, non
    # dopo — una foto in fondo alla pagina l'ha già persa chi si è annoiato.
    if isinstance(photo, dict) and photo.get("png") and photo.get("credito"):
        byte_foto = photo["png"]
        b64 = base64.b64encode(byte_foto).decode("ascii")
        tipo = foto.mime_immagine(byte_foto)
        parti.append(
            f"<div class='foto'><img src='data:{tipo};base64,{b64}' "
            f"alt='{_esc(nome or titolo)}'>"
            f"<div class='credito'>{_esc(photo['credito'])}</div></div>"
        )

    storia = guide.get("history_summary") or ""
    if storia:
        parti.append(f"<div class='corpo'>{_paragraphs(storia, 'corpo')}</div>")

    parti.append(_righe_nominate(guide.get("highlights"), "Cosa cercare, una volta dentro"))

    curiosita = [str(c).strip() for c in (guide.get("curiosita") or []) if str(c).strip()]
    if curiosita:
        parti.append("<div class='sottotitolo'>Da sapere</div><ul>")
        parti.extend(f"<li>{_esc(c)}</li>" for c in curiosita)
        parti.append("</ul>")

    consigli = [str(t).strip() for t in (guide.get("practical_tips") or []) if str(t).strip()]
    if consigli:
        parti.append("<div class='riquadro'><strong>Consigli pratici</strong><ul>")
        parti.extend(f"<li>{_esc(t)}</li>" for t in consigli)
        parti.append("</ul></div>")

    errore = str(guide.get("errore_da_evitare") or "").strip()
    if errore:
        parti.append(
            f"<div class='avviso'><strong>L'errore che fanno quasi tutti:</strong> "
            f"{_esc(errore)}</div>"
        )

    parti.append(_righe_nominate(guide.get("dintorni"), "A due passi da qui"))

    # --- Il blocco "micro": orari, biglietti, contatti, come arrivare ----
    # È la parte che Lorenzo ha elencato per nome («orari, biglietti, info,
    # guida turistica, come arrivare») e la ragione per cui il documento
    # principale può permettersi di diventare più scarno: qui c'è tutto
    # quello che serve DAVANTI al cancello, e solo a chi ci sta andando.
    righe = [
        # [AGGIUNTO 2026-08-03 — task #180] Gli orari stanno in cima e non in
        # fondo: e' l'unica riga di questa tabella che puo' far tornare
        # indietro il cliente davanti a un portone chiuso.
        _riga_pratica("Orari di apertura", _orari_settimana(open_hours)),
        _riga_pratica("Quando visitare", _esc(guide.get("best_time_to_visit") or "")),
        _riga_pratica("Durata della visita", _esc(guide.get("estimated_visit_duration") or "")),
        _riga_pratica("Indirizzo", _esc(card.get("address") or "")),
        _riga_pratica("Telefono", _esc(card.get("phone") or "")),
    ]
    for chiave, etichetta in (
        ("tickets_link", "Biglietti e orari"),
        ("info_link", "Scheda del luogo"),
        ("menu_link", "Menù e sito"),
    ):
        voce = card.get(chiave)
        if isinstance(voce, dict) and voce.get("url"):
            righe.append(_riga_pratica(etichetta, _link(voce["url"], voce.get("label") or etichetta)))
    if come_arrivare:
        righe.append(_riga_pratica("Come arrivare", come_arrivare))
    righe = [r for r in righe if r]
    if righe:
        parti.append("<div class='sottotitolo'>Informazioni pratiche</div>")
        parti.append("<table class='pratico'>" + "".join(righe) + "</table>")

    if guide.get("disclaimer"):
        parti.append(f"<div class='nota'>{_esc(guide['disclaimer'])}</div>")

    # --- I bottoni di ritorno --------------------------------------------
    # [RIFATTO 2026-08-05 — task #191] Prima ce n'era uno solo e portava
    # "all'itinerario", genericamente. Ora, in modalità fascicolo, ce n'è uno
    # per ogni punto da cui si arriva qui, e ognuno riporta esattamente lì.
    voci_ritorno = [
        v for v in (ritorni or [])
        if isinstance(v, dict) and v.get("ancora")
    ]
    if voci_ritorno:
        parti.append("<div class='sottotitolo'>Torna dove eri</div>")
        for voce in voci_ritorno:
            etichetta = str(voce.get("etichetta") or "Torna all'itinerario")
            parti.append(
                f"<div class='bottone-torna'>"
                f"<a href='#{_esc(str(voce['ancora']))}'>&#8617; {etichetta}</a>"
                f"</div>"
            )
        if len(voci_ritorno) > 1:
            parti.append(
                "<div class='nota'>Questo luogo compare pi&#249; volte nel "
                "tuo programma: ogni bottone ti riporta al punto preciso da "
                "cui sei arrivato.</div>"
            )
    elif _link(itinerary_url, "Torna all'itinerario"):
        parti.append(
            "<div class='bottone-torna'>"
            + _link(itinerary_url, "Torna all'itinerario")
            + "</div>"
        )
        parti.append(
            "<div class='nota'>Il collegamento riapre il tuo itinerario "
            "completo, al capitolo del programma giorno per giorno.</div>"
        )
    else:
        parti.append(
            "<div class='nota'>Questa guida fa parte del tuo itinerario: "
            "per il programma della giornata, gli orari e gli spostamenti "
            "torna al documento principale che hai ricevuto per email.</div>"
        )

    parti.append("</body></html>")

    # [AGGIUNTO 2026-08-03 - task #183] La stessa passata di impaginazione del
    # documento principale: anche qui un paragrafo non si spezza fra due
    # pagine. Le guide per attrazione sono quasi solo prosa, quindi e' il
    # documento in cui il difetto si vedeva di piu' - ed e' anche quello che
    # il cliente apre dal telefono, dove una pagina mezza vuota si nota
    # subito. La regola sta in un posto solo per tutti e due i documenti: se
    # cambia la soglia, cambia per entrambi.
    return _tieni_uniti_i_paragrafi("".join(parti))


def render_guide_pdf(html: str) -> bytes | None:
    """Da HTML a byte di PDF. `None` se la stampa non riesce, mai
    un'eccezione: una guida in meno è un peccato, un itinerario non
    consegnato è un rimborso."""
    if not isinstance(html, str) or not html.strip():
        return None
    percorso_html = percorso_pdf = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(html)
            percorso_html = tmp.name
        fd, percorso_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        esito = subprocess.run(
            ["wkhtmltopdf", "--quiet", "--enable-internal-links",
             percorso_html, percorso_pdf],
            capture_output=True, text=True, timeout=TIMEOUT_S,
        )
        if esito.returncode != 0:
            return None
        dati = Path(percorso_pdf).read_bytes()
        return dati or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        for p in (percorso_html, percorso_pdf):
            if p:
                Path(p).unlink(missing_ok=True)


def nome_file_guida(guide: dict, indice: int) -> str:
    """Il nome con cui la guida vive nella URL.

    Descrive il CONTENUTO e mai il cliente — è la stessa regola scritta in
    cima a `src/hosting.py`: nella URL non deve comparire niente che
    identifichi una persona. `guida-duomo-di-siena`, non `guida-lorenzo`.
    """
    grezzo = guide.get("poi_name") or guide.get("title") or ""
    pulito = _slug(grezzo) if grezzo else ""
    # `_slug()` può restituire vuoto (nome tutto di caratteri non latini) e
    # la lista bianca di hosting.py taglia a 64 caratteri: entrambi i casi
    # vanno chiusi qui, non scoperti da un `None` di `store()`.
    if not pulito:
        return f"guida-{indice + 1}"
    return f"guida-{pulito}"[:60]


def costruisci_capitoli(
    guides,
    ritorni_per_poi=None,
    *,
    destination: str = "",
    place_cards: dict | None = None,
    photos: dict | None = None,
    directions_by_poi: dict | None = None,
    open_hours_by_poi: dict | None = None,
) -> list[dict]:
    """Le guide come CAPITOLI da cucire, non come file da pubblicare.

    [AGGIUNTO 2026-08-05 — task #190. Richiesta di Lorenzo: «questi documenti
    seppur diversi stiano in un unico file, non so come farai ma trova il
    modo»]

    È la sorella di `publish_guides()` e fa quasi lo stesso lavoro, con una
    differenza che cambia tutto: invece di caricare il PDF su Render e
    tornare una URL, tiene i byte e li consegna a chi dovrà cucirli.

    Perché sono due funzioni e non una con un interruttore: quella pubblicata
    e quella cucita non hanno lo stesso contenuto. La versione ospitata è un
    documento pubblico raggiungibile da chiunque abbia la URL, e per questo
    non contiene niente del cliente; quella cucita vive dentro il file del
    cliente e può permettersi i bottoni «torna al Giorno 2, ore 09:30», che
    su un documento pubblico non avrebbero senso. Un interruttore dentro una
    funzione sola avrebbe fatto sembrare le due cose intercambiabili.

    Ritorna una lista di `{"poi_id", "ancora", "pdf"}` nell'ordine in cui i
    capitoli andranno cuciti. Le guide che non riescono a essere stampate
    non compaiono: per quelle il documento principale continua a stampare il
    capitolo interno di sempre. Non solleva mai.
    """
    elenco = [g for g in (guides or []) if isinstance(g, dict)]
    if not elenco:
        return []

    ritorni = ritorni_per_poi if isinstance(ritorni_per_poi, dict) else {}
    schede = place_cards if isinstance(place_cards, dict) else {}
    foto = photos if isinstance(photos, dict) else {}
    tragitti = directions_by_poi if isinstance(directions_by_poi, dict) else {}
    orari = open_hours_by_poi if isinstance(open_hours_by_poi, dict) else {}

    capitoli: list[dict] = []
    for guide in elenco[:MAX_GUIDE]:
        poi_id = guide.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        try:
            html = build_guide_html(
                guide,
                destination=destination,
                place_card=schede.get(poi_id),
                photo=foto.get(poi_id),
                come_arrivare=str(tragitti.get(poi_id) or ""),
                open_hours=orari.get(poi_id),
                ancora_capitolo=fascicolo.ancora_capitolo(poi_id),
                ritorni=ritorni.get(poi_id),
            )
            blob = render_guide_pdf(html)
        except Exception:
            blob = None
        if not blob:
            continue
        capitoli.append({
            "poi_id": poi_id,
            "ancora": fascicolo.ancora_capitolo(poi_id),
            "pdf": blob,
        })
    return capitoli


def publish_guides(
    guides,
    *,
    consegna: str,
    destination: str = "",
    place_cards: dict | None = None,
    photos: dict | None = None,
    itinerary_url: str | None = None,
    directions_by_poi: dict | None = None,
    open_hours_by_poi: dict | None = None,
) -> dict:
    """Pubblica una guida per attrazione e ritorna `{poi_id: url}`.

    Ritorna un dizionario VUOTO — non solleva, non stampa niente — quando
    l'ospitalità non è configurata. È il caso normale finché
    `PUBLIC_BASE_URL` non è impostata su Render, e in quel caso il prodotto
    resta esattamente quello di ieri: un unico PDF con le guide dentro.

    Le attrazioni che non riescono a essere pubblicate semplicemente non
    compaiono nel risultato, e per quelle il documento principale continua
    a stampare il capitolo interno. Non è una degradazione teorica: la
    stampa di una guida può fallire per un timeout, e il cliente non deve
    accorgersene.
    """
    elenco = [g for g in (guides or []) if isinstance(g, dict)]
    if not elenco or not hosting.is_configured():
        return {}

    schede = place_cards if isinstance(place_cards, dict) else {}
    foto = photos if isinstance(photos, dict) else {}
    tragitti = directions_by_poi if isinstance(directions_by_poi, dict) else {}
    orari = open_hours_by_poi if isinstance(open_hours_by_poi, dict) else {}

    urls: dict = {}
    nomi_usati: set = set()
    for indice, guide in enumerate(elenco[:MAX_GUIDE]):
        poi_id = guide.get("poi_id")
        if not isinstance(poi_id, str) or not poi_id:
            continue
        nome = nome_file_guida(guide, indice)
        # Due attrazioni con lo stesso nome (succede: due chiese omonime)
        # si sovrascriverebbero a vicenda in silenzio, e il cliente
        # troverebbe la guida sbagliata dietro il link giusto.
        if nome in nomi_usati:
            nome = f"{nome}-{indice + 1}"[:60]
        nomi_usati.add(nome)

        html = build_guide_html(
            guide,
            destination=destination,
            place_card=schede.get(poi_id),
            photo=foto.get(poi_id),
            itinerary_url=itinerary_url,
            come_arrivare=str(tragitti.get(poi_id) or ""),
            open_hours=orari.get(poi_id),
        )
        blob = render_guide_pdf(html)
        if not blob:
            continue
        url = hosting.store(consegna, nome, blob)
        if url:
            urls[poi_id] = url
    return urls
