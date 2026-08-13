"""
[AGGIUNTO 2026-08-01] Copre src/predeparture.py — la sezione "Prima di
partire".

Il test di principio è `test_paese_sconosciuto_non_produce_un_numero_di_
emergenza_inventato`: è l'unico punto del prodotto in cui un dato plausibile
ma sbagliato può fare un danno fisico a una persona. Tutti gli altri test
girano attorno alla stessa regola espressa altrove: ogni riga della checklist
o è universalmente vera, o è ancorata a un dato REALE di QUESTO viaggio.
"""
import unittest

from src import pdf_links, predeparture
from src.pdf_renderer import _render_predeparture, render_html
from src.schemas import POI


class FakeTrip:
    def __init__(self, destination):
        self.destination = destination


HOTEL_DICT = {
    "name": "Hotel Duomo", "address": "Via Roma 1, Firenze", "phone": "+39 055 111222",
}


class HotelObj:
    name = "Hotel Duomo"
    address = "Via Roma 1, Firenze"
    phone = None


MUSEO = POI(id="M1", type="museum", name="Uffizi", lat=43.7678, lng=11.2553)
MUSEO_2 = POI(id="M2", type="museum", name="Accademia", lat=43.777, lng=11.258)
RISTORANTE = POI(id="R1", type="restaurant", name="Sostanza", lat=43.77, lng=11.24)

ITINERARIO = {
    "days": [
        {"day": 1, "blocks": [{"poi_id": "M1"}, {"poi_id": "R1"}]},
        {"day": 2, "blocks": [{"poi_id": "M1"}, {"poi_id": "M2"}]},
    ]
}


class TestSchedaPaese(unittest.TestCase):
    def test_dati_presi_tali_e_quali_dalla_tabella(self):
        card = predeparture.build_country_card(FakeTrip("Firenze, Italia"))
        self.assertEqual(card["emergency"], "112")
        self.assertIn("Euro", card["currency"])

    def test_paese_sconosciuto_non_produce_un_numero_di_emergenza_inventato(self):
        """La regola non negoziabile: meglio nessuna scheda che un numero
        'probabilmente giusto' composto in un'emergenza."""
        self.assertIsNone(predeparture.build_country_card(FakeTrip("Kathmandu, Nepal")))

    def test_destinazione_vuota_non_solleva(self):
        self.assertIsNone(predeparture.build_country_card(FakeTrip("   ")))

    def test_trip_come_dizionario(self):
        """`trip` viaggia come oggetto o come dict a seconda del chiamante."""
        card = predeparture.build_country_card({"destination": "Parigi, Francia"})
        self.assertIsNotNone(card)
        self.assertEqual(card["country"], "Francia")


