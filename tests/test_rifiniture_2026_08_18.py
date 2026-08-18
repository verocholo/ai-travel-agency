"""Le rifiniture viste da cliente sul fascicolo di Bologna (task #231).

PERCHE' QUESTO FILE ESISTE

Lorenzo ha guardato il PDF vero come lo guarda chi paga, e ha chiesto di
riparare tutto quello che gli faceva storcere il naso. Tre di quelle cose
sono piccole, si riparano in poche righe, e sono esattamente quelle che si
notano nella prima passata col pollice.

  1. **la pagina bianca** — a pagina 18 una riga grigia in cima e poi un
     foglio vuoto. Era la nota «questo luogo compare piu' volte» rimasta
     staccata dai suoi bottoni;
  2. **il testo sopra il numero di pagina** — a pagina 3 l'ultima riga
     finiva addosso al numero;
  3. **«16 tappe in programma»** in copertina, quando le tappe vere erano
     una decina e il resto erano spazi liberi.

Nessuna delle tre e' grave. Tutte e tre dicono al cliente la stessa cosa —
«questo documento non e' stato guardato da nessuno» — ed e' quella la cosa
grave.
"""

import re
import unittest


class TestLABLOCCODEIRITORNINONSISPEZZA(unittest.TestCase):
    """La pagina 18: una riga sola su un foglio intero.

    Il titolino «Torna dove eri», i bottoni e la nota che li spiega sono UNA
    cosa sola. Stampati come pezzi separati, il motore di stampa e'
    liberissimo di lasciare i bottoni in fondo a una pagina e mandare la nota
    su quella dopo, dove resta da sola perche' dopo di lei non c'e' piu'
    niente.
    """

    def _scheda(self, quanti_ritorni):
        from src import poi_pdf

        ritorni = [{"ancora": f"ritorno-{i}", "etichetta": f"Torna al Giorno {i}"}
                   for i in range(1, quanti_ritorni + 1)]
        return poi_pdf.build_guide_html(
            {"poi_id": "A", "poi_name": "Due Torri", "title": "Le Due Torri",
             "history_summary": "Una storia. " * 20},
            destination="Bologna", ritorni=ritorni)

    def test_titolo_bottoni_e_nota_viaggiano_dentro_lo_stesso_guscio(self):
        html = self._scheda(2)
        self.assertIn("Torna dove eri", html)
        self.assertIn("compare pi", html)
        # Dal titolino alla nota non si attraversa mai una chiusura di
        # guscio: sono nello stesso `<table class='keep'>`.
        pezzo = html.split("Torna dove eri", 1)[1]
        pezzo = pezzo.split("compare pi", 1)[0]
        self.assertNotIn("</table>", pezzo,
                         "la nota e' fuori dal guscio dei bottoni: puo' "
                         "restare da sola su una pagina, ed e' la pagina 18 "
                         "del fascicolo di Bologna")

    def test_con_un_ritorno_solo_la_nota_non_si_stampa(self):
        # La nota spiega perche' i bottoni sono piu' di uno: con un bottone
        # solo sarebbe una riga che non risponde a nessuna domanda.
        self.assertNotIn("compare pi", self._scheda(1))

    def test_il_guscio_non_si_spezza_per_regola(self):
        from src import poi_pdf

        pezzo = poi_pdf._CSS.split(".keep {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-inside: avoid", pezzo)


class TestILTESTONONTOCCAILNUMERODIPAGINA(unittest.TestCase):
    """Misurato: a pagina 3 l'inchiostro arrivava a 813 pixel su 842, e il
    numero di pagina sta a ventotto punti dal bordo.

    La causa non e' un errore di calcolo: questo motore di stampa, quando
    spezza un riquadro con riempimento, lascia sconfinare l'ultima riga oltre
    il margine invece di mandarla alla pagina dopo. Non lo si puo' vietare —
    gli si puo' solo lasciare lo spazio in cui sconfinare senza far danno.
    """

    # Quanto deve restare fra il fondo della colonna di testo e il numero di
    # pagina. Lo sconfinamento misurato era di ventotto punti: sotto quella
    # cifra la riparazione non ripara niente.
    FRANCO_MINIMO_PT = 35.0

    def test_fra_la_colonna_e_il_numero_ci_sono_almeno_trentacinque_punti(self):
        from src.fascicolo import ALTEZZA_DEL_NUMERO_PT
        from src.pdf_renderer import _CSS

        regola = _CSS.split("@page", 1)[1].split("}", 1)[0]
        misure = re.search(r"margin:\s*([\d.]+)cm\s+([\d.]+)cm(?:\s+([\d.]+)cm)?",
                           regola)
        self.assertTrue(misure, "il margine di pagina non si legge piu'")
        sotto_cm = float(misure.group(3) or misure.group(1))
        sotto_pt = sotto_cm * 72.0 / 2.54
        self.assertGreaterEqual(
            sotto_pt - ALTEZZA_DEL_NUMERO_PT, self.FRANCO_MINIMO_PT,
            "fra il fondo del testo e il numero di pagina non c'e' abbastanza "
            "spazio: una riga che sconfina ci finisce sopra, ed e' il difetto "
            "di pagina 3 del fascicolo di Bologna")

    def test_il_numero_non_finisce_nella_zona_che_le_stampanti_tagliano(self):
        from src.fascicolo import ALTEZZA_DEL_NUMERO_PT

        self.assertGreaterEqual(ALTEZZA_DEL_NUMERO_PT, 16.0)

    def test_il_margine_inferiore_e_piu_largo_di_quello_superiore(self):
        # Non e' estetica: e' la zona di sconfinamento. Se un domani
        # qualcuno riportasse i due margini uguali, il difetto tornerebbe
        # senza che nessuna prova se ne accorga — tranne questa.
        from src.pdf_renderer import _CSS

        regola = _CSS.split("@page", 1)[1].split("}", 1)[0]
        misure = re.search(r"margin:\s*([\d.]+)cm\s+([\d.]+)cm(?:\s+([\d.]+)cm)?",
                           regola)
        self.assertTrue(misure.group(3), "il margine inferiore non e' piu' "
                                         "dichiarato a parte")
        self.assertGreater(float(misure.group(3)), float(misure.group(1)))


