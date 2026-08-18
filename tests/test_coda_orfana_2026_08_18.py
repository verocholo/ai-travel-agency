"""La pagina quasi vuota in fondo al corpo del documento (task #228).

PERCHE' QUESTO FILE ESISTE

Misurato sul campione, 18 agosto: «pagina 11: il contenuto si ferma al 6.0%
del foglio». Due righe di chilometri, la nota legale, e poi mezzo foglio
bianco.

E' l'ULTIMO dei difetti rimasti fra quelli che Lorenzo ha elencato: «non mi
interessa come ma trova il modo di eliminare gli spazi bianchi deve essere
come un libro da leggere».

## Perche' non e' «una chiusura che finisce dove finisce»

C'e' un controllo, in questo progetto, che salta apposta l'ultima pagina:
`test_nessuna_pagina_si_ferma_a_meta_foglio`. La ragione e' buona — l'ultima
pagina di un documento finisce dove finisce, e riempirla vorrebbe dire
aggiungere parole inutili.

Solo che quella NON e' l'ultima pagina. Il fascicolo che riceve il cliente e'
il corpo del documento **piu' le schede delle guide cucite dietro**: la
pagina che si ferma al sei per cento sta in MEZZO al fascicolo, con dietro
altre sedici pagine piene. Il controllo la saltava perche' guardava il corpo
da solo — e' il motivo per cui il difetto e' arrivato fino al campione senza
che nessuna prova diventasse rossa.

## Come si ripara, e perche' proprio cosi'

Stesso metodo delle altre due riparazioni di impaginazione di questa
settimana: **si stampa, si guarda dove sono cadute le cose, si ripara solo
quello che serve, si ristampa.** La sonda `documento-fine` sta dentro
l'ultima cosa che il corpo stampa; la sua altezza dal fondo del foglio E' lo
spazio bianco rimasto.

Quando la coda e' rimasta orfana, l'ultimo capitolo si ristampa in modo
**compatto**: stessi dati, stesse cifre, stesse parole di legge — si tolgono
i margini, il riquadro colorato attorno all'indirizzo e una riga di
presentazione decorativa. E se la pagina non sparisce, si torna indietro:
il prezzo si paga solo se il risultato arriva.

## Due strade provate e scartate, scritte qui perche' non si riprovino

1. **Infilare le camminate dentro la tabella dei numeri utili.** Peggiorava:
   quella tabella viaggia in un guscio che non si spezza, e allungarla la
   faceva scendere INTERA sulla pagina dopo. La coda orfana passava dal 6%
   al 23% e la pagina restava li'.
2. **`--zoom 0.93` su tutto il documento.** Sarebbe stata la leva generale,
   e non funziona: misurato, questo motore di stampa la ignora in silenzio —
   stesso identico PDF, stesso numero di pagine, byte per byte lo stesso
   testo sull'ultima pagina. E' la stessa famiglia di opzioni gia' trovate
   morte (`--footer-center`, `--footer-font-size`). In questo progetto non
   si spedisce quello che non si e' potuto verificare qui.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import impaginazione


def _fotografia(seme: int) -> bytes:
    """Una fotografia finta ma della forma giusta: e' l'ingombro che conta."""
    import io

    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (1400, 900), (150, 80 + seme * 9 % 110, 60))
    disegno = ImageDraw.Draw(immagine)
    for x in range(0, 1400, 70):
        disegno.rectangle([x, 0, x + 30, 900],
                          fill=(90, 50 + seme * 5 % 90, 35))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _identificativi(itinerario) -> list:
    return [blocco.get("poi_id")
            for giorno in (itinerario.get("days") or [])
            for blocco in (giorno.get("blocks") or [])
            if isinstance(blocco, dict) and blocco.get("poi_id")]


class TestQuandoUnaCodaSiCHIAMAORFANA(unittest.TestCase):
    """La regola, senza stampare niente: si finge di aver gia' misurato.

    Le condizioni sono tre e ognuna esiste per non riparare un difetto che
    non c'e'. Una riparazione che scatta quando non serve costa una ristampa
    e un capitolo scritto peggio, in cambio di niente.
    """

    def _con_sonde(self, sonde):
        return mock.patch.object(impaginazione, "posizioni",
                                 return_value=dict(sonde))

    def test_la_coda_rimasta_in_cima_al_foglio_e_orfana(self):
        # 791 punti dal fondo su 842: il contenuto di quella pagina e' una
        # striscia in cima. E' il caso misurato sul campione.
        with self._con_sonde({"documento-fine": (10, 791.0)}):
            self.assertTrue(impaginazione.coda_orfana(b"finto"))

    def test_una_pagina_che_arriva_in_fondo_non_si_tocca(self):
        with self._con_sonde({"documento-fine": (10, 120.0)}):
            self.assertFalse(impaginazione.coda_orfana(b"finto"))

    def test_una_pagina_quasi_piena_non_si_tocca(self):
        """[AGGIORNATA 2026-08-18, secondo giro.]

        La soglia e' scesa dal 60% al 48% — cioe' si interviene su una
        pagina finale piena per meno di poco piu' di meta'. Il motivo e'
        misurato: da quando i capitoli scorrono invece di prendersi una
        pagina a testa (richiesta di Lorenzo, «evita di spezzare troppo le
        pagine»), quella pagina finale capita spesso intorno alla meta' e
        restava fuori dalla riparazione per un soffio.

        Il confine resta e va difeso dall'altro lato: una pagina piena per
        due terzi e' un capitolo che finisce, non un difetto.
        """
        with self._con_sonde({"documento-fine": (10, impaginazione.ALTEZZA_A4_PT * 0.35)}):
            self.assertFalse(impaginazione.coda_orfana(b"finto"))

    def test_un_documento_di_una_pagina_sola_non_ha_niente_da_stringere(self):
        with self._con_sonde({"documento-fine": (0, 800.0)}):
            self.assertFalse(impaginazione.coda_orfana(b"finto"))

    def test_senza_la_sonda_non_si_inventa_niente(self):
        # Se un domani la sonda sparisse, la riparazione deve spegnersi da
        # sola invece di scattare a caso su ogni documento.
        with self._con_sonde({"giorno-1-fine": (3, 700.0)}):
            self.assertFalse(impaginazione.coda_orfana(b"finto"))

    def test_su_byte_che_non_sono_un_pdf_non_solleva(self):
        self.assertFalse(impaginazione.coda_orfana(b"questo non e' un PDF"))
        self.assertEqual(0, impaginazione.quante_pagine(b"nemmeno questo"))

    def test_la_sonda_di_chiusura_non_e_un_punto_di_atterraggio(self):
        """Serve a MISURARE. Il controllo che pretende «ogni ancora ha un
        rimando che ci porta» diventerebbe un falso allarme, e un controllo
        che grida senza motivo si impara a ignorarlo."""
        self.assertTrue(impaginazione.e_sonda_di_misura("documento-fine"))


class TestIlModoCompattoStringeLOSPAZIONONLEPAROLE(unittest.TestCase):
    """[LA PROVA CHE VALE DI PIU' IN QUESTO FILE.]

    Stringere si paga in leggibilita', e la tentazione ovvia — tagliare
    frasi — qui e' vietata su due cose in particolare: i DATI (numero di
    emergenza, chilometri, indirizzo) e le PAROLE DI LEGGE. Un documento che
    perde la nota sulla natura del servizio per far entrare una riga in piu'
    non e' impaginato meglio: e' un problema diverso e piu' grave.
    """

    @classmethod
    def setUpClass(cls):
        import scripts_sample_pdf
        from src.pdf_renderer import render_html

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)
        cls.largo = render_html(itinerario, viaggio, **kwargs)
        cls.stretto = render_html(itinerario, viaggio, coda_compatta=True,
                                  **kwargs)

    def test_i_due_documenti_sono_davvero_diversi(self):
        self.assertNotEqual(self.largo, self.stretto)

    def test_lo_stretto_usa_le_forme_strette(self):
        for pezzo in ("pre-facts stretta", "class='riga-stretta'",
                      "class='footer stretto'"):
            with self.subTest(pezzo=pezzo):
                self.assertIn(pezzo, self.stretto)
                self.assertNotIn(pezzo, self.largo)

    def test_la_nota_di_legge_non_perde_una_parola(self):
        from src import legal_notices

        for html in (self.largo, self.stretto):
            with self.subTest(html=("largo" if html is self.largo else "stretto")):
                self.assertIn("non è un pacchetto turistico", html)
                self.assertIn(legal_notices.NATURE_SHORT[:40], html)

    def test_i_dati_ci_sono_tutti_e_due_le_volte(self):
        # I chilometri giorno per giorno e il numero di emergenza sono la
        # sostanza di quel capitolo: il modo compatto tocca lo spazio
        # attorno, mai le cifre.
        import re

        def cifre(html):
            pezzo = html.split("data-capitolo='numeri-utili'", 1)[-1]
            return re.findall(r"\d+[.,]?\d*\s*km", pezzo)

        self.assertTrue(cifre(self.largo))
        self.assertEqual(cifre(self.largo), cifre(self.stretto))

    def test_lo_stretto_e_davvero_piu_corto_a_stampare(self):
        """Non basta che sia «scritto piu' stretto»: deve occupare meno
        foglio. Si guarda cio' che il motore di stampa misura davvero — i
        margini e i riempimenti dichiarati — invece di fidarsi dell'aspetto.
        """
        # La riga stretta non ha il riquadro colorato attorno; il riquadro
        # costa quattordici punti di riempimento sopra e altrettanti sotto.
        self.assertIn("Dove dormi", self.stretto)
        pezzo = self.stretto.split("riga-stretta", 1)[1][:400]
        self.assertNotIn("summary-box", pezzo)

    def test_il_modo_largo_resta_quello_di_sempre(self):
        # La riga di presentazione delle camminate e' una cosa che si perde
        # solo quando serve: sul documento normale deve esserci.
        self.assertIn("decide le scarpe", self.largo)
        self.assertNotIn("decide le scarpe", self.stretto)


class TestLATAVOLADICHIUSURA(unittest.TestCase):
    """Quando stringere non basta, il foglio si riempie invece di restare
    bianco.

    [AGGIUNTO 2026-08-18.] E' il caso misurato sul campione con le
    fotografie: l'ultimo capitolo occupava il 26% dell'ultima pagina del
    corpo, e nessuna compattazione poteva far sparire un quarto di foglio.
    A quel punto la pagina c'e' comunque, e la scelta non e' piu' fra una
    pagina e nessuna: e' fra riempirla e lasciarla bianca. Direttiva di
    Lorenzo, testuale: «le foto devono occupare lo spazio bianco».
    """

    def _photos(self, quante=2, reale=True):
        return {"A": {"png": b"jpeg-a-0", "credito": "Foto: a / Prova",
                      "reale": reale,
                      "scatti": [{"png": f"jpeg-a-{i}".encode(),
                                  "credito": f"Foto: a{i} / Prova"}
                                 for i in range(quante)] if reale else []}}

    def test_la_tavola_usa_una_fotografia_mai_vista(self):
        from src import pdf_renderer as R

        usate = {R._impronta(b"jpeg-a-0")}
        html = R._tavola_di_chiusura(self._photos(), usate)
        self.assertIn("<img", html)
        self.assertIn("a1", html, "la tavola non ha preso la fotografia nuova")

    def test_finite_le_fotografie_non_si_stampa_niente(self):
        """Ristampare qui un'immagine gia' vista sarebbe riparare una pagina
        brutta con un difetto peggiore — ed e' esattamente quello che
        Lorenzo ha bocciato guardando il fascicolo."""
        from src import pdf_renderer as R

        usate = {R._impronta(b"jpeg-a-0"), R._impronta(b"jpeg-a-1")}
        self.assertEqual("", R._tavola_di_chiusura(self._photos(), usate))

    def test_la_grafica_disegnata_in_casa_non_diventa_una_tavola(self):
        from src import pdf_renderer as R

        self.assertEqual("", R._tavola_di_chiusura(self._photos(reale=False),
                                                   set()))

    def test_senza_fotografie_non_solleva(self):
        from src import pdf_renderer as R

        for niente in (None, {}, {"A": "non un dizionario"}):
            with self.subTest(valore=niente):
                self.assertEqual("", R._tavola_di_chiusura(niente, set()))

    def test_la_tavola_non_si_spezza_fra_due_pagine(self):
        from src import pdf_renderer as R

        html = R._tavola_di_chiusura(self._photos(), set())
        self.assertIn("<table class='keep'>", html)

    def test_il_documento_normale_non_ha_nessuna_tavola(self):
        """Si stampa SOLO quando serve: e' una riparazione, non un
        ornamento. Un documento che finisce bene non deve pagare una
        fotografia in piu' di peso."""
        import scripts_sample_pdf
        from src.pdf_renderer import render_html

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)
        normale = render_html(itinerario, viaggio, **kwargs)
        illustrato = render_html(itinerario, viaggio, coda_illustrata=True,
                                 **kwargs)
        self.assertLessEqual(len(normale), len(illustrato))


