"""
[AGGIUNTO 2026-07-31 — richiesta di Lorenzo: architect's tips per direttrici +
piani B se piove] Copre src/tips_generator.py.

Nessuna chiamata di rete: `generate_architect_tips` è testata mockando il
client `anthropic`, stesso pattern di test_guide_generator.py e
test_feedback_generator.py. Tutto il resto sono funzioni pure.

Il test più importante del file è `test_swap_con_poi_inventato_viene_scartato`:
è la Fedeltà RAG applicata al piano B — un cliente sotto la pioggia mandato a
un museo inesistente è il modo peggiore di scoprire che il documento mente.
"""
import unittest
from unittest.mock import patch, MagicMock

from src.tips_generator import (
    TIP_CATEGORIES,
    TipsGeneratorError,
    build_grounding_facts,
    build_indoor_candidates,
    build_light_facts,
    build_tips_user_message,
    days_needing_rain_plan,
    generate_architect_tips,
    normalize_tips,
    render_tips_markdown,
    select_categories,
    _validate_tips_shape,
)
from src.schemas import Hotel, POI, Trip


def _trip(**overrides):
    base = dict(
        email="cliente@example.com",
        destination="Firenze, Italia",
        date_start="2026-06-20",
        date_end="2026-06-24",
        duration_days=4,
        budget_eur=800.0,
        budget_mode="LIMITED",
        objective_function="BALANCED",
        raw_notes="",
        dest_lat=43.7696,
        dest_lng=11.2558,
    )
    base.update(overrides)
    return Trip(**base)


POI_PARCO = POI(id="P1", type="park", name="Giardino di Boboli", lat=43.762, lng=11.248)
POI_RISTORANTE = POI(id="P2", type="restaurant", name="Trattoria Sostanza", lat=43.773, lng=11.246)
POI_MUSEO = POI(id="P3", type="museum", name="Uffizi", lat=43.7678, lng=11.2553)
POI_MUSEO_NON_USATO = POI(id="P4", type="museum", name="Bargello", lat=43.7705, lng=11.2586)
POIS = [POI_PARCO, POI_RISTORANTE, POI_MUSEO, POI_MUSEO_NON_USATO]

ITINERARY = {
    "days": [
        {"day": 1, "title": "Arrivo e Oltrarno", "blocks": [
            {"time": "15:00", "activity": "Passeggiata a Boboli", "poi_id": "P1"},
            {"time": "20:00", "activity": "Cena", "poi_id": "P2"},
        ]},
        {"day": 2, "title": "Il centro", "blocks": [
            {"time": "10:00", "activity": "Uffizi", "poi_id": "P3"},
        ]},
    ]
}


class TestSelectCategories(unittest.TestCase):
    def test_default_include_tutte_le_direttrici_di_lorenzo(self):
        ids = [c["id"] for c in select_categories(_trip())]
        for richiesta in (
            "biglietti_prenotazioni", "bagagli_logistica", "risparmio_pagamenti",
            "meteo_luce_stagione", "pratico_sicurezza", "vita_notturna",
        ):
            self.assertIn(richiesta, ids, f"direttrice richiesta da Lorenzo mancante: {richiesta}")

    def test_ordine_deterministico_e_su_misura_in_fondo(self):
        ids = [c["id"] for c in select_categories(_trip())]
        self.assertEqual(ids, [c["id"] for c in TIP_CATEGORIES])
        self.assertEqual(ids[-1], "su_misura")

    def test_vita_notturna_esclusa_col_modulo_famiglia(self):
        ids = [c["id"] for c in select_categories(_trip(), module_id="famiglia_con_bambini")]
        self.assertNotIn("vita_notturna", ids)
        self.assertIn("su_misura", ids)

    def test_vita_notturna_esclusa_se_le_note_parlano_di_bambini_piccoli(self):
        trip = _trip(raw_notes="Viaggiamo con un neonato, serve il passeggino")
        self.assertNotIn("vita_notturna", [c["id"] for c in select_categories(trip)])

    def test_note_su_un_museo_non_escludono_la_vita_notturna(self):
        trip = _trip(raw_notes="Ci interessa molto l'arte rinascimentale")
        self.assertIn("vita_notturna", [c["id"] for c in select_categories(trip)])

    def test_trip_none_non_solleva(self):
        self.assertTrue(select_categories(None))

    def test_ogni_categoria_ha_un_brief_non_banale(self):
        # il `brief` è la vera specifica passata al modello: se si svuota,
        # la sezione degenera in consigli generici — che è il difetto che
        # questo modulo esiste per eliminare.
        for category in TIP_CATEGORIES:
            self.assertGreater(len(category["brief"]), 80, category["id"])
            self.assertTrue(category["title"])


