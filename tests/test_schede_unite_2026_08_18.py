"""Le schede di guida condividono le pagine (task #229).

PERCHE' QUESTO FILE ESISTE

Misurato il 18 agosto sul fascicolo con nove schede cucite: **dieci pagine su
ventisette piene fra l'8% e il 26%**.

    pagina  9: 25.9%   pagina 19: 10.5%
    pagina 11: 24.2%   pagina 21:  8.4%
    pagina 13: 11.8%   pagina 23: 10.4%
    pagina 15: 24.2%   pagina 25: 10.4%
    pagina 17: 19.4%   pagina 27: 10.4%

Ogni scheda occupava una pagina piena e una quasi vuota, e non era una
scelta di impaginazione sbagliata: era l'impianto. Ogni scheda era un PDF a
se', cucito dietro l'altro, e **due PDF diversi non possono condividere un
foglio**. Con schede lunghe circa una pagina e un quarto, il quarto avanzava
sempre.

E' la stessa famiglia dei difetti che Lorenzo aveva segnalato sul fascicolo
di Bologna («due foto piccole e tutto lo spazio vuoto», pagine 13/15/17…) e
delle sue due direttive: «non possono esserci pagine solo con foto e poi
tutto bianco» e «deve essere come un libro da leggere».

La strada l'ha scelta lui, fra tre: cucire piu' schede in un documento solo,
cosi' che possano condividere le pagine. E' la piu' invasiva ed e' l'unica
che toglie il difetto alla radice.

## Cosa difendono i controlli qui sotto

1. che le schede finiscano **davvero** in un documento solo, e non una per
   documento come prima;
2. che nessuna scheda perda la sua ancora — i bottoni «Apri la guida» del
   documento principale ci atterrano sopra;
3. che si sappia **su quale pagina** e' atterrata ognuna: senza, i bottoni
   porterebbero tutti all'inizio del blocco;
4. che il risultato costi meno pagine, misurato sul fascicolo vero, con la
   stessa lente con cui e' stato misurato il difetto.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from src import fascicolo, poi_pdf


def _guida(identificativo, righe=18):
    return {
        "poi_id": identificativo,
        "poi_name": f"Luogo {identificativo}",
        "title": f"Luogo {identificativo}",
        "history_summary": "Una storia di questo posto. " * righe,
        "what_to_look_for": [f"dettaglio {k}" for k in range(4)],
        "practical_tips": [f"consiglio {k}, lungo quanto basta per girare riga"
                           for k in range(3)],
        "errore_da_evitare": "Arrivare senza biglietto.",
        "best_time_to_visit": "la mattina presto",
        "estimated_visit_duration": "un'ora",
    }


class TestLUNIONEDELLESCHEDE(unittest.TestCase):
    """`unisci_le_schede()` senza stampare niente: e' cucitura di testo."""

    def _pezzi(self, quante=3):
        return [(f"capitolo-{i}",
                 f"<html><head><style>p{{}}</style></head><body>"
                 f"<div id='c{i}'>scheda {i}</div></body></html>")
                for i in range(quante)]

    def test_tutte_le_schede_finiscono_in_un_documento_solo(self):
        unito = poi_pdf.unisci_le_schede(self._pezzi(3))
        self.assertEqual(1, unito.count("</body>"))
        self.assertEqual(1, unito.count("</html>"))
        for i in range(3):
            with self.subTest(scheda=i):
                self.assertIn(f"scheda {i}", unito)

    def test_il_foglio_di_stile_della_prima_resta(self):
        # Le schede di un fascicolo condividono la tavolozza — la sceglie
        # `costruisci_capitoli` una volta sola — quindi un foglio di stile
        # basta. Se si perdesse, uscirebbero nove schede senza colori.
        self.assertIn("<style>", poi_pdf.unisci_le_schede(self._pezzi(2)))

    def test_la_prima_non_va_mai_a_capo(self):
        # Un salto pagina prima della prima scheda vorrebbe dire aprire il
        # blocco delle guide con un foglio bianco.
        unito = poi_pdf.unisci_le_schede(
            self._pezzi(3), a_capo=("capitolo-0", "capitolo-1"))
        prima_scheda = unito.index("scheda 0")
        self.assertNotIn("page-break-before", unito[:prima_scheda])

    def test_le_altre_vanno_a_capo_solo_se_richiesto(self):
        unito = poi_pdf.unisci_le_schede(self._pezzi(3), a_capo=("capitolo-2",))
        self.assertEqual(1, unito.count("page-break-before"))
        # ...e il salto sta PRIMA della scheda giusta.
        self.assertLess(unito.index("page-break-before"), unito.index("scheda 2"))

    def test_senza_schede_non_esce_un_documento_vuoto(self):
        self.assertEqual("", poi_pdf.unisci_le_schede([]))
        self.assertEqual("", poi_pdf.unisci_le_schede([("a", "")]))

    def test_un_guscio_di_forma_imprevista_non_perde_la_scheda(self):
        """Se un domani `build_guide_html` cambiasse forma, meglio una
        scheda con un guscio di troppo che una scheda tagliata via."""
        unito = poi_pdf.unisci_le_schede(
            [("a", "<html><body>prima</body></html>"),
             ("b", "niente body qui, solo testo")])
        self.assertIn("prima", unito)
        self.assertIn("niente body qui", unito)


