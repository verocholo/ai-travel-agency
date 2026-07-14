"""
[AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "cartina + percorsi"] Copre
src/maps_static.py. Nessuna vera chiamata di rete: `requests.get` è
sempre mockato, stesso pattern del resto della suite (places_client.py,
liteapi_client.py, geocoding.py).
"""
import unittest
from unittest.mock import patch, MagicMock

from src.maps_static import (
    build_static_map_url, fetch_static_map_png, build_map_for_itinerary, MapsStaticError,
    _PATH_COLORS, _MAX_URL_LENGTH, _pick_day_anchor, compute_center_zoom, _parse_size,
)
from src.schemas import Hotel, POI

HOTEL = Hotel(id="H1", name="Hotel Test", lat=43.08, lng=11.60, price_night_eur=100.0)
POI_RESTAURANT = POI(id="POI1", type="restaurant", name="Trattoria", lat=43.075, lng=11.605)
POI_MUSEUM = POI(id="POI3", type="museum", name="Museo del Vino", lat=43.078, lng=11.62)
POI_UNUSED = POI(id="POI9", type="activity", name="Mai scelto da Claude", lat=43.09, lng=11.70)

# [AGGIUNTO 2026-07-12 — audit di revisione completa] Fixture per i test
# del fix multi-hotel (_pick_day_anchor): due hotel in città diverse,
# ordinati DELIBERATAMENTE con HOTEL_ROMA per primo — prima del fix,
# `hotel_points[0]` sarebbe stato sempre usato come ancora, sbagliando
# ogni giorno trascorso vicino a Firenze.
HOTEL_ROMA = Hotel(id="HB", name="Hotel Roma", lat=41.9, lng=12.5, price_night_eur=120.0)
HOTEL_FIRENZE = Hotel(id="HA", name="Hotel Firenze", lat=43.77, lng=11.25, price_night_eur=100.0)
POI_FIRENZE = POI(id="PF", type="museum", name="Uffizi", lat=43.768, lng=11.255)
POI_ROMA = POI(id="PR", type="restaurant", name="Trattoria Roma", lat=41.89, lng=12.49)

ITINERARY_MULTI_HOTEL = {
    "days": [
        {"day": 1, "blocks": [
            {"time": "09:00", "activity": "Check-in Firenze", "poi_id": "HA"},
            {"time": "13:00", "activity": "Uffizi", "poi_id": "PF"},
        ]},
        {"day": 2, "blocks": [
            {"time": "09:00", "activity": "Check-in Roma", "poi_id": "HB"},
            {"time": "13:00", "activity": "Pranzo Roma", "poi_id": "PR"},
        ]},
    ],
}

ITINERARY = {
    "days": [
        {"day": 1, "blocks": [
            {"time": "09:00", "activity": "Check-in", "poi_id": "H1"},
            {"time": "13:00", "activity": "Pranzo", "poi_id": "POI1"},
        ]},
        {"day": 2, "blocks": [
            {"time": "10:00", "activity": "Museo", "poi_id": "POI3"},
            {"time": "15:00", "activity": "Slot libero", "poi_id": None},
        ]},
    ],
}