class TestGroundingFacts(unittest.TestCase):
    def test_paese_riconosciuto_dalla_destinazione_composta(self):
        facts = build_grounding_facts(_trip(), ITINERARY)
        self.assertEqual(facts["paese"]["emergency"], "112")
        self.assertEqual(facts["paese"]["country"], "Italia")

    def test_paese_sconosciuto_non_produce_invenzioni(self):
        facts = build_grounding_facts(_trip(destination="Kathmandu, Nepal"), ITINERARY)
        self.assertNotIn("paese", facts)

    def test_luce_del_giorno_calcolata_per_giorni_campione(self):
        facts = build_grounding_facts(_trip(), ITINERARY)
        light = facts["luce_del_giorno"]
        self.assertTrue(light)
        for entry in light:
            self.assertRegex(entry["sunrise"], r"^\d{2}:\d{2}$")
            self.assertRegex(entry["sunset"], r"^\d{2}:\d{2}$")
            # senza fuso orario reale il dato DEVE dichiararsi approssimato
            self.assertTrue(entry["approximate"])

    def test_senza_coordinate_niente_sezione_luce(self):
        trip = _trip(dest_lat=None, dest_lng=None)
        self.assertEqual(build_light_facts(trip, ITINERARY, hotels=[]), [])

    def test_coordinate_dell_hotel_usate_come_ripiego(self):
        trip = _trip(dest_lat=None, dest_lng=None)
        hotel = Hotel(id="H1", name="Hotel", lat=43.77, lng=11.25, price_night_eur=90.0)
        self.assertTrue(build_light_facts(trip, ITINERARY, hotels=[hotel]))

    def test_data_di_inizio_non_valida_non_solleva(self):
        trip = _trip(date_start="non-una-data")
        self.assertEqual(build_light_facts(trip, ITINERARY, hotels=[]), [])

    def test_stima_costi_inclusa_solo_se_ha_righe(self):
        facts = build_grounding_facts(_trip(), ITINERARY, cost_summary={"lines": []})
        self.assertNotIn("stima_costi", facts)
        facts = build_grounding_facts(_trip(), ITINERARY, cost_summary={
            "lines": [{"known": True}], "total_min_eur": 100.0, "total_max_eur": 200.0,
            "budget_eur": 800.0, "budget_verdict": "within", "unknown_count": 1,
        })
        self.assertEqual(facts["stima_costi"]["verdetto"], "within")
        self.assertEqual(facts["stima_costi"]["totale_max_eur"], 200.0)

    def test_date_viaggio_sempre_presenti(self):
        facts = build_grounding_facts(_trip(), ITINERARY)
        self.assertEqual(facts["date_viaggio"]["inizio"], "2026-06-20")


class TestIndoorCandidates(unittest.TestCase):
    def test_solo_tipi_al_chiuso(self):
        ids = [c["poi_id"] for c in build_indoor_candidates(POIS, ITINERARY)]
        self.assertNotIn("P1", ids)  # il parco non ripara dalla pioggia
        self.assertIn("P3", ids)
        self.assertIn("P4", ids)

    def test_i_luoghi_non_ancora_visitati_vengono_prima(self):
        candidates = build_indoor_candidates(POIS, ITINERARY)
        self.assertEqual(candidates[0]["poi_id"], "P4")

    def test_limite_rispettato(self):
        many = [POI(id=f"M{i}", type="museum", name=f"Museo {i}", lat=43.0, lng=11.0) for i in range(40)]
        self.assertEqual(len(build_indoor_candidates(many, ITINERARY, limit=5)), 5)

    def test_input_vuoto_o_malformato_non_solleva(self):
        self.assertEqual(build_indoor_candidates(None, None), [])
        self.assertEqual(build_indoor_candidates([], {"days": "non una lista"}), [])


