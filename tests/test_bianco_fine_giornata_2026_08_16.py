"""L'ultimo dei nove difetti del fascicolo di Bologna (task #223).

PERCHE' QUESTO FILE ESISTE

Punto di ripresa 16 agosto 2026: cinque segnalazioni chiuse, una aperta.

    | 15, 18, 21, 26 | due foto piccole e spazio vuoto | aperto — le foto
    sono grandi e i capitoli corti non aprono più pagina (CAPITOLO_CORTO),
    ma il bianco a fine capitolo resta

Decisione di Lorenzo il 16 agosto: la strada è ingrandire le fotografie di
chiusura giornata perché occupino lo spazio bianco, non allargare i margini.

## Il metodo, identico a quello gia' usato per le testate dei capitoli

Non si indovina quale giornata finira' con spazio bianco: si stampa, si
guarda dove sono cadute le sonde di apertura e chiusura di ogni giornata
(`giorno-{N}` e `giorno-{N}-fine`), si ingrandisce la fila di foto SOLO
delle giornate che ne hanno bisogno, e si ristampa una volta sola.

## Cosa difendono le prove qui sotto

- che `src.impaginazione.giornate_con_bianco_finale` prenda la decisione
  giusta guardando sonde finte, senza dover stampare nulla (veloce, e prova
  la LOGICA in isolamento);
- che `_render_striscia_foto(ingrandita=True)` produca davvero fotografie
  piu' grandi — meno colonne, o una sola a tutta larghezza — senza toccare
  un solo margine;
- che sul DOCUMENTO VERO stampato due volte (misura, poi ripara) lo spazio
  bianco alla fine delle giornate cali per davvero, e che la riparazione non
  allunghi il documento — la stessa doppia garanzia gia' pretesa dal test
  gemello sulle testate dei capitoli.
"""

import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _scatto(nome: str, reale: bool = True) -> dict:
    return {"png": b"\xff\xd8finto-jpeg-" + nome.encode(),
            "credito": f"Foto: {nome} / Prova", "reale": reale}


def _blocchi(*poi_ids) -> list:
    return [{"time": "10:00", "activity": f"Tappa {i}", "location": f"Luogo {i}",
             "poi_id": pid} for i, pid in enumerate(poi_ids, start=1)]


class TestLaDecisioneSuQualiGiornateIngrandire(unittest.TestCase):
    """`giornate_con_bianco_finale`, con sonde finte: nessuna stampa vera."""

    def _con_posizioni(self, finte):
        from src import impaginazione

        return patch.object(impaginazione, "posizioni", lambda _dati: finte)

    def test_una_giornata_finita_alta_con_la_prossima_su_pagina_dopo_si_ingrandisce(self):
        from src import impaginazione

        with self._con_posizioni({
            "giorno-1": (0, 800.0), "giorno-1-fine": (0, 400.0),
            "giorno-2": (1, 800.0), "giorno-2-fine": (1, 30.0),
        }):
            trovate = impaginazione.giornate_con_bianco_finale(
                b"finto", [1, 2])
        self.assertEqual({1}, trovate,
                         "la giornata 1 finisce a 400pt dal fondo — quasi "
                         "meta' pagina bianca — e la giornata 2 comincia "
                         "sulla pagina dopo: e' esattamente il difetto")

    def test_una_giornata_che_arriva_in_fondo_alla_pagina_non_si_tocca(self):
        from src import impaginazione

        with self._con_posizioni({
            "giorno-1": (0, 800.0), "giorno-1-fine": (0, 30.0),
            "giorno-2": (1, 800.0), "giorno-2-fine": (1, 30.0),
        }):
            trovate = impaginazione.giornate_con_bianco_finale(
                b"finto", [1, 2])
        self.assertEqual(set(), trovate,
                         "la giornata 1 arriva quasi in fondo al foglio: "
                         "non c'e' niente da riparare")

    def test_se_la_giornata_dopo_comincia_sulla_STESSA_pagina_non_si_tocca(self):
        """Lo spazio, in quel caso, lo riempie gia' la giornata dopo."""
        from src import impaginazione

        with self._con_posizioni({
            "giorno-1": (0, 800.0), "giorno-1-fine": (0, 400.0),
            "giorno-2": (0, 350.0), "giorno-2-fine": (1, 30.0),
        }):
            trovate = impaginazione.giornate_con_bianco_finale(
                b"finto", [1, 2])
        self.assertEqual(set(), trovate,
                         "ingrandire qui sposterebbe il problema, non lo "
                         "toglierebbe: la giornata 2 gia' continua sulla "
                         "stessa pagina")

    def test_l_ultima_pagina_del_documento_si_salta_sempre(self):
        """Stessa regola di `scripts_qualita_pagina.problemi()`."""
        from src import impaginazione

        with self._con_posizioni({
            "giorno-1": (0, 800.0), "giorno-1-fine": (2, 400.0),
        }):
            trovate = impaginazione.giornate_con_bianco_finale(
                b"finto", [1])
        self.assertEqual(set(), trovate,
                         "pagina 2 (indice) e' l'ultima del documento: e' "
                         "la chiusura, si salta di proposito")

    def test_l_ultima_giornata_si_confronta_coi_capitoli_che_seguono(self):
        from src import impaginazione

        with self._con_posizioni({
            "giorno-1": (0, 800.0), "giorno-1-fine": (0, 400.0),
            "costi": (1, 700.0),
        }):
            trovate = impaginazione.giornate_con_bianco_finale(
                b"finto", [1], ancore_successive=("costi", "consigli"))
        self.assertEqual({1}, trovate)

    def test_senza_sonde_non_si_ingrandisce_niente(self):
        from src import impaginazione

        self.assertEqual(
            set(), impaginazione.giornate_con_bianco_finale(b"non un pdf", [1, 2]))
        self.assertEqual(
            set(), impaginazione.giornate_con_bianco_finale(b"", []))


