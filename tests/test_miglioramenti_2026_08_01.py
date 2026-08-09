"""
[AGGIUNTO 2026-08-01] Test dei quattro interventi nati dal feedback "da
investitore" del 2026-08-01 (claude/feedback-investitore-2026-08-01.md):

  punto 2 → src/cost_telemetry.py   quanto costa DAVVERO un itinerario
  punto 5 → src/alerting.py         un fallimento non deve essere silenzioso
  punto 6 → src/feedback_link.py    la recensione deve avere dove atterrare
  (+ l'estrazione difensiva di src/redaction.py, usata da entrambi)

Il criterio con cui questi test sono scritti è lo stesso del resto della
suite: non verificano che il codice faccia quello che fa, verificano le
PROPRIETÀ da cui dipende la sicurezza del prodotto — la telemetria non può
rompere una generazione riuscita, l'allarme non può far fallire una
richiesta né spedire fuori un segreto o un'email, il codice di recensione
non può contenere dati personali.
"""
import os
import unittest
from html import escape as html_escape
from unittest.mock import patch

from src import alerting
from src import cost_telemetry
from src import feedback_link
from src import legal_notices
from src import pdf_renderer
from src.redaction import redact_secrets
from src.schemas import Trip


_TRIP = Trip(
    email="cliente@example.com",
    destination="Siena",
    date_start="2026-09-14",
    date_end="2026-09-17",
    duration_days=3,
    objective_function="ENERGY_PACING",
    budget_eur=800,
    budget_mode="LIMITED",
    raw_notes="Anniversario. Niente scale, per favore.",
)


# ---------------------------------------------------------------------------
# cost_telemetry
# ---------------------------------------------------------------------------
class TestCostTelemetryNoOp(unittest.TestCase):
    """La proprietà più importante del modulo: fuori da `measure()` NON
    esiste. È ciò che permette di averlo chiamato da nove moduli della
    pipeline senza cambiare il comportamento del CLI e dei test."""

    def test_record_llm_fuori_da_measure_non_solleva_e_non_accumula(self):
        cost_telemetry.record_llm("claude-sonnet-5", {"input_tokens": 100})
        cost_telemetry.record_api_call("google_geocoding")
        self.assertIsNone(cost_telemetry.current_ledger())

    def test_usage_malformata_non_solleva(self):
        # Un oggetto usage inatteso (SDK cambiato, risposta mockata a metà)
        # non deve poter far fallire una generazione già riuscita.
        with cost_telemetry.measure("t") as ledger:
            cost_telemetry.record_llm("claude-sonnet-5", usage=object())
            cost_telemetry.record_llm(None, usage=None)
            cost_telemetry.record_llm("claude-sonnet-5", usage={"input_tokens": "non-un-numero"})
        self.assertEqual(len(ledger.llm_calls), 3)
        self.assertEqual(ledger.llm_calls[2].input_tokens, 0)

    def test_measure_annidato_non_somma_al_chiamante(self):
        with cost_telemetry.measure("fuori") as esterno:
            cost_telemetry.record_api_call("google_geocoding")
            with cost_telemetry.measure("dentro") as interno:
                cost_telemetry.record_api_call("google_geocoding")
            cost_telemetry.record_api_call("google_geocoding")
        self.assertEqual(len(esterno.api_calls), 2)
        self.assertEqual(len(interno.api_calls), 1)