class TestDaysNeedingRainPlan(unittest.TestCase):
    def test_riconosce_la_giornata_all_aperto(self):
        days = days_needing_rain_plan(ITINERARY, POIS)
        self.assertEqual([d["day"] for d in days], [1])
        self.assertIn("Passeggiata a Boboli", days[0]["outdoor_blocks"])

    def test_giornata_tutta_al_chiuso_non_richiede_piano_b(self):
        indoor_only = {"days": [{"day": 2, "blocks": [{"time": "10:00", "activity": "Uffizi", "poi_id": "P3"}]}]}
        self.assertEqual(days_needing_rain_plan(indoor_only, POIS), [])

    def test_poi_sconosciuto_non_viene_classificato_a_caso(self):
        unknown = {"days": [{"day": 1, "blocks": [{"time": "10:00", "activity": "?", "poi_id": "ZZZ"}]}]}
        self.assertEqual(days_needing_rain_plan(unknown, POIS), [])


class TestUserMessage(unittest.TestCase):
    def setUp(self):
        self.categories = select_categories(_trip())
        self.facts = build_grounding_facts(_trip(), ITINERARY)
        self.candidates = build_indoor_candidates(POIS, ITINERARY)
        self.outdoor = days_needing_rain_plan(ITINERARY, POIS)

    def _message(self):
        return build_tips_user_message(
            _trip(), ITINERARY, self.categories, self.facts, self.candidates, self.outdoor
        )

    def test_contiene_tutti_i_blocchi_attesi(self):
        message = self._message()
        for marker in (
            "[VIAGGIO]", "[ITINERARIO_GIÀ_DECISO", "[FATTI_VERIFICATI",
            "[CATEGORIE_RICHIESTE", "[GIORNATE_CON_ATTIVITÀ_ALL_APERTO",
            "[ALTERNATIVE_AL_CHIUSO_DISPONIBILI",
        ):
            self.assertIn(marker, message)

    def test_ogni_category_id_richiesto_compare_nel_messaggio(self):
        message = self._message()
        for category in self.categories:
            self.assertIn(category["id"], message)

    def test_le_note_del_cliente_arrivano_al_modello(self):
        message = build_tips_user_message(
            _trip(raw_notes="sono celiaco"), ITINERARY, self.categories,
            self.facts, self.candidates, self.outdoor,
        )
        self.assertIn("sono celiaco", message)

    def test_e_una_funzione_pura_senza_rete(self):
        # nessun mock necessario: se toccasse la rete, questo test fallirebbe
        # in ambiente isolato — ed è esattamente il contratto che vogliamo.
        self.assertEqual(self._message(), self._message())