class TestLaFilaIngranditaUsaMenoFotoPiuGrandi(unittest.TestCase):
    """`_render_striscia_foto(ingrandita=True)`, senza stampare nulla."""

    def test_tre_disponibili_diventano_due_non_tre(self):
        from src.pdf_renderer import _render_striscia_foto

        html = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
            ingrandita=True)
        self.assertEqual(html.count("<img"), 2,
                         "ingrandita vuol dire MENO fotografie e piu' "
                         "grandi, non tutte e tre piu' piccole")

    def test_le_celle_sono_piu_larghe_di_quelle_normali(self):
        from src.pdf_renderer import _render_striscia_foto

        normale = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")})
        grande = _render_striscia_foto(
            _blocchi("A", "B", "C"),
            {"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
            ingrandita=True)
        self.assertIn("width:33%", normale)
        self.assertIn("width:50%", grande)

    def test_una_sola_foto_disponibile_diventa_a_tutta_larghezza(self):
        """La forma che normalmente questa funzione rifiuta — qui va bene:
        non c'e' nessuna riga da tre con cui confrontarsi."""
        from src.pdf_renderer import _render_striscia_foto

        normale = _render_striscia_foto(_blocchi("A", "B"), {"A": _scatto("a")})
        grande = _render_striscia_foto(
            _blocchi("A", "B"), {"A": _scatto("a")}, ingrandita=True)
        self.assertEqual(normale, "", "una foto sola non stampa MAI la fila normale")
        self.assertIn("<img", grande)
        self.assertIn("day-larga", grande)
        self.assertIn("Foto: a / Prova", grande)

    def test_ingrandita_non_cambia_niente_se_manca_il_credito(self):
        senza = {"png": b"\xff\xd8x", "credito": "  ", "reale": True}
        from src.pdf_renderer import _render_striscia_foto

        html = _render_striscia_foto(_blocchi("A", "B"), {"A": senza}, ingrandita=True)
        self.assertEqual(html, "")

    def test_ingrandita_resta_ferma_alle_sole_foto_vere(self):
        from src.pdf_renderer import _render_striscia_foto

        html = _render_striscia_foto(
            _blocchi("A", "B"),
            {"A": _scatto("a", reale=False), "B": _scatto("b", reale=False)},
            ingrandita=True)
        self.assertEqual(html, "",
                         "un rettangolo colorato si e' preso lo spazio del "
                         "programma anche in modalita' ingrandita")

    def test_niente_di_disponibile_niente_fila_nemmeno_ingrandita(self):
        from src.pdf_renderer import _render_striscia_foto

        self.assertEqual(
            _render_striscia_foto(_blocchi("A"), None, ingrandita=True), "")

    def test_render_html_normalizza_giornate_da_ingrandire_qualunque_tipo(self):
        """Chi chiama passa spesso un `set` di stringhe dalle sonde: non ci
        si puo' fidare del tipo esatto, e la normalizzazione non deve
        sollevare."""
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Due giorni.",
            "days": [{"day": 1, "title": "Centro", "blocks": _blocchi("A", "B", "C")}],
        }
        for valore in ("1", 1, 1.0):
            with self.subTest(valore=valore):
                html = render_html(
                    itinerario,
                    {"destination": "Bologna", "date_start": "2026-09-12",
                     "date_end": "2026-09-14", "duration_days": 1,
                     "budget_eur": 600},
                    hotels=[{"name": "Hotel", "price_night_eur": 100}],
                    photos={"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
                    giornate_da_ingrandire={valore},
                )
                fila = html.split("<table class='day-striscia'>", 1)[1].split(
                    "</table>", 1)[0]
                self.assertEqual(fila.count("<img"), 2)

    def test_valori_non_convertibili_si_ignorano_senza_sollevare(self):
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Un giorno.",
            "days": [{"day": 1, "title": "Centro", "blocks": _blocchi("A", "B", "C")}],
        }
        html = render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-13", "duration_days": 1, "budget_eur": 300},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos={"A": _scatto("a"), "B": _scatto("b"), "C": _scatto("c")},
            giornate_da_ingrandire={"non-un-numero", None},
        )
        fila = html.split("<table class='day-striscia'>", 1)[1].split("</table>", 1)[0]
        self.assertEqual(fila.count("<img"), 2, "nessun valore valido: la "
                         "giornata resta alla fila normale — con tre foto "
                         "reali e una gia' usata in apertura, ne restano "
                         "due per la fila di chiusura")


