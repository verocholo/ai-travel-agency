"""
[AGGIUNTO 2026-08-01] Test del rimedio ai difetti trovati nel COLLAUDO del
primo PDF venduto davvero (claude/collaudo-pdf-reale-2026-08-01.md).

Il collaudo ha prodotto nove POI per tre giorni di viaggio — sette ristoranti
e due attrazioni — e da lì quattro blocchi vuoti, attività da tre ore per cose
che ne richiedono quaranta minuti, nomi di luoghi con la ragione sociale
dentro, nomi in inglese in una città italiana, e righe "circa 0 min in auto"
tra due tappe dello stesso centro storico.

La lezione, ed è il motivo per cui questi test stanno tutti insieme in un solo
file: NON era un problema di prompt. Era un problema di INGREDIENTI. Un
modello non può proporre una visita che non ha nei dati, per quanto bene glielo
si chieda. Quindi ciò che va protetto da qui in avanti non è il testo generato
— è la qualità dell'insieme di POI che arriva al modello, e l'onestà con cui i
numeri misurati vengono scritti nel PDF.

Copertura:
  difetto 1 (bolla geografica)   → geocoding._viewport_radius_m, poi_discovery
  difetto 2 (nomi sporchi)       → places_client.clean_poi_name
  difetto 3 (nomi in lingua err.)→ geocoding._extract_country_code
  difetto 4 ("circa 0 min")      → directions.describe_leg_duration
  densità/varietà                → poi_discovery.compose, distance_matrix.plan_matrix
"""
import math
import unittest
from unittest.mock import patch

from src import distance_matrix, places_client, poi_discovery, tips_generator
from src.directions import (
    NEGLIGIBLE_LEG_MINUTES, build_day_legs, describe_leg_duration,
)
from src.geocoding import parse_geocoding_response_full
from src.places_client import clean_poi_name, drop_low_signal, rank_by_relevance
from src.schemas import POI


def _poi(pid, name="Luogo", ptype="tourist_attraction", lat=43.77, lng=11.25,
         rating=None, count=None):
    return POI(id=pid, type=ptype, name=name, lat=lat, lng=lng,
               rating=rating, user_rating_count=count)


# --------------------------------------------------------------------------
# Difetto 1 — la bolla geografica: un raggio fisso di 3 km per ogni città
# --------------------------------------------------------------------------
class TestRaggioDalViewport(unittest.TestCase):
    """Il geocoding ci diceva GIÀ quanto è grande la destinazione (il
    `viewport` del risultato) e noi lo buttavamo via, cercando con lo stesso
    raggio di 3 km a Siena e a Roma. Tre km a Roma sono un quartiere."""

    @staticmethod
    def _response(ne_lat, ne_lng, sw_lat, sw_lng, country="IT"):
        return {
            "status": "OK",
            "results": [{
                "geometry": {
                    "location": {"lat": (ne_lat + sw_lat) / 2, "lng": (ne_lng + sw_lng) / 2},
                    "location_type": "APPROXIMATE",
                    "viewport": {
                        "northeast": {"lat": ne_lat, "lng": ne_lng},
                        "southwest": {"lat": sw_lat, "lng": sw_lng},
                    },
                },
                "formatted_address": "Test, Italia",
                "address_components": [
                    {"types": ["country", "political"], "short_name": country, "long_name": "Italia"},
                ],
            }],
        }

    def test_citta_grande_produce_un_raggio_maggiore_di_una_piccola(self):
        grande = parse_geocoding_response_full(self._response(41.99, 12.66, 41.80, 12.36))
        piccola = parse_geocoding_response_full(self._response(43.34, 11.35, 43.30, 11.30))
        self.assertGreater(grande["viewport_radius_m"], piccola["viewport_radius_m"])

    def test_raggio_sempre_dentro_limiti_ragionevoli(self):
        """Un viewport enorme (una regione, un paese mal geocodificato) non
        deve farci cercare a cento chilometri: il tetto è parte del contratto."""
        enorme = parse_geocoding_response_full(self._response(47.0, 18.0, 36.0, 6.0))
        minuscolo = parse_geocoding_response_full(self._response(43.3001, 11.3001, 43.3000, 11.3000))
        self.assertLessEqual(enorme["viewport_radius_m"], 12000)
        self.assertGreaterEqual(minuscolo["viewport_radius_m"], 1200)

    def test_viewport_assente_non_rompe_nulla(self):
        risposta = self._response(43.34, 11.35, 43.30, 11.30)
        del risposta["results"][0]["geometry"]["viewport"]
        parsed = parse_geocoding_response_full(risposta)
        self.assertIsNone(parsed["viewport_radius_m"])
        self.assertEqual(parsed["country_code"], "IT")

    def test_viewport_malformato_non_solleva(self):
        risposta = self._response(43.34, 11.35, 43.30, 11.30)
        risposta["results"][0]["geometry"]["viewport"] = {"northeast": {"lat": "x"}}
        self.assertIsNone(parse_geocoding_response_full(risposta)["viewport_radius_m"])


