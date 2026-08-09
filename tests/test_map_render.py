"""
Test della cartina disegnata in locale (`src/map_render.py`).

PERCHÉ QUESTO FILE ESISTE
Il PDF di esempio è arrivato al cliente senza cartine. Il codice delle cartine
era intatto: mancava la CHIAVE Google, e l'unica sorgente di cartine era Google.
Una funzione del prodotto che dipende da una sola chiamata di rete non è una
funzione, è una speranza — e la speranza non si testa.

Questi test bloccano quel difetto alla radice: una giornata con coordinate deve
produrre una figura SEMPRE, senza rete e senza chiavi. Se qualcuno domani
reintroduce la dipendenza singola, qui si accende un rosso.

Nessun test qui usa la rete. È il punto.
"""

import unittest

from src import map_render


HOTEL = (43.3167, 11.3300)


def _stop(label, name, lat, lng, color="blue"):
    return {"label": label, "name": name, "point": (lat, lng), "color": color,
            "time": "10:00", "type_label": "Attività"}


def _plan(**over):
    plan = {
        "day": 1,
        "title": "Centro storico",
        "hotel_point": HOTEL,
        "hotel_name": "Palazzo Ravizza",
        "stops": [
            _stop("1", "Piazza del Campo", 43.3182, 11.3315),
            _stop("2", "Duomo di Siena", 43.3175, 11.3288, "orange"),
            _stop("3", "Osteria Le Logge", 43.3188, 11.3330, "green"),
        ],
    }
    plan.update(over)
    return plan


def _is_png(blob) -> bool:
    return isinstance(blob, bytes) and blob[:8] == b"\x89PNG\r\n\x1a\n"


class TestRenderDayMapPng(unittest.TestCase):

    def test_una_giornata_con_coordinate_produce_sempre_una_figura(self):
        # Il test che non c'era. Senza chiave, senza rete, senza Google.
        png = map_render.render_day_map_png(_plan(), "Giorno 1")
        self.assertTrue(_is_png(png), "una giornata geolocalizzata deve avere la sua cartina")

    def test_nessuna_tappa_geolocalizzata_niente_figura(self):
        # Meglio nessuna figura di una figura vuota: un riquadro grigio con
        # dentro il nulla fa sembrare rotto il documento, e non aggiunge niente
        # alla legenda testuale che c'è comunque accanto.
        for stops in ([], [{"label": "1", "name": "Senza coordinate"}]):
            with self.subTest(stops=stops):
                self.assertIsNone(map_render.render_day_map_png(_plan(stops=stops)))

    def test_funziona_anche_senza_albergo(self):
        # Il perno può mancare (viaggio senza pernottamento, hotel non
        # geolocalizzato): le tappe restano e la cartina pure.
        png = map_render.render_day_map_png(_plan(hotel_point=None))
        self.assertTrue(_is_png(png))

    def test_una_sola_tappa_non_fa_saltare_il_disegno(self):
        # Caso degenere della proiezione: un punto solo non ha estensione, e una
        # divisione per zero qui cancellerebbe la cartina di quel giorno.
        png = map_render.render_day_map_png(
            _plan(stops=[_stop("1", "Unica tappa", 43.3182, 11.3315)], hotel_point=None))
        self.assertTrue(_is_png(png))

    def test_punti_coincidenti_non_fanno_saltare_il_disegno(self):
        # Due POI allo stesso indirizzo (museo e caffè del museo): distanza zero.
        same = [_stop("1", "Museo", 43.3182, 11.3315),
                _stop("2", "Caffè del museo", 43.3182, 11.3315)]
        self.assertTrue(_is_png(map_render.render_day_map_png(_plan(stops=same, hotel_point=None))))

    def test_accetta_le_coordinate_anche_in_forma_di_dizionario(self):
        # `maps_static` usa la tupla, Google e Make usano {"lat", "lng"}: la
        # cartina non deve sparire perché il payload arriva dall'altra strada.
        stops = [{"label": "1", "name": "Piazza", "point": {"lat": 43.3182, "lng": 11.3315}},
                 {"label": "2", "name": "Duomo", "point": {"lat": 43.3175, "lng": 11.3288}}]
        png = map_render.render_day_map_png({"stops": stops, "hotel_point": {"lat": 43.3167, "lng": 11.33}})
        self.assertTrue(_is_png(png))

    def test_coordinate_malformate_non_fanno_cadere_l_intera_giornata(self):
        # Una tappa con coordinate spazzatura deve costare quella tappa, non la
        # cartina di tutti gli altri.
        stops = [_stop("1", "Buona", 43.3182, 11.3315),
                 {"label": "2", "name": "Rotta", "point": ("nord", "ovest")},
                 {"label": "3", "name": "Fuori scala", "point": (999.0, 999.0)},
                 _stop("4", "Buona 2", 43.3175, 11.3288)]
        self.assertTrue(_is_png(map_render.render_day_map_png(_plan(stops=stops))))

    def test_non_solleva_mai(self):
        # Contratto esplicito: la cartina è un di più, il documento non deve mai
        # cadere per colpa sua. Qualunque schifezza in ingresso → None.
        for junk in (None, {}, {"stops": None}, {"stops": "non una lista"},
                     {"stops": [None, 42, "x"]}):
            with self.subTest(junk=junk):
                self.assertIsNone(map_render.render_day_map_png(junk))

    def test_la_figura_resta_leggera(self):
        # Make tronca le stringhe intorno ai 256 KB e il PDF viaggia in
        # allegato: una cartina da mezzo mega per giorno romperebbe la catena
        # in un punto che nessuno guarda.
        png = map_render.render_day_map_png(_plan())
        self.assertLess(len(png), 120_000, "cartina troppo pesante per il trasporto")


