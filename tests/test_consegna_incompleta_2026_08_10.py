"""Un documento a cui manca la meta' non si spedisce (task #196).

PERCHE' QUESTO FILE ESISTE

Il 10 agosto 2026 il credito del modello si e' esaurito a meta' lavoro. Il
servizio ha costruito il fascicolo lo stesso — perche' ogni sezione e' scritta
per degradare invece di rompersi — e ha risposto **200 OK** con
`guides_requested: 5` e `guides_generated: 0`. Make ha visto un successo, ha
spedito la mail, e il cliente ha ricevuto un documento senza NESSUNA delle
schede dei luoghi: cioe' senza la parte per cui aveva pagato.

Nessun errore da nessuna parte. Non nei log, non nella risposta, non nella
casella di Lorenzo. Ce ne siamo accorti solo perche' quel giorno qualcuno
stava guardando i numeri riga per riga.

## La forma del guasto, che e' quella che conta

E' la stessa di tutti i guasti seri di questo progetto: **degradano invece di
rompersi**. La cartina che ripiega sullo schema, la guida che non viene
pubblicata, il collegamento che non salta, il foglio della valigia che non
nasce perche' manca una libreria. Nessuno fa cadere il servizio; tutti tolgono
qualcosa al cliente senza dirlo.

La difesa non e' «generare meglio le guide» — quello si guasta comunque, prima
o poi, per un motivo che oggi non sappiamo. La difesa e' che un documento
troppo incompleto **non riesca a essere spedito**.

## Perche' 502 e non 200 con un avviso

Perche' l'unica cosa che Make guarda e' il codice. Un avviso dentro un 200
sarebbe una riga di testo che nessun modulo legge: esattamente la situazione
del 10 agosto, con l'aggiunta della soddisfazione di averla scritta.

## Perche' il documento resta nella risposta

Il lavoro e' gia' stato fatto e gia' pagato — otto minuti di generazione e
qualche decina di centesimi. Buttarlo via insieme all'errore sarebbe punire
due volte lo stesso guasto. Il fascicolo resta in `pdf_base64`, intatto: chi
vuole puo' guardarlo, e chi ripara il motivo puo' rigiocare l'esecuzione.
"""

import unittest
from unittest.mock import patch

import service


class TestLaRegolaDaSola(unittest.TestCase):
    """La regola e' una funzione pura: si prova senza costruire un PDF."""

    def _motivo(self, **contatori):
        return service._fascicolo_troppo_incompleto(contatori)

    def test_zero_guide_su_cinque_ferma_la_consegna(self):
        # Il caso vero del 10 agosto, fissato per numeri.
        motivo = self._motivo(guides_requested=5, guides_generated=0)
        self.assertTrue(motivo)
        self.assertIn("5", motivo)

    def test_qualcuna_che_manca_non_ferma_niente(self):
        """Il confine, ed e' la parte piu' importante di questa regola.

        Un luogo su nove senza scheda e' un documento un po' piu' magro.
        Fermare la consegna per quello vorrebbe dire non consegnare mai, e
        una regola che blocca tutto viene spenta entro una settimana — e con
        lei sparisce anche la protezione sul caso vero.
        """
        self.assertFalse(self._motivo(guides_requested=9, guides_generated=8))
        self.assertFalse(self._motivo(guides_requested=5, guides_generated=1))

    def test_se_le_guide_non_erano_state_chieste_va_tutto_bene(self):
        # Un documento senza guide, chiesto senza guide, e' completo.
        self.assertFalse(self._motivo(guides_requested=0, guides_generated=0))

    def test_il_motivo_dice_anche_perche_e_non_solo_che(self):
        """Senza il perche', chi riceve l'allarme deve riprodurre il guasto.

        Il 10 agosto la frase che serviva era gia' scritta nei
        `section_errors` («credit balance is too low»): bastava portarla
        fuori. Cinque minuti invece di un pomeriggio.
        """
        motivo = self._motivo(
            guides_requested=5, guides_generated=0,
            section_errors={"guides": "credito esaurito"})
        self.assertIn("credito esaurito", motivo)

    def test_contatori_mancanti_o_storti_non_fanno_cadere_niente(self):
        # Questa funzione gira alla fine di una generazione da otto minuti:
        # se sollevasse, butterebbe via tutto il lavoro per un contatore
        # assente. Meglio consegnare che perdere.
        for contatori in ({}, {"guides_requested": None, "guides_generated": None},
                          {"guides_requested": 3, "guides_generated": 0,
                           "section_errors": None}):
            with self.subTest(contatori=contatori):
                service._fascicolo_troppo_incompleto(contatori)


