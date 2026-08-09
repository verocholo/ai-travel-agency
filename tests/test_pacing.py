"""
[NUOVO 2026-08-02 — task #166, richiesta di Lorenzo dopo aver riletto un PDF
reale: "tra le varie attività mi sembra che ci sia ancora troppo tempo con il
rischio che la gente si annoi oppure finisca prima, valuta tu caso per caso ma
stacci molto attento"]

Test di `src/pacing.py` e del suo innesto nel documento e nel validator.

Perché questa suite è scritta come è scritta. La stessa lamentela era già
arrivata il 2026-07-31 e aveva prodotto due difese: una regola in prosa nel
system prompt e un termometro nel validator tarato a 180 minuti uguali per
tutti. Lorenzo ha riletto un PDF generato DOPO quelle difese e ha trovato lo
stesso difetto. Quindi qui non basta verificare che il codice nuovo faccia
quello che dice: bisogna verificare le due cose che avevano lasciato passare
il difetto la volta scorsa, e sono entrambe testate sotto —

  1) che la soglia sia davvero SPECIFICA DEL LUOGO e non un numero unico
     (`TestDensityThresholdIsPerPlace`): il caso reale — 40 minuti di visita
     a cui sono state assegnate due ore e mezza — passa sotto qualunque
     soglia piatta a tre ore, ed è esattamente il caso che deve fallire;

  2) che la tabella nel prompt e la tabella nel codice non possano divergere
     (`TestPromptTableStaysAligned`). Sono due copie della stessa
     conoscenza, in due file diversi, che nessuno rileggerà mai insieme. Il
     giorno in cui divergono, il validator emette warning su itinerari che
     hanno seguito le istruzioni alla lettera: il falso positivo che insegna
     a ignorare i warning, cioè il modo in cui un controllo muore senza che
     nessuno se ne accorga. Il test lo impedisce leggendo davvero il file
     del prompt e confrontando i numeri.
"""

import re
import unittest
from pathlib import Path

from src import pacing
from src import pdf_renderer
from src.validator import check_day_density


def _block(time, activity="Attività", poi_id=None):
    return {"time": time, "activity": activity, "location": "x", "poi_id": poi_id}


class _Poi:
    """POI minimo: a `pacing` servono solo `type` e `primary_type`."""

    def __init__(self, poi_type=None, primary_type=None):
        self.type = poi_type
        self.primary_type = primary_type


class TestTimeHelpers(unittest.TestCase):
    def test_parses_valid_times(self):
        self.assertEqual(pacing._to_minutes("09:30"), 570)
        self.assertEqual(pacing._to_minutes("00:00"), 0)
        self.assertEqual(pacing._to_minutes("23:59"), 1439)

    def test_rejects_everything_else_without_raising(self):
        for bad in (None, 930, "9.30", "", "24:00", "09:60", "-1:00", "ore nove", ["09:00"]):
            self.assertIsNone(pacing._to_minutes(bad), bad)

    def test_formats_back(self):
        self.assertEqual(pacing._to_hhmm(570), "09:30")
        self.assertEqual(pacing._to_hhmm(0), "00:00")

    def test_formatting_wraps_past_midnight(self):
        # Una cena alle 23:00 con durata tipica 2h finirebbe alle 25:00: un
        # orario che non esiste e che il cliente leggerebbe come un errore.
        self.assertEqual(pacing._to_hhmm(25 * 60), "01:00")

    def test_duration_is_written_the_way_people_write_it(self):
        self.assertEqual(pacing.describe_duration(45), "45 min")
        self.assertEqual(pacing.describe_duration(60), "1h")
        self.assertEqual(pacing.describe_duration(90), "1h30")
        self.assertEqual(pacing.describe_duration(125), "2h05")
        self.assertEqual(pacing.describe_duration(0), "0 min")

    def test_negative_duration_never_printed(self):
        self.assertEqual(pacing.describe_duration(-30), "0 min")

    def test_typical_span_collapses_when_extremes_coincide(self):
        self.assertEqual(pacing.describe_typical((60, 105)), "1h-1h45")
        self.assertEqual(pacing.describe_typical((45, 45)), "45 min")


