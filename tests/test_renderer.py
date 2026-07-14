"""
[AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima suite di test mai
scritta per src/renderer.py (Nodo 10A) — un gap notato durante la
revisione sistematica pre-lancio. Copre il rendering base e, in
particolare, il bug trovato in audit: `if poi_id` (truthy) trattava un
poi_id="" (stringa vuota) come equivalente a None, renderizzando
"[SLOT LIBERO]" — nascondendo silenziosamente proprio il caso che
validator.py/scenario_checks.py segnalerebbero altrove nello stesso run
come id non riconosciuto. Ora `poi_id is None` è l'unico caso "nessun
POI", coerente con la convenzione usata in tutto il resto del prototipo.
"""
import unittest
from src.renderer import render_markdown

TRIP = {
    "destination": "Roma",
    "objective_function": "BALANCED",
    "date_start": "2026-09-01",
    "date_end": "2026-09-04",
    "duration_days": 3,
    "budget_mode": "UNLIMITED",
    "budget_eur": 0,
}


class TestRenderMarkdown(unittest.TestCase):
    def test_basic_rendering_includes_destination_and_summary(self):
        itinerary = {
            "destination": "Roma",
            "executive_summary": "Un bel viaggio.",
            "days": [],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("Roma", out)
        self.assertIn("Un bel viaggio.", out)

    def test_poi_id_present_renders_as_bracketed_id(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Giorno 1", "blocks": [
                {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "POI1"},
            ]}],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("`[POI1]`", out)
        self.assertNotIn("SLOT LIBERO", out)

    def test_poi_id_none_renders_as_slot_libero(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Giorno 1", "blocks": [
                {"time": "09:00", "activity": "Tempo libero", "location": "", "poi_id": None},
            ]}],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("SLOT LIBERO", out)

    def test_empty_string_poi_id_is_not_hidden_as_slot_libero(self):
        # [AGGIUNTO 2026-07-11] Il bug specifico trovato in audit: prima,
        # poi_id="" (falsy ma non None) veniva reso "[SLOT LIBERO]" come se
        # fosse un blocco senza POI — nascondendo un caso che il Nodo 9
        # (Fedeltà RAG) segnalerebbe come id non riconosciuto. Ora deve
        # apparire visibilmente diverso da un vero [SLOT LIBERO].
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "title": "Giorno 1", "blocks": [
                {"time": "09:00", "activity": "Sospetto", "location": "", "poi_id": ""},
            ]}],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertNotIn("SLOT LIBERO", out)
        self.assertIn("`[]`", out)

    def test_budget_alert_rendered_when_present(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x", "days": [],
            "budget_alert": "Budget insufficiente per l'hotel richiesto.",
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("Avviso Budget", out)
        self.assertIn("Budget insufficiente", out)

    def test_no_budget_alert_when_absent(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_markdown(itinerary, TRIP)
        self.assertNotIn("Avviso Budget", out)

    def test_zero_days_does_not_crash(self):
        itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}
        out = render_markdown(itinerary, TRIP)
        self.assertIsInstance(out, str)

    def test_block_missing_optional_fields_does_not_crash(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x",
            "days": [{"day": 1, "blocks": [{"time": "09:00", "activity": "X", "poi_id": None}]}],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("09:00", out)

    def test_architect_tips_rendered_when_present(self):
        itinerary = {
            "destination": "Roma", "executive_summary": "x", "days": [],
            "architect_tips": ["Consiglio uno", "Consiglio due"],
        }
        out = render_markdown(itinerary, TRIP)
        self.assertIn("Architect's Tips", out)
        self.assertIn("Consiglio uno", out)
        self.assertIn("Consiglio due", out)


class TestMultiPlatformSearchLinks(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: "questa
    integrazione multi-piattaforma la facciamo"] Copre il nuovo parametro
    opzionale `hotels` di render_markdown() — vedi la nota estesa nel
    docstring della funzione e in affiliate_links.py per il razionale
    completo (link di ricerca pubblica, non dati live).
    """

    def setUp(self):
        self.itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}

    def test_no_hotels_param_no_section_rendered(self):
        # Comportamento di default invariato — TUTTI i test sopra in questo
        # file chiamano render_markdown() senza `hotels` e devono continuare
        # a funzionare identicamente (nessuna sezione aggiunta).
        out = render_markdown(self.itinerary, TRIP)
        self.assertNotIn("Confronta anche su altre piattaforme", out)

    def test_empty_hotels_list_no_section_rendered(self):
        out = render_markdown(self.itinerary, TRIP, hotels=[])
        self.assertNotIn("Confronta anche su altre piattaforme", out)

    def test_hotels_provided_renders_section_with_all_three_platforms(self):
        hotels = [{"name": "TURIM Boulevard Hotel", "property_type": "Hotels"}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertIn("Confronta anche su altre piattaforme", out)
        self.assertIn("TURIM Boulevard Hotel", out)
        self.assertIn("booking.com", out.lower())
        self.assertIn("airbnb.com", out.lower())
        self.assertIn("vrbo.com", out.lower())

    def test_property_type_shown_when_present(self):
        hotels = [{"name": "Lisbon Art Stay Apartments", "property_type": "Apartments"}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertIn("Apartments", out)

    def test_missing_property_type_falls_back_to_neutral_term_not_invented(self):
        hotels = [{"name": "Struttura X"}]  # nessun property_type — fixture/mock vecchi
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertIn("alloggio", out)

    def test_multiple_hotels_each_get_own_links(self):
        hotels = [
            {"name": "Hotel Uno", "property_type": "Hotels"},
            {"name": "Villa Due", "property_type": "Villas"},
        ]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertIn("Hotel Uno", out)
        self.assertIn("Villa Due", out)

    def test_explicit_none_name_falls_back_to_placeholder(self):
        # [AGGIUNTO 2026-07-11 — audit mirato] Prima: `h.get("name",
        # "[Da Verificare]")` applicava il default SOLO se la chiave
        # mancava, non se presente con valore `None` — renderizzava
        # letteralmente "None" invece del placeholder onesto.
        hotels = [{"name": None, "property_type": "Hotels"}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        # Il testo del placeholder viene sfuggito come qualunque altro testo
        # di link (stesso trattamento imparziale del bug sulle parentesi
        # sotto) — visivamente identico ("[Da Verificare]"), solo la
        # rappresentazione Markdown grezza ha i backslash di escape.
        self.assertIn("Da Verificare", out)
        self.assertNotIn("**None**", out)

    def test_destination_with_brackets_does_not_break_link_syntax(self):
        # [AGGIUNTO 2026-07-11 — audit mirato] Una destinazione con `]`/`(`/
        # `)` chiudeva prematuramente il testo del link Markdown,
        # iniettando una parentesi/bracket falsi accanto all'URL reale.
        trip = dict(TRIP, destination="Roma] (evil.com)[click qui")
        hotels = [{"name": "Hotel Test", "property_type": "Hotels"}]
        out = render_markdown(self.itinerary, trip, hotels=hotels)
        # Il markdown risultante deve avere i caratteri speciali sfuggiti,
        # non un secondo `](url)` iniettato subito dopo il testo previsto.
        self.assertNotIn("evil.com)[click qui](https", out)
        self.assertIn("\\]", out)
        self.assertIn("\\(", out)

    def test_hotel_name_with_brackets_does_not_break_link_syntax(self):
        hotels = [{"name": "Hotel [Fake](url) Test", "property_type": "Hotels"}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertNotIn("**Hotel [Fake](url) Test**", out)


class TestHotelPriceAndCuratedPoiSections(unittest.TestCase):
    """[AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo",
    "ristoranti"/"intrattenimento"] Copre il nuovo parametro `poi` e il
    prezzo/notte nella sezione hotel di render_markdown()."""

    def setUp(self):
        self.itinerary = {"destination": "Roma", "executive_summary": "x", "days": []}

    def test_hotel_price_per_night_shown(self):
        hotels = [{"name": "Hotel Test", "property_type": "Hotels", "price_night_eur": 150.0}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertIn("150.0€/notte", out)

    def test_hotel_without_price_omits_suffix(self):
        hotels = [{"name": "Hotel Test", "property_type": "Hotels", "price_night_eur": None}]
        out = render_markdown(self.itinerary, TRIP, hotels=hotels)
        self.assertNotIn("None€/notte", out)

    def test_curated_restaurant_and_activity_sections_grouped(self):
        poi = [
            {"id": "POI1", "type": "restaurant", "name": "Trattoria Toscana", "price_level": "MODERATE"},
            {"id": "POI3", "type": "museum", "name": "Museo del Vino", "price_level": "INEXPENSIVE"},
        ]
        out = render_markdown(self.itinerary, TRIP, poi=poi)
        self.assertIn("Dove mangiare", out)
        self.assertIn("Trattoria Toscana", out)
        # [CORRETTO 2026-07-13 — audit di revisione completa, gap di
        # mutation-testing trovato dall'agente di audit qualità test]
        # `assertIn("€€", out)` è debole: combacerebbe anche con un
        # simbolo sbagliato "€€€" (EXPENSIVE) o "€€€€" (VERY_EXPENSIVE),
        # dato che "€€" è una sottostringa di entrambi — non avrebbe
        # rilevato una mutazione che restituisse il simbolo di fascia di
        # prezzo sbagliata. Il formato esatto atteso include le parentesi
        # chiuse, che delimitano il simbolo (vedi renderer.py riga 137).
        self.assertIn("Trattoria Toscana (€€) `[POI1]`", out)
        self.assertNotIn("(€€€)", out)
        self.assertIn("Cosa fare", out)
        self.assertIn("Museo del Vino", out)
        # Strumento di revisione interna: a differenza del PDF cliente,
        # l'id resta visibile per audit.
        self.assertIn("[POI1]", out)
        self.assertIn("[POI3]", out)

    def test_no_poi_no_curated_section(self):
        out = render_markdown(self.itinerary, TRIP)
        self.assertNotIn("Ristoranti e intrattenimento", out)

    def test_poi_without_price_level_no_fake_symbol(self):
        poi = [{"id": "POI4", "type": "activity", "name": "Escursione", "price_level": None}]
        out = render_markdown(self.itinerary, TRIP, poi=poi)
        self.assertIn("Escursione `[POI4]`", out)

    def test_curated_shopping_section_grouped_separately(self):
        # [AGGIUNTO 2026-07-13 (ter) — categoria shopping, stesso terzo
        # bucket aggiunto in pdf_renderer.py — verifica che questo
        # strumento di revisione interna non sia rimasto disallineato dal
        # documento cliente reale.]
        poi = [{"id": "POI5", "type": "shopping", "name": "Mercato di San Lorenzo", "price_level": None}]
        out = render_markdown(self.itinerary, TRIP, poi=poi)
        self.assertIn("Shopping", out)
        self.assertIn("Mercato di San Lorenzo `[POI5]`", out)


if __name__ == "__main__":
    unittest.main()