class TestCodicePaese(unittest.TestCase):
    """Difetto 3: senza `regionCode` Google risponde con i nomi nella lingua
    che gli pare. Il codice paese era già nella risposta del geocoding."""

    def test_codice_paese_estratto(self):
        parsed = parse_geocoding_response_full(TestRaggioDalViewport._response(
            43.34, 11.35, 43.30, 11.30, country="FR"))
        self.assertEqual(parsed["country_code"], "FR")

    def test_componente_non_paese_ignorata(self):
        risposta = TestRaggioDalViewport._response(43.34, 11.35, 43.30, 11.30)
        risposta["results"][0]["address_components"] = [
            {"types": ["locality"], "short_name": "SI"},
        ]
        self.assertIsNone(parse_geocoding_response_full(risposta)["country_code"])

    def test_componenti_malformate_non_sollevano(self):
        risposta = TestRaggioDalViewport._response(43.34, 11.35, 43.30, 11.30)
        risposta["results"][0]["address_components"] = ["non un dizionario", None, 42]
        self.assertIsNone(parse_geocoding_response_full(risposta)["country_code"])


# --------------------------------------------------------------------------
# Difetto 2 — i nomi dei luoghi con dentro la ragione sociale
# --------------------------------------------------------------------------
class TestPuliziaNomi(unittest.TestCase):
    """Nel PDF reale il cliente ha letto "Ristorante Da Mario S.R.L." e
    "Via Roma 42". Il primo è un nome che nessuno pronuncerebbe, il secondo
    non è affatto un nome. La regola è conservativa per costruzione: si taglia
    SOLO in coda e SOLO forme legali riconosciute."""

    def test_suffissi_legali_rimossi(self):
        casi = {
            "Ristorante Da Mario S.R.L.": "Ristorante Da Mario",
            "Trattoria Il Borgo s.r.l.s.": "Trattoria Il Borgo",
            "Museo Civico S.p.A.": "Museo Civico",
            "Osteria Bella Vista SNC": "Osteria Bella Vista",
            "Bistrot du Port SARL": "Bistrot du Port",
            "Harbour Tours Ltd.": "Harbour Tours",
            "Kunsthaus GmbH": "Kunsthaus",
            "Pizzeria Napoli & C.": "Pizzeria Napoli",
            "Cooperativa Sole soc. coop. a r.l.": "Cooperativa Sole",
        }
        for grezzo, atteso in casi.items():
            with self.subTest(grezzo=grezzo):
                self.assertEqual(clean_poi_name(grezzo), atteso)

    def test_nomi_legittimi_non_vengono_toccati(self):
        """Il rischio opposto — e più grave — è mutilare un nome buono."""
        intatti = [
            "Uffizi", "Basilica di San Petronio", "Ponte Vecchio",
            "Piazza del Campo", "Caffè Rivoire", "Trattoria Sostanza",
            "Museo Nazionale Romano", "La Pergola", "Bar Sport",
            "Via Krupp",           # un nome vero che INIZIA con "Via"
            "Osteria del Cinghiale Bianco",
        ]
        for nome in intatti:
            with self.subTest(nome=nome):
                self.assertEqual(clean_poi_name(nome), nome)

    def test_indirizzi_scartati(self):
        for indirizzo in ["Via Roma 42", "Corso Italia 7", "Piazza Verdi 3",
                          "Rue de Rivoli 12", "Calle Mayor 8"]:
            with self.subTest(indirizzo=indirizzo):
                self.assertIsNone(clean_poi_name(indirizzo))

    def test_codice_postale_dentro_il_nome_lo_scarta(self):
        self.assertIsNone(clean_poi_name("Deposito 50122 Firenze"))

    def test_segnaposto_scartati(self):
        for segnaposto in ["N/A", "n.d.", "unnamed", "Senza nome", "-", "?", "   "]:
            with self.subTest(segnaposto=segnaposto):
                self.assertIsNone(clean_poi_name(segnaposto))

    def test_input_non_stringa_non_solleva(self):
        for valore in [None, 42, [], {}, object()]:
            self.assertIsNone(clean_poi_name(valore))

    def test_nome_di_soli_simboli_scartato(self):
        self.assertIsNone(clean_poi_name("*** ###"))

    def test_pulizia_non_svuota_mai_il_nome(self):
        """"S.R.L." da solo non deve diventare stringa vuota: o è un nome, o
        è None. Una stringa vuota nel PDF è un buco silenzioso."""
        risultato = clean_poi_name("S.R.L.")
        self.assertTrue(risultato is None or risultato.strip())


# --------------------------------------------------------------------------
# Rilevanza — l'ordinamento che ha causato "sette ristoranti su nove"
# --------------------------------------------------------------------------
class TestRilevanza(unittest.TestCase):
    def test_ordina_per_notorieta_non_per_ordine_di_arrivo(self):
        pois = [_poi("A", count=10, rating=4.9), _poi("B", count=8000, rating=4.4),
                _poi("C", count=300, rating=4.8)]
        self.assertEqual([p.id for p in rank_by_relevance(pois)], ["B", "C", "A"])

    def test_ordinamento_stabile_senza_dati(self):
        pois = [_poi("A", name="Zeta"), _poi("B", name="Alfa")]
        self.assertEqual([p.id for p in rank_by_relevance(pois)], ["B", "A"])

    def test_scarta_i_luoghi_senza_segnale(self):
        pois = [_poi(f"P{i}", count=500) for i in range(10)] + [
            _poi("X", count=1), _poi("Y", count=0)]
        kept = {p.id for p in drop_low_signal(pois)}
        self.assertNotIn("X", kept)
        self.assertNotIn("Y", kept)

    def test_non_svuota_l_insieme_quando_nessuno_ha_recensioni(self):
        """In un borgo di trecento abitanti nessun luogo ha quindici
        recensioni. Meglio un insieme non filtrato che un insieme vuoto."""
        pois = [_poi(f"P{i}", count=0) for i in range(8)]
        self.assertEqual(len(drop_low_signal(pois)), 8)

    def test_lista_vuota(self):
        self.assertEqual(drop_low_signal([]), [])