class TestAttachLocalMaps(unittest.TestCase):

    def test_riempie_le_giornate_senza_immagine(self):
        out = map_render.attach_local_maps([dict(_plan(), png=None)])
        self.assertTrue(_is_png(out[0]["png"]))
        self.assertEqual(out[0]["map_source"], "schema")

    def test_non_sovrascrive_mai_la_cartina_di_google(self):
        # Una mappa stradale vera è meglio del nostro schema ogni volta che c'è:
        # se questo test diventa rosso stiamo peggiorando il prodotto per
        # uniformità, che è il peggior motivo possibile.
        out = map_render.attach_local_maps([dict(_plan(), png=b"MAPPA-DI-GOOGLE")])
        self.assertEqual(out[0]["png"], b"MAPPA-DI-GOOGLE")
        self.assertEqual(out[0]["map_source"], "google")

    def test_e_idempotente(self):
        once = map_render.attach_local_maps([dict(_plan(), png=None)])
        twice = map_render.attach_local_maps(once)
        self.assertEqual(once[0]["png"], twice[0]["png"])
        self.assertEqual(twice[0]["map_source"], "schema")

    def test_non_modifica_la_lista_in_ingresso(self):
        # Effetto collaterale silenzioso su una struttura condivisa fra cartine,
        # legenda e sezione "come arrivare": da evitare.
        original = dict(_plan(), png=None)
        map_render.attach_local_maps([original])
        self.assertIsNone(original["png"])

    def test_una_giornata_senza_coordinate_resta_senza_immagine(self):
        out = map_render.attach_local_maps([{"day": 2, "title": "Riposo", "stops": [], "png": None}])
        self.assertIsNone(out[0]["png"])
        self.assertNotIn("map_source", out[0])

    def test_lista_vuota_o_none(self):
        self.assertEqual(map_render.attach_local_maps([]), [])
        self.assertEqual(map_render.attach_local_maps(None), [])

    def test_scarta_gli_elementi_non_dizionario_senza_sollevare(self):
        out = map_render.attach_local_maps([None, "x", dict(_plan(), png=None)])
        self.assertEqual(len(out), 1)