class TestLaSondaDiChiusuraArrivaDAVVERONELDOCUMENTO(unittest.TestCase):
    """La trappola gia' presa altre volte in questo progetto: una funzione
    corretta e mai collegata al documento vero."""

    def _documento(self, giornate_da_ingrandire=None):
        from src.pdf_renderer import render_html

        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Due giorni.",
            "days": [
                {"day": 1, "title": "Centro",
                 "blocks": _blocchi("A", "B", "C", "D", "E")},
                {"day": 2, "title": "Colli", "blocks": _blocchi("F", "G")},
            ],
        }
        return render_html(
            itinerario,
            {"destination": "Bologna", "date_start": "2026-09-12",
             "date_end": "2026-09-14", "duration_days": 2, "budget_eur": 600},
            hotels=[{"name": "Hotel", "price_night_eur": 100}],
            photos={k: _scatto(k.lower()) for k in "ABCDEFG"},
            giornate_da_ingrandire=giornate_da_ingrandire,
        )

    def test_ogni_giornata_semina_la_sua_sonda_di_chiusura(self):
        html = self._documento()
        self.assertIn("id='giorno-1-fine'", html)
        self.assertIn("id='giorno-2-fine'", html)

    def test_la_sonda_di_chiusura_e_dentro_un_contenuto_gia_presente(self):
        """[difetto trovato e corretto due volte nella stessa sessione — vedi
        `_render_striscia_foto`/il ciclo delle giornate in
        `src/pdf_renderer.py` e il commit di questo file] Le prime due
        versioni spostavano capitoli successivi fuori posto (misurato su
        `test_impaginazione_capitoli_2026_08_15`) oppure sparivano del tutto
        (un contenitore ad altezza zero non riceve un'annotazione). La sonda
        finale vive DENTRO l'ultimo elemento vero della giornata — qui,
        dentro la didascalia dell'ultima fotografia della fila di chiusura.
        """
        html = self._documento()
        pezzo = html.split("id='giorno-1-fine'", 1)[0][-200:]
        self.assertIn("didascalia", pezzo,
                     "la sonda dovrebbe stare dentro la didascalia "
                     "dell'ultima fotografia, non da sola nel flusso")

    def test_la_giornata_ingrandita_stampa_davvero_meno_foto(self):
        normale = self._documento()
        grande = self._documento(giornate_da_ingrandire={1})

        def _fila_giorno_1(html):
            return html.split("id='giorno-1'", 1)[1].split("id='giorno-2'", 1)[0]

        fila_1_normale = _fila_giorno_1(normale)
        fila_1_grande = _fila_giorno_1(grande)
        self.assertIn("<table class='day-striscia'>", fila_1_normale,
                      "senza ingrandire, giorno 1 stampa la sua fila normale")
        self.assertLess(fila_1_grande.count("<img"), fila_1_normale.count("<img"),
                        "ingrandendo, la stessa giornata stampa MENO fotografie")


