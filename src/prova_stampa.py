"""Chiede al motore di stampa VERO che cosa fa dei rimandi interni (task #207).

PERCHE' QUESTO FILE ESISTE

Lorenzo, il 13 agosto 2026: «ho la necessita' che tu trovi un modo per avere
la certezza matematica».

Aveva ragione a pretenderla, ed era la terza volta che gli dicevo «adesso
dovrebbe funzionare» senza poterlo dimostrare.

## Perche' non si poteva dimostrare

I collegamenti interni del documento sono stati distrutti per una settimana da
una differenza che in sviluppo NON esiste: il binario di `wkhtmltopdf`. In
produzione e' la build con le patch (`wkhtmltox 0.12.6.1-3 bookworm`, vedi il
Dockerfile); in sviluppo e' quella normale. La prima prende sul serio
`--enable-internal-links`, cerca il bersaglio di ogni `href="#x"` nella pagina
che sta stampando, non lo trova — perche' `x` sta in un capitolo che verra'
cucito DOPO, in un altro file — e butta via il collegamento. La seconda quel
flag lo ignora e non tocca niente.

Risultato: in sviluppo ogni prova era verde, in produzione il documento usciva
con ZERO navigazione. Nessun controllo scritto in sviluppo poteva accorgersene,
perche' in sviluppo il difetto non esiste.

Nella sandbox il binario patchato non si puo' nemmeno installare: non c'e'
rete. Quindi la certezza da qui non si prende. **Si prende chiedendola a
produzione**, che quel binario ce l'ha.

## Che cosa fa questa prova

Ricostruisce esattamente la condizione che rompeva tutto — un rimando verso
un'ancora che al momento della stampa NON esiste ancora — e stampa una
paginetta con lo stesso identico comando del prodotto
(`pdf_renderer.COMANDO_STAMPA`, definito in un posto solo apposta).

Nella paginetta ci sono TRE rimandi, e servono tutti e tre:

- **nuovo** — la forma di oggi, `https://ancora-interna.invalid/vai/<ancora>`.
  Deve sopravvivere: e' l'ipotesi che stiamo verificando.
- **vecchio** — la forma di ieri, `#<ancora>`. In produzione deve MORIRE. Se
  sopravvivesse, vorrebbe dire che la diagnosi di questa settimana e'
  sbagliata da capo, e lo sapremmo prima di spendere un altro Replay.
- **esterno** — un indirizzo qualunque verso un sito. Deve sopravvivere
  sempre, ovunque. E' il controllo del controllo: se muore anche lui, non e'
  il motore di stampa che si comporta male, e' questa misura che non
  funziona — e senza di lui leggeremmo «tutto morto» come una risposta invece
  che come un guasto dello strumento.

Poi guarda il PDF **prima** della riparazione e, per ognuno dei tre, risponde
a due domande: l'annotazione c'e'? e ha un rettangolo con area vera, o e' uno
di quei gusci `[0 0 0 0]` che abbiamo contato a 26 sul documento venduto?

## Quanto costa

Niente. Nessuna chiamata a Claude, nessun credito Make, nessuna immagine,
nessuna rete: due paginette bianche e una lettura di byte. Un paio di secondi.

## Perche' resta qui per sempre e non e' un usa-e-getta

Il giorno in cui Render ricostruira' l'immagine e `apt` tirera' giu' un
binario diverso — cosa che puo' succedere senza che nessuno cambi una riga —
questa pagina lo dira' in due secondi, invece di farlo scoprire a un cliente
che clicca e non vede succedere niente.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src import pdf_links

# L'ancora bersaglio. Il nome dice il perche': al momento in cui la paginetta
# viene stampata, questo bersaglio NON e' in quella pagina — sta nel capitolo,
# che verra' cucito dopo. E' la condizione precisa che faceva buttare via i
# collegamenti al documento venduto; una prova con il bersaglio nella stessa
# pagina sarebbe verde sempre e non direbbe niente.
ANCORA = "bersaglio-in-un-altro-file"

# Un indirizzo esterno riconoscibile e che non esiste: `.invalid` e' riservato
# dallo standard, quindi nessuno lo puo' comprare e nessuna richiesta parte
# davvero verso qualcuno.
ESTERNO = "https://sito-di-prova.invalid/pagina.html"

_STILE = (
    "<style>"
    "body { font-family: sans-serif; font-size: 14pt; }"
    "a { color: #16212f; }"
    "</style>"
)


def _pagina(corpo: str) -> str:
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'>{_STILE}</head><body>{corpo}</body></html>"


def _html_principale() -> str:
    """La pagina che PARTE: tre rimandi, nessun bersaglio."""
    return _pagina(
        "<h1>Prova dei collegamenti</h1>"
        f"<p><a href='{pdf_links.href_interno(ANCORA)}'>rimando nuovo</a></p>"
        f"<p><a href='#{ANCORA}'>rimando vecchio</a></p>"
        f"<p><a href='{ESTERNO}'>rimando esterno</a></p>"
    )


def _html_capitolo() -> str:
    """La pagina che ARRIVA: qui vive il bersaglio, con la sua sonda."""
    return _pagina(
        f"<h1 id='{ANCORA}'>Il bersaglio</h1>"
        f"<p><a href='{pdf_links.PROBE_PREFIX}{ANCORA}'>&#160;</a></p>"
        "<p>Se il rimando funziona, si atterra qui.</p>"
    )


def _stampa(html: str, percorso: Path) -> None:
    from src import pdf_renderer

    sorgente = percorso.with_suffix(".html")
    sorgente.write_text(html, encoding="utf-8")
    esito = subprocess.run(
        [*pdf_renderer.COMANDO_STAMPA, str(sorgente), str(percorso)],
        capture_output=True, text=True, timeout=60,
    )
    if esito.returncode != 0 or not percorso.exists():
        raise RuntimeError(
            f"wkhtmltopdf ha fallito (codice {esito.returncode}): "
            f"{(esito.stderr or '').strip()[:300] or 'nessun dettaglio'}")


def _annotazioni(dati: bytes) -> list[tuple[str, tuple]]:
    """Ogni collegamento del PDF: indirizzo e rettangolo.

    Usa le funzioni interne di `pdf_links` di proposito: sono le stesse che
    leggono il documento venduto. Rileggere i byte con un lettore diverso
    vorrebbe dire misurare una cosa leggermente diversa da quella che poi
    viene riparata, e la differenza si scoprirebbe nel momento peggiore.
    """
    pdf = pdf_links._Pdf(dati)
    fuori = []
    for num in pdf.objects:
        corpo = pdf.body(num)
        if b"/Subtype /Link" not in corpo and b"/Subtype/Link" not in corpo:
            continue
        fuori.append((pdf_links._uri_di(corpo), pdf_links._rect(corpo)))
    return fuori


def _verdetto_su(indirizzo: str, annotazioni) -> dict:
    """C'e'? ed e' un collegamento vero o un guscio vuoto?

    La distinzione non e' pignoleria: sul documento venduto le 26 annotazioni
    dei rimandi interni C'ERANO. Erano larghe zero e non contenevano nessuna
    azione. Un controllo che si fosse limitato a contarle le avrebbe trovate
    tutte e avrebbe detto che andava tutto bene.
    """
    trovate = [r for (u, r) in annotazioni if u == indirizzo]
    con_area = [
        r for r in trovate
        if r and (r[2] - r[0]) > 1 and (r[3] - r[1]) > 1
    ]
    return {
        "indirizzo": indirizzo,
        "annotazioni": len(trovate),
        "cliccabili": len(con_area),
        "sopravvive": bool(con_area),
    }


def prova_collegamenti() -> dict:
    """La misura, sul motore di stampa di QUESTA macchina."""
    if shutil.which("wkhtmltopdf") is None:
        return {"errore": "wkhtmltopdf non e' installato su questa macchina"}

    cartella = Path(tempfile.mkdtemp(prefix="prova-collegamenti-"))
    try:
        principale = cartella / "principale.pdf"
        capitolo = cartella / "capitolo.pdf"
        _stampa(_html_principale(), principale)
        _stampa(_html_capitolo(), capitolo)

        annotazioni = _annotazioni(principale.read_bytes())
        nuovo = _verdetto_su(pdf_links.href_interno(ANCORA), annotazioni)
        esterno = _verdetto_su(ESTERNO, annotazioni)
        # La forma vecchia il motore la riscrive: con le patch la fa sparire,
        # senza patch la trasforma in `file:///tmp/....html#ancora`. Non si
        # puo' cercare per indirizzo esatto, si cerca per quello che ne resta.
        vecchie = [
            (u, r) for (u, r) in annotazioni
            if u and u.startswith("file:") and ANCORA in u
        ]
        vecchio = {
            "indirizzo": f"#{ANCORA}",
            "annotazioni": len(vecchie),
            "cliccabili": sum(
                1 for (_, r) in vecchie
                if r and (r[2] - r[0]) > 1 and (r[3] - r[1]) > 1),
        }
        vecchio["sopravvive"] = vecchio["cliccabili"] > 0

        # E adesso il giro completo, come sul documento vero: si cuce e si
        # ripara. `goto` sono i salti veri dentro al file.
        from src import fascicolo

        # `cuci` torna DUE cose: il file e il resoconto. Scordarsi la coppia
        # qui darebbe un errore in una rotta di diagnostica — cioe' proprio
        # nel punto in cui si va a guardare quando qualcosa non va.
        unito, _resoconto = fascicolo.cuci(
            principale.read_bytes(), [capitolo.read_bytes()], ancore=[ANCORA])
        letto = pdf_links.analyse(unito)

        return {
            "motore": _versione_del_motore(),
            "rimando_nuovo": nuovo,
            "rimando_vecchio": vecchio,
            "rimando_esterno": esterno,
            "dopo_la_riparazione": {
                "salti_veri": letto.get("goto"),
                "rimasti_rotti": len(letto.get("rotti") or {}),
                "sentinella_rimasto_nel_file": unito.count(b"ancora-interna"),
            },
            "verdetto": _verdetto(nuovo, vecchio, esterno, letto, unito),
        }
    except Exception as errore:  # nessuna diagnosi vale un servizio caduto
        return {"errore": f"{type(errore).__name__}: {errore}"}
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def _versione_del_motore() -> str:
    try:
        esito = subprocess.run(["wkhtmltopdf", "--version"],
                               capture_output=True, text=True, timeout=20)
        return (esito.stdout or esito.stderr or "").strip()[:120]
    except Exception:
        return "sconosciuta"


def _verdetto(nuovo, vecchio, esterno, letto, unito) -> str:
    """La riga che si legge davvero, in italiano, senza numeri da tradurre."""
    if not esterno["sopravvive"]:
        return ("MISURA NON VALIDA: su questa macchina non sopravvive nemmeno "
                "un normale collegamento a un sito. Non e' il prodotto a non "
                "funzionare, e' questa prova: non fidarti degli altri numeri")
    if not nuovo["sopravvive"]:
        return ("NO: il motore di stampa di questa macchina cancella anche la "
                "forma nuova dei rimandi interni. La riparazione del 13 agosto "
                "NON basta, e un Replay uscirebbe di nuovo senza navigazione")
    if letto.get("goto", 0) < 1:
        return ("A META': il rimando sopravvive alla stampa ma non diventa un "
                "salto vero. Il guasto e' nella riparazione, non nel motore")
    if unito.count(b"ancora-interna") > 0:
        return ("QUASI: i salti ci sono, ma nel file resta un indirizzo "
                "sentinella non riparato — cliccandolo il cliente vedrebbe "
                "partire il browser verso un sito che non esiste")
    coda = (" — e conferma la diagnosi: la forma vecchia, sulla stessa pagina, "
            "viene cancellata" if not vecchio["sopravvive"] else
            " — nota: qui sopravvive anche la forma vecchia, quindi questa "
            "macchina NON riproduce il guasto di produzione")
    return ("SI: il rimando interno sopravvive alla stampa e diventa un salto "
            "vero dentro al documento" + coda)


def prova_abilitata() -> bool:
    """Interruttore, spento solo se qualcuno lo spegne di proposito.

    Non e' una rotta che costa o che espone qualcosa (stampa due pagine
    bianche fatte in casa e non legge nessun dato di nessuno), ma un modo di
    chiuderla senza rifare un deploy deve esistere comunque.
    """
    return (os.getenv("PROVA_STAMPA_SPENTA") or "").strip().lower() not in (
        "1", "si", "sì", "true", "yes")
