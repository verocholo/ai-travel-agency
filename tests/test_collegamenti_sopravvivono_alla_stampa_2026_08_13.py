"""I rimandi interni escono dalla porta giusta e arrivano interi (task #206).

PERCHE' QUESTO FILE ESISTE

Per una settimana il documento venduto e' uscito senza NESSUNA navigazione
interna. Non un collegamento sbagliato: zero collegamenti. Il cliente che
cliccava sul pallino di una cartina, o sul rimando alla guida in fondo, non
vedeva succedere niente — e in un PDF questo non da' nessun errore, quindi il
cliente conclude che il documento e' rotto, non che manca una funzione.

## Cosa si e' misurato sul PDF vero, e cosa dice

    pagine: 28   sonde: 0   rotti: 0   esterni: 42   goto: 0

piu' 26 annotazioni con rettangolo `[0 0 0 0]` e nessuna azione dentro. Lo
STESSO codice, in sviluppo, ne produceva 65.

Il taglio e' netto e non lascia spazio a interpretazioni: **tutto cio' che
puntava fuori dal documento e' sopravvissuto, tutto cio' che puntava dentro e'
diventato un guscio vuoto.**

La spiegazione che regge quei numeri e' una sola. Il binario di produzione ha
le patch e `--enable-internal-links` funziona davvero: vede un `href="#x"`,
lo prende sul serio, cerca `x` nella pagina che sta stampando, non lo trova
(perche' `x` sta in un capitolo che verra' cucito DOPO, in un altro file) e
butta via il collegamento lasciando l'annotazione vuota. Il binario di
sviluppo, senza patch, quel flag lo ignora del tutto e non tocca niente: per
questo qui non si e' mai visto nulla, e per questo la diagnosi e' costata
giorni.

## La riparazione

Non chiedere piu' al motore di stampa di occuparsi dei rimandi interni. Un
rimando interno oggi si scrive come un indirizzo esterno qualunque —
`https://ancora-interna.invalid/vai/<ancora>` — che nessun motore, patchato o
no, ha motivo di reinterpretare. Poi, sul PDF gia' cucito, `src/pdf_links.py`
lo trasforma in un salto vero verso pagina e altezza giuste.

`.invalid` e' riservato dallo standard e non risolve MAI: se un giorno un
rimando sfuggisse alla riparazione, il cliente troverebbe un link morto invece
del sito di qualcun altro. E' il modo giusto di sbagliare.

## Che cosa difendono i controlli qui sotto

Il difetto vero non e' «i collegamenti non funzionano»: quello e' il sintomo.
Il difetto e' **scrivere un rimando interno in una forma che il motore di
stampa si sente in diritto di interpretare**. Quella forma comincia con `#`.
Quindi il controllo che serve non e' sul PDF — sul PDF locale il difetto non
si riproduce, e' proprio questo il punto — ma sull'HTML, ed e' strutturale:
nessun `href` stampato da questo progetto puo' cominciare con `#`.

E' una regola che si puo' verificare guardando, senza dipendere da quale .deb
ha vinto l'ultima `apt-get`.
"""

import re
import unittest

import scripts_sample_pdf
from src import fascicolo, pdf_links, pdf_renderer


def _documento_principale() -> str:
    """L'HTML del campione completo, montato una volta sola."""
    if not hasattr(_documento_principale, "_cache"):
        itinerary, trip, kwargs, errori = \
            scripts_sample_pdf.build_sample_render_kwargs()
        assert not errori, f"il campione monta con sezioni cadute: {errori}"
        _documento_principale._cache = pdf_renderer.render_html(
            itinerary, trip, **kwargs)
    return _documento_principale._cache


def _capitolo_staccato() -> str:
    """L'HTML di un capitolo del fascicolo, con il suo pulsante di ritorno.

    Va guardato a parte e non e' pignoleria: il capitolo ha un foglio di
    stile suo e un costruttore suo (`src/poi_pdf.py`), ed e' gia' successo
    una volta — il 13 agosto — che un controllo scritto solo sul documento
    principale passasse mentre i capitoli facevano l'esatto contrario.
    """
    from src import poi_pdf

    return poi_pdf.build_guide_html(
        {"poi_id": "POI1", "poi_name": "Duomo", "title": "Il Duomo",
         "history_summary": "Storia.", "practical_tips": ["Arriva presto."]},
        ancora_capitolo=fascicolo.ancora_capitolo("POI1"),
        ritorni=[{"ancora": fascicolo.ancora_ritorno("POI1", ("blocco", 2, 0)),
                  "etichetta": "Torna al Giorno 2"}],
    )


class TestNessunRimandoChiedeAiutoAlMotoreDiStampa(unittest.TestCase):
    """Il controllo che avrebbe risparmiato la settimana.

    Prima del 13 agosto sarebbe stato rosso su una quarantina di rimandi.
    """

    def test_il_documento_principale_non_scrive_nessun_href_col_cancelletto(self):
        colpevoli = re.findall(r"href='#[^']*'", _documento_principale())
        self.assertEqual(
            [], sorted(set(colpevoli)),
            "questi rimandi cominciano con '#': il motore di stampa patchato "
            "li prende in carico, cerca il bersaglio nella pagina che sta "
            "stampando, non lo trova e li cancella. E' esattamente cio' che "
            "ha azzerato la navigazione del documento venduto",
        )

    def test_nemmeno_i_capitoli_staccati_lo_fanno(self):
        colpevoli = re.findall(r"href='#[^']*'", _capitolo_staccato())
        self.assertEqual([], sorted(set(colpevoli)))

    def test_i_rimandi_ci_sono_davvero(self):
        """La rete sotto ai due controlli qui sopra.

        Un documento senza nessun rimando li supererebbe tutti e due a mani
        basse, ed e' proprio il documento che non vogliamo consegnare. Senza
        questa riga, cancellare la navigazione sarebbe il modo piu' rapido di
        far tornare verde la suite.
        """
        self.assertGreater(
            len(pdf_links.RIFERIMENTI_NELL_HTML.findall(_documento_principale())),
            10, "il documento ha perso i suoi rimandi interni")
        self.assertTrue(
            pdf_links.RIFERIMENTI_NELL_HTML.findall(_capitolo_staccato()),
            "il capitolo staccato non ha piu' il pulsante per tornare indietro")

    def test_ogni_rimando_ha_il_suo_bersaglio_nel_documento(self):
        html = _documento_principale()
        bersagli = set(re.findall(r"id='([^']+)' class='anchor-probe'", html))
        partenze = set(pdf_links.RIFERIMENTI_NELL_HTML.findall(html))
        self.assertEqual(
            set(), partenze - bersagli,
            f"rimandi senza bersaglio: {sorted(partenze - bersagli)}")