class TestBuildStaticMapUrl(unittest.TestCase):
    def test_no_markers_no_paths_returns_none(self):
        self.assertIsNone(build_static_map_url([], [], "fake-key"))

    def test_single_marker_style_includes_size_key_and_markers(self):
        url = build_static_map_url(
            [{"color": "red", "label": "H", "points": [(43.08, 11.60)]}], [], "fake-key"
        )
        self.assertIsNotNone(url)
        self.assertIn("size=640x400", url)
        self.assertIn("key=fake-key", url)
        self.assertIn("markers=color:red|label:H|43.08,11.6", url)

    def test_multiple_marker_styles_produce_multiple_markers_params(self):
        url = build_static_map_url(
            [
                {"color": "red", "label": "H", "points": [(1.0, 2.0)]},
                {"color": "green", "label": "R", "points": [(3.0, 4.0)]},
            ],
            [],
            "fake-key",
        )
        self.assertEqual(url.count("markers="), 2)

    def test_style_with_empty_points_is_skipped(self):
        url = build_static_map_url(
            [{"color": "red", "label": "H", "points": []}],
            [],
            "fake-key",
        )
        self.assertIsNone(url)

    def test_path_with_single_point_is_skipped(self):
        # Un solo punto non disegna nessuna linea — verifica che non
        # produca comunque un parametro "path=" vuoto/inutile.
        url = build_static_map_url([], [{"color": "0xff0000", "points": [(1.0, 2.0)]}], "fake-key")
        self.assertIsNone(url)

    def test_path_with_two_or_more_points_included(self):
        url = build_static_map_url(
            [], [{"color": "0xff0000", "points": [(1.0, 2.0), (3.0, 4.0)]}], "fake-key"
        )
        self.assertIsNotNone(url)
        self.assertIn("path=", url)

    def test_custom_size_respected(self):
        url = build_static_map_url(
            [{"color": "red", "points": [(1.0, 2.0)]}], [], "fake-key", size="800x600"
        )
        self.assertIn("size=800x600", url)

    def test_center_and_zoom_omitted_by_default_no_regression(self):
        # Un chiamante esistente che non passa center/zoom ottiene lo
        # stesso URL di prima di questa modifica (auto-fit implicito di
        # Google) — nessuna rottura.
        url = build_static_map_url([{"color": "red", "points": [(1.0, 2.0)]}], [], "fake-key")
        self.assertNotIn("center=", url)
        self.assertNotIn("zoom=", url)

    def test_center_and_zoom_included_when_provided(self):
        url = build_static_map_url(
            [{"color": "red", "points": [(1.0, 2.0)]}], [], "fake-key",
            center=(45.1, 9.2), zoom=13,
        )
        self.assertIn("center=45.1,9.2", url)
        self.assertIn("zoom=13", url)


# [AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "la mappa dovrebbe
# essere più zoomata sulla città", confermata come miglioramento generale
# di prodotto via AskUserQuestion] Stessa tecnica di calcolo (Web
# Mercator, centro+zoom espliciti) già validata a mano per le mappe
# TomTom del viaggio personale di Lorenzo — qui generalizzata e testata.
class TestComputeCenterZoom(unittest.TestCase):
    def test_empty_points_returns_none(self):
        self.assertIsNone(compute_center_zoom([], 640, 400))

    def test_single_point_returns_that_point_with_fixed_close_zoom(self):
        result = compute_center_zoom([(45.0, 9.0)], 640, 400, max_zoom=17)
        self.assertEqual(result, (45.0, 9.0, 15))

    def test_coincident_points_treated_like_single_point(self):
        result = compute_center_zoom([(45.0, 9.0), (45.0, 9.0)], 640, 400, max_zoom=17)
        self.assertEqual(result, (45.0, 9.0, 15))

    def test_center_is_midpoint_of_bbox(self):
        lat, lng, _ = compute_center_zoom([(45.0, 9.0), (45.02, 9.04)], 640, 400)
        self.assertAlmostEqual(lat, 45.01)
        self.assertAlmostEqual(lng, 9.02)

    def test_wider_spread_produces_lower_zoom_than_tight_cluster(self):
        # Più i punti sono distanti, più lo zoom scende (mai il
        # contrario) — la stessa relazione che ha guidato il calcolo
        # manuale per le mappe TomTom (giorni con tappe sparse su
        # un'area ampia -> zoom più basso, mai un ritaglio che tagli
        # fuori tappe reali).
        _, _, zoom_tight = compute_center_zoom([(45.0, 9.0), (45.005, 9.005)], 640, 400)
        _, _, zoom_wide = compute_center_zoom([(45.0, 9.0), (46.0, 10.0)], 640, 400)
        self.assertGreater(zoom_tight, zoom_wide)

    def test_zoom_never_exceeds_max_zoom_or_goes_below_min_zoom(self):
        # Un cluster estremamente stretto non deve produrre uno zoom
        # "impossibile" (oltre il livello massimo supportato dall'API);
        # un'estensione enorme (es. tappe su due continenti) non deve
        # scendere sotto il livello minimo.
        _, _, zoom_tiny = compute_center_zoom(
            [(45.0, 9.0), (45.0000001, 9.0000001)], 640, 400, max_zoom=17
        )
        self.assertLessEqual(zoom_tiny, 17)
        _, _, zoom_huge = compute_center_zoom([(-40.0, -70.0), (60.0, 140.0)], 640, 400, min_zoom=2)
        self.assertGreaterEqual(zoom_huge, 2)

    def test_larger_image_size_allows_higher_zoom_for_same_points(self):
        # Un'immagine più grande ha più pixel utili per lo stesso bbox
        # geografico -> può permettersi uno zoom più alto (più
        # ravvicinato) mantenendo lo stesso margine di sicurezza.
        _, _, zoom_small = compute_center_zoom([(45.0, 9.0), (45.05, 9.05)], 320, 200)
        _, _, zoom_large = compute_center_zoom([(45.0, 9.0), (45.05, 9.05)], 1280, 800)
        self.assertGreaterEqual(zoom_large, zoom_small)