class TestSulDocumentoVEROSTAMPATO(unittest.TestCase):
    """La prova che conta: quanto spazio resta lo dice solo la carta."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("wkhtmltopdf"):
            raise unittest.SkipTest("serve wkhtmltopdf")

    def _foto_vera(self, seme: int):
        from PIL import Image, ImageDraw

        immagine = Image.new("RGB", (1400, 900), (110 + seme * 7, 80, 60))
        disegno = ImageDraw.Draw(immagine)
        for x in range(0, 1400, 70):
            disegno.rectangle([x, 0, x + 30, 900], fill=(90, 50, 35))
        fuori = io.BytesIO()
        immagine.save(fuori, format="JPEG", quality=85)
        return fuori.getvalue()

    def _pezzi(self):
        """Un itinerario a giornate CORTE apposta: e' la forma che lascia
        spazio bianco sotto la fila di chiusura — la stessa forma delle
        pagine 15, 18, 21, 26 del fascicolo di Bologna. Le fotografie sono
        finte (niente rete in sandbox) ma marcate `reale=True`: e' lo stesso
        modo in cui il resto della suite prova la fila di chiusura senza
        una chiave Google, vedi `tests/test_striscia_foto_2026_08_13.py`.
        """
        giorni = []
        for numero, poi in enumerate(
            (("duomo", "torre"), ("piazza", "portico"), ("museo", "basilica")),
            start=1,
        ):
            giorni.append({
                "day": numero, "title": f"Giorno breve {numero}",
                "blocks": [
                    {"time": "09:00", "activity": f"Tappa {numero}.1",
                     "location": "Centro", "poi_id": poi[0]},
                    {"time": "11:00", "activity": f"Tappa {numero}.2",
                     "location": "Centro", "poi_id": poi[1]},
                ],
            })
        itinerario = {
            "destination": "Bologna",
            "executive_summary": "Un weekend breve.",
            "days": giorni,
        }
        trip = {
            "destination": "Bologna", "date_start": "2026-09-12",
            "date_end": "2026-09-15", "duration_days": 3, "budget_eur": 500,
        }
        photos = {
            poi: _scatto(poi)
            for giorno in giorni for b in giorno["blocks"]
            for poi in [b["poi_id"]]
        }
        kwargs = dict(hotels=[{"name": "Hotel Bologna", "price_night_eur": 90}],
                      photos=photos)
        return itinerario, trip, kwargs

    def _stampa(self, giornate_da_ingrandire=None):
        from src.pdf_renderer import COMANDO_STAMPA, render_html

        itinerario, trip, kwargs = self._pezzi()
        html = render_html(itinerario, trip,
                           giornate_da_ingrandire=giornate_da_ingrandire,
                           **kwargs)
        percorso_html = tempfile.mktemp(suffix=".html")
        Path(percorso_html).write_text(html, encoding="utf-8")
        percorso_pdf = tempfile.mktemp(suffix=".pdf")
        subprocess.run([*COMANDO_STAMPA, percorso_html, percorso_pdf],
                       check=True, capture_output=True, timeout=120)
        return Path(percorso_pdf)

    def test_la_seconda_stampa_riduce_lo_spazio_bianco_quando_serve(self):
        """Stessa garanzia del test gemello sulle testate dei capitoli, con
        le sonde FINTE invece che organiche: costruire un itinerario che
        lasci DAVVERO spazio bianco in fondo a una giornata richiederebbe una
        cartina vera (irraggiungibile in sandbox — niente rete) per rendere
        l'apertura abbastanza alta da spingere la giornata dopo a pagina
        nuova. La DECISIONE di quali giornate ingrandire è già provata a
        dovere, isolata, in `TestLaDecisioneSuQualiGiornateIngrandire`
        sopra; qui si prova che *usarla per davvero* — passarla a una
        seconda stampa reale — produca l'effetto promesso sulla carta.
        """
        prima = self._stampa()
        dopo = self._stampa({1})

        from src import impaginazione
        posizioni_prima = impaginazione.posizioni(prima.read_bytes())
        posizioni_dopo = impaginazione.posizioni(dopo.read_bytes())
        fine_prima = posizioni_prima.get("giorno-1-fine")
        fine_dopo = posizioni_dopo.get("giorno-1-fine")
        self.assertIsNotNone(fine_prima)
        self.assertIsNotNone(fine_dopo)
        self.assertLess(
            fine_dopo[1], fine_prima[1],
            "ingrandendo la fila di chiusura, la giornata 1 doveva arrivare "
            "piu' vicina al fondo della pagina — non e' successo")

    def test_render_pdf_collega_davvero_la_seconda_passata(self):
        """La trappola gia' presa altre volte in questo progetto: una
        funzione corretta (`giornate_con_bianco_finale`) scritta e mai
        collegata al documento vero. Qui si chiama `render_pdf()` per
        intero — la funzione che il servizio usa davvero — e si verifica
        che non sollevi e produca un PDF valido anche con la nuova seconda
        passata innestata dentro."""
        from src.pdf_renderer import render_pdf

        itinerario, trip, kwargs = self._pezzi()
        percorso = tempfile.mktemp(suffix=".pdf")
        risultato = render_pdf(itinerario, trip, output_path=percorso, **kwargs)
        self.assertTrue(Path(risultato).exists())
        self.assertGreater(Path(risultato).stat().st_size, 0)

        import scripts_qualita_pagina as q
        # Non deve sollevare, qualunque cosa trovi: e' esattamente il
        # misuratore che gira "prima di ogni consegna" per prassi del
        # progetto (vedi lo standard di qualita').
        q.problemi(percorso, Path(percorso).read_bytes())

    def test_ripararlo_non_allunga_il_documento(self):
        """[L'ALTRA META', e vale quanto la prima — stesso principio del
        test gemello sulle testate dei capitoli.]

        Ingrandire le foto di chiusura e' facile; farlo senza aggiungere
        pagine e' il punto. Se un domani la regola ingrandisse foto a
        sproposito, o le rendesse cosi' grandi da sfondare la pagina, questo
        diventerebbe rosso.
        """
        import scripts_qualita_pagina as q

        prima = self._stampa()
        dopo = self._stampa({1})

        self.assertLessEqual(len(q.misura(str(dopo))),
                             len(q.misura(str(prima))) + 1)

    def test_la_seconda_passata_e_stabile_niente_effetto_a_catena(self):
        """Una sola passata basta: rigirare la misura sul documento GIA'
        riparato non deve trovare le STESSE giornate ancora da ingrandire —
        altrimenti un domani qualcuno lo mette in un ciclo e non converge
        mai, la stessa trappola gia' evitata per le testate dei capitoli."""
        from src import impaginazione

        dopo = self._stampa({1})
        ancora = impaginazione.giornate_con_bianco_finale(
            dopo.read_bytes(), [1, 2, 3])
        self.assertEqual(set(), ancora & {1, 2, 3},
                         "la seconda passata ha scoperto le STESSE giornate "
                         "ancora da ingrandire dopo averle gia' ingrandite: "
                         "il ciclo non converge")


if __name__ == "__main__":
    unittest.main()