class TestScala(unittest.TestCase):
    """La barra della scala è una PROMESSA al cliente: se dice 200 m, due punti
    a due centimetri devono distare davvero circa 200 m. Se questi test cadono,
    la cartina sta mentendo — ed è meglio nessuna cartina di una che mente."""

    def test_i_numeri_tondi_sono_della_serie_1_2_5(self):
        for raw, expected in ((1, 1), (3, 2), (7, 5), (12, 10), (30, 20), (80, 50),
                              (140, 100), (900, 500), (1400, 1000)):
            with self.subTest(raw=raw):
                self.assertEqual(map_render._nice_scale_metres(raw), expected)

    def test_la_distanza_reale_e_quella_giusta(self):
        # Un grado di latitudine ≈ 111 km: controllo indipendente dalla formula
        # usata dentro il modulo.
        d = map_render._haversine_m((43.0, 11.0), (44.0, 11.0))
        self.assertAlmostEqual(d / 1000, 111.2, delta=1.0)

    def test_la_proiezione_usa_UNA_sola_scala_per_i_due_assi(self):
        # Scale diverse su x e y schiaccerebbero la figura e la barra della
        # scala varrebbe solo in una direzione: la dicitura "in scala"
        # diventerebbe falsa.
        geo = [(43.30, 11.30), (43.31, 11.30), (43.30, 11.34)]
        px = map_render._project_points(geo, 400, 300)
        dy_px = abs(px[1][1] - px[0][1])
        dx_px = abs(px[2][0] - px[0][0])
        m_per_px_y = map_render._haversine_m(geo[0], geo[1]) / dy_px
        m_per_px_x = map_render._haversine_m(geo[0], geo[2]) / dx_px
        self.assertAlmostEqual(m_per_px_x / m_per_px_y, 1.0, delta=0.02)

    def test_formattazione_metri_e_chilometri(self):
        self.assertEqual(map_render._format_metres(200), "200 m")
        self.assertEqual(map_render._format_metres(2000), "2 km")


# ---------------------------------------------------------------------------
# LA CARTINA VERA SOTTO I VETTORI
#
# [Richiesta di Lorenzo del 2026-08-02, con la foto in mano: "ora quella parte
# e' fatta bene ma manca la cartina, ci sono solamente i vettori ma la cartina
# in se' manca"]
#
# Aveva ragione e la causa non era un errore: Google e lo schema erano due
# sorgenti ALTERNATIVE, e senza chiave restava lo schema — pallini su una
# griglia, senza una strada sotto. Ora si mettono INSIEME: a Google si chiede
# solo lo sfondo, i pallini li disegniamo noi sopra.
#
# Questi test bloccano i due modi in cui la cosa puo' tornare indietro:
#   1. qualcuno rimette i marker nell'URL di Google (e i colori smettono di
#      corrispondere alla legenda accanto, e l'URL puo' di nuovo sforare);
#   2. il disegno sopra lo sfondo fallisce e viene consegnato lo SFONDO NUDO,
#      che e' la cartina della citta' e non della giornata: il cliente
#      cercherebbe i pallini della legenda senza trovarli. E' esattamente il
#      difetto di partenza al contrario.
# ---------------------------------------------------------------------------

def _sfondo_finto(width=1280, height=876, colore=(233, 231, 227)) -> bytes:
    """Un PNG delle stesse dimensioni che restituirebbe Google. Non e' una
    cartina e non finge di esserlo: qui si verifica la GEOMETRIA del disegno
    sopra, e per quella lo sfondo e' irrilevante. La sandbox non ha rete verso
    nessun fornitore di mappe (verificato: Google, OSM, Mapbox e Carto
    rispondono tutti 000), quindi un test che scaricasse davvero una cartina
    sarebbe un test che non gira mai."""
    import io as _io
    from PIL import Image
    buffer = _io.BytesIO()
    Image.new("RGB", (width, height), colore).save(buffer, format="PNG")
    return buffer.getvalue()


BASE_MAP = {"center": (43.3181, 11.3307), "zoom": 17, "size": (640, 438), "scale": 2}


