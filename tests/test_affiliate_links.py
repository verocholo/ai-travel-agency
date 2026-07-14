"""
[AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: "questa
integrazione multi-piattaforma la facciamo"] Copre build_search_links() —
funzione pura, nessuna chiamata di rete. I pattern URL usati sono stati
verificati via ricerca web (fonti in CHANGELOG.md), ma MAI aperti davvero
in un browser da questo ambiente (nessun accesso di rete ai siti stessi) —
vedi la nota di onestà in src/affiliate_links.py. Questi test verificano
solo che la COSTRUZIONE della stringa URL sia corretta rispetto al formato
atteso, non che il link risolva davvero a una pagina valida.
"""
import unittest
from src.affiliate_links import build_search_links


class TestBuildSearchLinks(unittest.TestCase):
    def setUp(self):
        self.links = build_search_links("Lisbona, Portogallo", "2026-09-01", "2026-09-04",
                                         hotel_name="TURIM Boulevard Hotel")

    def test_returns_all_three_platforms(self):
        self.assertEqual(set(self.links.keys()), {"booking", "airbnb", "vrbo"})

    def test_booking_uses_hotel_name_alone_not_combined_with_destination(self):
        # [CORRETTO 2026-07-12 — tre round di bug reali trovati dal vivo da
        # Lorenzo, vedi nota estesa in src/affiliate_links.py] Round 1:
        # "nome hotel, destinazione" combinati -> redirect di errore di
        # Booking (`errorc_searchstring_not_found=ss`). Round 2: sola
        # destinazione -> stesso errore quando la destinazione è un'area/
        # valle (es. "Val d'Orcia") anziché una città/regione riconosciuta.
        # Round 3 (adottato): il nome hotel DA SOLO, quando disponibile,
        # risolve in modo affidabile (verificato dal vivo: nessun redirect
        # di errore, ricerca eseguita con risultati reali) — un hotel reale
        # è quasi sempre indicizzato con il suo nome esatto. Quindi: nome
        # hotel SÌ nella query, ma MAI insieme alla destinazione.
        self.assertIn("TURIM", self.links["booking"])
        self.assertNotIn("Lisbona", self.links["booking"])
        self.assertIn("booking.com/searchresults.html", self.links["booking"])

    def test_booking_includes_checkin_checkout(self):
        self.assertIn("checkin=2026-09-01", self.links["booking"])
        self.assertIn("checkout=2026-09-04", self.links["booking"])

    def test_airbnb_does_not_include_hotel_name(self):
        # [DELIBERATO] Airbnb è un marketplace di affitti indipendenti —
        # l'hotel-ancora scelto da LiteAPI tipicamente non è lì. Cercarlo
        # per nome sarebbe fuorviante: cerchiamo solo la destinazione.
        self.assertNotIn("TURIM", self.links["airbnb"])
        self.assertIn("airbnb.com/s/", self.links["airbnb"])

    def test_airbnb_location_in_path_not_query_string(self):
        # Formato reale confermato via ricerca web: la località va nel PATH
        # (es. /s/Lisbona-Portogallo/homes), non come parametro ?location=.
        self.assertIn("/s/Lisbona", self.links["airbnb"])
        self.assertIn("/homes", self.links["airbnb"])

    def test_airbnb_includes_checkin_checkout(self):
        self.assertIn("checkin=2026-09-01", self.links["airbnb"])
        self.assertIn("checkout=2026-09-04", self.links["airbnb"])

    def test_vrbo_does_not_include_hotel_name(self):
        # Stesso principio di Airbnb — vedi test_airbnb_does_not_include_hotel_name.
        self.assertNotIn("TURIM", self.links["vrbo"])

    def test_vrbo_includes_destination_and_dates(self):
        self.assertIn("vrbo.com/search", self.links["vrbo"])
        self.assertIn("startDate=2026-09-01", self.links["vrbo"])
        self.assertIn("endDate=2026-09-04", self.links["vrbo"])

    def test_no_hotel_name_booking_falls_back_to_destination_only(self):
        links = build_search_links("Firenze, Toscana", "2026-09-01", "2026-09-04")
        self.assertIn("Firenze", links["booking"])
        # Nessun crash, nessun "None" letterale nella query
        self.assertNotIn("None", links["booking"])

    def test_special_characters_in_destination_are_url_encoded(self):
        links = build_search_links("São Paulo, Brasile", "2026-09-01", "2026-09-04")
        # Non deve contenere spazi letterali non codificati nella query string
        self.assertNotIn(" ", links["booking"].split("?", 1)[1])
        self.assertNotIn(" ", links["vrbo"].split("?", 1)[1])