# --------------------------------------------------------------------------
# Densità e varietà — la composizione in due passate
# --------------------------------------------------------------------------
class TestComposizione(unittest.TestCase):
    def test_il_cibo_non_supera_la_sua_quota(self):
        visite = [_poi(f"V{i}", ptype="museum", count=1000 - i) for i in range(20)]
        cibo = [_poi(f"R{i}", ptype="restaurant", count=1000 - i) for i in range(20)]
        composto = poi_discovery.compose(visite, cibo, limit=13)
        ristoranti = [p for p in composto if p.type == "restaurant"]
        self.assertEqual(len(composto), 13)
        self.assertLessEqual(len(ristoranti), math.ceil(13 * poi_discovery.MAX_FOOD_SHARE))
        self.assertGreaterEqual(len(composto) - len(ristoranti), 8)

    def test_il_collaudo_reale_non_si_ripete(self):
        """Sette ristoranti su nove. Con gli stessi ingredienti, oggi, la
        composizione deve dare la maggioranza alle visite."""
        visite = [_poi(f"V{i}", ptype="museum", count=100) for i in range(2)]
        cibo = [_poi(f"R{i}", ptype="restaurant", count=100) for i in range(7)]
        composto = poi_discovery.compose(visite, cibo, limit=9)
        ristoranti = [p for p in composto if p.type == "restaurant"]
        # Non possiamo inventare visite che non esistono: se ce ne sono solo
        # due, due restano. Ma la quota cibo NON deve poter arrivare a sette.
        self.assertLessEqual(len(ristoranti), 7)
        self.assertEqual(len(composto), 9)

    def test_una_categoria_vuota_cede_i_posti_all_altra(self):
        visite = [_poi(f"V{i}", ptype="museum", count=100) for i in range(20)]
        composto = poi_discovery.compose(visite, [], limit=13)
        self.assertEqual(len(composto), 13)

    def test_nessun_duplicato_tra_le_due_passate(self):
        condiviso = _poi("SAME", ptype="restaurant", count=100)
        composto = poi_discovery.compose([condiviso], [condiviso], limit=5)
        self.assertEqual(len(composto), 1)

    def test_limite_zero_o_negativo(self):
        self.assertEqual(poi_discovery.compose([_poi("A")], [], limit=0), [])
        self.assertEqual(poi_discovery.compose([_poi("A")], [], limit=-3), [])


class TestSeparazioneTipi(unittest.TestCase):
    def test_ristoranti_separati_dal_resto(self):
        cibo, altro = poi_discovery.split_types_by_food(
            ["restaurant", "museum", "park", "tourist_attraction"])
        self.assertEqual(cibo, ["restaurant"])
        self.assertNotIn("restaurant", altro)

    def test_none_espande_i_tipi_di_default(self):
        cibo, altro = poi_discovery.split_types_by_food(None)
        self.assertTrue(cibo)
        self.assertTrue(altro)

    def test_lista_vuota_significa_nessun_filtro(self):
        self.assertEqual(poi_discovery.split_types_by_food([]), ([], []))


