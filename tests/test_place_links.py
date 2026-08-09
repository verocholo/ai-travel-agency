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
    build_info_link, build_menu_link, build_phone_link, build_place_card,
    build_place_cards_by_id, build_place_page_url, build_tickets_link,
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
# [AGGIUNTO 2026-08-01] Il caso residuo: nessun sito E nessun identificativo
# Google. Con i POI che vengono davvero da Places non capita mai — un place_id
# c'è sempre — ma è il solo caso in cui una RICERCA resta l'unica cosa onesta
# che possiamo offrire, e va comunque coperto.
RISTORANTE_SENZA_IDENTITA = POI(
    id="", type="restaurant", name="Osteria del Vicolo", lat=43.77, lng=11.25,
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

    def test_senza_sito_va_sulla_scheda_del_locale_non_su_una_ricerca(self):
        """[CAMBIATO 2026-08-01 — richiesta di Lorenzo: "devi collegarti
        direttamente al loro menù senza dover far cercare nulla al cliente"]

        Il vecchio secondo gradino era una pagina di RISULTATI Google: proprio
        il lavoro che è stato chiesto di togliere. Adesso in mezzo c'è la
        scheda del locale — un tap, e ci sono menù (quando c'è), orari di
        oggi, foto dei piatti e numero."""
        link = build_menu_link(RISTORANTE_SPOGLIO)
        self.assertFalse(link["is_search"])
        self.assertIn("place_id:R2", link["url"])

    def test_letichetta_non_promette_un_menu_che_potrebbe_non_esserci(self):
        """Promettere "Menù" e mostrare una scheda sarebbe la stessa
        disonestà del `sito.it/menu` indovinato che questo modulo rifiuta."""
        label = build_menu_link(RISTORANTE_SPOGLIO)["label"]
        self.assertIn("scheda", label.lower())

    def test_senza_sito_e_senza_identificativo_resta_la_ricerca_dichiarata(self):
        link = build_menu_link(RISTORANTE_SENZA_IDENTITA)
        self.assertTrue(link["is_search"])
        self.assertIn("Cerca", link["label"])
        query = parse_qs(urlparse(link["url"]).query)["q"][0]
        self.assertIn("Osteria del Vicolo", query)
        self.assertIn("menu", query)

    def test_indirizzo_incluso_nella_ricerca_per_disambiguare(self):
        query = parse_qs(urlparse(build_menu_link(RISTORANTE_SENZA_IDENTITA)["url"]).query)["q"][0]
        self.assertIn("Via Vecchia", query)

    def test_nessun_menu_per_un_museo(self):
        self.assertIsNone(build_menu_link(MUSEO))

    def test_ristorante_senza_nome_ne_identita_non_produce_una_ricerca_vuota(self):
        poi = POI(id="", type="restaurant", name="", lat=43.0, lng=11.0)
        self.assertIsNone(build_menu_link(poi))

    def test_sito_vuoto_trattato_come_assente(self):
        poi = POI(id="R4", type="restaurant", name="Bar", lat=43.0, lng=11.0, website="   ")
        link = build_menu_link(poi)
        self.assertNotIn("   ", link["url"])
        self.assertIn("place_id:R4", link["url"])


class TestSchedaDelLocale(unittest.TestCase):
    """[AGGIUNTO 2026-08-01] `build_place_page_url` è il pezzo che sostituisce
    "cerca su Google" con "eccolo". Vale per menù e per info."""

    def test_preferisce_luri_canonico_dellapi(self):
        self.assertEqual(build_place_page_url(RISTORANTE_COMPLETO),
                         "https://maps.google.com/?cid=123")

    def test_altrimenti_lo_ricostruisce_dal_place_id(self):
        url = build_place_page_url(RISTORANTE_SPOGLIO)
        self.assertTrue(url.startswith("https://www.google.com/maps/place/"))
        self.assertIn("place_id:R2", url)

    def test_place_id_con_caratteri_speciali_viene_codificato(self):
        poi = POI(id="ChIJ+a/b c", type="museum", name="X", lat=1.0, lng=2.0)
        url = build_place_page_url(poi)
        self.assertNotIn(" ", url)
        self.assertIn("%2F", url)  # la barra dentro l'id non deve rompere il path

    def test_senza_identita_nessun_link_inventato(self):
        self.assertIsNone(build_place_page_url(POI(id="", type="museum", name="X",
                                                   lat=1.0, lng=2.0)))


class TestTelefonoCliccabile(unittest.TestCase):
    """[AGGIUNTO 2026-08-01] Un numero stampato come testo, su un PDF letto
    dal telefono in viaggio, significa: memorizzalo, esci, riapri, ridigita."""

    def test_schema_tel_normalizzato_ma_etichetta_leggibile(self):
        link = build_phone_link(RISTORANTE_COMPLETO)
        self.assertEqual(link["url"], "tel:+3905521269 1".replace(" ", ""))
        self.assertEqual(link["label"], "+39 055 212691")

    def test_numero_nazionale_senza_prefisso_internazionale(self):
        poi = POI(id="R9", type="restaurant", name="X", lat=1.0, lng=2.0,
                  phone="055 212 691")
        self.assertEqual(build_phone_link(poi)["url"], "tel:055212691")

    def test_niente_numero_niente_link(self):
        self.assertIsNone(build_phone_link(RISTORANTE_SPOGLIO))

    def test_un_numero_senza_cifre_non_produce_un_tel_vuoto(self):
        poi = POI(id="R8", type="restaurant", name="X", lat=1.0, lng=2.0,
                  phone="non disponibile")
        self.assertIsNone(build_phone_link(poi))


class TestBiglietti(unittest.TestCase):
    """[AGGIUNTO 2026-08-01] Solo il sito UFFICIALE, mai una rivendita: lo
    stesso ingresso su un portale terzo costa regolarmente il 20-30 % in più,
    e mandarcelo noi sarebbe farlo perdere al cliente."""

    def test_museo_con_sito_ufficiale(self):
        museo = POI(id="M2", type="museum", name="Uffizi", lat=1.0, lng=2.0,
                    website="https://uffizi.example/")
        link = build_tickets_link(museo)
        self.assertEqual(link["url"], "https://uffizi.example/")
        self.assertIn("Biglietti", link["label"])

    def test_senza_sito_ufficiale_nessun_ripiego_inventato(self):
        self.assertIsNone(build_tickets_link(MUSEO))

    def test_nessun_biglietto_per_un_ristorante(self):
        self.assertIsNone(build_tickets_link(RISTORANTE_COMPLETO))


class TestInfoLink(unittest.TestCase):
    def test_scheda_google_maps_ufficiale_preferita(self):
        link = build_info_link(RISTORANTE_COMPLETO)
        self.assertEqual(link["url"], "https://maps.google.com/?cid=123")
        self.assertIn("orari", link["label"])

    def test_scheda_ricostruita_dal_place_id_quando_manca_luri(self):
        """[CAMBIATO 2026-08-01] Prima qui si ripiegava sulle coordinate anche
        avendo il `place_id`: mandava il cliente su un puntino della mappa
        invece che sulla scheda del locale, con orari e recensioni. Le
        coordinate restano il ripiego, ma solo quando non c'è altro."""
        link = build_info_link(RISTORANTE_SPOGLIO)
        self.assertIn("place_id:R2", link["url"])

    def test_ripiego_su_coordinate_reali(self):
        link = build_info_link(RISTORANTE_SENZA_IDENTITA)
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