class TestIPalliniCadonoDoveCadonoDavvero(unittest.TestCase):
    """La georeferenziazione. Se questa e' sbagliata il danno e' PEGGIO di non
    avere la cartina: un pallino appoggiato sull'isolato accanto e' un'immagine
    che mente con l'autorevolezza di una mappa stradale."""

    def test_il_centro_della_cartina_cade_al_centro_dell_immagine(self):
        px = map_render._google_pixels([BASE_MAP["center"]], BASE_MAP, 1280, 876)[0]
        self.assertAlmostEqual(px[0], 640.0, delta=0.5)
        self.assertAlmostEqual(px[1], 438.0, delta=0.5)

    def test_la_distanza_in_pixel_corrisponde_alla_distanza_in_metri(self):
        """Il controllo che rende verificabile "allineato": si prendono due
        coordinate reali, si misura quanti pixel le separano sul disegno e si
        confronta con la distanza vera divisa per la scala nota della cartina.
        Se qualcuno cambia la proiezione o dimentica il fattore `scale`, qui
        salta subito."""
        centro = BASE_MAP["center"]
        altro = (43.3220, 11.3360)
        (p1, p2) = map_render._google_pixels([centro, altro], BASE_MAP, 1280, 876)
        dist_px = ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
        metri_veri = map_render._haversine_m(centro, altro)
        mpp = map_render._metres_per_pixel_at_zoom(BASE_MAP)
        self.assertAlmostEqual(dist_px * mpp / metri_veri, 1.0, delta=0.01)

    def test_la_scala_dipende_da_zoom_latitudine_e_fattore_di_scala(self):
        # Uno zoom in piu' dimezza i metri per pixel; `scale=2` li dimezza
        # ancora (piu' pixel, stessa area).
        base = dict(BASE_MAP)
        piu_zoom = dict(BASE_MAP, zoom=18)
        senza_scale = dict(BASE_MAP, scale=1)
        self.assertAlmostEqual(
            map_render._metres_per_pixel_at_zoom(base)
            / map_render._metres_per_pixel_at_zoom(piu_zoom), 2.0, delta=0.001)
        self.assertAlmostEqual(
            map_render._metres_per_pixel_at_zoom(senza_scale)
            / map_render._metres_per_pixel_at_zoom(base), 2.0, delta=0.001)


class TestIlDisegnoSopraLaCartina(unittest.TestCase):

    def test_sopra_lo_sfondo_esce_una_figura_diversa_dallo_sfondo(self):
        """Ovvio a dirsi, ed e' il difetto che si vuole impedire: consegnare
        lo sfondo cosi' com'e' significa dare al cliente la cartina della
        citta' al posto della cartina della sua giornata."""
        sfondo = _sfondo_finto()
        png, meta = map_render.render_day_map_over_base(
            _plan(), "Giorno 1", sfondo, BASE_MAP)
        self.assertTrue(_is_png(png))
        self.assertNotEqual(png, sfondo, "nessun pallino e' stato disegnato sopra")
        self.assertIn("declustered", meta)

    def test_uno_sfondo_illeggibile_non_fa_cadere_niente(self):
        png, meta = map_render.render_day_map_over_base(
            _plan(), "Giorno 1", b"non-sono-un-png", BASE_MAP)
        self.assertIsNone(png)
        self.assertEqual(meta, {})

    def test_parametri_di_georeferenziazione_mancanti_niente_disegno(self):
        # Meglio nessun disegno che pallini appoggiati a caso: senza centro e
        # zoom non si sa DOVE cade una coordinata su quell'immagine.
        for rotto in ({}, {"center": (43.3, 11.3)}, {"zoom": 17}, None):
            with self.subTest(base_map=rotto):
                png, _ = map_render.render_day_map_over_base(
                    _plan(), "Giorno 1", _sfondo_finto(), rotto)
                self.assertIsNone(png)


class TestAttachLocalMapsSceglieLaSorgenteGiusta(unittest.TestCase):

    def test_con_lo_sfondo_di_google_si_disegna_sopra_e_si_dichiara_google(self):
        sfondo = _sfondo_finto()
        out = map_render.attach_local_maps([
            dict(_plan(), png=sfondo, base_map=BASE_MAP),
        ])
        self.assertEqual(out[0]["map_source"], "google")
        self.assertTrue(_is_png(out[0]["png"]))
        self.assertNotEqual(out[0]["png"], sfondo,
                            "lo sfondo nudo non deve mai arrivare al cliente")

    def test_se_il_disegno_sopra_fallisce_si_ripiega_sullo_schema(self):
        """La regola: mai consegnare lo sfondo senza i pallini. Se il disegno
        non riesce si butta lo sfondo e si ridisegna lo schema, che non dipende
        da niente di esterno."""
        out = map_render.attach_local_maps([
            dict(_plan(), png=b"sfondo-rotto", base_map=BASE_MAP),
        ])
        self.assertEqual(out[0]["map_source"], "schema")
        self.assertTrue(_is_png(out[0]["png"]))
        self.assertNotEqual(out[0]["png"], b"sfondo-rotto")

    def test_una_cartina_gia_finita_non_viene_toccata(self):
        # Comportamento storico: `png` senza `base_map` e' gia' completa.
        out = map_render.attach_local_maps([dict(_plan(), png=b"GIA-FINITA")])
        self.assertEqual(out[0]["png"], b"GIA-FINITA")
        self.assertEqual(out[0]["map_source"], "google")

    def test_senza_niente_si_disegna_lo_schema(self):
        out = map_render.attach_local_maps([dict(_plan(), png=None, base_map=None)])
        self.assertEqual(out[0]["map_source"], "schema")
        self.assertTrue(_is_png(out[0]["png"]))