class TestTypicalMinutesFor(unittest.TestCase):
    def test_primary_type_wins_over_normalized_type(self):
        # È il punto della tabella: `art_gallery` non è `museum`, e il tipo
        # normalizzato di places_client li appiattisce entrambi su "museum".
        poi = _Poi(poi_type="museum", primary_type="art_gallery")
        self.assertEqual(pacing.typical_minutes_for(poi), pacing.TYPICAL_VISIT_MINUTES["art_gallery"])

    def test_falls_back_to_normalized_type(self):
        poi = _Poi(poi_type="museum", primary_type="tipo_che_google_ha_inventato_ieri")
        self.assertEqual(pacing.typical_minutes_for(poi), pacing.TYPICAL_VISIT_MINUTES["museum"])

    def test_unknown_place_gets_the_wide_default(self):
        self.assertEqual(pacing.typical_minutes_for(_Poi()), pacing.DEFAULT_VISIT_MINUTES)
        self.assertEqual(pacing.typical_minutes_for(None), pacing.DEFAULT_VISIT_MINUTES)

    def test_accepts_a_dict_as_well_as_an_object(self):
        # Il renderer maneggia i POI come dict, il validator come oggetti:
        # la stessa funzione serve entrambi, e un errore qui si vedrebbe
        # solo in produzione da una parte sola.
        self.assertEqual(
            pacing.typical_minutes_for({"type": "museum", "primary_type": "church"}),
            pacing.TYPICAL_VISIT_MINUTES["church"],
        )

    def test_dinner_is_longer_than_lunch_at_the_same_place(self):
        poi = _Poi(poi_type="restaurant", primary_type="restaurant")
        lunch = pacing.typical_minutes_for(poi, pacing._to_minutes("13:00"))
        dinner = pacing.typical_minutes_for(poi, pacing._to_minutes("20:30"))
        self.assertEqual(lunch, pacing.TYPICAL_VISIT_MINUTES["restaurant"])
        self.assertEqual(dinner, pacing.DINNER_MINUTES)
        self.assertGreater(dinner[1], lunch[1])

    def test_dinner_rule_only_applies_to_restaurants(self):
        # Un museo aperto in notturna non diventa una cena.
        poi = _Poi(poi_type="museum", primary_type="museum")
        self.assertEqual(
            pacing.typical_minutes_for(poi, pacing._to_minutes("21:00")),
            pacing.TYPICAL_VISIT_MINUTES["museum"],
        )

    def test_dinner_rule_without_a_time_keeps_the_lunch_span(self):
        poi = _Poi(poi_type="restaurant")
        self.assertEqual(pacing.typical_minutes_for(poi, None), pacing.TYPICAL_VISIT_MINUTES["restaurant"])

    def test_every_span_is_ordered_and_positive(self):
        for key, (low, high) in pacing.TYPICAL_VISIT_MINUTES.items():
            with self.subTest(key=key):
                self.assertGreater(low, 0)
                self.assertLessEqual(low, high)


