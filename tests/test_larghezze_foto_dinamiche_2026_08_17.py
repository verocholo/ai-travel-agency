"""Le fotografie affiancate hanno sempre la stessa larghezza (task #224/228).

PERCHE' QUESTO FILE ESISTE, E PERCHE' SOSTITUISCE LA VERSIONE PRECEDENTE

Prima versione (17 agosto, mattina): Lorenzo segnala che a pagina 4 «una
foto è troppo più piccola dell'altra». La riparazione di allora rendeva le
DUE COLONNE dell'apertura eroe-laterale di larghezza VARIABILE, calcolata
dal rapporto di ritaglio davvero ottenuto da ciascuna fotografia — così le
due figure venivano alla stessa ALTEZZA.

Seconda versione (17 agosto, stesso giorno): Lorenzo chiarisce la
direttiva — «più immagini in una stessa pagina devono avere la stessa
dimensione se sono inserite in serie», e conferma esplicitamente che vale
anche per questa coppia. Non vuole più una colonna "grande" e una
"piccola": le vuole sempre uguali, 50/50.

La funzione `_larghezze_per_altezza_uguale` (che calcolava le larghezze
variabili) è stata rimossa: non serve più, e tenerla in giro senza un
chiamante vero sarebbe esattamente il tipo di codice-mai-collegato che
questo progetto evita di proposito. Questo file la sostituisce con le
prove sul comportamento NUOVO: colonne sempre al 50%, stesso rapporto di
ritaglio richiesto per entrambe le fotografie.
"""

import io
import unittest


def _foto(larghezza, altezza, seme=0):
    from PIL import Image

    fuori = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), (120 + seme, 90, 60)).save(
        fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _scatto(larghezza, altezza, nome="x", seme=0):
    return {"png": _foto(larghezza, altezza, seme),
            "credito": f"Foto: {nome} / Prova", "reale": True}


def _blocchi(*poi_ids):
    return [{"time": "10:00", "activity": f"Tappa {i}", "location": f"Luogo {i}",
             "poi_id": pid} for i, pid in enumerate(poi_ids, start=1)]


class TestEroeLateraleUsaSempreColonneUguali(unittest.TestCase):
    """Giorno 1 su "Bologna", con due fotografie disponibili, sceglie
    deterministicamente "eroe-laterale" (verificato con
    `compositore.scegli_apertura`, vedi la sessione precedente)."""

    def _documento(self, larga_1=1600, alta_1=1000, larga_2=600, alta_2=1400):
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Un giorno.",
            "days": [{"day": 1, "title": "Centro",
                      "blocks": _blocchi("piazza", "torri")}],
        }
        photos = {
            "piazza": _scatto(larga_1, alta_1, "piazza", seme=10),
            "torri": _scatto(larga_2, alta_2, "torri", seme=40),
        }
        return render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-13", "duration_days": 1, "budget_eur": 300},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos=photos,
        )

    def _larghezze(self, html):
        import re

        self.assertIn("<table class='day-eroe'>", html,
                      "questa combinazione dovrebbe scegliere "
                      "deterministicamente eroe-laterale")
        tabella = html.split("<table class='day-eroe'>", 1)[1].split(
            "</table>", 1)[0]
        return [int(m) for m in re.findall(r"<td style='width:(\d+)%'>", tabella)]

    def test_una_foto_panoramica_e_una_molto_verticale_restano_al_50_50(self):
        """Il caso vero segnalato da Lorenzo: Piazza Maggiore (orizzontale)
        accanto alle Due Torri (molto verticale). Prima di questa
        correzione le due colonne avrebbero avuto larghezze diverse."""
        html = self._documento(1600, 1000, 600, 1400)
        larghezze = self._larghezze(html)
        self.assertEqual([50, 50], larghezze)

    def test_due_fotografie_della_stessa_forma_restano_al_50_50(self):
        html = self._documento(1400, 900, 1400, 900)
        larghezze = self._larghezze(html)
        self.assertEqual([50, 50], larghezze)

    def test_due_fotografie_quadrate_restano_al_50_50(self):
        html = self._documento(1000, 1000, 1000, 1000)
        larghezze = self._larghezze(html)
        self.assertEqual([50, 50], larghezze)


class TestMosaicoRestaATreColonneUguali(unittest.TestCase):

    def test_le_tre_celle_restano_al_33_per_cento_ciascuna(self):
        """Giorno 11 su "Bologna", con tre fotografie disponibili, sceglie
        deterministicamente "mosaico" (verificato con
        `compositore.scegli_apertura`)."""
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Un giorno.",
            "days": [{"day": 11, "title": "Centro",
                      "blocks": _blocchi("a", "torri", "c")}],
        }
        photos = {
            "a": _scatto(1600, 1000, "a", seme=5),
            "torri": _scatto(600, 1400, "torri", seme=40),
            "c": _scatto(1400, 900, "c", seme=70),
        }
        html = render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-13", "duration_days": 1, "budget_eur": 300},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos=photos,
        )
        self.assertIn("<table class='day-striscia'>", html,
                      "questa combinazione dovrebbe scegliere "
                      "deterministicamente il mosaico")
        import re

        tabella = html.split("<table class='day-striscia'>", 1)[1].split(
            "</table>", 1)[0]
        larghezze = [int(m) for m in re.findall(r"<td style='width:(\d+)%'>", tabella)]
        self.assertEqual([33, 33, 33], larghezze)


class TestLeCostantiVecchieSonoDavveroSparite(unittest.TestCase):
    """[AGGIUNTA insieme al rovesciamento della direttiva.] Un test che
    verifica l'ASSENZA e' insolito in questa suite, ma qui serve: se un
    domani qualcuno reintroducesse `_larghezze_per_altezza_uguale` senza
    ricollegarla a un chiamante vero, sarebbe di nuovo codice-mai-usato —
    esattamente il difetto che questo progetto ha gia' imparato a evitare
    (vedi il changelog del 16 agosto sulle sonde di misura)."""

    def test_la_vecchia_funzione_non_e_piu_importabile(self):
        import src.pdf_renderer as pr

        self.assertFalse(hasattr(pr, "_larghezze_per_altezza_uguale"))
        self.assertFalse(hasattr(pr, "RAPPORTO_EROE_LATO"))
        self.assertFalse(hasattr(pr, "QUOTA_MINIMA_EROE_LATO"))


if __name__ == "__main__":
    unittest.main()