# ---------------------------------------------------------------------------
# I PALLINI DIVENTANO CLICCABILI
#
# La cartina e' un PNG: dentro un PNG non si clicca niente. Perche' il cliente
# possa toccare il pallino "2" sul telefono e trovarsi la navigazione verso il
# museo, il renderer deve sapere DOVE, sull'immagine, e' finito quel pallino —
# e deve saperlo in percentuale, perche' l'immagine nel documento e' scalata a
# `max-width: 100%` e i pixel del disegno non sono i pixel della pagina.
#
# Queste coordinate NON si possono ricalcolare a valle: il declutter sposta i
# pallini per renderli distinguibili, e un secondo calcolo che non lo rifacesse
# identico metterebbe il link a qualche millimetro dal pallino. Su un telefono
# quel millimetro e' la differenza fra "si apre il museo" e "non succede
# niente" — o peggio, "si apre il ristorante di fianco".
# ---------------------------------------------------------------------------

# Quattro punti lontani fra loro: alla scala di BASE_MAP distano centinaia di
# pixel, cioe' molto piu' del diametro di un pallino. Su questa disposizione il
# declutter NON deve muovere niente, ed e' l'unico caso in cui la posizione
# esportata e la posizione proiettata devono coincidere.
def _plan_sparso(**over):
    plan = _plan(stops=[
        _stop("1", "Punto a nord-ovest", 43.3193, 11.3287),
        _stop("2", "Punto a nord-est", 43.3193, 11.3327, "orange"),
        _stop("3", "Punto a sud-est", 43.3169, 11.3327, "green"),
    ], hotel_point=(43.3181, 11.3307))
    plan.update(over)
    return plan


def _geo_del_piano(plan):
    """Le coordinate nell'ordine in cui il disegno le proietta: hotel (se c'e')
    e poi le tappe geolocalizzate."""
    stops, hotel_point = map_render._stops_and_hotel(plan)
    return map_render._geo_points(stops, hotel_point)