class TestNormalizeTips(unittest.TestCase):
    def setUp(self):
        self.categories = select_categories(_trip())
        self.candidates = build_indoor_candidates(POIS, ITINERARY)

    def test_ordine_di_stampa_deterministico_non_quello_del_modello(self):
        raw = {"sections": [
            {"category_id": "su_misura", "tips": ["ultimo"]},
            {"category_id": "biglietti_prenotazioni", "tips": ["primo"]},
        ]}
        result = normalize_tips(raw, self.categories, self.candidates)
        self.assertEqual(
            [s["category_id"] for s in result["sections"]],
            ["biglietti_prenotazioni", "su_misura"],
        )

    def test_categoria_inventata_dal_modello_viene_scartata(self):
        raw = {"sections": [{"category_id": "categoria_fantasma", "tips": ["x"]}]}
        self.assertEqual(normalize_tips(raw, self.categories, self.candidates)["sections"], [])

    def test_sezione_vuota_non_finisce_nel_documento(self):
        raw = {"sections": [
            {"category_id": "fotografia", "tips": []},
            {"category_id": "su_misura", "tips": ["   ", None, 42]},
        ]}
        self.assertEqual(normalize_tips(raw, self.categories, self.candidates)["sections"], [])

    def test_titolo_aggiunto_dal_codice_non_dal_modello(self):
        raw = {"sections": [{"category_id": "fotografia", "tips": ["scatta all'ora d'oro"]}]}
        section = normalize_tips(raw, self.categories, self.candidates)["sections"][0]
        self.assertEqual(section["title"], "Fotografia e punti panoramici")

    def test_swap_con_poi_inventato_viene_scartato(self):
        # IL test di questo file: Fedeltà RAG sul piano B.
        raw = {"sections": [{"category_id": "su_misura", "tips": ["ok"]}], "rain_plans": [
            {"day": 1, "summary": "Sposta tutto al chiuso", "swaps": [
                {"replaces": "Boboli", "poi_id": "P4", "why": "coperto e vicino"},
                {"replaces": "Boboli", "poi_id": "MUSEO_INVENTATO", "why": "non esiste"},
            ]},
        ]}
        result = normalize_tips(raw, self.categories, self.candidates)
        swaps = result["rain_plans"][0]["swaps"]
        self.assertEqual([s["poi_id"] for s in swaps], ["P4"])
        self.assertEqual(result["dropped_swaps"], 1)

    def test_nome_dello_swap_preso_dai_dati_reali_non_dal_modello(self):
        raw = {"sections": [{"category_id": "su_misura", "tips": ["ok"]}], "rain_plans": [
            {"day": 1, "summary": "piano", "swaps": [
                {"replaces": "x", "poi_id": "P4", "why": "y", "name": "Nome Inventato"},
            ]},
        ]}
        swap = normalize_tips(raw, self.categories, self.candidates)["rain_plans"][0]["swaps"][0]
        self.assertEqual(swap["name"], "Bargello")

    def test_piano_b_senza_alternative_resta_valido(self):
        raw = {"sections": [{"category_id": "su_misura", "tips": ["ok"]}], "rain_plans": [
            {"day": 1, "summary": "Inverti l'ordine: musei la mattina.", "swaps": []},
        ]}
        result = normalize_tips(raw, self.categories, self.candidates)
        self.assertEqual(len(result["rain_plans"]), 1)
        self.assertEqual(result["rain_plans"][0]["swaps"], [])

    def test_piano_b_senza_summary_viene_scartato(self):
        raw = {"sections": [{"category_id": "su_misura", "tips": ["ok"]}],
               "rain_plans": [{"day": 1, "summary": "", "swaps": []}]}
        self.assertEqual(normalize_tips(raw, self.categories, self.candidates)["rain_plans"], [])

    def test_piani_b_ordinati_per_giorno(self):
        raw = {"sections": [{"category_id": "su_misura", "tips": ["ok"]}], "rain_plans": [
            {"day": 3, "summary": "c"}, {"day": 1, "summary": "a"}, {"day": None, "summary": "z"},
        ]}
        days = [p["day"] for p in normalize_tips(raw, self.categories, self.candidates)["rain_plans"]]
        self.assertEqual(days, [1, 3, None])

    def test_spazi_multipli_normalizzati(self):
        raw = {"sections": [{"category_id": "su_misura", "tips": ["  a   b \n c "]}]}
        tip = normalize_tips(raw, self.categories, self.candidates)["sections"][0]["tips"][0]
        self.assertEqual(tip, "a b c")

    def test_forme_malformate_non_sollevano_mai(self):
        for raw in (None, {}, {"sections": "no"}, {"sections": [None, 5]},
                    {"rain_plans": [None, "x"]}, {"sections": [{"category_id": 7, "tips": ["a"]}]}):
            with self.subTest(raw=raw):
                result = normalize_tips(raw, self.categories, self.candidates)
                self.assertIn("sections", result)
                self.assertIn("rain_plans", result)


