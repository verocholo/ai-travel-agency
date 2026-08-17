"""La fila di foto in fondo alla guida non spreca colonne (task #224).

PERCHE' QUESTO FILE ESISTE

Lorenzo, sul fascicolo di Bologna, pagine 15, 18, 21 e 26: «due foto piccole
e tutto lo spazio vuoto, non va bene» — ripetuto identico su quattro pagine.

Non erano le giornate dell'itinerario (quelle sono un altro capitolo, gia'
coperto da `tests/test_bianco_fine_giornata_2026_08_16.py`): erano le GUIDE
delle singole attrazioni, un capitolo PDF a se' per ognuna. In fondo a ogni
scheda c'e' una fila di fotografie di ALTRE tappe del viaggio
(`_altre_foto`), che esclude il luogo di cui la scheda gia' parla — e con un
itinerario piccolo (5-6 luoghi illustrati in tutto, come il weekend di
Bologna) restano quasi sempre due candidati, mai tre.

`_banda_di_foto()` pero' disegnava SEMPRE tre colonne, riempiendo quelle
senza una fotografia vera con una cella vuota: due fotografie finivano
strette a un terzo di pagina ciascuna, come se fossero tre, con un terzo
della riga sprecato e niente che riempisse lo spazio sotto.

La riparazione: le colonne si dividono per le fotografie DAVVERO presenti.
Due fotografie diventano due colonne al 50%, quindi piu' alte a parita' di
ritaglio — la stessa idea gia' provata per la fila di chiusura giornata,
applicata qui alla fila delle guide.
"""

import unittest

from src import poi_pdf


def _scatto(nome: str, credito: bool = True) -> dict:
    return {
        "png": b"\xff\xd8finto-jpeg-" + nome.encode(),
        "credito": f"Foto: {nome} / Prova" if credito else "",
    }


class TestLeColonneSiDividonoPerQuelleDavveroPresenti(unittest.TestCase):

    def test_due_fotografie_diventano_due_colonne_non_tre(self):
        html = poi_pdf._banda_di_foto([_scatto("a"), _scatto("b")])
        self.assertEqual(html.count("<td"), 2,
                         "due fotografie non devono produrre una terza "
                         "cella vuota")
        self.assertIn("width:50%", html)
        self.assertNotIn("<td></td>", html,
                         "nessuna cella vuota: e' proprio quello che sprecava "
                         "spazio sulle pagine 15, 18, 21 e 26")

    def test_una_sola_fotografia_diventa_una_colonna_a_tutta_larghezza(self):
        html = poi_pdf._banda_di_foto([_scatto("a")])
        self.assertEqual(html.count("<td"), 1)
        self.assertIn("width:100%", html)

    def test_tre_fotografie_restano_tre_colonne_uguali(self):
        html = poi_pdf._banda_di_foto([_scatto("a"), _scatto("b"), _scatto("c")])
        self.assertEqual(html.count("<td"), 3)
        self.assertIn("width:33%", html)

    def test_oltre_tre_fotografie_si_ferma_a_tre(self):
        html = poi_pdf._banda_di_foto(
            [_scatto(c) for c in "abcde"])
        self.assertEqual(html.count("<img"), 3)

    def test_niente_fotografie_niente_fila(self):
        for scatti in (None, [], [{}], [{"png": None}]):
            with self.subTest(scatti=scatti):
                self.assertEqual(poi_pdf._banda_di_foto(scatti), "")

    def test_senza_credito_quella_fotografia_non_conta_per_le_colonne(self):
        # Tre candidate, una senza credito: restano due fotografie stampabili
        # e le colonne devono adattarsi a quelle, non contare la terza vuota.
        html = poi_pdf._banda_di_foto(
            [_scatto("a"), _scatto("senza", credito=False), _scatto("c")])
        self.assertEqual(html.count("<img"), 2)
        self.assertIn("width:50%", html)

    def test_il_foglio_di_stile_non_forza_piu_un_terzo_fisso(self):
        """[difetto gemello, trovato nello stesso giro] La larghezza scritta
        in linea da `_banda_di_foto()` non serve a niente se il foglio di
        stile impone `width: 33.33%` su ogni `td`: quella regola vince
        sempre sulla stessa proprieta' scritta in linea con specificita'
        piu' bassa... in realta' e' il contrario (l'inline vince), ma la
        regola nel foglio era comunque un doppione pericoloso e fuorviante
        da tenere in giro. Deve essere sparita."""
        css = poi_pdf._css()
        regola = css.split(".guida-banda td {", 1)[1].split("}", 1)[0]
        self.assertNotIn("33.33%", regola)
        self.assertNotIn("width", regola)