class TestAnalyzeDay(unittest.TestCase):
    def test_window_is_the_gap_to_the_next_block(self):
        entries = pacing.analyze_day([_block("09:00"), _block("11:30")])
        self.assertEqual(entries[0]["window_minutes"], 150)

    def test_last_block_has_no_window_no_idle_no_end(self):
        # Inventare una fine della giornata produrrebbe un margine fantasma
        # su ogni cena del prodotto.
        entries = pacing.analyze_day([_block("09:00"), _block("20:00")])
        last = entries[-1]
        self.assertTrue(last["is_last"])
        self.assertIsNone(last["window_minutes"])
        self.assertIsNone(last["idle_minutes"])
        self.assertIsNone(last["end_estimate"])

    def test_travel_time_is_subtracted_from_the_margin(self):
        blocks = [_block("09:00", poi_id="POI1"), _block("11:30", poi_id="POI2")]
        poi_by_id = {"POI1": _Poi(primary_type="monument")}  # 20-45 min
        without = pacing.analyze_day(blocks, poi_by_id)
        with_travel = pacing.analyze_day(blocks, poi_by_id, {("POI1", "POI2"): 40})
        self.assertEqual(without[0]["idle_minutes"] - with_travel[0]["idle_minutes"], 40)

    def test_travel_lookup_accepts_the_reversed_pair(self):
        # Le misure di Distance Matrix sono simmetriche a piedi: chiedere
        # la coppia nell'ordine sbagliato non deve far sparire lo
        # spostamento e gonfiare il margine dichiarato al cliente.
        blocks = [_block("09:00", poi_id="POI1"), _block("11:30", poi_id="POI2")]
        entries = pacing.analyze_day(blocks, {}, {("POI2", "POI1"): 25})
        self.assertEqual(entries[0]["travel_minutes"], 25)

    def test_idle_uses_the_upper_end_of_the_span(self):
        # Scelta dichiarata nel docstring: sul minimo, ogni forbice ampia
        # genererebbe un margine enorme e il segnale diventerebbe rumore.
        blocks = [_block("09:00", poi_id="POI1"), _block("13:00", poi_id="POI2")]
        poi_by_id = {"POI1": _Poi(primary_type="museum")}  # 60-180
        entries = pacing.analyze_day(blocks, poi_by_id)
        self.assertEqual(entries[0]["idle_minutes"], 240 - 180)
        self.assertEqual(entries[0]["end_estimate"], "12:00")

    def test_out_of_sequence_times_produce_no_numbers(self):
        entries = pacing.analyze_day([_block("19:00"), _block("10:00")])
        self.assertIsNone(entries[0]["window_minutes"])
        self.assertIsNone(entries[0]["idle_minutes"])

    def test_unreadable_times_produce_no_numbers(self):
        entries = pacing.analyze_day([_block("mattina"), _block("13:00")])
        self.assertIsNone(entries[0]["window_minutes"])

    def test_malformed_shapes_never_raise(self):
        for broken in (
            None, [], [None, 42, "x"], [{"time": None}], [{"poi_id": ["lista"], "time": "09:00"}, _block("12:00")],
            [{"time": "09:00", "poi_id": {"un": "dict"}}, _block("12:00")],
        ):
            with self.subTest(broken=broken):
                self.assertIsInstance(pacing.analyze_day(broken), list)

    def test_unhashable_poi_id_does_not_break_the_document(self):
        # Difetto reale trovato da questa suite: `render_html()` non è
        # protetto dall'esito del validator, quindi un `poi_id` che è una
        # lista arriva fin qui. Usarlo come chiave sollevava TypeError e
        # faceva fallire l'INTERO PDF per un campo malformato in un solo
        # blocco — il cliente non riceveva niente invece di una riga in meno.
        blocks = [{"time": "09:00", "poi_id": ["POI1"]}, _block("13:00")]
        entries = pacing.analyze_day(blocks, {"POI1": _Poi(primary_type="museum")})
        self.assertEqual(entries[0]["typical"], pacing.DEFAULT_VISIT_MINUTES)


class TestDescribeMargin(unittest.TestCase):
    def _entry(self, idle):
        return {
            "idle_minutes": idle,
            "typical_text": "1h-1h30",
            "end_estimate": "11:30",
        }

    def test_silent_below_the_physiological_buffer(self):
        # [HARD_CONSTRAINTS] punto 2 CHIEDE 30-45 min di respiro fra i
        # blocchi: segnalarlo significherebbe presentare come difetto una
        # regola del prodotto, su ogni blocco del documento.
        self.assertEqual(pacing.describe_margin(self._entry(0)), "")
        self.assertEqual(pacing.describe_margin(self._entry(44)), "")

    def test_speaks_from_the_tolerance_upward(self):
        text = pacing.describe_margin(self._entry(pacing.IDLE_TOLERANCE_MINUTES))
        self.assertIn("45 min", text)

    def test_says_the_three_facts_and_the_next_activity(self):
        text = pacing.describe_margin(self._entry(90), "Pranzo al mercato")
        self.assertIn("1h-1h30", text)      # quanto dura la sosta
        self.assertIn("11:30", text)        # quando esce
        self.assertIn("1h30", text)         # quanto gli resta
        self.assertIn("Pranzo al mercato", text)

    def test_no_dangling_preposition_without_a_next_activity(self):
        text = pacing.describe_margin(self._entry(90), "")
        self.assertTrue(text.endswith("margine."), text)

    def test_missing_or_non_numeric_idle_is_silent(self):
        for idle in (None, "tanto", True):
            self.assertEqual(pacing.describe_margin({"idle_minutes": idle}), "")