class TestLIndirizzoSentinellaNonArrivaMaiAlCliente(unittest.TestCase):
    """Il rischio che questa riparazione porta con se', e il suo freno.

    Prima, un rimando che sfuggiva alla riparazione restava un `#ancora`: al
    massimo non faceva niente. Adesso e' un indirizzo `https://` vero: se
    sfuggisse, il lettore PDF proverebbe ad APRIRLO. Il cliente vedrebbe il
    browser partire verso `ancora-interna.invalid` e concluderebbe che il
    documento lo sta mandando su un sito rotto — molto peggio di un click che
    non fa niente.

    Il dominio `.invalid` fa in modo che non si finisca mai sul sito di
    qualcun altro. Questo controllo fa in modo che non ci si finisca affatto.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path

        itin, trip, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs(
            con_fascicolo=True)
        percorso = Path(tempfile.mkdtemp(prefix="collegamenti-")) / "campione.pdf"
        pdf_renderer.render_pdf(itin, trip, output_path=str(percorso), **kwargs)
        cls.pdf = percorso.read_bytes()

    def test_nel_pdf_consegnato_non_resta_una_traccia_del_sentinella(self):
        self.assertEqual(
            0, self.pdf.count(b"ancora-interna"),
            "un rimando e' sfuggito alla riparazione: cliccandolo il cliente "
            "vedrebbe partire il browser verso un indirizzo che non esiste")

    def test_e_i_salti_ci_sono(self):
        # Il controllo qui sopra sarebbe verde anche su un documento in cui
        # la riparazione ha cancellato tutto invece di riscriverlo.
        letto = pdf_links.analyse(self.pdf)
        self.assertGreater(letto["goto"], 20, letto)
        # `rotti` e' un dizionario ancora → annotazioni, non un numero: qui
        # deve restare vuoto, cioe' nessun rimando e' rimasto senza il suo
        # salto. Scriverlo come `assertEqual(0, ...)` passa il confronto per
        # sbaglio con nessun dizionario e fallisce con tutti: l'ho gia' fatto
        # scrivendo questo file, ed e' il motivo per cui c'e' il commento.
        self.assertEqual({}, letto["rotti"], letto)


class TestLaFormaDellIndirizzoStaInUnPostoSolo(unittest.TestCase):
    """Questa forma e' gia' cambiata due volte in dieci giorni.

    `#ancora` → `ancora-interna:<nome>` → `https://ancora-interna.invalid/vai/`.
    Ogni cambio ha lasciato in giro decine di stringhe scritte a mano, fra
    codice e controlli, e l'ultimo giro e' costato mezza giornata solo per
    ritrovarle tutte. Da qui in poi si passa da `href_interno()` e da
    `RIFERIMENTI_NELL_HTML`, cosi' un eventuale terzo cambio si fa in due
    righe.
    """

    def test_chi_scrive_e_chi_cerca_usano_la_stessa_forma(self):
        indirizzo = pdf_links.href_interno("guida-poi1")
        self.assertEqual(["guida-poi1"],
                         pdf_links.RIFERIMENTI_NELL_HTML.findall(indirizzo))

    def test_il_riparatore_riconosce_cio_che_il_documento_scrive(self):
        # Il punto piu' fragile di tutta la catena: chi stampa e chi ripara
        # devono essere d'accordo sulla forma. Se si allontanassero, il
        # documento resterebbe pieno di link e la riparazione non ne
        # troverebbe nessuno — senza che niente protesti.
        self.assertEqual(
            "guida-poi1",
            pdf_links._anchor_of_uri(pdf_links.href_interno("guida-poi1")))

    def test_l_indirizzo_e_cifrato_e_su_un_dominio_che_non_esiste(self):
        # `http://` in chiaro dentro un documento venduto e' un difetto di
        # sicurezza; un dominio vero sarebbe peggio, perche' un giorno
        # qualcuno potrebbe comprarlo.
        self.assertTrue(pdf_links.HOST_INTERNO.startswith("https://"))
        self.assertIn(".invalid/", pdf_links.HOST_INTERNO)

    def test_le_sonde_e_i_rimandi_non_si_confondono_fra_loro(self):
        """Sono due cose diverse: una marca dove si atterra, l'altra ci porta.

        Se un prefisso fosse l'inizio dell'altro, il riparatore scambierebbe
        i bersagli per collegamenti e finirebbe per far puntare ogni ancora a
        se stessa: un documento pieno di link che non muovono la pagina.
        """
        self.assertFalse(pdf_links.LINK_PREFIX.startswith(pdf_links.PROBE_PREFIX))
        self.assertFalse(pdf_links.PROBE_PREFIX.startswith(pdf_links.LINK_PREFIX))


if __name__ == "__main__":
    unittest.main()