class TestDallaRottaVera(unittest.TestCase):
    """Il giro completo: il guasto del 10 agosto, riprodotto.

    Non basta che la regola sia giusta: deve essere COLLEGATA. Una funzione
    corretta e mai chiamata e' il modo piu' elegante di non risolvere un
    problema.
    """

    TRIP = {
        "email": "cliente@mail.com", "destination": "Roma",
        "date_start": "2026-09-01", "date_end": "2026-09-04",
        "duration_days": 3, "budget_eur": 0, "budget_mode": "UNLIMITED",
        "objective_function": "ENERGY_PACING",
    }
    API_PAYLOAD = {
        "hotels": [{"id": "H1", "name": "Hotel Test", "lat": 41.9, "lng": 12.5,
                    "price_night_eur": 100.0}],
        "travel_times": [],
        "poi": [{"id": "P1", "type": "museum", "name": "Colosseo",
                 "lat": 41.89, "lng": 12.49}],
    }
    ITINERARIO = {
        "destination": "Roma",
        "executive_summary": "Un bel viaggio.",
        "days": [{"day": 1, "title": "Arrivo", "blocks": [
            {"time": "09:00", "activity": "Colosseo", "location": "Roma",
             "poi_id": "P1"}]}],
    }

    def setUp(self):
        service.app.testing = True
        self.client = service.app.test_client()
        self._env = patch.dict("os.environ", {"SERVICE_API_KEY": "segreto-di-test"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    @staticmethod
    def _pdf_finto(itinerary, trip, hotels=None, guides=None, feedback=None,
                   poi=None, map_png_bytes=None, output_path=None, **kwargs):
        from pathlib import Path

        Path(output_path).write_bytes(b"%PDF-1.4 contenuto finto\n")
        return output_path

    def _chiedi_il_fascicolo(self, guida_riuscita):
        from tests.test_main import wire_guide_module

        with patch("src.config.SETTINGS.anthropic_api_key", "chiave-finta"), \
             patch("src.pdf_extras.guide_generator") as guide, \
             patch("src.pdf_extras.feedback_generator") as feedback, \
             patch("src.pdf_extras.maps_static") as mappe, \
             patch("service.pdf_renderer.render_pdf", side_effect=self._pdf_finto):
            wire_guide_module(guide)
            if guida_riuscita:
                guide.generate_poi_guide.return_value = {
                    "title": "Guida", "poi_name": "Colosseo"}
            else:
                # Il guasto vero, parola per parola.
                guide.generate_poi_guide.side_effect = RuntimeError(
                    "Your credit balance is too low to access the Anthropic API")
            feedback.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
            mappe.build_map_for_itinerary.return_value = b"png-finto"
            mappe.build_overview_map.return_value = {
                "day": None, "title": "Il viaggio a colpo d'occhio", "stops": [],
                "hotel_point": None, "hotel_name": None, "hotel_id": None,
                "png": b"png-finto", "base_map": None,
            }
            return self.client.post("/v1/pdf", json={
                "trip": self.TRIP, "api_payload": self.API_PAYLOAD,
                "itinerary": self.ITINERARIO,
            }, headers={"X-Service-Key": "segreto-di-test"})

    def test_senza_nessuna_guida_la_rotta_non_dice_piu_va_tutto_bene(self):
        risposta = self._chiedi_il_fascicolo(guida_riuscita=False)
        self.assertNotEqual(
            risposta.status_code, 200,
            "il servizio dice ancora «riuscito» per un documento a cui manca "
            "la parte che il cliente ha comprato: e' il guasto del 10 agosto")
        self.assertEqual(risposta.status_code, 502)
        dati = risposta.get_json()
        self.assertEqual(dati["guides_generated"], 0)
        self.assertGreater(dati["guides_requested"], 0)
        self.assertIn("error", dati)

    def test_il_documento_non_viene_buttato_via_insieme_all_errore(self):
        # Otto minuti di generazione, gia' pagati. L'errore ferma la
        # spedizione, non cancella il lavoro.
        dati = self._chiedi_il_fascicolo(guida_riuscita=False).get_json()
        self.assertTrue(dati.get("pdf_base64"))

    def test_con_le_guide_al_loro_posto_si_consegna_come_sempre(self):
        # Il controllo gemello: senza questo, bloccare TUTTO passerebbe.
        risposta = self._chiedi_il_fascicolo(guida_riuscita=True)
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.get_json()["guides_generated"], 1)


class TestUnItinerarioVuotoNonPassaAvanti(unittest.TestCase):
    """L'errore deve nascere dove nasce il guasto.

    Il 10 agosto il modello non ha prodotto un itinerario leggibile.
    `/v1/itinerary` ha risposto **200 OK** con un oggetto vuoto — nel codice
    c'era perfino un commento che diceva «e' un fallimento vero, anche se la
    risposta HTTP e' 200» — e la catena e' andata avanti: due attese, otto
    minuti, e finalmente un `400 Bad Request` dal modulo che stampa, cioe'
    l'errore piu' lontano possibile dalla causa.

    Chi guarda quel log legge «richiesta malformata» e va a cercare un
    problema di formato dove il problema era che non c'era niente da
    stampare. Il costo di un errore non e' il guasto: e' la distanza fra
    dove si vede e dove e' successo.
    """

    def test_un_itinerario_senza_giornate_non_e_utilizzabile(self):
        for vuoto in ({}, {"days": []}, {"destination": "Roma"}, None, "", []):
            with self.subTest(vuoto=vuoto):
                self.assertFalse(service._itinerario_utilizzabile(vuoto))

    def test_un_itinerario_con_una_giornata_lo_e(self):
        self.assertTrue(service._itinerario_utilizzabile(
            {"days": [{"day": 1, "blocks": []}]}))

    def test_e_la_stessa_condizione_che_la_stampa_pretende_in_ingresso(self):
        """I due controlli devono restare d'accordo.

        Se questo diventasse piu' permissivo di quello di `/v1/pdf`, si
        tornerebbe esattamente a oggi: un 200 qui e un 400 otto minuti dopo.
        """
        import inspect

        stampa = inspect.getsource(service._esegui_pdf)
        self.assertIn('isinstance(itinerary.get("days"), list)', stampa,
                      "la stampa ha cambiato la condizione: questo controllo "
                      "va riallineato, non cancellato")


class TestLaCatenaSiFermaAlPrimoAnelloRotto(unittest.TestCase):
    """Dalla rotta vera, con il modello che non produce niente di leggibile."""

    CORPO = {"mode": "mock", "scenario_key": "happy_path", "trip": {
        "email": "cliente@esempio.it", "scopo": "Relax",
        "destinazione": "Siena", "arrivo": "2026-09-12",
        "partenza": "2026-09-14", "budget": 500, "note": "",
    }}

    def setUp(self):
        service.app.testing = True
        self.client = service.app.test_client()
        self._env = patch.dict("os.environ", {"SERVICE_API_KEY": "segreto-di-test"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def _risultato_finto(self, itinerario, parse_error=None):
        from src.schemas import Trip

        viaggio = Trip(email="cliente@esempio.it", destination="Siena",
                       date_start="2026-09-12", date_end="2026-09-14",
                       duration_days=2, budget_eur=500,
                       budget_mode="TOTAL", objective_function="ENERGY_PACING")

        class _Finto:
            trip = viaggio
            api_payload = None
            data_layer_error = None
            geocoding_warning = None
            validation_report = None
            rendered_markdown = ""

        _Finto.itinerary = itinerario
        _Finto.parse_error = parse_error
        return _Finto()

    def _chiedi(self, itinerario, parse_error=None):
        with patch.object(service, "run_mock_from_raw",
                          return_value=self._risultato_finto(itinerario, parse_error)), \
             patch.object(service.SETTINGS, "missing_for_mock_mode",
                          lambda: []):
            return self.client.post("/v1/itinerary", json=self.CORPO,
                                    headers={"X-Service-Key": "segreto-di-test"})

    def test_niente_giornate_niente_duecento(self):
        risposta = self._chiedi({}, parse_error="risposta del modello non leggibile")
        self.assertEqual(
            risposta.status_code, 502,
            "la rotta dice ancora «riuscito» per un itinerario vuoto: la "
            "catena ripartirebbe e morirebbe otto minuti dopo, altrove")

    def test_il_messaggio_nomina_la_causa_vera(self):
        dati = self._chiedi({}, parse_error="risposta del modello non leggibile").get_json()
        self.assertIn("nessuna giornata", dati["error"])
        self.assertIn("non leggibile", dati["error"])

    def test_il_lavoro_gia_fatto_resta_nella_risposta(self):
        dati = self._chiedi({}, parse_error="tagliato a meta'").get_json()
        for campo in ("trip", "itinerary", "parse_error", "cost_estimate"):
            with self.subTest(campo=campo):
                self.assertIn(campo, dati)

    def test_un_itinerario_buono_passa_come_sempre(self):
        risposta = self._chiedi({"days": [{"day": 1, "blocks": []}]})
        self.assertEqual(risposta.status_code, 200)


if __name__ == "__main__":
    unittest.main()