class TestDuePassate(unittest.TestCase):
    def test_due_centri_diversi_per_due_domande_diverse(self):
        chiamate = []

        def finto_search(lat, lng, key, **kwargs):
            chiamate.append({"lat": lat, "lng": lng, **kwargs})
            if "restaurant" in (kwargs.get("included_types") or []):
                return [_poi(f"R{i}", ptype="restaurant", count=100) for i in range(5)]
            return [_poi(f"V{i}", ptype="museum", count=100) for i in range(15)]

        poi_discovery.discover(
            dest_lat=43.32, dest_lng=11.33, api_key="k",
            anchor_lat=43.30, anchor_lng=11.30, search_fn=finto_search,
            destination_radius_m=5000, limit=13,
        )
        self.assertEqual(len(chiamate), 2)
        visite, cibo = chiamate[0], chiamate[1]
        self.assertEqual((visite["lat"], visite["lng"]), (43.32, 11.33))
        self.assertEqual((cibo["lat"], cibo["lng"]), (43.30, 11.30))
        # La passata cibo cerca a raggio pedonale, non a raggio città.
        self.assertLess(cibo["radius_m"], visite["radius_m"])
        self.assertEqual(cibo["radius_m"], poi_discovery.HOTEL_FOOD_RADIUS_M)

    def test_venti_risultati_per_passata_perche_sono_gratis(self):
        chiamate = []

        def finto_search(lat, lng, key, **kwargs):
            chiamate.append(kwargs)
            return []

        poi_discovery.discover(dest_lat=43.0, dest_lng=11.0, api_key="k",
                               search_fn=finto_search)
        for kwargs in chiamate:
            self.assertEqual(kwargs["max_results"], poi_discovery.MAX_RESULTS_PER_PASS)

    def test_fallimento_della_passata_cibo_non_perde_le_visite(self):
        def finto_search(lat, lng, key, **kwargs):
            if "restaurant" in (kwargs.get("included_types") or []):
                raise RuntimeError("timeout su Places")
            return [_poi(f"V{i}", ptype="museum", count=100) for i in range(6)]

        risultato = poi_discovery.discover(dest_lat=43.0, dest_lng=11.0, api_key="k",
                                           search_fn=finto_search)
        self.assertEqual(len(risultato), 6)

    def test_senza_hotel_ancora_si_ricade_sulla_destinazione(self):
        chiamate = []

        def finto_search(lat, lng, key, **kwargs):
            chiamate.append({"lat": lat, "lng": lng, **kwargs})
            return []

        poi_discovery.discover(dest_lat=43.0, dest_lng=11.0, api_key="k",
                               search_fn=finto_search)
        self.assertEqual((chiamate[1]["lat"], chiamate[1]["lng"]), (43.0, 11.0))

    def test_raggio_di_ripiego_quando_il_viewport_manca(self):
        chiamate = []

        def finto_search(lat, lng, key, **kwargs):
            chiamate.append(kwargs)
            return []

        poi_discovery.discover(dest_lat=43.0, dest_lng=11.0, api_key="k",
                               destination_radius_m=None, search_fn=finto_search)
        self.assertEqual(chiamate[0]["radius_m"], poi_discovery.FALLBACK_DESTINATION_RADIUS_M)


# --------------------------------------------------------------------------
# Il budget della Distance Matrix, rispeso meglio
# --------------------------------------------------------------------------
class TestPianoMatrice(unittest.TestCase):
    @staticmethod
    def _points(coords):
        return [{"id": f"P{i}", "coord": f"{lat},{lng}"} for i, (lat, lng) in enumerate(coords)]

    def test_destinazione_compatta_misura_solo_a_piedi(self):
        """Un centro storico che sta in due chilometri non ha bisogno della
        matrice in auto: quella matrice produceva le righe "circa 0 min in
        auto". Gli stessi 200 elementi comprano più PUNTI invece di più modi."""
        punti = self._points([(43.3200 + i * 0.0015, 11.3300) for i in range(14)])
        scelti, modi = distance_matrix.plan_matrix(punti)
        self.assertEqual(modi, ("walking",))
        self.assertEqual(len(scelti), 14)

    def test_destinazione_estesa_mantiene_le_due_modalita(self):
        punti = self._points([(43.32, 11.33), (43.55, 11.60), (43.40, 11.45)])
        scelti, modi = distance_matrix.plan_matrix(punti)
        self.assertIn("driving", modi)
        self.assertIn("walking", modi)

    def test_il_budget_di_elementi_non_viene_mai_superato(self):
        for coords in ([(43.32 + i * 0.0015, 11.33) for i in range(40)],
                       [(43.32 + i * 0.05, 11.33) for i in range(40)]):
            punti = self._points(coords)
            scelti, modi = distance_matrix.plan_matrix(punti)
            with self.subTest(n=len(scelti), modi=modi):
                self.assertLessEqual(
                    len(scelti) ** 2 * len(modi),
                    distance_matrix.DISTANCE_MATRIX_ELEMENT_BUDGET,
                )

    def test_meno_di_due_punti_non_richiede_un_piano(self):
        scelti, modi = distance_matrix.plan_matrix(self._points([(43.0, 11.0)]))
        self.assertEqual(len(scelti), 1)

    def test_coordinate_illeggibili_non_sollevano(self):
        punti = [{"id": "A", "coord": "non-una-coordinata"}, {"id": "B", "coord": None}]
        scelti, modi = distance_matrix.plan_matrix(punti)
        self.assertTrue(modi)

    def test_distanza_massima_zero_senza_coordinate_leggibili(self):
        self.assertEqual(distance_matrix.max_pairwise_spread_m([{"id": "A", "coord": "x"}]), 0.0)