class TestParseSize(unittest.TestCase):
    def test_standard_size_parsed(self):
        self.assertEqual(_parse_size("640x400"), (640, 400))

    def test_malformed_size_falls_back_to_default_no_crash(self):
        self.assertEqual(_parse_size("not-a-size"), (640, 400))
        self.assertEqual(_parse_size(""), (640, 400))
        self.assertEqual(_parse_size(None), (640, 400))


class TestFetchStaticMapPng(unittest.TestCase):
    @patch("src.maps_static.requests.get")
    def test_success_returns_bytes(self, mock_get):
        mock_resp = MagicMock(status_code=200, content=b"\x89PNG\r\n...")
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_get.return_value = mock_resp
        self.assertEqual(fetch_static_map_png("https://example.com/map"), b"\x89PNG\r\n...")

    @patch("src.maps_static.requests.get")
    def test_non_200_raises_maps_static_error(self, mock_get):
        mock_resp = MagicMock(status_code=403, text="API key invalid")
        mock_resp.headers = {}
        mock_get.return_value = mock_resp
        with self.assertRaises(MapsStaticError):
            fetch_static_map_png("https://example.com/map")

    @patch("src.maps_static.requests.get")
    def test_non_image_content_type_raises_maps_static_error(self, mock_get):
        mock_resp = MagicMock(status_code=200, text="<html>quota exceeded</html>")
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_resp
        with self.assertRaises(MapsStaticError):
            fetch_static_map_png("https://example.com/map")


