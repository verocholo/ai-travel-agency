"""
[AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "per i ristoranti è utile che
crei un collegamento con il menù del ristorante ... ed un altro collegamento
con le info utili"] Copre src/place_links.py.

Il test di principio è `test_niente_url_di_menu_indovinato`: Google Places non
restituisce l'URL del menù, e generare `sito.it/menu` a caso produrrebbe link
rotti nella maggior parte dei casi — un cliente che paga e trova link morti
smette di fidarsi dell'intero documento.
"""
import unittest
from urllib.parse import parse_qs, urlparse

from src.place_links import (
    build_info_link, build_menu_link, build_place_card, build_place_cards_by_id,
)
from src.schemas import POI

RISTORANTE_COMPLETO = POI(
    id="R1", type="restaurant", name="Trattoria Sostanza", lat=43.7739, lng=11.2459,
    website="https://trattoriasostanza.example/", phone="+39 055 212691",
    address="Via del Porcellana 25/R, Firenze", google_maps_uri="https://maps.google.com/?cid=123",
)
RISTORANTE_SPOGLIO = POI(
    id="R2", type="restaurant", name="Osteria del Vicolo", lat=43.77, lng=11.25,
    address="Via Vecchia 3, Firenze",
)
MUSEO = POI(id="M1", type="museum", name="Uffizi", lat=43.7678, lng=11.2553,
            google_maps_uri="https://maps.google.com/?cid=999")


class TestMenuLink(unittest.TestCase):
    def test_sito_ufficiale_preferito_ed_etichettato_come_tale(self):
        link = build_menu_link(RISTORANTE_COMPLETO)
        self.assertEqual(link["url"], "https://trattoriasostanza.example/")
        self.assertFalse(link["is_search"])
        self.assertIn("Menù", link["label"])

    def test_niente_url_di_menu_indovinato(self):
        link = build_menu_link(RISTORANTE_COMPLETO)
        self.assertFalse(link["url"].rstrip("/").endswith("/menu"))

    def test_senza_sito_ricade_su_una_ricerca_dichiarata_come_ricerca(self):
        link = build_menu_link(RISTORANTE_SPOGLIO)
        self.assertTrue(link["is_search"])
        self.assertIn("Cerca", link["label"])
        query = parse_qs(urlparse(link["url"]).query)["q"][0]
        self.assertIn("Osteria del Vicolo", query)
        self.assertIn("menu", query)

    def test_indirizzo_incluso_nella_ricerca_per_disambiguare(self):
        query = parse_qs(urlparse(build_menu_link(RISTORANTE_SPOGLIO)["url"]).query)["q"][0]
        self.assertIn("Via Vecchia", query)

    def test_nessun_menu_per_un_museo(self):
        self.assertIsNone(build_menu_link(MUSEO))

    def test_ristorante_senza_nome_non_produce_una_ricerca_vuota(self):
        poi = POI(id="R3", type="restaurant", name="", lat=43.0, lng=11.0)
        self.assertIsNone(build_menu_link(poi))

    def test_sito_vuoto_trattato_come_assente(self):
        poi = POI(id="R4", type="restaurant", name="Bar", lat=43.0, lng=11.0, website="   ")
        self.assertTrue(build_menu_link(poi)["is_search"])


class TestInfoLink(unittest.TestCase):
    def test_scheda_google_maps_ufficiale_preferita(self):
        link = build_info_link(RISTORANTE_COMPLETO)
        self.assertEqual(link["url"], "https://maps.google.com/?cid=123")
        self.assertIn("orari", link["label"])

    def test_ripiego_su_coordinate_reali(self):
        link = build_info_link(RISTORANTE_SPOGLIO)
        self.assertIn("43.77,11.25", link["url"])
        self.assertIn("google.com/maps", link["url"])

    def test_funziona_anche_per_i_musei(self):
        self.assertIsNotNone(build_info_link(MUSEO))

    def test_coordinate_non_valide_danno_none_non_un_link_rotto(self):
        class Fake:
            type = "restaurant"
            name = "X"
            google_maps_uri = None
            lat = None
            lng = None
        self.assertIsNone(build_info_link(Fake()))


class TestPlaceCard(unittest.TestCase):
    def test_scheda_completa(self):
        card = build_place_card(RISTORANTE_COMPLETO)
        self.assertEqual(card["poi_id"], "R1")
        self.assertEqual(card["phone"], "+39 055 212691")
        self.assertIsNotNone(card["menu_link"])
        self.assertIsNotNone(card["info_link"])

    def test_campi_mancanti_restano_none_mai_segnaposto_inventati(self):
        card = build_place_card(RISTORANTE_SPOGLIO)
        self.assertIsNone(card["phone"])
        self.assertNotIn("[Da Verificare]", str(card["address"]))


class TestPlaceCardsById(unittest.TestCase):
    def test_tutti_per_default(self):
        cards = build_place_cards_by_id([RISTORANTE_COMPLETO, MUSEO])
        self.assertEqual(set(cards), {"R1", "M1"})

    def test_fedelta_rag_solo_i_poi_usati(self):
        cards = build_place_cards_by_id([RISTORANTE_COMPLETO, RISTORANTE_SPOGLIO, MUSEO],
                                        only_ids={"R1"})
        self.assertEqual(set(cards), {"R1"})

    def test_input_vuoti_o_malformati_non_sollevano(self):
        self.assertEqual(build_place_cards_by_id(None), {})
        self.assertEqual(build_place_cards_by_id([], only_ids=set()), {})


if __name__ == "__main__":
    unittest.main()