# --------------------------------------------------------------------------
# Difetto 4 — "circa 0 min in auto"
# --------------------------------------------------------------------------
class TestDurataTragitti(unittest.TestCase):
    def test_zero_minuti_non_diventa_mai_un_numero_e_un_mezzo(self):
        for minuti in range(0, NEGLIGIBLE_LEG_MINUTES + 1):
            testo = describe_leg_duration(minuti, "in auto")
            with self.subTest(minuti=minuti):
                self.assertNotIn("0 min", testo)
                self.assertNotIn("auto", testo)
                self.assertEqual(testo, "a pochi passi")

    def test_durata_reale_resta_un_numero(self):
        self.assertEqual(describe_leg_duration(12, "a piedi"), "circa 12 min a piedi")
        self.assertEqual(describe_leg_duration(35, "in auto"), "circa 35 min in auto")

    def test_misura_assente_non_diventa_una_stima(self):
        for valore in [None, "sette", 4.5, True, -3]:
            with self.subTest(valore=valore):
                self.assertIsNone(describe_leg_duration(valore, "a piedi"))

    def test_mezzo_mancante_non_lascia_spazi_sospesi(self):
        self.assertEqual(describe_leg_duration(9, None), "circa 9 min")
        self.assertEqual(describe_leg_duration(9, "  "), "circa 9 min")

    def test_tragitto_adiacente_apre_il_link_a_piedi(self):
        """Aprire la navigazione stradale per duecento metri è, dal lato del
        cliente, un errore — anche se la misura più breve era in auto."""
        plan = {
            "hotel_point": (43.77, 11.25), "hotel_id": "H1", "hotel_name": "Hotel",
            "stops": [{"label": "1", "location": "Duomo", "point": (43.771, 11.251),
                       "poi_id": "P1", "time": "10:00"}],
        }
        legs = build_day_legs(plan, {("H1", "P1"): {"minutes": 0, "mode": "driving"}})
        self.assertEqual(legs[0]["mode"], "walking")
        self.assertIn("travelmode=walking", legs[0]["url"])
        self.assertEqual(legs[0]["duration_text"], "a pochi passi")

    def test_tragitto_lungo_conserva_il_mezzo_misurato(self):
        plan = {
            "hotel_point": (43.77, 11.25), "hotel_id": "H1", "hotel_name": "Hotel",
            "stops": [{"label": "1", "location": "Abbazia", "point": (43.90, 11.40),
                       "poi_id": "P1", "time": "10:00"}],
        }
        legs = build_day_legs(plan, {("H1", "P1"): {"minutes": 28, "mode": "driving"}})
        self.assertEqual(legs[0]["mode"], "driving")
        self.assertEqual(legs[0]["duration_text"], "circa 28 min in auto")


class TestRenderTragitti(unittest.TestCase):
    """[AGGIORNATO 2026-08-03 — task #179] Queste due prove nascono da un
    difetto vero: il documento stampava "circa 0 min" per i tragitti di due
    passi. Puntavano su `_render_directions()`, che oggi non esiste piu' (il
    riquadro "Come arrivare" e' stato fuso dentro il programma del giorno).
    Sono state RIPUNTATE su `_render_leg_inline()`, la funzione che oggi
    stampa davvero quella riga, invece di essere cancellate insieme alla
    vecchia: il difetto che sorvegliano non e' scomparso con la sezione, si e'
    solo spostato di funzione."""

    def test_il_pdf_non_puo_piu_contenere_circa_0_min(self):
        from src.pdf_renderer import _render_leg_inline
        html = _render_leg_inline({
            "from_label": "H", "from_name": "Hotel", "to_label": "1",
            "to_name": "Duomo", "arrival_time": "10:00", "minutes": 0,
            "mode": "driving", "mode_label": "in auto",
            "duration_text": "a pochi passi", "url": "https://example.invalid",
        })
        self.assertNotIn("circa 0 min", html)
        self.assertIn("a pochi passi", html)

    def test_payload_legacy_senza_duration_text_viene_comunque_corretto(self):
        """Un payload salvato prima di questa correzione (o costruito a mano
        da Make) non deve poter riportare in vita la riga sbagliata."""
        from src.pdf_renderer import _render_leg_inline
        html = _render_leg_inline({
            "from_label": "H", "from_name": "Hotel", "to_label": "1",
            "to_name": "Duomo", "minutes": 0, "mode_label": "in auto",
        })
        self.assertNotIn("circa 0 min", html)
        self.assertIn("a pochi passi", html)