class TestBuildMapForItinerary(unittest.TestCase):
    @patch("src.maps_static.fetch_static_map_png")
    def test_missing_api_key_returns_none_no_network_call(self, mock_fetch):
        result = build_map_for_itinerary([HOTEL], [POI_RESTAURANT], ITINERARY, None)
        self.assertIsNone(result)
        mock_fetch.assert_not_called()

    @patch("src.maps_static.fetch_static_map_png")
    def test_happy_path_returns_png_bytes(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        result = build_map_for_itinerary(
            [HOTEL], [POI_RESTAURANT, POI_MUSEUM, POI_UNUSED], ITINERARY, "fake-key"
        )
        self.assertEqual(result, b"fake-png-bytes")
        mock_fetch.assert_called_once()

    @patch("src.maps_static.fetch_static_map_png")
    def test_url_includes_computed_center_and_zoom(self, mock_fetch):
        # [AGGIUNTO 2026-07-13 (ter)] Copre l'integrazione end-to-end:
        # `build_map_for_itinerary()` calcola davvero centro/zoom dai
        # marker REALMENTE disegnati (hotel-ancora + POI usati), non solo
        # `compute_center_zoom()` in isolamento.
        mock_fetch.return_value = b"fake-png-bytes"
        build_map_for_itinerary([HOTEL], [POI_RESTAURANT, POI_MUSEUM], ITINERARY, "fake-key")
        url = mock_fetch.call_args[0][0]
        self.assertIn("center=", url)
        self.assertIn("zoom=", url)

    @patch("src.maps_static.fetch_static_map_png")
    def test_unused_poi_excluded_from_map_url(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        build_map_for_itinerary([HOTEL], [POI_RESTAURANT, POI_MUSEUM, POI_UNUSED], ITINERARY, "fake-key")
        called_url = mock_fetch.call_args[0][0]
        self.assertNotIn("11.7", called_url)  # coordinate di POI_UNUSED, mai usato nell'itinerario

    @patch("src.maps_static.fetch_static_map_png")
    def test_no_hotel_no_used_poi_returns_none(self, mock_fetch):
        empty_itinerary = {"days": [{"day": 1, "blocks": [{"time": "10:00", "activity": "x", "poi_id": None}]}]}
        result = build_map_for_itinerary([], [], empty_itinerary, "fake-key")
        self.assertIsNone(result)
        mock_fetch.assert_not_called()

    @patch("src.maps_static.fetch_static_map_png", side_effect=MapsStaticError("quota esaurita"))
    def test_network_failure_degrades_to_none_not_an_exception(self, mock_fetch):
        # Non deve MAI propagare — una cartina mancante non deve far
        # fallire l'intero PDF.
        result = build_map_for_itinerary([HOTEL], [POI_RESTAURANT], ITINERARY, "fake-key")
        self.assertIsNone(result)

    # [AGGIUNTO 2026-07-12 — audit di revisione completa] Test di
    # integrazione end-to-end del fix multi-hotel: dimostra che, con due
    # hotel in città diverse, ciascun giorno ancora il proprio percorso
    # all'hotel corretto (quello con check-in quel giorno) e non sempre a
    # `hotel_points[0]` — prima del fix questo test avrebbe fallito perché
    # HOTEL_ROMA è passato per primo nella lista `hotels`.
    @patch("src.maps_static.fetch_static_map_png")
    def test_multi_hotel_each_day_anchors_to_its_own_hotel_not_always_the_first(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        build_map_for_itinerary(
            [HOTEL_ROMA, HOTEL_FIRENZE], [POI_FIRENZE, POI_ROMA], ITINERARY_MULTI_HOTEL, "fake-key"
        )
        url = mock_fetch.call_args[0][0]
        path_params = [p for p in url.split("&") if p.startswith("path=")]
        self.assertEqual(len(path_params), 2)
        # Giorno 1 (check-in Firenze): il percorso deve contenere le
        # coordinate di Firenze e NON quelle di Roma.
        day1_path = path_params[0]
        self.assertIn("43.77,11.25", day1_path)
        self.assertNotIn("41.9,12.5", day1_path)
        # Giorno 2 (check-in Roma): esattamente il contrario.
        day2_path = path_params[1]
        self.assertIn("41.9,12.5", day2_path)
        self.assertNotIn("43.77,11.25", day2_path)

    # [AGGIUNTO 2026-07-12 — audit di revisione completa] Chiude il gap di
    # mutation-testing trovato dall'agente di audit sulla qualità test:
    # nessun test precedente asseriva ESATTAMENTE quale colore viene usato
    # per il percorso di ciascun giorno (ciclo su `_PATH_COLORS`) — una
    # mutazione che rompesse `i % len(_PATH_COLORS)` sarebbe passata
    # inosservata.
    @patch("src.maps_static.fetch_static_map_png")
    def test_path_color_cycles_through_path_colors_by_day_index(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        poi_a = POI(id="PA", type="restaurant", name="A", lat=43.01, lng=11.01)
        poi_b = POI(id="PB", type="museum", name="B", lat=43.02, lng=11.02)
        poi_c = POI(id="PC", type="activity", name="C", lat=43.03, lng=11.03)
        itinerary_3day = {
            "days": [
                {"day": 1, "blocks": [{"time": "10:00", "activity": "x", "poi_id": "PA"}]},
                {"day": 2, "blocks": [{"time": "10:00", "activity": "y", "poi_id": "PB"}]},
                {"day": 3, "blocks": [{"time": "10:00", "activity": "z", "poi_id": "PC"}]},
            ],
        }
        build_map_for_itinerary([HOTEL], [poi_a, poi_b, poi_c], itinerary_3day, "fake-key")
        url = mock_fetch.call_args[0][0]
        path_params = [p for p in url.split("&") if p.startswith("path=")]
        self.assertEqual(len(path_params), 3)
        self.assertTrue(path_params[0].startswith(f"path=color:{_PATH_COLORS[0]}"))
        self.assertTrue(path_params[1].startswith(f"path=color:{_PATH_COLORS[1]}"))
        self.assertTrue(path_params[2].startswith(f"path=color:{_PATH_COLORS[2]}"))

    # [AGGIUNTO 2026-07-12 — audit di revisione completa] Altro gap di
    # mutation-testing: nessun test asseriva la mappatura esatta
    # tipo-di-POI -> colore/etichetta marker (né il fallback grigio per un
    # tipo sconosciuto) — una mutazione che scambiasse due colori sarebbe
    # passata inosservata.
    @patch("src.maps_static.fetch_static_map_png")
    def test_marker_color_and_label_mapped_correctly_per_poi_type(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        poi_activity = POI(id="PACT", type="activity", name="Attività", lat=43.05, lng=11.05)
        poi_unknown_type = POI(id="PUNK", type="landmark", name="Monumento", lat=43.06, lng=11.06)
        itinerary_all_types = {
            "days": [{"day": 1, "blocks": [
                {"time": "09:00", "activity": "a", "poi_id": "POI1"},
                {"time": "10:00", "activity": "b", "poi_id": "POI3"},
                {"time": "11:00", "activity": "c", "poi_id": "PACT"},
                {"time": "12:00", "activity": "d", "poi_id": "PUNK"},
            ]}],
        }
        build_map_for_itinerary(
            [HOTEL], [POI_RESTAURANT, POI_MUSEUM, poi_activity, poi_unknown_type],
            itinerary_all_types, "fake-key",
        )
        url = mock_fetch.call_args[0][0]
        self.assertIn("markers=color:red|label:H|43.08,11.6", url)  # hotel
        self.assertIn("markers=color:green|label:R|43.075,11.605", url)  # restaurant
        self.assertIn("markers=color:orange|label:M|43.078,11.62", url)  # museum
        self.assertIn("markers=color:blue|label:A|43.05,11.05", url)  # activity
        self.assertIn("markers=color:gray|label:P|43.06,11.06", url)  # tipo sconosciuto -> fallback

    # [AGGIUNTO 2026-07-12 — audit di revisione completa] Verifica il
    # nuovo comportamento di degradazione per URL troppo lunghi: prima
    # ritenta senza i percorsi (solo marker), invece di sparire subito del
    # tutto. Numero di giorni scelto empiricamente (verificato prima con
    # uno script diretto su questo modulo): con solo 3 POI riusati su 150
    # giorni, l'URL completo (con i percorsi) supera `_MAX_URL_LENGTH`, ma
    # quello coi soli marker resta ben al di sotto (i marker sono
    # deduplicati per id, i percorsi no — un percorso per giorno).
    @patch("src.maps_static.fetch_static_map_png")
    def test_url_too_long_with_paths_degrades_to_markers_only(self, mock_fetch):
        mock_fetch.return_value = b"fake-png-bytes"
        pois = [
            POI(id=f"P{i}", type="activity", name=f"Poi {i}", lat=41.9 + i * 0.001, lng=12.5 + i * 0.001)
            for i in range(3)
        ]
        days = [
            {"day": d, "blocks": [{"time": "10:00", "activity": "x", "poi_id": f"P{(d - 1) % 3}"}]}
            for d in range(1, 151)
        ]
        big_itinerary = {"days": days}
        result = build_map_for_itinerary([HOTEL], pois, big_itinerary, "fake-key")
        self.assertEqual(result, b"fake-png-bytes")
        mock_fetch.assert_called_once()
        called_url = mock_fetch.call_args[0][0]
        self.assertLessEqual(len(called_url), _MAX_URL_LENGTH)
        self.assertNotIn("path=", called_url)  # confermato: fallback SENZA percorsi

    # [AGGIUNTO 2026-07-12 — audit di revisione completa] Caso estremo:
    # anche i soli marker superano il limite (molti POI distinti, non
    # riusati) — deve arrendersi restituendo `None`, non un'eccezione né
    # un URL tagliato a metà da inviare comunque a Google.
    @patch("src.maps_static.fetch_static_map_png")
    def test_url_too_long_even_without_paths_returns_none(self, mock_fetch):
        n = 500
        pois = [
            POI(id=f"P{i}", type="activity", name=f"Poi {i}", lat=41.9 + i * 0.0001, lng=12.5 + i * 0.0001)
            for i in range(n)
        ]
        days = [
            {"day": i + 1, "blocks": [{"time": "10:00", "activity": "x", "poi_id": f"P{i}"}]}
            for i in range(n)
        ]
        big_itinerary = {"days": days}
        result = build_map_for_itinerary([HOTEL], pois, big_itinerary, "fake-key")
        self.assertIsNone(result)
        mock_fetch.assert_not_called()


class TestPickDayAnchor(unittest.TestCase):
    """[AGGIUNTO 2026-07-12 — audit di revisione completa] Test unitari
    diretti su `_pick_day_anchor()`, isolati dal resto dell'orchestrazione
    — più semplici da leggere e da far fallire in modo specifico rispetto
    ai soli test end-to-end su `build_map_for_itinerary()`."""

    ALL_POINTS = {
        "HA": (43.77, 11.25),   # Hotel Firenze
        "HB": (41.9, 12.5),     # Hotel Roma
        "PF": (43.768, 11.255),  # POI vicino a Firenze
        "PR": (41.89, 12.49),   # POI vicino a Roma
    }
    HOTEL_POINTS = [(41.9, 12.5), (43.77, 11.25)]  # HB prima di HA, di proposito
    HOTEL_IDS = {"HA", "HB"}

    def test_no_hotels_returns_none(self):
        self.assertIsNone(_pick_day_anchor(["PF"], [], set(), self.ALL_POINTS))

    def test_single_hotel_always_used_regardless_of_distance(self):
        # Con un solo hotel (il caso reale oggi, architettura "1
        # hotel-ancora") non c'è alcuna scelta da fare — deve sempre
        # essere quello, anche se lontano dai punti del giorno.
        self.assertEqual(
            _pick_day_anchor(["PR"], [(43.77, 11.25)], {"HA"}, self.ALL_POINTS),
            (43.77, 11.25),
        )

    def test_explicitly_referenced_hotel_wins_even_if_farther(self):
        # HA è referenziato esplicitamente quel giorno (check-in) — deve
        # vincere anche se HB fosse geograficamente più vicino ai punti
        # reali del giorno.
        anchor = _pick_day_anchor(["HA", "PF"], self.HOTEL_POINTS, self.HOTEL_IDS, self.ALL_POINTS)
        self.assertEqual(anchor, (43.77, 11.25))

    def test_no_explicit_reference_picks_nearest_hotel_to_days_real_points(self):
        # Nessun hotel referenziato esplicitamente quel giorno — deve
        # scegliere l'hotel geograficamente più vicino al POI del giorno
        # (Roma), NON semplicemente `hotel_points[0]` (che qui è Roma per
        # coincidenza: verificato anche nel caso opposto sotto).
        anchor = _pick_day_anchor(["PR"], self.HOTEL_POINTS, self.HOTEL_IDS, self.ALL_POINTS)
        self.assertEqual(anchor, (41.9, 12.5))

    def test_no_explicit_reference_picks_nearest_even_when_not_first_in_list(self):
        # Stesso test di sopra ma con l'ordine della lista hotel invertito
        # — dimostra che la scelta dipende dalla distanza reale e non
        # dalla posizione nella lista `hotel_points`.
        reversed_hotel_points = [(43.77, 11.25), (41.9, 12.5)]  # HA prima di HB
        anchor = _pick_day_anchor(["PR"], reversed_hotel_points, self.HOTEL_IDS, self.ALL_POINTS)
        self.assertEqual(anchor, (41.9, 12.5))

    def test_no_real_points_and_no_reference_falls_back_to_first_hotel(self):
        # Giornata senza alcun punto reale (es. tutto "[SLOT LIBERO]") e
        # nessun hotel referenziato — unico caso oggi raggiungibile con
        # l'architettura a 1 hotel-ancora, ma verificato comunque per
        # difesa in profondità.
        anchor = _pick_day_anchor([], self.HOTEL_POINTS, self.HOTEL_IDS, self.ALL_POINTS)
        self.assertEqual(anchor, self.HOTEL_POINTS[0])


if __name__ == "__main__":
    unittest.main()