class TestDensityThresholdIsPerPlace(unittest.TestCase):
    """
    Il caso reale, quello che le difese del 2026-07-31 lasciavano passare.
    """

    def _trip(self, blocks):
        # Primo e ultimo giorno sono "di bordo" ed esenti: il giorno in
        # esame è quello centrale.
        return {
            "days": [
                {"day": 1, "blocks": [_block("16:00"), _block("19:00")]},
                {"day": 2, "blocks": blocks},
                {"day": 3, "blocks": [_block("09:00"), _block("11:00")]},
            ]
        }

    def _full_day_around(self, inflated):
        return [
            _block("09:00"), inflated, _block("13:00"),
            _block("15:00"), _block("17:30"), _block("20:00"),
        ]

    def test_forty_minute_visit_given_two_and_a_half_hours_is_flagged(self):
        blocks = [
            _block("09:00"),
            _block("10:30", "Visita alla fontana monumentale", poi_id="POI9"),
            _block("13:00"), _block("15:00"), _block("17:30"), _block("20:00"),
        ]
        poi_by_id = {"POI9": _Poi(poi_type="activity", primary_type="fountain")}
        # Senza la mappa dei luoghi: 150 min < 180, nessun warning. È
        # letteralmente il difetto che Lorenzo ha riletto stampato.
        self.assertEqual(check_day_density(self._trip(blocks)), [])
        # Con la mappa: la soglia è quella di una fontana, e il buco si vede.
        warnings = check_day_density(self._trip(blocks), None, poi_by_id)
        self.assertTrue(any("fontana" in w for w in warnings), warnings)

    def test_two_hours_in_a_national_museum_is_not_flagged(self):
        blocks = self._full_day_around(_block("10:30", "Uffizi", poi_id="POI1"))
        blocks[2] = _block("12:30")
        poi_by_id = {"POI1": _Poi(poi_type="museum", primary_type="museum")}
        self.assertEqual(check_day_density(self._trip(blocks), None, poi_by_id), [])

    def test_flat_threshold_still_applies_when_the_place_is_unknown(self):
        # Un blocco senza scheda Google ("passeggiata in centro") non ha un
        # tipo: la vecchia rete grossolana resta, perché una soglia stretta
        # su un luogo ignoto sarebbe rumore sistematico.
        blocks = self._full_day_around(_block("10:30", "Passeggiata in centro"))
        blocks[2] = _block("15:30")  # 5h implicite
        warnings = check_day_density(self._trip(blocks), None, {"POI1": _Poi()})
        self.assertTrue(any("Passeggiata in centro" in w for w in warnings))

    def test_exclusivity_profile_still_exempt_with_the_new_map(self):
        blocks = self._full_day_around(_block("10:30", "Fontana", poi_id="POI9"))
        poi_by_id = {"POI9": _Poi(primary_type="fountain")}
        self.assertEqual(
            check_day_density(self._trip(blocks), "EXCLUSIVITY_ZERO_FRICTION", poi_by_id), []
        )

    def test_warning_names_the_typical_duration_not_just_a_threshold(self):
        # Un warning che dice solo "supera la soglia" non dice all'operatore
        # quanto sarebbe stato giusto: è la differenza fra un allarme e
        # un'informazione.
        blocks = self._full_day_around(_block("10:30", "Fontana", poi_id="POI9"))
        blocks[2] = _block("14:00")
        warnings = check_day_density(self._trip(blocks), None, {"POI9": _Poi(primary_type="fountain")})
        self.assertTrue(warnings)
        self.assertIn("di norma", warnings[0])
        self.assertIn("vuoto non programmato", warnings[0])


class TestMarginReachesTheDocument(unittest.TestCase):
    """
    Il collaudo che conta: la frase deve arrivare nel PDF, non solo esistere
    in una funzione. Questo progetto ha già avuto due controlli scritti,
    testati in isolamento e MAI collegati alla produzione.
    """

    ITINERARY = {
        "days": [{
            "day": 1,
            "title": "Centro storico",
            "blocks": [
                {"time": "09:00", "activity": "Fontana monumentale", "location": "Centro", "poi_id": "POI1"},
                {"time": "13:00", "activity": "Pranzo in trattoria", "location": "Centro", "poi_id": "POI2"},
                {"time": "20:00", "activity": "Cena", "location": "Centro", "poi_id": "POI2"},
            ],
        }]
    }
    TRIP = {"destination": "Roma", "date_start": "2026-09-01", "date_end": "2026-09-02", "duration_days": 2}
    POI = [
        {"id": "POI1", "name": "Fontana di Trevi", "type": "activity", "primary_type": "fountain",
         "lat": 41.9, "lng": 12.48},
        {"id": "POI2", "name": "Trattoria", "type": "restaurant", "primary_type": "restaurant",
         "lat": 41.9, "lng": 12.48},
    ]

    def _html(self):
        return pdf_renderer.render_html(self.ITINERARY, self.TRIP, poi=self.POI)

    def test_the_margin_line_is_printed(self):
        html = self._html()
        self.assertIn("block-margin", html)
        self.assertIn("di margine", html)

    def test_it_names_the_next_activity(self):
        self.assertIn("Pranzo in trattoria", self._html())

    def test_the_last_block_of_the_day_gets_no_margin_line(self):
        # La cena delle 20:00 non ha un dopo: un margine lì sarebbe inventato.
        # I blocchi con un margine sono i primi due (09:00 e 13:00), non tre.
        html = self._html()
        self.assertEqual(html.count("<div class='block-margin'>"), 2)

    def test_margin_css_survives_the_print_engine(self):
        # wkhtmltopdf monta Qt WebKit del 2014: i token vietati non devono
        # comparire nella regola .block-margin.
        html = self._html()
        rule = html.split(".block-margin {")[1].split("}")[0]
        for forbidden in ("rgba", "opacity", "gradient", "flex"):
            self.assertNotIn(forbidden, rule)