class TestSuOgniPallinoSiPuoMettereUnLink(unittest.TestCase):
    """Il contratto `plan["pins"]`: per ogni pallino DISEGNATO, dove sta e
    quanto e' grande, in percentuale dell'immagine. Se qui si rompe qualcosa il
    cliente tocca il pallino del museo e gli si apre il ristorante, oppure non
    gli si apre niente — e un link che non risponde e' peggio di un link che
    non c'e', perche' fa credere che sia rotto il documento."""

    def test_ogni_pallino_disegnato_ha_la_sua_voce(self):
        """Se una tappa e' sulla cartina ma non in `pins`, quella tappa non e'
        cliccabile: il cliente la vede, la tocca e non succede niente."""
        out = map_render.attach_local_maps([dict(_plan(), png=None)])[0]
        # Tre tappe + l'albergo.
        self.assertEqual(len(out["pins"]), 4)

    def test_senza_albergo_non_c_e_il_pallino_dell_albergo(self):
        """Un link "torna in hotel" su una giornata senza hotel geolocalizzato
        porterebbe il cliente da nessuna parte."""
        out = map_render.attach_local_maps([dict(_plan(hotel_point=None), png=None)])[0]
        self.assertEqual(len(out["pins"]), 3)
        self.assertNotIn("H", [p["label"] for p in out["pins"]])

    def test_le_etichette_e_gli_id_seguono_l_ordine_delle_tappe(self):
        """`label` e `poi_id` sono le due chiavi con cui il renderer ricollega
        il pallino alla riga della legenda e al link "come arrivare". Se
        scivolano di uno, il link della tappa 2 punta al POI della tappa 3: il
        cliente si presenta all'indirizzo sbagliato."""
        stops = [
            dict(_stop("1", "Piazza del Campo", 43.3182, 11.3315), poi_id="poi-a"),
            dict(_stop("2", "Duomo di Siena", 43.3175, 11.3288), poi_id="poi-b"),
            dict(_stop("3", "Osteria Le Logge", 43.3188, 11.3330), poi_id="poi-c"),
        ]
        out = map_render.attach_local_maps([dict(_plan(stops=stops), png=None)])[0]
        pins = out["pins"]
        self.assertEqual(pins[0]["label"], "H")
        self.assertIsNone(pins[0]["poi_id"], "l'albergo non e' una tappa numerata")
        self.assertEqual(pins[0]["name"], "Palazzo Ravizza")
        self.assertEqual([p["label"] for p in pins[1:]], ["1", "2", "3"])
        self.assertEqual([p["poi_id"] for p in pins[1:]], ["poi-a", "poi-b", "poi-c"])
        self.assertEqual([p["name"] for p in pins[1:]],
                         ["Piazza del Campo", "Duomo di Siena", "Osteria Le Logge"])

    def test_una_tappa_senza_coordinate_non_produce_un_pallino_e_non_sposta_le_altre(self):
        """La tappa senza coordinate non e' sulla figura, quindi non deve avere
        un link; ma soprattutto non deve far scalare di uno le altre, che e' il
        modo silenzioso in cui tutti i link della giornata diventano sbagliati."""
        stops = [_stop("1", "Buona", 43.3182, 11.3315),
                 {"label": "2", "name": "Rotta", "point": ("nord", "ovest"), "poi_id": "poi-x"},
                 _stop("3", "Buona 2", 43.3175, 11.3288)]
        out = map_render.attach_local_maps([dict(_plan(stops=stops), png=None)])[0]
        self.assertEqual([p["label"] for p in out["pins"]], ["H", "1", "3"])
        self.assertNotIn("poi-x", [p["poi_id"] for p in out["pins"]])

    def test_le_percentuali_stanno_dentro_l_immagine(self):
        """Una percentuale fuori da 0-100 e' un link che finisce fuori dalla
        figura, sopra il testo della pagina: il cliente lo tocca per sbaglio
        mentre legge."""
        casi = [
            dict(_plan(), png=None),
            dict(_plan(hotel_point=None), png=None),
            dict(_plan_sparso(), png=_sfondo_finto(), base_map=BASE_MAP),
            # Tutte le tappe nello stesso punto: il caso che spinge di piu' il
            # declutter contro i bordi.
            dict(_plan(stops=[_stop("1", "Museo", 43.3182, 11.3315),
                              _stop("2", "Caffe del museo", 43.3182, 11.3315),
                              _stop("3", "Libreria del museo", 43.3182, 11.3315)]), png=None),
        ]
        for piano in casi:
            with self.subTest(piano=piano.get("title")):
                out = map_render.attach_local_maps([piano])[0]
                for pin in out["pins"]:
                    self.assertTrue(0.0 <= pin["x_pct"] <= 100.0, pin)
                    self.assertTrue(0.0 <= pin["y_pct"] <= 100.0, pin)
                    self.assertGreater(pin["r_pct"], 0.0)

    def test_senza_figura_la_chiave_pins_non_c_e_proprio(self):
        """Assente, non lista vuota: il renderer decide se disegnare lo strato
        dei link con lo stesso `in` con cui decide per `map_source`, e una lista
        vuota gli farebbe montare un overlay su un'immagine che non esiste."""
        out = map_render.attach_local_maps(
            [{"day": 2, "title": "Riposo", "stops": [], "png": None}])[0]
        self.assertIsNone(out["png"])
        self.assertNotIn("pins", out)

    def test_chiamarlo_due_volte_da_gli_stessi_pallini(self):
        """Il documento viene rigenerato (anteprima, poi versione finale): due
        PDF dello stesso viaggio devono avere i link nello stesso posto."""
        for piano in (dict(_plan(), png=None),
                      dict(_plan(), png=_sfondo_finto(), base_map=BASE_MAP)):
            with self.subTest(sorgente=piano.get("base_map") and "google" or "schema"):
                una = map_render.attach_local_maps([piano])
                due = map_render.attach_local_maps(una)
                self.assertEqual(una[0]["pins"], due[0]["pins"])

    def test_non_solleva_mai_nemmeno_sui_piani_malformati(self):
        """Stesso contratto della cartina: la geometria e' un di piu', il
        documento non deve mai cadere per colpa sua."""
        for junk in ({}, {"stops": None}, {"stops": "non una lista"},
                     {"stops": [None, 42, "x"]},
                     dict(_plan(), png=b"non-sono-un-png", base_map=BASE_MAP),
                     dict(_plan(), stops=[{"label": "1", "point": (43.3, 11.3)}], png=None)):
            with self.subTest(junk=junk):
                map_render.attach_local_maps([junk])