class TestILCONTEGGIODELLETAPPE(unittest.TestCase):
    """«16 tappe in programma» quando le tappe vere sono una decina.

    Gli spazi liberi sono una cosa buona e onesta — un programma che respira
    — ma non sono tappe. Un numero gonfiato sulla prima pagina e' il tipo di
    dettaglio che, se il cliente lo scopre, gli fa rileggere con sospetto
    tutto il resto.
    """

    def _copertina(self, blocks):
        from src.pdf_renderer import render_html

        html = render_html(
            {"destination": "Bologna", "executive_summary": "Due giorni.",
             "days": [{"day": 1, "title": "Centro", "blocks": blocks}]},
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-13", "duration_days": 1, "budget_eur": 300},
            hotels=[{"name": "Hotel", "price_night_eur": 100}])
        return html.split("class='cover-facts'", 1)[1].split("</table>", 1)[0]

    def _valore(self, copertina, etichetta):
        pezzo = copertina.split(etichetta, 1)
        if len(pezzo) < 2:
            return None
        trovato = re.search(r">([^<]+)<", pezzo[1])
        return trovato.group(1).strip() if trovato else None

    def test_gli_spazi_liberi_non_si_contano_come_tappe(self):
        blocks = [
            {"time": "09:00", "activity": "Visita", "location": "Due Torri",
             "poi_id": "A"},
            {"time": "12:00", "activity": "Pranzo", "location": "Osteria",
             "poi_id": "B"},
            {"time": "15:00", "activity": "[SLOT LIBERO] Passeggiata libera",
             "location": "Centro"},
            {"time": "19:00", "activity": "[SLOT LIBERO] Cena libera",
             "location": "Zona centro"},
        ]
        copertina = self._copertina(blocks)
        self.assertEqual("2", self._valore(copertina, "Tappe in programma"))

    def test_gli_spazi_liberi_si_dicono_lo_stesso_ma_per_quello_che_sono(self):
        """Non si nascondono: si raccontano. Dire «2 momenti liberi» e'
        meglio che sommarli alle tappe, e anche meglio che tacerli."""
        blocks = [
            {"time": "09:00", "activity": "Visita", "location": "Due Torri",
             "poi_id": "A"},
            {"time": "15:00", "activity": "[SLOT LIBERO] Passeggiata",
             "location": "Centro"},
            {"time": "19:00", "activity": "[SLOT LIBERO] Cena libera",
             "location": "Centro"},
        ]
        copertina = self._copertina(blocks)
        self.assertIn("Spazi liberi", copertina)
        self.assertEqual("2 momenti", self._valore(copertina, "Spazi liberi"))

    def test_senza_spazi_liberi_la_riga_non_compare(self):
        blocks = [{"time": "09:00", "activity": "Visita", "location": "Due Torri",
                   "poi_id": "A"}]
        copertina = self._copertina(blocks)
        self.assertNotIn("Spazi liberi", copertina)
        self.assertEqual("1", self._valore(copertina, "Tappe in programma"))

    def test_una_tappa_senza_poi_id_resta_una_tappa(self):
        """Non tutte le tappe vere hanno un `poi_id`: la colazione in hotel
        non e' un punto di interesse, ma e' un appuntamento con un orario e
        un posto. Il segno di uno spazio libero e' la scritta, non l'assenza
        dell'identificativo."""
        blocks = [
            {"time": "08:30", "activity": "Colazione in hotel",
             "location": "Hotel"},
            {"time": "09:00", "activity": "Visita", "location": "Due Torri",
             "poi_id": "A"},
        ]
        copertina = self._copertina(blocks)
        self.assertEqual("2", self._valore(copertina, "Tappe in programma"))
        self.assertNotIn("Spazi liberi", copertina)


if __name__ == "__main__":
    unittest.main()