class TestChecklist(unittest.TestCase):
    def _titles(self, items):
        return " | ".join(i["title"] for i in items)

    def test_il_documento_didentita_ce_sempre(self):
        items = predeparture.build_checklist(FakeTrip("Nepal"), None)
        self.assertIn("Documento", self._titles(items))

    def test_indirizzo_dellalloggio_solo_se_lalloggio_esiste(self):
        senza = predeparture.build_checklist(FakeTrip("Italia"), ITINERARIO, hotels=[])
        self.assertNotIn("alloggio", self._titles(senza))
        con = predeparture.build_checklist(
            FakeTrip("Italia"), ITINERARIO, hotels=[HOTEL_DICT],
        )
        self.assertIn("alloggio", self._titles(con))

    def test_lindirizzo_vero_finisce_nel_testo(self):
        items = predeparture.build_checklist(
            FakeTrip("Italia"), ITINERARIO, hotels=[HOTEL_DICT],
        )
        riga = [i for i in items if "alloggio" in i["title"]][0]
        self.assertIn("Via Roma 1", riga["detail"])
        self.assertIn("+39 055 111222", riga["detail"])

    def test_hotel_come_oggetto_e_come_dizionario(self):
        """L'asimmetria è reale nel prodotto (`cost_estimator` legge oggetti,
        `pdf_renderer` dizionari): una funzione che ne accetta una sola
        fallirebbe in silenzio in metà del codice."""
        items = predeparture.build_checklist(
            FakeTrip("Italia"), ITINERARIO, hotels=[HotelObj()],
        )
        riga = [i for i in items if "alloggio" in i["title"]][0]
        self.assertIn("Hotel Duomo", riga["detail"])
        self.assertNotIn("tel.", riga["detail"])  # telefono assente: niente "tel. None"

    def test_prenotazioni_nominano_solo_i_musei_davvero_in_programma(self):
        items = predeparture.build_checklist(
            FakeTrip("Italia"), ITINERARIO, pois=[MUSEO, MUSEO_2, RISTORANTE],
        )
        riga = [i for i in items if "Biglietti" in i["title"]][0]
        self.assertIn("Uffizi", riga["detail"])
        self.assertIn("Accademia", riga["detail"])
        self.assertNotIn("Sostanza", riga["detail"])

    def test_nessun_museo_in_programma_nessuna_riga_prenotazioni(self):
        solo_cena = {"days": [{"day": 1, "blocks": [{"poi_id": "R1"}]}]}
        items = predeparture.build_checklist(
            FakeTrip("Italia"), solo_cena, pois=[MUSEO, RISTORANTE],
        )
        self.assertNotIn("Biglietti", self._titles(items))

    def test_un_poi_non_presente_nellitinerario_non_viene_citato(self):
        """Fedeltà al programma: `MUSEO_2` è nei POI ma non nei blocchi."""
        solo_uffizi = {"days": [{"day": 1, "blocks": [{"poi_id": "M1"}]}]}
        items = predeparture.build_checklist(
            FakeTrip("Italia"), solo_uffizi, pois=[MUSEO, MUSEO_2],
        )
        riga = [i for i in items if "Biglietti" in i["title"]][0]
        self.assertNotIn("Accademia", riga["detail"])

    def test_valuta_non_euro_avverte_della_conversione_dinamica(self):
        items = predeparture.build_checklist(FakeTrip("Londra, Regno Unito"), None)
        riga = [i for i in items if "Carte" in i["title"]][0]
        self.assertIn("conversione", riga["detail"].lower())
        self.assertIn("Sterlina", riga["detail"])

    def test_valuta_euro_non_parla_di_conversione(self):
        items = predeparture.build_checklist(FakeTrip("Roma, Italia"), None)
        riga = [i for i in items if "Carte" in i["title"]][0]
        self.assertNotIn("conversione", riga["detail"].lower())

    def test_paese_fuori_tabella_niente_riga_prese_ne_riga_carte(self):
        titoli = self._titles(predeparture.build_checklist(FakeTrip("Nepal"), None))
        self.assertNotIn("Adattatore", titoli)
        self.assertNotIn("Carte", titoli)
        # ma le voci universali restano: la lista non sparisce
        self.assertIn("Mappa", titoli)

    def test_ordine_dei_luoghi_e_quello_di_visita(self):
        rovesciato = {"days": [{"day": 1, "blocks": [{"poi_id": "M2"}, {"poi_id": "M1"}]}]}
        items = predeparture.build_checklist(
            FakeTrip("Italia"), rovesciato, pois=[MUSEO, MUSEO_2],
        )
        detail = [i for i in items if "Biglietti" in i["title"]][0]["detail"]
        self.assertLess(detail.index("Accademia"), detail.index("Uffizi"))

    def test_nessuna_voce_duplicata(self):
        items = predeparture.build_checklist(
            FakeTrip("Italia"), ITINERARIO, hotels=[HOTEL_DICT], pois=[MUSEO],
        )
        titoli = [i["title"] for i in items]
        self.assertEqual(len(titoli), len(set(titoli)))

    def test_ogni_voce_ha_titolo_e_dettaglio_non_vuoti(self):
        for item in predeparture.build_checklist(FakeTrip("Italia"), ITINERARIO):
            self.assertTrue(item["title"].strip())
            self.assertTrue(item["detail"].strip())


class TestElencoNomi(unittest.TestCase):
    def test_pochi_nomi_elencati_per_esteso(self):
        self.assertEqual(predeparture._name_list(["A", "B"]), "A e B")

    def test_tanti_nomi_troncati_col_conteggio(self):
        testo = predeparture._name_list(["A", "B", "C", "D", "E", "F"])
        self.assertIn("e altri 2", testo)
        self.assertNotIn("F", testo)

    def test_lista_vuota(self):
        self.assertEqual(predeparture._name_list([]), "")


class TestBuildPredeparture(unittest.TestCase):
    def test_forma_del_risultato(self):
        data = predeparture.build_predeparture(FakeTrip("Italia"), ITINERARIO)
        self.assertIn("country", data)
        self.assertIsInstance(data["checklist"], list)

    def test_input_malformato_non_solleva_mai(self):
        for itinerario in (None, {}, {"days": None}, {"days": [None, "x"]},
                           {"days": [{"blocks": [None, 3]}]}):
            data = predeparture.build_predeparture(FakeTrip("Italia"), itinerario)
            self.assertIsInstance(data["checklist"], list)


