"""
[AGGIUNTO 2026-07-31 — aggiunta mia ("stupiscimi"), al servizio della
direttrice "pratico e sicurezza"] Copre src/local_info.py.

Il test che conta davvero è `test_paese_sconosciuto_non_inventa_nulla`: la
tabella esiste proprio perché un numero di emergenza allucinato è l'errore più
grave che questo documento possa contenere, e l'omissione è la risposta
corretta quando non sappiamo.
"""
import unittest

from src.local_info import (
    country_practical_info, known_countries, resolve_country,
)

_REQUIRED_KEYS = {"emergency", "currency", "plug", "tap_water", "tipping"}


class TestResolveCountry(unittest.TestCase):
    def test_nome_esatto(self):
        self.assertEqual(resolve_country("Italia"), "italia")

    def test_maiuscole_e_spazi_irrilevanti(self):
        self.assertEqual(resolve_country("  FRANCIA  "), "francia")

    def test_alias_inglesi_e_locali(self):
        for text, expected in (
            ("UK", "regno unito"), ("England", "regno unito"), ("Scozia", "regno unito"),
            ("Olanda", "paesi bassi"), ("Czech Republic", "repubblica ceca"),
            ("Suisse", "svizzera"), ("España", "spagna"), ("Danmark", "danimarca"),
        ):
            with self.subTest(text=text):
                self.assertEqual(resolve_country(text), expected)

    def test_citta_piu_paese(self):
        self.assertEqual(resolve_country("Parigi, Francia"), "francia")
        self.assertEqual(resolve_country("Lisbon, Portugal"), "portogallo")
        self.assertEqual(resolve_country("Londra / Regno Unito"), "regno unito")

    def test_solo_il_nome_della_citta(self):
        """[AGGIUNTO 2026-08-01 — difetto reale trovato rigenerando il PDF di
        esempio] `destinazione: "Siena"` non risolveva nulla e la scheda del
        paese spariva. È la forma in cui la destinazione arriva davvero dal
        form: quasi nessuno scrive "Firenze, Italia"."""
        for text, expected in (
            ("Siena", "italia"), ("Firenze", "italia"), ("Parigi", "francia"),
            ("Barcellona", "spagna"), ("Praga", "repubblica ceca"),
            ("Londra", "regno unito"), ("Amsterdam", "paesi bassi"),
            ("Zurigo", "svizzera"), ("Lubiana", "slovenia"),
        ):
            with self.subTest(text=text):
                self.assertEqual(resolve_country(text), expected)

    def test_citta_piu_regione_senza_paese(self):
        self.assertEqual(resolve_country("Siena, Toscana"), "italia")

    def test_il_paese_esplicito_vince_sulla_citta(self):
        """Se le due tabelle si contraddicono, il paese scritto per esteso è
        l'intenzione più esplicita delle due."""
        self.assertEqual(resolve_country("Cortina, Austria"), "austria")

    def test_citta_ambigua_resta_senza_paese(self):
        """Valencia (Spagna/Venezuela), Cambridge (UK/Massachusetts): meglio
        nessuna scheda che il numero di emergenza di un altro continente."""
        for ambigua in ("Valencia", "Cambridge", "Toledo", "Monaco", "Santiago"):
            with self.subTest(ambigua=ambigua):
                self.assertIsNone(resolve_country(ambigua))

    def test_paese_sconosciuto_non_inventa_nulla(self):
        for text in ("Nepal", "Kathmandu, Nepal", "Marte", ""):
            with self.subTest(text=text):
                self.assertIsNone(resolve_country(text))

    def test_input_non_stringa_non_solleva(self):
        for bad in (None, 42, [], {}):
            with self.subTest(bad=bad):
                self.assertIsNone(resolve_country(bad))

    def test_nome_di_via_non_fa_scattare_un_paese(self):
        # "italia" dentro "Corso Italia 12, Nizza" non deve far dedurre l'Italia
        # quando il viaggio è in Francia: il match è per pezzo separato da
        # virgola, non per sottostringa.
        self.assertIsNone(resolve_country("Corso Italia 12 Nizza"))


class TestCountryPracticalInfo(unittest.TestCase):
    def test_scheda_completa(self):
        info = country_practical_info("Italia")
        self.assertTrue(_REQUIRED_KEYS.issubset(info))
        self.assertEqual(info["emergency"], "112")
        self.assertEqual(info["country"], "Italia")

    def test_paese_extra_ue_ha_il_proprio_numero(self):
        self.assertIn("999", country_practical_info("Regno Unito")["emergency"])

    def test_paese_sconosciuto_restituisce_none(self):
        self.assertIsNone(country_practical_info("Nepal"))

    def test_ogni_paese_in_tabella_e_completo(self):
        for country in known_countries():
            with self.subTest(country=country):
                info = country_practical_info(country)
                self.assertTrue(_REQUIRED_KEYS.issubset(info), country)
                for key in _REQUIRED_KEYS:
                    self.assertTrue(str(info[key]).strip(), f"{country}.{key} vuoto")

    def test_ogni_alias_punta_a_un_paese_esistente(self):
        from src.local_info import _ALIASES, _COUNTRY_INFO
        for alias, target in _ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(target, _COUNTRY_INFO)

    def test_ogni_citta_punta_a_un_paese_esistente(self):
        from src.local_info import _CITY_TO_COUNTRY, _COUNTRY_INFO
        for city, target in _CITY_TO_COUNTRY.items():
            with self.subTest(city=city):
                self.assertIn(target, _COUNTRY_INFO)

    def test_nessuna_citta_ambigua_in_tabella(self):
        """[AGGIUNTO 2026-08-01] La regola di ammissione della tabella città
        scritta come test e non solo come commento: da qui dipende un numero di
        emergenza, e un omonimo su un altro continente è peggio del silenzio.
        Se un giorno qualcuno aggiungerà "valencia" per comodità, questo test
        glielo impedirà."""
        from src.local_info import _CITY_TO_COUNTRY
        for ambigua in ("valencia", "cordoba", "córdoba", "toledo", "cambridge",
                        "birmingham", "santiago", "monaco", "san jose",
                        "alessandria", "vittoria", "las vegas", "atlanta"):
            with self.subTest(ambigua=ambigua):
                self.assertNotIn(ambigua, _CITY_TO_COUNTRY)

    def test_copertura_minima_europa(self):
        countries = known_countries()
        self.assertGreaterEqual(len(countries), 20)
        for atteso in ("italia", "francia", "spagna", "regno unito", "germania"):
            self.assertIn(atteso, countries)


if __name__ == "__main__":
    unittest.main()