class TestBuildSearchLinksEdgeCases(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-11 — audit mirato post-implementazione, richiesto da
    Lorenzo ("facciamo il massimo, la qualità migliore")] Copre i 6 bug
    reali trovati ED ESEGUITI (non solo ipotizzati) da un audit indipendente
    mirato solo su questa feature — vedi la nota estesa in
    src/affiliate_links.py e CHANGELOG.md per il dettaglio completo di
    ciascuno.
    """

    def test_none_destination_does_not_crash(self):
        # Prima: TypeError non gestito ("quote_from_bytes() expected bytes").
        links = build_search_links(None, "2026-09-01", "2026-09-04")
        self.assertIsInstance(links["booking"], str)
        self.assertIsInstance(links["airbnb"], str)
        self.assertIsInstance(links["vrbo"], str)

    def test_empty_destination_no_double_slash_in_airbnb_path(self):
        # Prima: "https://www.airbnb.com/s//homes" (doppio slash, path rotto).
        links = build_search_links("", "2026-09-01", "2026-09-04")
        self.assertNotIn("//homes", links["airbnb"])
        self.assertIn("/s/homes", links["airbnb"])

    def test_whitespace_only_destination_no_double_slash(self):
        links = build_search_links("   ", "2026-09-01", "2026-09-04")
        self.assertNotIn("//homes", links["airbnb"])

    def test_invalid_dates_omitted_not_literal_none_string(self):
        # Prima: "checkin=None&checkout=None" nell'URL — spazzatura non
        # validata invece di essere semplicemente omessa.
        links = build_search_links("Roma", None, None)
        self.assertNotIn("None", links["booking"])
        self.assertNotIn("None", links["airbnb"])
        self.assertNotIn("None", links["vrbo"])
        self.assertNotIn("checkin=", links["booking"])
        self.assertNotIn("startDate=", links["vrbo"])

    def test_malformed_date_string_also_omitted(self):
        links = build_search_links("Roma", "01/09/2026", "not-a-date")
        self.assertNotIn("None", links["booking"])
        self.assertNotIn("checkin=", links["booking"])

    def test_valid_dates_still_included_after_validation(self):
        # Non-regressione: la validazione non deve rompere il caso normale.
        links = build_search_links("Roma", "2026-09-01", "2026-09-04")
        self.assertIn("checkin=2026-09-01", links["booking"])
        self.assertIn("checkout=2026-09-04", links["booking"])
        self.assertIn("startDate=2026-09-01", links["vrbo"])
        self.assertIn("endDate=2026-09-04", links["vrbo"])

    def test_slash_in_destination_does_not_split_airbnb_path(self):
        # Prima: "/s/Bosnia/Herzegovina/homes" — due segmenti di path invece
        # di uno solo, perché quote() di default non codifica "/".
        links = build_search_links("Bosnia/Herzegovina", "2026-09-01", "2026-09-04")
        self.assertNotIn("/s/Bosnia/Herzegovina/homes", links["airbnb"])

    def test_booking_never_combines_hotel_name_and_destination_in_one_query(self):
        # [AGGIUNTO 2026-07-12 — tre round di bug reali trovati dal vivo da
        # Lorenzo] Regressione diretta sul caso reale scoperto da Lorenzo:
        # "Relais Borgo Val d'Orcia" + "Val d'Orcia, Toscana". Round 1
        # (combinati) e round 2 (sola destinazione) producevano entrambi,
        # cliccati davvero nel browser, un redirect di Booking alla propria
        # homepage con `errorc_searchstring_not_found=ss`. Round 3
        # (adottato, verificato dal vivo senza errori): nome hotel DA SOLO.
        # Questo test blocca la regressione al comportamento rotto:
        # destinazione e nome hotel non devono MAI comparire insieme nella
        # query Booking.
        links = build_search_links(
            "Val d'Orcia, Toscana", "2026-09-14", "2026-09-17",
            hotel_name="Relais Borgo Val d'Orcia",
        )
        self.assertIn("Relais", links["booking"])
        self.assertNotIn("Toscana", links["booking"])  # parte di destinazione, non del nome hotel
        self.assertIn("booking.com/searchresults.html", links["booking"])


if __name__ == "__main__":
    unittest.main()