class TestCostTelemetryConti(unittest.TestCase):
    def test_opus_costa_piu_di_sonnet_a_parita_di_token(self):
        with cost_telemetry.measure() as sonnet:
            cost_telemetry.record_llm(
                "claude-sonnet-5", {"input_tokens": 10_000, "output_tokens": 5_000}
            )
        with cost_telemetry.measure() as opus:
            cost_telemetry.record_llm(
                "claude-opus-4-8", {"input_tokens": 10_000, "output_tokens": 5_000}
            )
        self.assertGreater(opus.total_usd(), sonnet.total_usd())

    def test_distance_matrix_conta_gli_elementi_non_le_chiamate(self):
        # Google fattura la Distance Matrix per ELEMENTO (origini × destinazioni):
        # contare una chiamata da 25 elementi come "1" sottostimerebbe di 25 volte.
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_api_call("google_distance_matrix", units=25)
        with cost_telemetry.measure() as singola:
            cost_telemetry.record_api_call("google_distance_matrix", units=1)
        self.assertAlmostEqual(ledger.api_usd(), singola.api_usd() * 25, places=9)

    def test_distance_matrix_con_traffico_costa_il_doppio(self):
        # [AGGIUNTO 2026-08-01] Google ha due SKU per la Distance Matrix:
        # "Essentials" a 5 $/1000 elementi e "Advanced" a 10 $/1000, e la
        # seconda si attiva da sola appena la richiesta contiene
        # `departure_time`. Finché la telemetria aveva una voce sola, ogni
        # richiesta con traffico veniva contata a metà del suo prezzo vero:
        # sulla prima misura in produzione erano ~0,46 € nascosti per
        # itinerario, su un prezzo di vendita di 4,90 €. Questo test esiste
        # perché quel disallineamento non possa tornare in silenzio.
        with cost_telemetry.measure() as base:
            cost_telemetry.record_api_call("google_distance_matrix", units=100)
        with cost_telemetry.measure() as advanced:
            cost_telemetry.record_api_call("google_distance_matrix_advanced", units=100)
        self.assertAlmostEqual(advanced.api_usd(), base.api_usd() * 2, places=9)

    def test_distance_matrix_spegne_il_traffico_per_default(self):
        # Il viaggio del cliente parte fra settimane: il traffico di ADESSO
        # non lo descrive. Pagarlo il doppio per averlo è il peggiore dei due
        # mondi. Default spento, riaccendibile senza toccare il codice.
        from src import distance_matrix
        env = {k: v for k, v in os.environ.items() if k != "DISTANCE_MATRIX_TRAFFIC"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(distance_matrix.traffic_enabled())
        with patch.dict(os.environ, {"DISTANCE_MATRIX_TRAFFIC": "true"}):
            self.assertTrue(distance_matrix.traffic_enabled())
        with patch.dict(os.environ, {"DISTANCE_MATRIX_TRAFFIC": "false"}):
            self.assertFalse(distance_matrix.traffic_enabled())

    def test_fornitore_sconosciuto_resta_visibile_a_costo_zero(self):
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_api_call("fornitore_mai_visto", units=3)
        self.assertEqual(ledger.api_usd(), 0.0)
        self.assertIn("fornitore_mai_visto", ledger.to_dict()["dettaglio_api"])

    def test_prezzi_sovrascrivibili_da_variabile_dambiente(self):
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_llm("claude-sonnet-5", {"input_tokens": 1_000_000})
        base = ledger.total_usd()
        with patch.dict(os.environ, {"COST_USD_IN_PER_MTOK_SONNET": "6.0"}):
            self.assertAlmostEqual(ledger.total_usd(), base * 2, places=6)

    def test_resoconto_dichiara_sempre_che_i_prezzi_vanno_verificati(self):
        # Un numero che si spaccia per esatto quando non lo è è peggio di
        # nessun numero: la dichiarazione non deve poter sparire dal payload.
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_llm("claude-sonnet-5", {"input_tokens": 10})
        report = ledger.to_dict()
        self.assertTrue(report["prezzi_da_verificare"])
        self.assertEqual(report["listino_del"], cost_telemetry.LISTINO_DEL)

    def test_carryover_abbassa_il_margine(self):
        # Il cliente paga 4,90 € UNA volta ma il lavoro si fa in due chiamate
        # HTTP: calcolare il margine su una sola lo fa sembrare quasi doppio.
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_llm("claude-sonnet-5", {"input_tokens": 10_000})
        senza = ledger.to_dict()
        con = ledger.to_dict(carryover_eur=0.50)
        self.assertAlmostEqual(con["costo_totale_eur"], senza["costo_totale_eur"] + 0.50, places=4)
        self.assertAlmostEqual(con["margine_lordo_eur"], senza["margine_lordo_eur"] - 0.50, places=4)

    def test_carryover_non_numerico_vale_zero_invece_di_sollevare(self):
        # Make.com interpola i campi come TESTO: un carryover arrivato come
        # stringa vuota non deve far fallire la consegna del PDF.
        with cost_telemetry.measure() as ledger:
            cost_telemetry.record_llm("claude-sonnet-5", {"input_tokens": 10})
        self.assertEqual(ledger.to_dict(carryover_eur="")["costo_fasi_precedenti_eur"], 0.0)
        self.assertEqual(ledger.to_dict(carryover_eur=None)["costo_fasi_precedenti_eur"], 0.0)
        self.assertEqual(ledger.to_dict(carryover_eur="0.30")["costo_fasi_precedenti_eur"], 0.3)

    def test_commissione_di_incasso_e_inclusa_nel_margine(self):
        with cost_telemetry.measure() as ledger:
            pass
        report = ledger.to_dict()
        self.assertGreater(report["commissione_incasso_eur"], 0)
        self.assertAlmostEqual(
            report["margine_lordo_eur"],
            report["prezzo_di_vendita_eur"] - report["commissione_incasso_eur"],
            places=4,
        )


# ---------------------------------------------------------------------------
# alerting
# ---------------------------------------------------------------------------
class TestAlerting(unittest.TestCase):
    def test_senza_webhook_e_inerte_e_non_solleva(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALERT_WEBHOOK_URL", None)
            self.assertFalse(alerting.notify("prova", "dettaglio"))

    def test_non_solleva_mai_nemmeno_se_la_post_esplode(self):
        # Regola 1 del modulo: un allarme che rompe la consegna del PDF
        # sarebbe peggio del problema che segnala.
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://esempio.invalid/hook"}):
            with patch("requests.post", side_effect=RuntimeError("rete morta")):
                self.assertFalse(alerting.notify("prova", "dettaglio"))

    def test_il_payload_non_contiene_mai_una_chiave_api(self):
        # Regola 2: il webhook è fuori dal perimetro del servizio, cioè il
        # posto peggiore dove far finire una GOOGLE_MAPS_KEY.
        detail = (
            "HTTPError su https://maps.googleapis.com/maps/api/geocode/json"
            "?address=Siena&key=AIzaSyREALEKEYSEGRETA123 — con x-api-key: sk-ant-abcdef123456"
        )
        payload = alerting.build_alert_payload("data_layer_error", detail, {}, alerting.LEVEL_ERROR)
        self.assertNotIn("AIzaSyREALEKEYSEGRETA123", payload["detail"])
        self.assertNotIn("AIzaSyREALEKEYSEGRETA123", payload["text"])
        self.assertNotIn("sk-ant-abcdef123456", payload["detail"])
        self.assertIn("REDACTED", payload["detail"])

    def test_il_contesto_non_contiene_mai_dati_personali(self):
        # Regola 3: per capire COSA è rotto basta sapere dove e quanto dura
        # il viaggio — non serve spedire il cliente a un servizio terzo.
        context = alerting.safe_trip_context(_TRIP)
        as_text = repr(context)
        self.assertNotIn("cliente@example.com", as_text)
        self.assertNotIn("Niente scale", as_text)
        self.assertEqual(context["destination"], "Siena")
        self.assertEqual(context["duration_days"], 3)

    def test_safe_trip_context_accetta_none_e_dict_senza_sollevare(self):
        self.assertEqual(alerting.safe_trip_context(None), {})
        self.assertEqual(
            alerting.safe_trip_context({"destination": "Roma"})["destination"], "Roma"
        )

    def test_il_dettaglio_lunghissimo_viene_troncato(self):
        payload = alerting.build_alert_payload("x", "a" * 10_000, None, alerting.LEVEL_ERROR)
        self.assertLess(len(payload["detail"]), 2_000)

    def test_min_level_error_silenzia_gli_avvisi_ma_non_gli_errori(self):
        with patch.dict(os.environ, {
            "ALERT_WEBHOOK_URL": "https://esempio.invalid/hook",
            "ALERT_MIN_LEVEL": "error",
        }):
            with patch("requests.post") as post:
                alerting.notify("avviso", "x", level=alerting.LEVEL_WARNING)
                self.assertEqual(post.call_count, 0)
                alerting.notify("errore", "x", level=alerting.LEVEL_ERROR)
                self.assertEqual(post.call_count, 1)

    def test_pdf_completo_non_genera_nessun_allarme(self):
        completo = {
            "guides_requested": 3, "guides_generated": 3, "feedback_included": True,
            "map_included": True, "day_maps_included": 3, "directions_included": 2,
            "costs_included": True, "tips_included": True, "place_cards_included": 4,
        }
        self.assertFalse(alerting.notify_degraded_pdf(completo))

    def test_pdf_senza_cartine_genera_un_allarme_che_le_nomina(self):
        degradato = {
            "guides_requested": 3, "guides_generated": 3, "feedback_included": True,
            "map_included": True, "day_maps_included": 0, "directions_included": 2,
            "costs_included": True, "tips_included": True, "place_cards_included": 4,
        }
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://esempio.invalid/hook"}):
            with patch("requests.post") as post:
                self.assertTrue(alerting.notify_degraded_pdf(degradato))
                body = post.call_args.kwargs["data"].decode("utf-8")
                self.assertIn("cartine delle giornate", body)


class TestRedaction(unittest.TestCase):
    def test_token_sk_redatto_ovunque_appaia(self):
        self.assertNotIn("sk-ant-api03-SEGRETO", redact_secrets("token sk-ant-api03-SEGRETO qui"))

    def test_input_non_stringa_non_solleva(self):
        self.assertIsInstance(redact_secrets(None), str)
        self.assertIsInstance(redact_secrets(ValueError("boom")), str)


# ---------------------------------------------------------------------------
# feedback_link
# ---------------------------------------------------------------------------
class TestFeedbackLink(unittest.TestCase):
    def test_ref_deterministico_con_segreto(self):
        # Rigenerare il PDF (per un affinamento, per un errore) non deve
        # spezzare il collegamento con la risposta già data dal cliente.
        with patch.dict(os.environ, {"FEEDBACK_REF_SECRET": "segreto-di-test"}):
            self.assertEqual(
                feedback_link.build_reference(_TRIP), feedback_link.build_reference(_TRIP)
            )

    def test_ref_diverso_per_viaggi_diversi(self):
        altro = Trip(**{**_TRIP.__dict__, "destination": "Firenze"})
        with patch.dict(os.environ, {"FEEDBACK_REF_SECRET": "segreto-di-test"}):
            self.assertNotEqual(
                feedback_link.build_reference(_TRIP), feedback_link.build_reference(altro)
            )

    def test_ref_diverso_per_clienti_diversi_sullo_stesso_viaggio(self):
        altro = Trip(**{**_TRIP.__dict__, "email": "altro@example.com"})
        with patch.dict(os.environ, {"FEEDBACK_REF_SECRET": "segreto-di-test"}):
            self.assertNotEqual(
                feedback_link.build_reference(_TRIP), feedback_link.build_reference(altro)
            )

    def test_ref_non_contiene_dati_personali(self):
        # È la proprietà che rende accettabile mettere il codice in una URL.
        with patch.dict(os.environ, {"FEEDBACK_REF_SECRET": "segreto-di-test"}):
            ref = feedback_link.build_reference(_TRIP)
        for personale in ("cliente", "example.com", "Siena", "2026-09-14"):
            self.assertNotIn(personale.lower(), ref.lower())

    def test_senza_segreto_il_ref_esiste_comunque_ed_e_casuale(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FEEDBACK_REF_SECRET", None)
            primo = feedback_link.build_reference(_TRIP)
            secondo = feedback_link.build_reference(_TRIP)
        self.assertEqual(len(primo), feedback_link.REF_LENGTH)
        self.assertNotEqual(primo, secondo)

    def test_url_assente_se_il_modulo_non_e_configurato(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FEEDBACK_FORM_URL", None)
            self.assertIsNone(feedback_link.build_feedback_url("abc123"))

    def test_url_usa_il_separatore_giusto_se_ne_ha_gia_uno(self):
        with patch.dict(os.environ, {"FEEDBACK_FORM_URL": "https://tally.so/r/xyz?lang=it"}):
            url = feedback_link.build_feedback_url("abc123")
        self.assertEqual(url, "https://tally.so/r/xyz?lang=it&ref=abc123")

    def test_domande_confrontabili_hanno_id_unici(self):
        ids = [q["id"] for q in feedback_link.CORE_QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        # Il consenso alla testimonianza pubblica va CHIESTO, mai presunto.
        self.assertIn("testimonianza", ids)


# ---------------------------------------------------------------------------
# La sezione recensione nel PDF
# ---------------------------------------------------------------------------
_FEEDBACK = {
    "intro_message": "Com'è andata?",
    "questions": ["Ti è piaciuta la trattoria del secondo giorno?"],
    "testimonial_request": "Possiamo citarti?",
    "closing_message": "Grazie!",
}

_ITINERARY = {
    "destination": "Siena",
    "executive_summary": "Tre giorni.",
    "days": [{"day": 1, "title": "Arrivo", "blocks": [
        {"time": "10:00", "activity": "Piazza del Campo", "location": "Siena", "poi_id": None},
    ]}],
}


class TestSezioneRecensioneNelPdf(unittest.TestCase):
    def _html(self, feedback, link):
        return pdf_renderer.render_html(
            _ITINERARY, _TRIP.to_dict(), feedback=feedback, feedback_link=link
        )

    def test_il_link_compare_nel_documento(self):
        link = {"ref": "abc1234567", "url": "https://tally.so/r/xyz?ref=abc1234567",
                "core_questions": feedback_link.CORE_QUESTIONS}
        html = self._html(_FEEDBACK, link)
        self.assertIn("https://tally.so/r/xyz?ref=abc1234567", html)
        self.assertIn("abc1234567", html)

    def test_le_domande_confrontabili_compaiono_tutte(self):
        link = {"ref": "abc1234567", "url": "https://tally.so/r/xyz",
                "core_questions": feedback_link.CORE_QUESTIONS}
        html = self._html(_FEEDBACK, link)
        for question in feedback_link.CORE_QUESTIONS:
            # Il testo finisce nel documento ESCAPATO (l'apostrofo di "com'era"
            # diventa un'entità HTML), quindi il confronto va fatto sulla forma
            # escapata: cercare il testo grezzo darebbe un falso negativo su
            # ogni domanda che contiene un apostrofo.
            self.assertIn(html_escape(question["text"].split("?")[0][:30]), html)

    def test_senza_link_il_capitolo_non_esce_affatto(self):
        # [CAMBIATO 2026-08-03] Questo test asseriva l'opposto: che senza
        # link la sezione uscisse "come prima". Uscire come prima voleva
        # dire stampare il titolo e due domande personalizzate e nessun
        # posto dove rispondere. Per il cliente è indistinguibile da un
        # collegamento rotto — che è esattamente la lamentela da cui è
        # partito questo giro di lavoro. Ora tace.
        html = self._html(_FEEDBACK, None)
        self.assertNotIn("Facci sapere com'è andata", html)
        self.assertNotIn("Rispondi qui", html)

    def test_la_sezione_esce_anche_se_il_messaggio_personalizzato_e_fallito(self):
        # Il ciclo di dati non deve dipendere da una chiamata al modello
        # andata storta: se il messaggio manca ma il link c'è, si chiede lo
        # stesso. È l'unico modo di avere risposte anche nei giorni storti.
        link = {"ref": "abc1234567", "url": "https://tally.so/r/xyz",
                "core_questions": feedback_link.CORE_QUESTIONS}
        html = self._html(None, link)
        self.assertIn("Rispondi qui", html)
        self.assertIn("Facci sapere com'è andata", html)

    def test_nessun_costrutto_css_non_supportato_da_wkhtmltopdf(self):
        # Stessa rete di sicurezza già usata altrove: il motore di rendering è
        # un WebKit del 2014, e questi quattro costrutti vengono ignorati in
        # silenzio (cioè: il riquadro esce sfondato, e nessuno se ne accorge
        # finché non lo guarda un cliente).
        link = {"ref": "abc1234567", "url": "https://tally.so/r/xyz",
                "core_questions": feedback_link.CORE_QUESTIONS}
        html = self._html(_FEEDBACK, link)
        for vietato in ("linear-gradient", "display: flex", "display:flex", "rgba(", "opacity:"):
            self.assertNotIn(vietato, html)


# ---------------------------------------------------------------------------
# legal_notices — i due buchi bloccanti del punto 6
# ---------------------------------------------------------------------------
class TestAvvisiLegaliNelDocumento(unittest.TestCase):
    """Le due frasi che il memo chiama "da mettere a posto prima di vendere"
    non erano sbagliate: erano scritte solo nelle bozze in claude/legal/, cioè
    in documenti che il cliente non vede mai. Questi test verificano che
    adesso arrivino dove il cliente le legge — nel PDF che porta in viaggio."""

    _HOTELS = [{"name": "Palazzo Ravizza", "property_type": "hotel", "price_night_eur": 140}]

    def _html(self, hotels=None):
        return pdf_renderer.render_html(_ITINERARY, _TRIP.to_dict(), hotels=hotels)

    def test_il_piede_dice_che_non_e_un_pacchetto_turistico(self):
        # Vendere informazione e vendere un pacchetto turistico sono due
        # attività con obblighi incomparabili. La differenza deve stare
        # sull'artefatto che resta in mano al cliente, non solo nei Termini
        # che ha letto una volta al checkout.
        html = self._html()
        self.assertIn("non è un pacchetto turistico", html)

    def test_l_avviso_sta_accanto_ai_link_di_prenotazione(self):
        # È il punto del documento in cui l'ambiguità costa: un elenco di link
        # a piattaforme di prenotazione stampato sotto un itinerario.
        html = self._html(self._HOTELS)
        self.assertIn("Confronta anche su altre piattaforme", html)
        self.assertIn("non sono prenotazioni predisposte da noi", html)
        self.assertIn("non siamo parte del contratto", html)

    def test_senza_hotel_nessun_avviso_sui_link(self):
        # Nessun link di prenotazione, nessun avviso: un disclaimer che parla
        # di una sezione assente confonde e basta.
        html = self._html()
        self.assertNotIn("non sono prenotazioni predisposte da noi", html)

    def test_la_traccia_della_rinuncia_registra_la_versione_del_testo(self):
        # Sapere che una casella è stata spuntata non prova niente se non si
        # sa più che cosa dichiarava quel giorno. Per questo la versione del
        # testo è parte dell'evidenza, non un dettaglio.
        record = legal_notices.consent_record(True, timestamp="2026-08-01T10:00:00Z")
        self.assertTrue(record["recesso_rinuncia_accettata"])
        self.assertEqual(record["recesso_testo_versione"], legal_notices.NOTICES_VERSION)
        self.assertEqual(record["recesso_raccolta_il"], "2026-08-01T10:00:00Z")
        self.assertEqual(record["recesso_raccolta_da"], "checkout")

    def test_la_traccia_non_contiene_dati_personali(self):
        record = legal_notices.consent_record(True, timestamp="2026-08-01T10:00:00Z")
        blob = repr(record)
        self.assertNotIn("@", blob)

    def test_l_email_di_consegna_conferma_la_rinuncia_su_supporto_durevole(self):
        # La spunta al checkout da sola è una prova debole: l'art. 59 chiede
        # anche la conferma su supporto durevole, e l'email di consegna è
        # l'unico supporto durevole che questo servizio produce.
        testo = legal_notices.delivery_email_footer()
        self.assertIn("recesso", testo)
        self.assertIn("art. 59", testo)
        self.assertIn("garanzia legale di conformità", testo)
        # E la stessa email deve ribadire che cosa è stato venduto: è il
        # momento in cui il cliente ha in mano il prodotto ed è il più
        # probabile per un fraintendimento su che cosa ha comprato.
        self.assertIn("non vendiamo pacchetti turistici", testo)


if __name__ == "__main__":
    unittest.main()