class TestIlLinkCadeDoveCadeIlPallino(unittest.TestCase):
    """La verifica che rende "cliccabile" una promessa misurabile: la posizione
    esportata deve essere quella DISEGNATA, non quella proiettata. Sono la
    stessa cosa solo quando i pallini sono lontani; quando sono vicini il
    declutter li sposta, e chi esporta la posizione proiettata mette il link
    dove il pallino non c'e' piu'."""

    def test_sopra_la_cartina_di_google_la_percentuale_e_il_pixel_giusto(self):
        piano = _plan_sparso()
        out = map_render.attach_local_maps(
            [dict(piano, png=_sfondo_finto(), base_map=BASE_MAP)])[0]
        larghezza, altezza = 1280, 876
        attesi = map_render._google_pixels(_geo_del_piano(piano), BASE_MAP, larghezza, altezza)
        self.assertEqual(len(out["pins"]), len(attesi))
        for pin, (ax, ay) in zip(out["pins"], attesi):
            self.assertAlmostEqual(pin["x_pct"] * larghezza / 100.0, ax, delta=2.0)
            self.assertAlmostEqual(pin["y_pct"] * altezza / 100.0, ay, delta=2.0)
        # E il raggio e' quello vero del pallino, in percentuale della LARGHEZZA
        # (un cerchio ha un raggio solo: usare l'altezza lo renderebbe ovale).
        self.assertAlmostEqual(
            out["pins"][0]["r_pct"] * larghezza / 100.0, map_render._PIN_RADIUS, delta=0.5)

    def test_sullo_schema_la_percentuale_e_il_pixel_giusto(self):
        piano = _plan_sparso()
        out = map_render.attach_local_maps([dict(piano, png=None)])[0]
        larghezza = map_render._W * map_render._SCALE
        altezza = map_render._H * map_render._SCALE
        attesi = map_render._project_points(_geo_del_piano(piano), larghezza, altezza)
        self.assertEqual(len(out["pins"]), len(attesi))
        for pin, (ax, ay) in zip(out["pins"], attesi):
            self.assertAlmostEqual(pin["x_pct"] * larghezza / 100.0, ax, delta=2.0)
            self.assertAlmostEqual(pin["y_pct"] * altezza / 100.0, ay, delta=2.0)

    def test_due_tappe_sovrapposte_hanno_due_link_distinti(self):
        """Il museo e il caffe' del museo sono allo stesso indirizzo. Sulla
        figura i due pallini sono stati allontanati per renderli visibili: i due
        link devono seguirli, altrimenti se ne cliccherebbe sempre uno solo —
        ed e' l'altro quello che il cliente stava cercando."""
        stops = [_stop("1", "Museo", 43.3182, 11.3315),
                 _stop("2", "Caffe del museo", 43.3182, 11.3315),
                 _stop("3", "Osteria lontana", 43.3210, 11.3360)]
        piano = _plan(stops=stops, hotel_point=None)
        out = map_render.attach_local_maps(
            [dict(piano, png=_sfondo_finto(), base_map=BASE_MAP)])[0]
        larghezza, altezza = 1280, 876
        grezzi = map_render._google_pixels(_geo_del_piano(piano), BASE_MAP, larghezza, altezza)
        uno, due = out["pins"][0], out["pins"][1]
        distanza = ((uno["x_pct"] - due["x_pct"]) * larghezza / 100.0) ** 2 + \
                   ((uno["y_pct"] - due["y_pct"]) * altezza / 100.0) ** 2
        self.assertGreater(distanza ** 0.5, map_render._PIN_RADIUS,
                           "i due link sono uno sopra l'altro: se ne clicca sempre uno solo")
        # E nessuno dei due sta piu' dove cadeva la coordinata grezza: e'
        # esattamente la prova che si sta esportando il disegno, non la
        # proiezione.
        for pin, (gx, gy) in zip((uno, due), grezzi[:2]):
            scarto = ((pin["x_pct"] * larghezza / 100.0 - gx) ** 2 +
                      (pin["y_pct"] * altezza / 100.0 - gy) ** 2) ** 0.5
            self.assertGreater(scarto, 1.0,
                               "posizione grezza esportata: il link non segue il pallino")


if __name__ == "__main__":
    unittest.main()