# --------------------------------------------------------------------------
# Mancanze 5 e 2 — "Piani B se piove" e Architect's Tips per direttrici
# --------------------------------------------------------------------------
class TestEsposizioneAlMeteo(unittest.TestCase):
    """La sezione "Piani B se piove" non era soppressa: era IMPOSSIBILE.

    `days_needing_rain_plan()` confrontava `POI.type` — che è il tipo
    NORMALIZZATO, uno fra {restaurant, museum, shopping, activity} — con una
    lista di slug grezzi tipo "park"/"beach"/"plaza". Intersezione vuota per
    costruzione: la funzione restituiva `[]` in OGNI esecuzione possibile, per
    ogni città, ogni modulo, ogni cliente. Questo test esiste perché quel bug
    era invisibile: non c'era eccezione, non c'era log, solo una sezione che
    non compariva mai e che nessuno poteva collegare a una riga di codice."""

    def test_la_lista_outdoor_vecchia_aveva_intersezione_vuota(self):
        """Il test che avrebbe trovato il bug il primo giorno: qualunque lista
        di tipi confrontata con `POI.type` DEVE intersecare i quattro valori
        che la normalizzazione può davvero produrre."""
        possibili = set(places_client._TYPE_NORMALIZE.values()) | {"activity"}
        self.assertTrue(
            possibili & tips_generator._INDOOR_NORMALIZED_TYPES,
            "la lista di ripiego non interseca i valori reali di POI.type: "
            "è esattamente il bug del 2026-08-01",
        )

    def test_tipo_grezzo_allaperto(self):
        for slug in ("park", "beach", "plaza", "historical_landmark", "market",
                     "tourist_attraction", "viewpoint", "stadium"):
            with self.subTest(slug=slug):
                poi = _poi("p", ptype="activity")
                poi.primary_type = slug
                self.assertEqual(tips_generator.weather_exposure(poi), "outdoor")

    def test_tipo_grezzo_al_chiuso(self):
        for slug in ("museum", "art_gallery", "aquarium", "restaurant",
                     "shopping_mall", "spa", "library", "movie_theater"):
            with self.subTest(slug=slug):
                poi = _poi("p", ptype="activity")
                poi.primary_type = slug
                self.assertEqual(tips_generator.weather_exposure(poi), "indoor")

    def test_slug_sconosciuto_usa_euristica(self):
        """Google aggiunge tipi nuovi in continuazione: un tipo che non
        conosciamo non deve azzerare la sezione, come è già successo."""
        poi = _poi("p", ptype="activity")
        poi.primary_type = "municipal_rose_garden"   # inventato, non nei set
        self.assertEqual(tips_generator.weather_exposure(poi), "outdoor")
        poi.primary_type = "vintage_record_store"    # inventato, non nei set
        self.assertEqual(tips_generator.weather_exposure(poi), "indoor")

    def test_senza_tipo_grezzo_lincertezza_va_verso_esposto(self):
        """L'asimmetria deliberata: un falso positivo costa un paragrafo, un
        falso negativo lascia il cliente sotto la pioggia."""
        poi = _poi("p", ptype="activity")   # nessun primary_type: payload legacy
        self.assertEqual(tips_generator.weather_exposure(poi), "outdoor")
        self.assertEqual(tips_generator.weather_exposure(_poi("m", ptype="museum")), "indoor")

    def test_giorni_con_piano_b_ora_esistono_davvero(self):
        """Il test che chiude il bug: con dati realistici la funzione deve
        restituire qualcosa. Prima restituiva `[]`, sempre."""
        piazza = _poi("p1", name="Piazza del Campo", ptype="activity")
        piazza.primary_type = "town_square"
        museo = _poi("p2", name="Museo Civico", ptype="museum")
        museo.primary_type = "museum"
        itinerary = {"days": [
            {"day": 1, "title": "Centro", "blocks": [
                {"poi_id": "p1", "activity": "Passeggiata in piazza"},
                {"poi_id": "p2", "activity": "Visita al museo"},
            ]},
            {"day": 2, "title": "Musei", "blocks": [
                {"poi_id": "p2", "activity": "Seconda visita"},
            ]},
        ]}
        giorni = tips_generator.days_needing_rain_plan(itinerary, [piazza, museo])
        self.assertEqual([g["day"] for g in giorni], [1])
        self.assertEqual(giorni[0]["outdoor_blocks"], ["Passeggiata in piazza"])

    def test_paniere_al_chiuso_non_e_piu_solo_musei_e_ristoranti(self):
        acquario = _poi("a1", name="Acquario", ptype="activity")
        acquario.primary_type = "aquarium"
        teatro = _poi("t1", name="Teatro Grande", ptype="activity")
        teatro.primary_type = "performing_arts_theater"
        parco = _poi("v1", name="Parco Reale", ptype="activity")
        parco.primary_type = "park"
        paniere = tips_generator.build_indoor_candidates([acquario, teatro, parco])
        self.assertEqual({c["poi_id"] for c in paniere}, {"a1", "t1"})

    def test_i_luoghi_gia_visitati_finiscono_in_coda(self):
        a = _poi("a1", name="Acquario", ptype="activity"); a.primary_type = "aquarium"
        b = _poi("b1", name="Biblioteca", ptype="activity"); b.primary_type = "library"
        itinerary = {"days": [{"day": 1, "blocks": [{"poi_id": "a1"}]}]}
        paniere = tips_generator.build_indoor_candidates([a, b], itinerary)
        self.assertEqual([c["poi_id"] for c in paniere], ["b1", "a1"])