class TestPromptTableStaysAligned(unittest.TestCase):
    """
    La tabella delle durate esiste in due copie: in prosa nel punto 9 di
    [HARD_CONSTRAINTS] (la legge Claude, in generazione) e in forma
    eseguibile in `pacing.TYPICAL_VISIT_MINUTES` (la legge il validator, a
    valle). Se divergono, il validator segnala come difetti degli itinerari
    che hanno seguito le istruzioni alla lettera — falsi positivi
    sistematici, cioè il modo in cui un controllo smette di essere letto.
    """

    PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt_master.txt"

    # riga del prompt (sottostringa che la identifica) -> chiavi della tabella
    # eseguibile che DEVONO valere esattamente quell'intervallo.
    ROWS = {
        "Piazza, belvedere": ("plaza", "town_square", "viewpoint", "scenic_point",
                              "monument", "observation_deck", "fountain"),
        "Chiesa, mercato coperto": ("church", "cathedral", "market", "store"),
        "Museo o galleria di medie dimensioni": ("art_gallery",),
        "Parco, giardino": ("park", "garden"),
        "Terme/spa": ("spa",),
    }

    def _row(self, needle):
        text = self.PROMPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            if needle in line:
                return line
        self.fail(f"riga assente dal prompt: {needle!r}")

    def _first_range(self, line):
        match = re.search(r"(\d+)\s*[–-]\s*(\d+)\s*min", line)
        self.assertIsNotNone(match, f"intervallo non leggibile in: {line!r}")
        return int(match.group(1)), int(match.group(2))

    def test_each_prose_row_matches_the_executable_table(self):
        for needle, keys in self.ROWS.items():
            span = self._first_range(self._row(needle))
            for key in keys:
                with self.subTest(row=needle, key=key):
                    self.assertEqual(pacing.TYPICAL_VISIT_MINUTES[key], span)

    def test_lunch_and_dinner_match_the_prose(self):
        line = self._row("Pranzo:")
        ranges = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*[–-]\s*(\d+)\s*min", line)]
        self.assertEqual(len(ranges), 3, line)  # pranzo, cena, colazione/caffè
        self.assertEqual(pacing.TYPICAL_VISIT_MINUTES["restaurant"], ranges[0])
        self.assertEqual(pacing.DINNER_MINUTES, ranges[1])
        self.assertEqual(pacing.TYPICAL_VISIT_MINUTES["cafe"], ranges[2])

    def test_national_museum_ceiling_matches(self):
        line = self._row("Grande museo nazionale")
        ranges = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*[–-]\s*(\d+)\s*min", line)]
        medium, national = ranges[0], ranges[1]
        # `museum` copre entrambi i casi: minimo del museo medio, massimo del
        # grande museo nazionale. È dichiarato nel commento della tabella.
        self.assertEqual(pacing.TYPICAL_VISIT_MINUTES["museum"], (medium[0], national[1]))

    def test_the_worked_example_is_present_and_arithmetically_true(self):
        # L'esempio numerico è la parte del punto 9 che fa il conto AL POSTO
        # del modello. Se i numeri scritti lì non tornassero, insegnerebbe
        # l'errore che deve prevenire.
        line = self._row("ESEMPIO NUMERICO")
        self.assertIn("150 − 10 = 140", line)
        self.assertIn("140 − 45 = 95", line)
        self.assertEqual(pacing.TYPICAL_VISIT_MINUTES["fountain"][1], 45)

    def test_the_prompt_declares_that_the_document_prints_the_margin(self):
        # Il modello deve sapere che il buco che lascia viene stampato: è
        # l'unico modo in cui la regola ha un costo visibile per lui.
        text = self.PROMPT.read_text(encoding="utf-8")
        self.assertIn("STAMPA sotto quel blocco", text)
        self.assertIn(str(pacing.IDLE_TOLERANCE_MINUTES), text)


if __name__ == "__main__":
    unittest.main()