class TestICAPITOLICUCITISONOUNODOCUMENTOSOLO(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")
        cls.capitoli = poi_pdf.costruisci_capitoli(
            [_guida(f"P{i}") for i in range(4)], destination="Siena")

    def test_ogni_scheda_ha_la_sua_voce_e_la_sua_ancora(self):
        self.assertEqual(4, len(self.capitoli))
        ancore = [c["ancora"] for c in self.capitoli]
        self.assertEqual(len(ancore), len(set(ancore)), f"ancore doppie: {ancore}")
        for capitolo in self.capitoli:
            with self.subTest(poi=capitolo["poi_id"]):
                self.assertTrue(capitolo["ancora"])

    def test_i_byte_stanno_su_una_voce_sola(self):
        """E' il cuore della modifica: un documento, non quattro. Se un
        domani tornassero quattro, tornerebbero anche le pagine mezze
        vuote fra l'una e l'altra."""
        con_byte = [c for c in self.capitoli if c.get("pdf")]
        self.assertEqual(1, len(con_byte))
        self.assertIs(con_byte[0], self.capitoli[0])

    def test_si_sa_su_quale_pagina_e_atterrata_ognuna(self):
        pagine = [c["pagina"] for c in self.capitoli]
        self.assertEqual(sorted(pagine), pagine,
                         f"le schede non atterrano nell'ordine in cui stanno "
                         f"nel documento: {pagine}")
        self.assertEqual(0, pagine[0], "la prima scheda apre il blocco")
        self.assertGreater(pagine[-1], 0,
                           "tutte le ancore risultano sulla prima pagina: le "
                           "sonde non si stanno leggendo, e i bottoni «Apri "
                           "la guida» porterebbero tutti allo stesso punto")

    def test_ogni_scheda_comincia_su_una_facciata_sua(self):
        """[ROVESCIATA 2026-08-18, settimo giro, e va detto perche'.]

        Fino a stamattina questa prova pretendeva l'OPPOSTO: che le schede
        condividessero i fogli, perche' quattro schede corte su quattro
        pagine intere erano il difetto («dieci pagine su ventisette piene
        fra l'8% e il 26%») che l'unione dei capitoli era nata per togliere.

        Poi Lorenzo, in maiuscolo: «NON VOGLIO CHE SPEZZI A META' LE PAGINE
        DELLE GUIDE TURISTICHE. NON FARLO». Una facciata con la coda di una
        scheda e la testa di un'altra e' esattamente cio' che lui chiama
        pagina spezzata a meta', e la sua decisione batte la mia misura.

        Il difetto di partenza non e' pero' tornato, e la riparazione non e'
        piu' l'accorpamento ma il RIENTRO: le schede si stringono per stare
        in una facciata (vedi `RITAGLI_DI_RIENTRO`), invece di accodarsi
        l'una all'altra. Misurato sul campione vero: nove schede in nove
        facciate, tutte piene sopra il 92% — meglio delle dodici facciate
        che costava l'accorpamento.

        Qui si controlla la proprieta' nuova: nessuna facciata contiene
        l'inizio di due schede diverse.
        """
        from src import impaginazione

        blob = self.capitoli[0]["pdf"]
        dove = impaginazione.posizioni(blob)
        pagine_di_partenza = [dove[c["ancora"]][0] for c in self.capitoli
                              if c["ancora"] in dove]
        self.assertTrue(pagine_di_partenza, "nessuna ancora misurabile")
        self.assertEqual(len(pagine_di_partenza), len(set(pagine_di_partenza)),
                         "due schede cominciano sulla stessa facciata: "
                         f"pagine di partenza {pagine_di_partenza}")

    def test_senza_schede_non_si_cuce_niente(self):
        self.assertEqual([], poi_pdf.costruisci_capitoli([]))
        self.assertEqual([], poi_pdf.costruisci_capitoli(None))


class TestLEPAGINEDIPARTENZACAPISCONOILDOCUMENTOUNICO(unittest.TestCase):
    """`fascicolo.pagine_di_partenza()` sapeva contare un capitolo per PDF.
    Con un PDF che contiene tutte le schede, ogni ancora sta dove sta."""

    def _pdf_di(self, pagine: int) -> bytes:
        if not shutil.which("wkhtmltopdf"):
            self.skipTest("serve wkhtmltopdf")
        salti = "".join("<div style='page-break-before: always'>x</div>"
                        for _ in range(pagine - 1))
        return poi_pdf.render_guide_pdf(f"<html><body>x{salti}</body></html>")

    def test_un_pezzo_con_piu_ancore_le_colloca_una_per_una(self):
        principale = self._pdf_di(3)
        pezzo = self._pdf_di(4)
        mappa = fascicolo.pagine_di_partenza(
            principale, [pezzo], [{"capitolo-a": 0, "capitolo-b": 2}])
        self.assertEqual({"capitolo-a": 3, "capitolo-b": 5}, mappa)

    def test_la_forma_vecchia_continua_a_funzionare(self):
        # Un nome per pezzo: e' come si contava prima, e non deve smettere
        # di funzionare — le guide pubblicate restano un documento a testa.
        principale = self._pdf_di(2)
        mappa = fascicolo.pagine_di_partenza(
            principale, [self._pdf_di(1), self._pdf_di(1)], ["uno", "due"])
        self.assertEqual({"uno": 2, "due": 3}, mappa)

    def test_uno_scostamento_illeggibile_non_fa_saltare_il_fascicolo(self):
        principale = self._pdf_di(1)
        mappa = fascicolo.pagine_di_partenza(
            principale, [self._pdf_di(2)], [{"capitolo-a": "non un numero"}])
        self.assertEqual({"capitolo-a": 1}, mappa)


class TestSULFASCICOLOVEROSISONORISPARMIATEPAGINE(unittest.TestCase):
    """[SOGLIA VERA, la stessa lente con cui il difetto e' stato misurato.]

    Non «e' piu' bello»: e' meno carta, contata sul PDF finito.
    """

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
        from src.pdf_renderer import render_pdf

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)

        cls.capitoli = poi_pdf.costruisci_capitoli(
            list(scripts_sample_pdf.GUIDES or []),
            destination=str(viaggio.get("destination") or ""),
            photos=kwargs.get("photos"))

        cls._dir = tempfile.TemporaryDirectory()
        cls.pdf = f"{cls._dir.name}/fascicolo.pdf"
        render_pdf(itinerario, viaggio, output_path=cls.pdf,
                   capitoli_pdf=cls.capitoli, **kwargs)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_dir"):
            cls._dir.cleanup()

    # Prima della modifica: nove schede, diciotto pagine (una piena e una
    # quasi vuota a testa). Il tetto e' messo un po' sopra il misurato per
    # non diventare rosso a ogni virgola di testo in piu'.
    PAGINE_MASSIME_DELLE_SCHEDE = 14

    def test_le_schede_costano_meno_pagine_di_una_a_testa(self):
        from src import impaginazione

        quante = impaginazione.quante_pagine(self.capitoli[0]["pdf"])
        self.assertLessEqual(
            quante, self.PAGINE_MASSIME_DELLE_SCHEDE,
            f"{len(self.capitoli)} schede occupano {quante} pagine: stanno "
            "tornando a prendersi un foglio a testa")

    def test_nessuna_pagina_di_scheda_resta_quasi_vuota(self):
        """[IL DIFETTO, com'era: 8.4%, 10.4%, 10.5%, 11.8%…]

        Si guarda solo il blocco delle schede — il corpo ha i suoi
        controlli — e si salta l'ultima pagina del fascicolo, che e' la
        chiusura e finisce dove finisce.
        """
        import scripts_qualita_pagina as qualita
        from src import impaginazione

        pagine = qualita.misura(self.pdf)
        self.assertTrue(pagine, "non si e' riusciti a misurare il fascicolo")
        quante_schede = impaginazione.quante_pagine(self.capitoli[0]["pdf"])
        blocco = pagine[-quante_schede:-1]
        self.assertTrue(blocco, "il blocco delle schede non si individua")

        magre = [f"pagina {r['pagina']}: {r['arrivo']:.0f}%"
                 for r in blocco if r["arrivo"] < 40]
        self.assertEqual(
            [], magre,
            "pagine di scheda quasi vuote — e' il difetto delle dieci "
            "pagine all'8-26%: " + "; ".join(magre))


