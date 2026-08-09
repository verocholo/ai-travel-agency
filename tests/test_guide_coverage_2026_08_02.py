"""
[NUOVO 2026-08-02 — task #165, richiesta testuale di Lorenzo: "la parte
della guida turistica va migliorata: deve esserci una guida per ogni cosa
che lo richieda, non aver paura di sembrare prolisso è una cosa molto
interessante"]

Perché questa suite esiste, e perché è separata da test_guide_generator.py.

`test_guide_generator.py` copre il CONTRATTO di una singola guida: che il
JSON di Claude venga validato, che una risposta troncata sollevi un errore
leggibile, che il markdown contenga tutte le sezioni. Non ha mai coperto —
perché fino a ieri non esisteva come funzione — la domanda a monte: *per
quali tappe dell'itinerario una guida va chiesta?*

Quella regola viveva implicita dentro un ciclo di `pdf_extras.py`
(`for poi_id in sorted(extract_used_poi_ids(itinerary))`) ed era sbagliata
in DUE direzioni opposte, il che è esattamente il tipo di difetto che
nessun test coglie finché non lo si nomina:

- troppo stretta: un blocco senza `poi_id` ("mattinata nel quartiere di
  Alfama") non produceva nulla, pur essendo la tappa che più di ogni altra
  aveva bisogno di essere raccontata;
- troppo larga: una trattoria da trenta coperti riceveva "storia e
  contesto culturale" — tre paragrafi che il modello non poteva sapere e
  quindi inventava, bruciando un token budget reale per peggiorare il
  documento.

Ora la regola è pura, esplicita e in un posto solo (`select_guide_targets`),
quindi è testabile senza rete e senza mock. Questi test la inchiodano.
"""
import unittest

from src.guide_generator import (
    GuideGeneratorError,
    GuideSkipped,
    NOTABLE_REVIEW_COUNT,
    SKIP_MARKER,
    build_guide_user_message,
    looks_like_a_place,
    normalize_string_list,
    select_guide_targets,
    _validate_guide_shape,
)
from src.pdf_renderer import _paragraphs, _render_guide_section
from src.schemas import POI


def _poi(pid, poi_type, name, reviews=None):
    p = POI(id=pid, type=poi_type, name=name, lat=41.9, lng=12.5)
    p.user_rating_count = reviews
    return p


def _itin(*blocks_per_day):
    return {
        "days": [
            {"day": i + 1, "blocks": list(blocks)}
            for i, blocks in enumerate(blocks_per_day)
        ]
    }


class TestSelectGuideTargetsPoiRule(unittest.TestCase):
    """Quali POI con scheda Google meritano una guida."""

    def test_museum_activity_shopping_always_get_a_guide(self):
        # I tre tipi che il cliente "visita": su questi la conoscenza
        # generale del modello è reale e la guida ha sostanza.
        pois = {
            "M": _poi("M", "museum", "Museo Etrusco"),
            "A": _poi("A", "activity", "Terme di San Filippo"),
            "S": _poi("S", "shopping", "Mercato Centrale"),
        }
        itinerary = _itin([
            {"activity": "Visita", "poi_id": "M"},
            {"activity": "Visita", "poi_id": "A"},
            {"activity": "Visita", "poi_id": "S"},
        ])
        keys = [t["key"] for t in select_guide_targets(itinerary, pois)]
        self.assertEqual(keys, ["M", "A", "S"])

    def test_ordinary_restaurant_gets_no_guide(self):
        # Il difetto "troppo larga": su una trattoria qualunque il modello
        # non ha storia da raccontare, quindi la inventerebbe.
        pois = {"R": _poi("R", "restaurant", "Trattoria da Mario", reviews=120)}
        itinerary = _itin([{"activity": "Cena", "poi_id": "R"}])
        self.assertEqual(select_guide_targets(itinerary, pois), [])

    def test_restaurant_without_review_count_gets_no_guide(self):
        # Dato assente non è dato favorevole: nel dubbio non si scrive.
        pois = {"R": _poi("R", "restaurant", "Osteria senza dati", reviews=None)}
        itinerary = _itin([{"activity": "Cena", "poi_id": "R"}])
        self.assertEqual(select_guide_targets(itinerary, pois), [])

    def test_notable_restaurant_does_get_a_guide(self):
        # Un locale con migliaia di recensioni è un'istituzione cittadina:
        # lì la storia esiste davvero ed è nota.
        pois = {"R": _poi("R", "restaurant", "Antico Caffè", reviews=NOTABLE_REVIEW_COUNT)}
        itinerary = _itin([{"activity": "Cena", "poi_id": "R"}])
        targets = select_guide_targets(itinerary, pois)
        self.assertEqual([t["key"] for t in targets], ["R"])
        self.assertIn("recensioni", targets[0]["reason"])

    def test_threshold_is_inclusive_at_the_boundary(self):
        # Il confine è la parte che si sbaglia in un refactor distratto.
        pois = {
            "SOTTO": _poi("SOTTO", "restaurant", "Sotto", reviews=NOTABLE_REVIEW_COUNT - 1),
            "SOPRA": _poi("SOPRA", "restaurant", "Sopra", reviews=NOTABLE_REVIEW_COUNT),
        }
        itinerary = _itin([
            {"activity": "Pranzo", "poi_id": "SOTTO"},
            {"activity": "Cena", "poi_id": "SOPRA"},
        ])
        self.assertEqual([t["key"] for t in select_guide_targets(itinerary, pois)], ["SOPRA"])

    def test_unknown_type_is_treated_as_a_place_to_visit(self):
        # Se un domani places_client normalizzasse un tipo nuovo, il
        # default deve essere "scrivi", non "taci in silenzio": una guida
        # di troppo si nota e si corregge, una mancante no.
        pois = {"X": _poi("X", "belvedere", "Punto panoramico")}
        itinerary = _itin([{"activity": "Sosta", "poi_id": "X"}])
        self.assertEqual([t["key"] for t in select_guide_targets(itinerary, pois)], ["X"])