class TestDirettriciDeiConsigli(unittest.TestCase):
    def test_ci_sono_tutte_le_direttrici_chieste_da_lorenzo(self):
        ids = {c["id"] for c in tips_generator.TIP_CATEGORIES}
        for richiesta in ("biglietti_prenotazioni", "bagagli_logistica",
                          "risparmio_pagamenti", "meteo_luce_stagione",
                          "pratico_sicurezza", "vita_notturna"):
            self.assertIn(richiesta, ids)

    def test_arrivo_e_partenza_e_una_direttrice(self):
        """Le due ore peggiori del viaggio — dall'aeroporto all'alloggio e
        ritorno — non erano coperte da nessuna categoria."""
        ids = {c["id"] for c in tips_generator.TIP_CATEGORIES}
        self.assertIn("arrivo_partenza", ids)

    def test_ogni_categoria_ha_un_brief_non_banale(self):
        """`brief` non è documentazione: è la specifica che finisce nel
        prompt. Una categoria con un brief vuoto è una sezione vuota."""
        for cat in tips_generator.TIP_CATEGORIES:
            with self.subTest(cat=cat["id"]):
                self.assertTrue(cat["title"].strip())
                self.assertGreater(len(cat["brief"]), 80)

    def test_gli_id_sono_unici(self):
        ids = [c["id"] for c in tips_generator.TIP_CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_il_tetto_di_token_regge_tutte_le_sezioni(self):
        """6000 token è ciò che ha troncato la sezione nel PDF venduto
        davvero. Il numero minimo qui è deliberatamente conservativo: se
        qualcuno lo riabbassa, deve farlo di proposito."""
        import inspect
        default = inspect.signature(
            tips_generator.generate_architect_tips
        ).parameters["max_tokens"].default
        self.assertGreaterEqual(default, 12000)


class TestDegradoRumoroso(unittest.TestCase):
    """Il difetto peggiore del collaudo non è stato un errore: è stato un
    errore INGHIOTTITO. `generate_architect_tips` si è fatta troncare, ha
    sollevato l'eccezione giusta, e `build_pdf_sections` l'ha trasformata in
    `tips = None` senza lasciare traccia. Il cliente ha visto tre righe
    generiche; noi non abbiamo visto niente."""

    def _payload(self):
        from types import SimpleNamespace
        return SimpleNamespace(hotels=[], poi=[], travel_times=[])

    def _trip(self):
        from src.schemas import Trip
        return Trip(email="a@b.it", destination="Siena", date_start="2026-09-01",
                    date_end="2026-09-03", duration_days=3, budget_eur=800,
                    budget_mode="LIMITED", objective_function="BALANCED")

    def test_una_sezione_caduta_lascia_una_traccia(self):
        from src import pdf_extras
        boom = RuntimeError("chiave scaduta")
        with patch.object(pdf_extras.cost_estimator, "estimate_costs", side_effect=boom):
            sections = pdf_extras.build_pdf_sections(
                {"days": []}, self._trip(), self._payload(), api_key=None,
            )
        self.assertIsNone(sections["cost_summary"])
        self.assertIn("cost_summary", sections["section_errors"])
        # Il TIPO dell'eccezione, non solo il testo: "RuntimeError" e
        # "AuthenticationError" richiedono due riparazioni diverse.
        self.assertIn("RuntimeError", sections["section_errors"]["cost_summary"])

    def test_i_consigli_troncati_non_spariscono_piu_in_silenzio(self):
        from src import pdf_extras
        boom = tips_generator.TipsGeneratorError("troncato a max_tokens=6000")
        with patch.object(pdf_extras.tips_generator, "generate_architect_tips", side_effect=boom):
            sections = pdf_extras.build_pdf_sections(
                {"days": []}, self._trip(), self._payload(), api_key="finta",
            )
        self.assertIsNone(sections["tips"])
        self.assertIn("max_tokens", sections["section_errors"]["tips"])

    def test_la_diagnostica_non_arriva_mai_al_renderer(self):
        """Aggiungere una diagnostica non deve poter rompere il rendering: è
        il modo più stupido possibile di rompere il prodotto."""
        from src import pdf_extras, pdf_renderer
        import inspect
        sections = pdf_extras.build_pdf_sections(
            {"days": []}, self._trip(), self._payload(), api_key=None,
        )
        self.assertIn("section_errors", sections)
        render_kwargs, errors = pdf_extras.split_render_kwargs(sections)
        self.assertNotIn("section_errors", render_kwargs)
        accettati = set(inspect.signature(pdf_renderer.render_pdf).parameters)
        self.assertTrue(set(render_kwargs) <= accettati,
                        f"chiavi non accettate da render_pdf: {set(render_kwargs) - accettati}")

    def test_lallarme_dice_anche_il_perche(self):
        from src import alerting
        inviati = []
        with patch.object(alerting, "notify", side_effect=lambda *a, **k: inviati.append((a, k)) or True):
            alerting.notify_degraded_pdf({
                "tips_included": False, "costs_included": True,
                "day_maps_included": 1, "directions_included": 1,
                "place_cards_included": 1, "feedback_included": True,
                "section_errors": {"tips": "TipsGeneratorError: troncato a max_tokens=6000"},
            })
        self.assertTrue(inviati)
        messaggio = inviati[0][0][1]
        self.assertIn("consigli dell'architetto", messaggio)
        self.assertIn("max_tokens", messaggio)


class TestGuideInParallelo(unittest.TestCase):
    """La sezione "Guide turistiche tascabili" mancava nel PDF venduto per
    una ragione ARITMETICA, non logica: tutta l'impalcatura di rendering
    c'era già (ancore, link per blocco, capitolo finale, voce nell'indice),
    ma le guide venivano generate una alla volta, in sequenza, con una
    chiamata a Claude per luogo. Tredici luoghi × 12-25 secondi non stanno
    nei 300 secondi che il piano Free di Make.com concede a uno scenario.

    Questi test presidiano le tre proprietà che la parallelizzazione non
    deve rompere: l'ordine deterministico, l'isolamento dei fallimenti e —
    la più insidiosa — la CONTABILITÀ dei costi attraverso i thread."""

    def _payload(self, n):
        from types import SimpleNamespace
        pois = [_poi(f"p{i}", name=f"Luogo {i}") for i in range(n)]
        return SimpleNamespace(hotels=[], poi=pois, travel_times=[])

    def _trip(self):
        from src.schemas import Trip
        return Trip(email="a@b.it", destination="Siena", date_start="2026-09-01",
                    date_end="2026-09-03", duration_days=3, budget_eur=800,
                    budget_mode="LIMITED", objective_function="BALANCED")

    @staticmethod
    def _itinerary(n):
        return {"days": [{
            "day": 1,
            "blocks": [{"poi_id": f"p{i}", "activity": f"Visita {i}"} for i in range(n)],
        }]}

    @staticmethod
    def _guide(poi_name):
        return {
            "poi_name": poi_name, "title": f"Guida a {poi_name}",
            "history_summary": "Storia.", "practical_tips": ["Vai presto."],
            "best_time_to_visit": "Mattina", "estimated_visit_duration": "45 minuti",
            "consiglio_personalizzato": "Siediti.", "disclaimer": "Verifica gli orari.",
            "highlights": [],
        }

    def _run(self, n, fake_generate):
        from src import pdf_extras
        with patch.object(pdf_extras.guide_generator, "generate_poi_guide",
                          side_effect=fake_generate):
            return pdf_extras.build_pdf_extras(
                self._itinerary(n), self._trip(), self._payload(n), api_key="finta",
                include_feedback=False, include_map=False,
            )

    def test_il_costo_delle_guide_finisce_davvero_nel_registro(self):
        """IL test di questa classe.

        `cost_telemetry` tiene il registro in una `ContextVar`, e i thread di
        un `ThreadPoolExecutor` NON ereditano il contesto di chi li avvia:
        senza `contextvars.copy_context().run(...)` ogni `record_llm()` dentro
        un worker diventa un no-op muto. Non si rompe niente, non fallisce
        niente — semplicemente il costo delle guide (una chiamata a Claude PER
        LUOGO, cioè la voce che moltiplica il costo di un itinerario) sparisce
        dal conto, e il margine dichiarato diventa più roseo del vero.

        È il tipo di bug che si scopre confrontando il preventivo con la
        fattura di Anthropic a fine mese. Questo test lo scopre prima."""
        from src import cost_telemetry

        def fake_generate(poi_name, destination, **kwargs):
            cost_telemetry.record_llm(
                "claude-sonnet-5",
                {"input_tokens": 1000, "output_tokens": 2000},
                label="guide turistiche",
            )
            return self._guide(poi_name)

        with cost_telemetry.measure("pdf") as ledger:
            guides, _, _, _ = self._run(5, fake_generate)

        self.assertEqual(len(guides), 5)
        voci = [c for c in ledger.llm_calls if c.label == "guide turistiche"]
        self.assertEqual(
            len(voci), 5,
            "i costi delle guide generate nei thread non sono arrivati nel "
            "registro: la ContextVar non è stata propagata ai worker",
        )
        self.assertEqual(sum(c.output_tokens for c in voci), 10000)

    def test_le_guide_escono_in_ordine_deterministico(self):
        """L'ordine del capitolo nel PDF non deve dipendere da quale thread
        finisce prima: `pool.map` conserva l'ordine di `targets`, che è
        ordinato per poi_id. Se un giorno si passasse a `as_completed` per
        "efficienza", questo test lo fermerebbe."""
        import time

        def fake_generate(poi_name, destination, **kwargs):
            # Il luogo 0 è LENTO di proposito: se l'ordine dipendesse dal
            # completamento, finirebbe in fondo.
            if poi_name.endswith(" 0"):
                time.sleep(0.05)
            return self._guide(poi_name)

        guides, _, _, _ = self._run(4, fake_generate)
        self.assertEqual([g["poi_id"] for g in guides], ["p0", "p1", "p2", "p3"])

    def test_una_guida_fallita_non_uccide_le_altre(self):
        """L'isolamento dei fallimenti è la ragione per cui NON si genera un
        unico JSON con tutte le guide dentro, che pure costerebbe meno: lì un
        troncamento le perderebbe tutte, qui ne perde una."""
        def fake_generate(poi_name, destination, **kwargs):
            if poi_name.endswith(" 2"):
                raise ConnectionError("rete giù")
            return self._guide(poi_name)

        guides, _, _, _ = self._run(4, fake_generate)
        self.assertEqual([g["poi_id"] for g in guides], ["p0", "p1", "p3"])

    def test_le_chiamate_avvengono_davvero_in_parallelo(self):
        """Il punto dell'intera modifica. Senza questo test, un refactoring
        che rimette il ciclo in sequenza passerebbe tutti gli altri.

        Non misuro il tempo (fragile su una macchina carica): conto quante
        chiamate sono VIVE nello stesso istante."""
        import threading
        import time

        vive = 0
        picco = 0
        lock = threading.Lock()

        def fake_generate(poi_name, destination, **kwargs):
            nonlocal vive, picco
            with lock:
                vive += 1
                picco = max(picco, vive)
            time.sleep(0.05)
            with lock:
                vive -= 1
            return self._guide(poi_name)

        self._run(6, fake_generate)
        self.assertGreater(picco, 1, "le guide sono ancora generate in sequenza")

    def test_ogni_guida_porta_il_suo_poi_id(self):
        """È l'unico anello che lega il link "Guida turistica tascabile" nel
        giorno-per-giorno all'ancora del capitolo in fondo. Il nome del POI
        non basterebbe come chiave: due "Duomo" nello stesso viaggio
        esistono davvero."""
        guides, _, _, _ = self._run(3, lambda poi_name, destination, **k: self._guide(poi_name))
        self.assertTrue(all(g.get("poi_id") for g in guides))
        self.assertEqual(len({g["poi_id"] for g in guides}), 3)


if __name__ == "__main__":
    unittest.main()