if __name__ == "__main__":
    unittest.main()


class TestLAFOTOGRAFIASISPOSTAQUANDONONCISTA(unittest.TestCase):
    """La pagina 16 dell'anteprima: mezzo foglio bianco sotto un titolo.

    Segnalazione di Lorenzo, 18 agosto: «non mi piace come e' impaginata
    pagina 16, sistemala togliendo lo spazio bianco».

    Il difetto: una scheda che comincia a meta' pagina stampa il titolo, e
    poi la sua fotografia — alta dodici centimetri fra figura e didascalia —
    non ci entra piu'. La fotografia scende alla pagina dopo e si porta
    dietro TUTTO il testo, lasciando mezzo foglio bianco sotto un titolo
    solo.

    La riparazione non e' mandare la scheda a capo — quello sposta il vuoto,
    non lo toglie — ma spostare la FOTOGRAFIA in fondo alla scheda: il testo
    comincia subito sotto il titolo e riempie il foglio. E' anche il posto in
    cui una rivista mette la figura quando apre un pezzo col testo.
    """

    def test_la_fotografia_normalmente_apre_la_scheda(self):
        html = poi_pdf.build_guide_html(
            _guida("A"), destination="Siena",
            photo={"png": b"\xff\xd8finta", "credito": "Foto: a / Prova"})
        prima_del_testo = html.split("Una storia di questo posto", 1)[0]
        self.assertIn("<img", prima_del_testo,
                      "la fotografia non apre piu' la scheda")

    def test_quando_serve_la_fotografia_va_in_fondo(self):
        html = poi_pdf.build_guide_html(
            _guida("A"), destination="Siena",
            photo={"png": b"\xff\xd8finta", "credito": "Foto: a / Prova"},
            foto_in_coda=True)
        prima_del_testo = html.split("Una storia di questo posto", 1)[0]
        self.assertNotIn("<img", prima_del_testo)
        self.assertIn("<img", html, "la fotografia e' sparita del tutto")

    def test_in_fondo_vuol_dire_dopo_il_corpo_non_dopo_la_storia(self):
        """[MISURATO, e la misura ha cambiato la riparazione.]

        Mettendola subito dopo la storia il difetto si dimezzava e basta:
        tre righe di testo e poi ancora un terzo di foglio bianco, perche'
        la fotografia bloccava comunque il corpo della scheda. In fondo, il
        corpo riempie la pagina.
        """
        html = poi_pdf.build_guide_html(
            {**_guida("A"), "highlights": [{"nome": "Una cosa",
                                            "testo": "da guardare"}]},
            destination="Siena",
            photo={"png": b"\xff\xd8finta", "credito": "Foto: a / Prova"},
            foto_in_coda=True)
        self.assertLess(html.rindex("guida-colonne"), html.rindex("<img"),
                        "la fotografia sta prima del corpo: il corpo finisce "
                        "sulla pagina dopo e il foglio resta mezzo vuoto")

    def test_la_misura_sceglie_solo_le_schede_che_cominciano_in_basso(self):
        from unittest import mock

        from src import impaginazione

        finte = {
            "capitolo-alta": (0, impaginazione.ALTEZZA_A4_PT * 0.80),
            "capitolo-bassa": (0, impaginazione.ALTEZZA_A4_PT * 0.50),
        }
        with mock.patch.object(impaginazione, "posizioni",
                               lambda _d: finte):
            scelte = impaginazione.capitoli_con_foto_in_coda(
                b"finto", ["capitolo-alta", "capitolo-bassa"])
        self.assertIn("capitolo-bassa", scelte)
        self.assertNotIn("capitolo-alta", scelte)

    def test_una_scheda_gia_mandata_a_capo_non_sposta_niente(self):
        """Per quelle il problema e' un altro e la riparazione pure:
        cominciano su una pagina nuova, dove di posto ce n'e' tutto."""
        from unittest import mock

        from src import impaginazione

        # Due schede: la prima e' la piu' in alto (non si manda mai a capo),
        # la seconda cade a due dita dal fondo.
        finte = {
            "capitolo-uno": (0, impaginazione.ALTEZZA_A4_PT * 0.90),
            "capitolo-due": (0, impaginazione.ALTEZZA_A4_PT * 0.10),
        }
        with mock.patch.object(impaginazione, "posizioni", lambda _d: finte):
            a_capo = impaginazione.capitoli_da_mandare_a_capo(
                b"finto", ["capitolo-uno", "capitolo-due"])
            in_coda = impaginazione.capitoli_con_foto_in_coda(
                b"finto", ["capitolo-uno", "capitolo-due"])
        self.assertIn("capitolo-due", a_capo)
        self.assertEqual(set(), a_capo & in_coda,
                         "la stessa scheda riceve due riparazioni diverse "
                         "per lo stesso difetto")

    def test_senza_sonde_non_si_sposta_niente(self):
        from src import impaginazione

        self.assertEqual(
            set(), impaginazione.capitoli_con_foto_in_coda(b"non un pdf", ["x"]))