class TestSelectGuideTargetsBlockRule(unittest.TestCase):
    """Il difetto "troppo stretta": tappe senza scheda Google."""

    def test_block_naming_a_place_becomes_a_target(self):
        itinerary = _itin([{"activity": "Mattinata nel quartiere di Alfama"}])
        targets = select_guide_targets(itinerary, {})
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["kind"], "blocco")
        self.assertIsNone(targets[0]["poi_id"])
        self.assertEqual(targets[0]["name"], "Mattinata nel quartiere di Alfama")

    def test_purely_logistic_blocks_produce_nothing(self):
        # Nessuna di queste righe nasconde un luogo: chiedere una guida
        # significherebbe pagare una chiamata a Claude per farsi dire
        # "skip", o peggio per ricevere una pagina inventata.
        for testo in (
            "Trasferimento in hotel",
            "Cena",
            "Tempo libero",
            "Check-in e sistemazione bagagli",
            "Rientro in hotel e riposo",
            "Partenza",
        ):
            with self.subTest(testo=testo):
                itinerary = _itin([{"activity": testo}])
                self.assertEqual(select_guide_targets(itinerary, {}), [], testo)

    def test_empty_or_missing_activity_produces_nothing(self):
        itinerary = _itin([{"activity": ""}, {"time": "09:00"}, {}])
        self.assertEqual(select_guide_targets(itinerary, {}), [])

    def test_looks_like_a_place_is_the_underlying_rule(self):
        self.assertTrue(looks_like_a_place("Visita al Castello Sforzesco"))
        self.assertFalse(looks_like_a_place("Cena e rientro in hotel"))
        self.assertFalse(looks_like_a_place(""))
        self.assertFalse(looks_like_a_place(None))


class TestSelectGuideTargetsOrderAndDedup(unittest.TestCase):
    def test_targets_come_out_in_visit_order_not_alphabetical(self):
        # L'ordine vecchio era `sorted(poi_ids)`: alfabetico sugli ID
        # opachi di Google, cioè casuale per il lettore. Le guide in fondo
        # al documento devono seguire l'ordine in cui il cliente incontra
        # i luoghi, così sfogliandole ripercorre il viaggio.
        pois = {
            "zzz": _poi("zzz", "museum", "Primo visitato"),
            "aaa": _poi("aaa", "museum", "Secondo visitato"),
        }
        itinerary = _itin(
            [{"activity": "Visita", "poi_id": "zzz"}],
            [{"activity": "Visita", "poi_id": "aaa"}],
        )
        self.assertEqual([t["key"] for t in select_guide_targets(itinerary, pois)], ["zzz", "aaa"])

    def test_a_place_visited_twice_gets_one_guide(self):
        pois = {"M": _poi("M", "museum", "Museo")}
        itinerary = _itin(
            [{"activity": "Visita", "poi_id": "M"}],
            [{"activity": "Seconda visita", "poi_id": "M"}],
        )
        self.assertEqual(len(select_guide_targets(itinerary, pois)), 1)

    def test_identical_free_text_blocks_are_deduplicated(self):
        itinerary = _itin(
            [{"activity": "Passeggiata sul lungomare Caracciolo"}],
            [{"activity": "Passeggiata sul lungomare Caracciolo"}],
        )
        self.assertEqual(len(select_guide_targets(itinerary, {})), 1)

    def test_unknown_poi_id_falls_back_to_the_text_rule(self):
        # `poi_id` che non risolve (payload disallineato): il blocco non
        # va perso in silenzio, si valuta il suo testo.
        itinerary = _itin([{"activity": "Visita alla Certosa di Pavia", "poi_id": "MANCANTE"}])
        targets = select_guide_targets(itinerary, {})
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["kind"], "blocco")

    def test_malformed_itinerary_never_raises(self):
        for bad in (None, {}, {"days": None}, {"days": [None]}, {"days": [{"blocks": None}]},
                    {"days": [{"blocks": [None, "stringa"]}]}):
            with self.subTest(bad=bad):
                self.assertEqual(select_guide_targets(bad, {}), [])