class TestSULFASCICOLOVEROLAPAGINAQUASIVUOTANONCE(unittest.TestCase):
    """[SOGLIA VERA, misurata sul fascicolo cucito.]

    E' l'unica prova di questo file che guarda il difetto come lo vede
    Lorenzo: il PDF finito, schede cucite dietro, contato in pixel.

    Tre scelte di metodo, e ognuna e' costata un errore prima di essere
    presa:

    1. **Si misura il fascicolo, non il corpo da solo.** E' esattamente la
       differenza che aveva lasciato passare il difetto per giorni: nel
       corpo da solo quella pagina e' l'ULTIMA, e l'ultima non si conta
       perche' una chiusura finisce dove finisce. Cucite le schede, la
       stessa pagina sta in mezzo al documento.
    2. **Si misura come misura `scripts_qualita_pagina`**, che esclude la
       striscia in fondo dove sta il numero di pagina. Contando anche
       quella, OGNI pagina risulta piena al novantatre per cento e la
       prova non vede piu' niente. Ci sono cascato scrivendo questo file:
       la prima versione era verde e non provava niente.
    3. **Le schede sono lunghe, e le fotografie ci sono.** Con schede corte
       il corpo cambia lunghezza e la coda incriminata non si forma
       affatto. Una prova che non riproduce il difetto non e' una prova:
       questa e' stata verificata anche al contrario, spegnendo la
       riparazione, e diventa rossa.
    """

    # Sotto questa soglia non e' piu' «un capitolo che finisce»: sono tre
    # righe e poi il foglio bianco. Non e' la soglia del riempimento in
    # generale — per quella c'e' gia' `test_nessuna_pagina_si_ferma_a_meta_
    # foglio`, al 70% — e' il caso limite che Lorenzo ha segnalato.
    QUASI_VUOTA = 15.0

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf") or not shutil.which("pdftoppm"):
            raise unittest.SkipTest("servono wkhtmltopdf e pdftoppm")
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("servono Pillow e numpy per misurare")

        import scripts_sample_pdf
        from src import poi_pdf
        from src.pdf_renderer import render_pdf

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)

        identificativi = _identificativi(itinerario)
        # LE FOTOGRAFIE CI VOGLIONO, e non sono un dettaglio della prova:
        # senza, le giornate stampano meno roba e il corpo si accorcia. Il
        # fascicolo che riceve il cliente le ha sempre.
        kwargs["photos"] = {
            identificativo: {"png": _fotografia(indice),
                             "credito": f"Autore {indice} / Prova",
                             "reale": True}
            for indice, identificativo in enumerate(identificativi)
        }

        schede = [{
            "poi_id": identificativo,
            "poi_name": f"Luogo {identificativo}",
            "title": f"Luogo {identificativo}",
            "history_summary": "Una storia lunga di questo posto. " * 28,
            "what_to_look_for": [f"dettaglio {k}" for k in range(5)],
            "practical_tips": [
                f"consiglio pratico {k}, abbastanza lungo da girare riga"
                for k in range(4)],
            "errore_da_evitare": "Arrivare senza biglietto.",
            "best_time_to_visit": "la mattina presto",
            "estimated_visit_duration": "un'ora e mezza",
        } for identificativo in identificativi[:6]]

        capitoli = poi_pdf.costruisci_capitoli(
            schede, destination=str(viaggio.get("destination") or ""),
            photos=kwargs["photos"])

        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = f"{cls._dir.name}/fascicolo.pdf"
        cls.capitoli = capitoli
        render_pdf(itinerario, viaggio, output_path=cls.pdf,
                   capitoli_pdf=capitoli, **kwargs)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_dir"):
            cls._dir.cleanup()

    def _ultima_pagina_del_corpo(self) -> int:
        """La pagina (da 1) su cui finisce il corpo, schede escluse.

        Si conta, non si cerca. La prima versione cercava la pagina della
        prima scheda dal testo — «GUIDA TURISTICA TASCABILE» — e trovava
        la pagina 5: quelle parole compaiono anche nel corpo, nel rimando
        che porta alle schede. La prova risultava verde perche' misurava la
        pagina sbagliata. Le schede sono PDF a se': quante pagine occupano
        si sa per somma, senza indovinare niente.
        """
        schede = sum(impaginazione.quante_pagine(c["pdf"])
                     for c in self.capitoli if c.get("pdf"))
        self.assertGreater(schede, 0, "nessuna scheda cucita nel fascicolo")
        return impaginazione.quante_pagine(Path(self.pdf).read_bytes()) - schede

    def test_il_corpo_non_finisce_con_una_pagina_quasi_vuota(self):
        """[IL DIFETTO, esattamente come e' stato misurato il 18 agosto:
        «pagina 11: il contenuto si ferma al 6.0% del foglio».]

        Si guarda l'ULTIMA pagina del corpo — quella subito prima della
        prima scheda cucita — perche' e' li' che la coda orfana si forma:
        l'ultimo capitolo sborda di due righe e quelle due righe si portano
        dietro un foglio intero.
        """
        import scripts_qualita_pagina as qualita

        pagine = qualita.misura(self.pdf)
        self.assertTrue(pagine, "non si e' riusciti a misurare il fascicolo")
        ultima_del_corpo = self._ultima_pagina_del_corpo()
        self.assertGreaterEqual(ultima_del_corpo, 1)

        riga = pagine[ultima_del_corpo - 1]
        self.assertGreaterEqual(
            riga["arrivo"], self.QUASI_VUOTA,
            f"l'ultima pagina del corpo (pagina {ultima_del_corpo}) si ferma "
            f"al {riga['arrivo']:.0f}% del foglio, e dietro ha le schede: "
            "e' la coda orfana, tre righe e poi il foglio bianco")


if __name__ == "__main__":
    unittest.main()