class TestRenderPredeparture(unittest.TestCase):
    def test_senza_dati_nessuna_sezione(self):
        self.assertEqual(_render_predeparture(None), "")
        self.assertEqual(_render_predeparture({"country": None, "checklist": []}), "")

    def test_il_numero_di_emergenza_e_evidenziato(self):
        html = _render_predeparture(
            predeparture.build_predeparture(FakeTrip("Italia"), ITINERARIO)
        )
        self.assertIn("emergency", html)
        self.assertIn("112", html)

    def test_le_caselle_sono_disegnate_non_caratteri_unicode(self):
        """I glifi di casella non esistono nei font del renderer: uscirebbero
        come rettangoli vuoti, cioè come un difetto di stampa."""
        html = _render_predeparture(
            predeparture.build_predeparture(FakeTrip("Italia"), ITINERARIO)
        )
        self.assertIn("check-box", html)
        for glifo in ("☐", "☑", "□"):
            self.assertNotIn(glifo, html)

    def test_ogni_voce_e_una_tabella_per_non_spezzarsi_tra_due_pagine(self):
        html = _render_predeparture(
            predeparture.build_predeparture(FakeTrip("Italia"), ITINERARIO)
        )
        self.assertEqual(html.count("<table class='check-row'>"), html.count("</table>") - 1)

    def test_testo_pericoloso_viene_neutralizzato(self):
        html = _render_predeparture({
            "country": None,
            "checklist": [{"title": "<script>x</script>", "detail": "a & b"}],
        })
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)


class TestSezioneNelDocumento(unittest.TestCase):
    ITINERARIO_MINIMO = {
        "executive_summary": "x",
        "days": [{"day": 1, "title": "Centro", "blocks": [{"poi_id": "M1"}]}],
    }
    TRIP = {"destination": "Firenze, Italia", "objective_function": "Cultura",
            "date_start": "2026-09-01", "date_end": "2026-09-03", "duration_days": 3}

    def _html(self):
        return render_html(
            self.ITINERARIO_MINIMO, self.TRIP,
            predeparture=predeparture.build_predeparture(
                FakeTrip("Firenze, Italia"), self.ITINERARIO_MINIMO,
                hotels=[HOTEL_DICT], pois=[MUSEO],
            ),
        )

    def test_la_sezione_compare_con_la_sua_ancora(self):
        self.assertIn("id='prima-di-partire'", self._html())

    def test_e_raggiungibile_dallindice(self):
        html = self._html()
        # [AGGIORNATO 2026-08-13] I rimandi interni non partono piu' con
        # `#`: in produzione il motore di stampa li cancellava.
        self.assertIn(f"href='{pdf_links.href_interno('prima-di-partire')}'", html)
        self.assertIn("Prima di partire", html)

    def test_senza_dati_il_documento_resta_identico_a_prima(self):
        html = render_html(self.ITINERARIO_MINIMO, self.TRIP)
        self.assertNotIn("prima-di-partire", html)

    def test_nessuna_proprieta_css_non_supportata_dal_motore(self):
        """Stesso vincolo di tutto il resto del foglio di stile: il motore
        Qt WebKit di wkhtmltopdf le ignora in silenzio e il risultato è un
        blocco che sembra rotto."""
        html = self._html()
        for vietata in ("linear-gradient", "rgba(", "display: flex", "opacity:"):
            self.assertNotIn(vietata, html)


class TestIndiceDiCopertinaCliccabile(unittest.TestCase):
    """[AGGIUNTO 2026-08-01] La copertina elencava i capitoli senza renderli
    raggiungibili: era l'unico elenco del documento non cliccabile, ed è la
    prima pagina che il cliente tocca."""

    def test_le_voci_di_copertina_sono_link(self):
        html = render_html(
            {"executive_summary": "x", "days": [{"day": 1, "title": "A", "blocks": []}]},
            {"destination": "Firenze", "duration_days": 1},
        )
        # Taglio sulla fascia d'intestazione: l'indice a pagina intera non
        # esiste più (task #168, è stato inglobato nella copertina) e tagliare
        # su `class='toc'` restituiva tutto il documento invece della sola
        # copertina — un test che passa senza più guardare dove doveva.
        cover = html.split("class='header'")[0]
        self.assertIn("cover-toc-item", cover)
        self.assertIn(f"href='{pdf_links.href_interno('giorno-per-giorno')}'", cover)
        # I giorni annidati erano l'unica cosa che la pagina d'indice separata
        # aveva in più della copertina: se si perdessero, la fusione delle due
        # pagine avrebbe tolto informazione invece che spazio bianco.
        self.assertIn("cover-toc-sub", cover)
        self.assertIn(f"href='{pdf_links.href_interno('giorno-1')}'", cover)


if __name__ == "__main__":
    unittest.main()
