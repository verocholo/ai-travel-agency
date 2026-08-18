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

    def test_le_schede_condividono_i_fogli(self):
        """La prova che il difetto e' andato via: quattro schede corte
        NON possono occupare quattro pagine intere."""
        from src import impaginazione

        pagine = impaginazione.quante_pagine(self.capitoli[0]["pdf"])
        self.assertGreater(pagine, 0)
        self.assertLess(pagine, 4,
                        f"quattro schede corte occupano ancora {pagine} "
                        "pagine: stanno tornando una per foglio")

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