class TestLARIPARAZIONESIRIPETEFINCHEISERVE(unittest.TestCase):
    """[Lorenzo, secondo giro: «non hai risolto il problema, lo hai
    semplicemente spostato in un'altra pagina».]

    Aveva ragione, ed era un difetto di metodo, non di regola: spostare la
    fotografia di una scheda cambia dove cadono TUTTE quelle dopo. Alla prima
    passata si ripara la scheda che si vedeva, e una che prima stava bene
    finisce a due terzi di pagina con la sua fotografia dietro — il vuoto
    riappare dieci pagine piu' in la'.

    Si misura, si ripara, si RIMISURA. Al massimo tre volte: un ciclo che
    insegue l'impaginazione perfetta non converge, e ogni passata e' una
    stampa.
    """

    def test_la_soglia_delle_schede_e_piu_bassa_di_quella_dei_capitoli(self):
        """E la differenza e' giustificata: nel documento principale sotto la
        testata c'e' subito un blocco che non si spezza (una tabella, una
        cartina), nelle schede c'e' prosa, che scorre."""
        from src import impaginazione

        self.assertLess(poi_pdf.QUOTA_A_CAPO_SCHEDE,
                        impaginazione.QUOTA_MINIMA_SOTTO)
        self.assertGreater(poi_pdf.QUOTA_A_CAPO_SCHEDE, 0.05)

    def test_la_storia_scorre_quando_la_scheda_comincia_in_basso(self):
        """Le due colonne sono una TABELLA, e una tabella non si spezza fra
        due pagine: su una scheda che comincia a due terzi del foglio non
        entra mai e si porta dietro tutto. Su una colonna sola i paragrafi
        scorrono."""
        guida = {**_guida("A"),
                 "history_summary": "Primo paragrafo.\n\nSecondo paragrafo.\n\nTerzo."}
        alta = poi_pdf.build_guide_html(guida, destination="Siena")
        bassa = poi_pdf.build_guide_html(guida, destination="Siena",
                                         foto_in_coda=True)
        # Si guarda SOLO dentro il riquadro della storia: sotto c'e' il
        # corpo della scheda, che sta su due colonne da sempre. Una finestra
        # piu' larga troverebbe quella tabella e direbbe di si' sempre.
        def _storia(html):
            dentro = html.split("<div class='corpo'>", 1)[1]
            return dentro.split("</div><table class='guida-colonne'", 1)[0]

        # [AGGIORNATA 2026-08-18, secondo giro.] La storia sta su una
        # colonna SEMPRE, non solo quando la scheda comincia in basso: e' la
        # scelta per chi legge da telefono. La proprieta' che questa prova
        # difende resta la stessa e vale ancora — il testo della storia deve
        # poter scorrere fra due pagine, cioe' non deve mai finire in una
        # tabella.
        for html in (alta, bassa):
            self.assertNotIn("guida-colonne", _storia(html),
                             "la storia e' in una tabella che non si spezza: "
                             "la scheda si porta dietro tutto e lascia il bianco")

    def test_il_ciclo_si_ferma_da_solo(self):
        """Un tetto di passate e una condizione di uscita.

        [AGGIORNATA 2026-08-18, settimo giro.] Il ciclo non insegue piu' le
        fotografie da spostare ma i RIENTRI da stringere: cambia cosa
        misura, non la regola che questa prova difende. Senza il tetto, una
        scheda che oscilla fra due posizioni farebbe stampare all'infinito;
        senza la condizione di uscita, si stamperebbe quattro volte anche
        quando alla prima e' gia' tutto a posto.
        """
        import inspect

        sorgente = inspect.getsource(poi_pdf.costruisci_capitoli)
        self.assertIn("for _passata in range(6)", sorgente)
        self.assertIn("if not cambiato:", sorgente,
                      "manca la condizione di uscita: il ciclo non sa "
                      "riconoscere di aver finito")