class TestValidateShape(unittest.TestCase):
    def test_scalare_json_da_errore_pulito(self):
        with self.assertRaises(TipsGeneratorError):
            _validate_tips_shape(42)

    def test_sections_mancanti_da_errore_pulito(self):
        with self.assertRaises(TipsGeneratorError):
            _validate_tips_shape({"rain_plans": []})

    def test_rain_plans_di_tipo_sbagliato_da_errore_pulito(self):
        with self.assertRaises(TipsGeneratorError):
            _validate_tips_shape({"sections": [{"category_id": "x", "tips": []}], "rain_plans": {}})

    def test_forma_valida_passa(self):
        _validate_tips_shape({"sections": [{"category_id": "su_misura", "tips": ["a"]}]})


def _mock_anthropic(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    client = MagicMock()
    client.messages.create.return_value = response
    module = MagicMock()
    module.Anthropic.return_value = client
    return module, client


class TestGenerateArchitectTips(unittest.TestCase):
    def _run(self, text, stop_reason="end_turn"):
        module, client = _mock_anthropic(text, stop_reason)
        with patch.dict("sys.modules", {"anthropic": module}):
            result = generate_architect_tips(
                _trip(), ITINERARY, api_key="fake-key",
                hotels=[], pois=POIS, objective_function="BALANCED",
            )
        return result, client

    def test_percorso_felice(self):
        payload = (
            '{"sections": [{"category_id": "pratico_sicurezza", '
            '"tips": ["Il numero unico di emergenza in Italia è il 112."]}], '
            '"rain_plans": [{"day": 1, "summary": "Anticipa gli Uffizi.", '
            '"swaps": [{"replaces": "Boboli", "poi_id": "P4", "why": "tutto al coperto"}]}]}'
        )
        result, client = self._run(payload)
        self.assertEqual(result["sections"][0]["title"], "Pratico e sicurezza")
        self.assertEqual(result["rain_plans"][0]["swaps"][0]["name"], "Bargello")
        self.assertEqual(result["dropped_swaps"], 0)

    def test_i_fatti_verificati_arrivano_davvero_nel_prompt(self):
        payload = '{"sections": [{"category_id": "su_misura", "tips": ["ok"]}]}'
        _, client = self._run(payload)
        sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("FATTI_VERIFICATI", sent)
        self.assertIn("112", sent)  # numero di emergenza reale, non generato

    def test_fence_markdown_avvolgente_gestita(self):
        payload = '```json\n{"sections": [{"category_id": "su_misura", "tips": ["ok"]}]}\n```'
        result, _ = self._run(payload)
        self.assertEqual(len(result["sections"]), 1)

    def test_json_non_valido_da_errore_esplicito(self):
        with self.assertRaises(TipsGeneratorError):
            self._run("non sono json")

    def test_troncamento_rilevato(self):
        with self.assertRaises(TipsGeneratorError) as ctx:
            self._run('{"sections": [{"category_id": "su_misura",', stop_reason="max_tokens")
        self.assertIn("max_tokens", str(ctx.exception))

    def test_usa_il_system_prompt_dedicato(self):
        _, client = self._run('{"sections": [{"category_id": "su_misura", "tips": ["ok"]}]}')
        system = client.messages.create.call_args.kwargs["system"]
        self.assertIn("[OUTPUT_CONTRACT]", system)
        self.assertIn("ALTERNATIVE_AL_CHIUSO_DISPONIBILI", system)


class TestRenderMarkdown(unittest.TestCase):
    def test_rende_sezioni_e_piani(self):
        tips = {
            "sections": [{"category_id": "fotografia", "title": "Fotografia", "tips": ["a", "b"]}],
            "rain_plans": [{"day": 2, "summary": "riorganizza", "swaps": [
                {"replaces": "parco", "poi_id": "P4", "name": "Bargello", "why": "coperto"}]}],
        }
        markdown = render_tips_markdown(tips)
        self.assertIn("## Fotografia", markdown)
        self.assertIn("- a", markdown)
        self.assertIn("## Giorno 2", markdown)
        self.assertIn("Bargello", markdown)

    def test_struttura_vuota_non_solleva(self):
        self.assertIn("Consigli", render_tips_markdown({}))


if __name__ == "__main__":
    unittest.main()