class TestLaBandaArrivaDAVVERONELLASCHEDA(unittest.TestCase):
    """La trappola gia' presa altre volte in questo progetto: una funzione
    corretta e mai collegata al documento vero."""

    def _guida(self, poi_id="B", nome="Le due Torri"):
        return {
            "poi_id": poi_id, "poi_name": nome, "title": nome,
            "history_summary": "Una storia breve.",
            "highlights": [{"name": "Vista", "why": "Bella."}],
        }

    def test_con_due_foto_extra_la_fila_finale_ha_due_colonne(self):
        # Cinque foto disponibili in tutto: due vanno in cima (compagne),
        # le restanti tre in fondo — ma qui ne passiamo solo due extra oltre
        # alla foto del luogo, per riprodurre esattamente il caso di
        # Bologna: un itinerario piccolo dove restano poche "altre tappe".
        html = poi_pdf.build_guide_html(
            self._guida(),
            photo=_scatto("torri"),
            foto_extra=[_scatto("piazza"), _scatto("erbe")],
        )
        # Le prime due (piazza, erbe) vanno in cima insieme alla foto del
        # luogo: tre foto, tre colonne uguali. Non ne resta nessuna per la
        # fila in fondo — è il caso peggiore, verificato altrove — quindi
        # qui uso tre foto extra per vedere davvero la fila finale.
        html = poi_pdf.build_guide_html(
            self._guida(),
            photo=_scatto("torri"),
            foto_extra=[_scatto("piazza"), _scatto("erbe"), _scatto("orsa"),
                        _scatto("giardini")],
        )
        fasce = html.split("<table class='guida-banda'>")
        self.assertGreaterEqual(len(fasce), 3, "mancano sia la fascia in "
                                "cima che quella in fondo")
        fascia_finale = fasce[-1]
        self.assertEqual(fascia_finale.count("<td"), 2)
        self.assertIn("width:50%", fascia_finale)


class TestIlCreditoRestaPiccoloOvunqueCompaia(unittest.TestCase):
    """[Lorenzo, pagina 13: «i crediti delle foto sono scritti troppo in
    grande».]

    La causa: `.foto .credito` valeva solo per la fotografia singola in
    testa alla scheda. La fascia di tre fotografie scrive lo stesso
    `<div class='credito'>` ma DENTRO una cella di tabella, fuori da
    `.foto`: il credito ereditava la dimensione del corpo del testo (13px)
    invece della sua (9.5px vecchi, 8px nuovi).
    """

    def test_la_regola_non_e_piu_ristretta_a_foto_singola(self):
        css = poi_pdf._css()
        self.assertNotIn(".foto .credito {", css,
                         "la regola deve valere ovunque compaia un "
                         "credito, non solo dentro .foto")
        self.assertIn(".credito {", css)

    def test_il_credito_della_fascia_a_tre_foto_non_eredita_dal_corpo(self):
        """Prova diretta sul difetto: tre fotografie nella testata (come
        pagina 13), e il credito NON deve avere la dimensione del corpo."""
        css = poi_pdf._css()
        regola = css.split(".credito {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size", regola)
        dimensione = regola.split("font-size:", 1)[1].split(";", 1)[0].strip()
        self.assertTrue(dimensione.endswith("px"))
        valore = float(dimensione[:-2])
        self.assertLess(valore, 10,
                        "il credito deve restare piccolo — sotto i 10px, "
                        "non ai tredici del corpo del testo")

    def test_il_credito_arriva_davvero_dentro_la_fascia_a_tre_foto(self):
        html = poi_pdf._banda_di_foto(
            [_scatto("a"), _scatto("b"), _scatto("c")])
        self.assertIn("class='credito'", html)


if __name__ == "__main__":
    unittest.main()