class TestSkipContract(unittest.TestCase):
    """{"skip": true} è un esito legittimo, non un guasto."""

    def test_skip_marker_raises_guide_skipped(self):
        with self.assertRaises(GuideSkipped):
            _validate_guide_shape({SKIP_MARKER: True}, "riga di programma")

    def test_guide_skipped_is_not_a_generator_error(self):
        # Distinzione voluta: un guasto vero va contato e indagato, una
        # pagina saltata è il sistema che funziona. Se GuideSkipped
        # ereditasse da GuideGeneratorError i due casi si confonderebbero
        # nei log e nessuno saprebbe più se le guide mancanti sono un
        # problema.
        self.assertFalse(issubclass(GuideSkipped, GuideGeneratorError))

    def test_skip_is_checked_before_required_fields(self):
        # Una risposta di skip non ha né title né history_summary: se il
        # controllo dei campi obbligatori girasse per primo, lo skip
        # arriverebbe al chiamante travestito da errore di formato.
        try:
            _validate_guide_shape({SKIP_MARKER: True}, "x")
        except GuideSkipped:
            pass
        except GuideGeneratorError as e:  # pragma: no cover - è il fallimento
            self.fail(f"skip scambiato per errore di formato: {e}")

    def test_block_kind_tells_the_model_it_may_skip(self):
        msg = build_guide_user_message("Mattinata libera ad Alfama", "Lisbona", kind="blocco")
        self.assertIn(SKIP_MARKER, msg)
        msg_poi = build_guide_user_message("Torre di Belém", "Lisbona", kind="poi")
        self.assertNotIn(SKIP_MARKER, msg_poi)


class TestNormalizeStringList(unittest.TestCase):
    def test_plain_list_passes_through(self):
        self.assertEqual(normalize_string_list(["a", "b"]), ["a", "b"])

    def test_bare_string_becomes_a_one_item_list(self):
        # Errore ricorrente dei modelli quando un campo lista contiene una
        # sola voce. Costava l'intera guida per un dettaglio di forma.
        self.assertEqual(normalize_string_list("una sola curiosità"), ["una sola curiosità"])

    def test_dicts_are_flattened_to_their_text(self):
        self.assertEqual(normalize_string_list([{"text": "primo"}, {"why": "secondo"}]),
                         ["primo", "secondo"])

    def test_empty_and_none_give_an_empty_list(self):
        for raw in (None, "", [], ["", "   "], 42):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_string_list(raw), [])


class TestParagraphRendering(unittest.TestCase):
    """
    Il difetto che avrebbe reso "scrivi di più" un peggioramento: il
    renderer incollava `history_summary` in un unico blocco, quindi più il
    modello scriveva, più il cliente riceveva un muro di testo.
    """

    def test_double_newline_becomes_separate_paragraphs(self):
        out = _paragraphs("Primo.\n\nSecondo.\n\nTerzo.")
        self.assertEqual(out.count("<p class='guide-para'>"), 3)

    def test_single_newlines_are_used_only_as_a_fallback(self):
        self.assertEqual(_paragraphs("Riga uno\nRiga due").count("<p class='guide-para'>"), 2)
        self.assertEqual(_paragraphs("Una frase sola.").count("<p class='guide-para'>"), 1)

    def test_empty_input_renders_nothing(self):
        for raw in (None, "", "   ", "\n\n"):
            with self.subTest(raw=raw):
                self.assertEqual(_paragraphs(raw), "")

    def test_content_is_escaped(self):
        self.assertNotIn("<script>", _paragraphs("<script>alert(1)</script>"))


class TestGuideCardMarkup(unittest.TestCase):
    def _guide(self, **extra):
        guide = {
            "poi_id": "P1",
            "poi_name": "Colosseo",
            "title": "Il Colosseo",
            "history_summary": "Primo paragrafo.\n\nSecondo paragrafo.",
            "practical_tips": ["Scarpe comode"],
            "best_time_to_visit": "Primo mattino",
            "estimated_visit_duration": "2-3 ore",
            "consiglio_personalizzato": "Sali con calma",
            "disclaimer": "Verifica orari e prezzi sul sito ufficiale",
        }
        guide.update(extra)
        return guide

    def test_multi_paragraph_history_is_not_collapsed(self):
        out = _render_guide_section(self._guide())
        self.assertEqual(out.count("<p class='guide-para'>"), 2)

    def test_new_fields_render_when_present(self):
        out = _render_guide_section(self._guide(
            highlights=[{"name": "Arena", "why": "il piano dei sotterranei"}],
            curiosita=["Il velario era manovrato dai marinai della flotta"],
            errore_da_evitare="Mettersi nella coda dei biglietti invece che in quella dei prenotati",
            dintorni=[{"name": "Colle Oppio", "why": "la vista dall'alto"}],
        ))
        self.assertIn("guide-sub", out)
        self.assertIn("guide-warn", out)
        self.assertIn("Arena", out)
        self.assertIn("velario", out)
        self.assertIn("Colle Oppio", out)

    def test_absent_optional_fields_leave_no_empty_headings(self):
        out = _render_guide_section(self._guide())
        self.assertNotIn("guide-warn", out)
        self.assertNotIn("A due passi", out)
        self.assertNotIn("Da sapere", out)


if __name__ == "__main__":
    unittest.main()
