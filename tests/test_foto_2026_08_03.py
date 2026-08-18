"""
Controlli sulle IMMAGINI del documento — task #181, 2026-08-03.

Richiesta di Lorenzo: «inserisci alcune immagini con senso» e «meno testo piu'
immagini, non deve essere noioso», con la sua scelta esplicita "Foto vere
ovunque + grafica interna".

Cosa difendono questi controlli, in ordine di importanza.

1. **L'onesta'.** Una fotografia altrui senza il nome di chi l'ha scattata non
   si stampa MAI, e la copertina disegnata in casa non compare MAI in cima al
   programma di una giornata, dove sarebbe scambiata per una foto del posto.
   Sono le due bugie piu' facili da raccontare con un'immagine, e sono
   entrambe bugie che il cliente scopre davanti al luogo.
2. **Il costo.** Ogni fotografia vera e' una chiamata a pagamento. Il tetto
   `MAX_FOTO` non e' un dettaglio di implementazione: e' l'unica cosa fra un
   itinerario da trenta tappe e una bolletta di trenta foto.
3. **La resa garantita.** Senza chiave, senza rete o a tetto esaurito il
   documento deve restare illustrato lo stesso. Una funzione di prodotto che
   sparisce quando la rete non risponde non e' una funzione di prodotto.
"""
import io
import unittest
from unittest import mock

from src import foto
from src import pdf_renderer
from src import places_client
from src import wikimedia


# Un JPEG vero, minuscolo, costruito al volo: serve a provare che
# `normalizza_png` converte davvero il formato, cosa che con dei byte finti
# non si potrebbe dimostrare.
def _jpeg_finto(larghezza=1600, altezza=900) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), (200, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def _poi(identificativo, nome, tipo="museum", ref="places/x/photos/y",
         credito="Foto: Mario Rossi / Google"):
    return {
        "id": identificativo, "name": nome, "type": tipo,
        "photo_ref": ref, "photo_credit": credito,
    }


def _guida(identificativo, nome):
    return {"poi_id": identificativo, "poi_name": nome, "title": nome,
            "history_summary": "Due righe di storia."}


class TestNormalizzaPng(unittest.TestCase):
    """La conversione e il ridimensionamento delle immagini scaricate."""

    def test_una_fotografia_esce_in_jpeg(self):
        """[CAMBIATO 2026-08-11] Prima questa prova pretendeva un PNG.

        Il cambio nasce da una segnalazione di Lorenzo — «le foto sono in
        bassa risoluzione» — e dal conto che c'e' dietro: una fotografia
        salvata in PNG pesa circa dieci volte quanto la stessa in JPEG, senza
        che nessun occhio veda la differenza. Quel peso e' il motivo per cui
        la larghezza era ferma a 800 pixel, cioe' il motivo per cui le foto
        sembravano sgranate sulla pagina stampata.

        In JPEG si porta il doppio della risoluzione pesando meno di prima.
        Si controlla la firma dei byte e non il tipo dichiarato: e' l'unico
        modo di sapere che la conversione e' davvero avvenuta.
        """
        uscita = foto.normalizza_png(_jpeg_finto())
        self.assertIsNotNone(uscita)
        self.assertEqual(uscita[:2], b"\xff\xd8")
        self.assertEqual(foto.mime_immagine(uscita), "image/jpeg")

    def test_il_documento_non_dichiara_mai_il_formato_sbagliato(self):
        """La bugia che il motore di stampa non perdona.

        Scrivere `data:image/png` davanti a un JPEG funziona in un browser e
        fa sparire l'immagine dal PDF. Da quando i due formati convivono —
        fotografie in JPEG, cartine e disegni in PNG — il tipo va letto dai
        byte, mai ricordato a memoria.
        """
        self.assertEqual(foto.mime_immagine(foto.normalizza_png(_jpeg_finto())),
                         "image/jpeg")
        self.assertEqual(
            foto.mime_immagine(foto.copertina_interna("Torre", "museum")),
            "image/png")
        for storto in (b"", b"xy", None, "non byte"):
            with self.subTest(storto=storto):
                self.assertEqual(foto.mime_immagine(storto), "image/png")

    def test_la_larghezza_basta_per_la_stampa(self):
        """[REGRESSIONE 2026-08-11] Erano 800 pixel, e si vedeva.

        Su una pagina A4 una fotografia a piena larghezza copre circa diciotto
        centimetri: a 800 pixel fanno poco piu' di 110 punti per pollice, che
        e' sotto la soglia in cui una foto comincia a sembrare sgranata. Il
        numero non e' un gusto, e' una divisione.
        """
        self.assertGreaterEqual(foto.LARGHEZZA_MAX, 1400)

    def test_un_immagine_larga_viene_rimpicciolita(self):
        """1600 px in ingresso, al massimo `LARGHEZZA_MAX` in uscita.

        E' il taglio che tiene l'allegato dentro una casella di posta: senza,
        venti guide da 1600 px in base64 fanno un file che non parte.
        """
        from PIL import Image

        uscita = foto.normalizza_png(_jpeg_finto(1600, 900))
        self.assertLessEqual(Image.open(io.BytesIO(uscita)).width, foto.LARGHEZZA_MAX)

    def test_byte_che_non_sono_un_immagine_danno_None(self):
        """Nessuna eccezione: una foto rotta costa una foto, non il documento."""
        self.assertIsNone(foto.normalizza_png(b"questo non e' un'immagine"))
        self.assertIsNone(foto.normalizza_png(b""))
        self.assertIsNone(foto.normalizza_png(None))


class TestCopertinaInterna(unittest.TestCase):
    """La grafica disegnata in casa, il ripiego che deve esserci sempre."""

    def test_esce_un_png_anche_senza_rete_e_senza_chiave(self):
        uscita = foto.copertina_interna("Torre del Mangia", "museum")
        self.assertIsNotNone(uscita)
        self.assertEqual(uscita[:8], b"\x89PNG\r\n\x1a\n")

    def test_lo_stesso_nome_da_sempre_la_stessa_immagine(self):
        """Deterministica di proposito.

        Se cambiasse a ogni generazione, due copie dello stesso itinerario
        sarebbero diverse e nessuno potrebbe piu' confrontarle — che e'
        esattamente cio' che serve per accorgersi di una regressione.
        """
        self.assertEqual(
            foto.copertina_interna("Duomo di Siena", "museum"),
            foto.copertina_interna("Duomo di Siena", "museum"),
        )

    def test_il_credito_dichiara_che_non_e_una_fotografia(self):
        """La riga che impedisce lo scambio.

        Non si controlla che la costante "esista": si controlla che DICA che
        non e' una fotografia. Una didascalia generica passerebbe il primo
        controllo e non il secondo, ed e' il secondo che protegge il cliente.
        """
        self.assertIn("non è una fotografia", foto.CREDITO_GRAFICA_INTERNA)
        # Nessun apostrofo ASCII: e' testo stampato su un documento venduto,
        # non un commento nel codice. Vedi la nota in `scheduling_criteria`.
        self.assertNotIn("e'", foto.CREDITO_GRAFICA_INTERNA)


class TestRaccogliFoto(unittest.TestCase):
    """La regola di raccolta: prima la foto libera, poi quella a pagamento,
    poi la copertina disegnata.

    Perche' Wikimedia e' spenta in tutta questa classe: qui si prova la
    RISERVA, cioe' cosa succede quando la fonte gratuita non ha trovato
    niente. Se la si lasciasse accesa, questi controlli chiamerebbero
    davvero Internet e direbbero cose diverse a seconda di come e' andata la
    rete quel giorno — che e' il modo piu' rapido per avere una suite che
    non si puo' credere. La fonte gratuita ha la sua classe, piu' sotto.
    """

    def setUp(self):
        spenta = mock.patch.object(wikimedia, "cerca_immagini", return_value=[])
        self.wikimedia_spenta = spenta.start()
        self.addCleanup(spenta.stop)

    def test_con_chiave_e_credito_si_prende_la_foto_vera(self):
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=_jpeg_finto()
        ) as chiamata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [_poi("A", "Duomo")], api_key="finta",
            )
        self.assertEqual(chiamata.call_count, 1)
        self.assertTrue(uscita["A"]["reale"])
        self.assertEqual(uscita["A"]["credito"], "Foto: Mario Rossi / Google")

    def test_senza_chiave_non_si_chiama_google_ma_l_immagine_c_e_lo_stesso(self):
        """Il caso normale sul portatile, e il caso di ogni guasto di rete."""
        with mock.patch.object(places_client, "fetch_place_photo") as chiamata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [_poi("A", "Duomo")], api_key=None,
            )
        chiamata.assert_not_called()
        self.assertFalse(uscita["A"]["reale"])
        self.assertEqual(uscita["A"]["credito"], foto.CREDITO_GRAFICA_INTERNA)

    def test_senza_credito_non_si_spende_e_non_si_stampa_la_foto_altrui(self):
        """Il controllo sta PRIMA della spesa, non dopo.

        Google obbliga a mostrare l'autore. Se l'attribuzione non e' arrivata,
        quella foto non e' pubblicabile: scaricarla comunque significherebbe
        pagare per un file da buttare, e stamparla significherebbe usare il
        lavoro di qualcuno senza dirlo, su un documento che vendiamo.
        """
        senza_credito = _poi("A", "Duomo", credito=None)
        with mock.patch.object(places_client, "fetch_place_photo") as chiamata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [senza_credito], api_key="finta",
            )
        chiamata.assert_not_called()
        self.assertFalse(uscita["A"]["reale"])

    def test_una_foto_che_non_arriva_diventa_la_copertina_interna(self):
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=None
        ):
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [_poi("A", "Duomo")], api_key="finta",
            )
        self.assertFalse(uscita["A"]["reale"])
        self.assertTrue(uscita["A"]["png"])

    def test_il_tetto_di_costo_e_rispettato(self):
        """Oltre il tetto si smette di PAGARE, non di illustrare.

        E' la differenza fra un limite di costo e un limite di prodotto: le
        guide oltre la dodicesima hanno la copertina disegnata, non il vuoto.
        """
        guide = [_guida(f"P{i}", f"Luogo {i}") for i in range(20)]
        pois = [_poi(f"P{i}", f"Luogo {i}") for i in range(20)]
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=_jpeg_finto(100, 100)
        ) as chiamata:
            uscita = foto.raccogli_foto(guide, pois, api_key="finta", massimo=3)
        self.assertEqual(chiamata.call_count, 3)
        self.assertEqual(len(uscita), 20)
        self.assertEqual(sum(1 for v in uscita.values() if v["reale"]), 3)

    def test_accetta_i_poi_come_oggetti_oltre_che_come_dizionari(self):
        """Il servizio passa dataclass, il campione passa dizionari.

        Se questa funzione ne accettasse uno solo, la differenza si vedrebbe
        soltanto in produzione — cioe' sul documento di un cliente pagante.
        """
        from src.schemas import POI

        oggetto = POI(
            id="A", type="museum", name="Duomo", lat=43.3, lng=11.3,
            photo_ref="places/x/photos/y", photo_credit="Foto: Tizio / Google",
        )
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=_jpeg_finto(100, 100)
        ):
            uscita = foto.raccogli_foto([_guida("A", "Duomo")], [oggetto],
                                        api_key="finta")
        self.assertTrue(uscita["A"]["reale"])

    def test_senza_guide_non_si_raccoglie_e_non_si_spende_nulla(self):
        with mock.patch.object(places_client, "fetch_place_photo") as chiamata:
            self.assertEqual(foto.raccogli_foto([], [_poi("A", "Duomo")],
                                                api_key="finta"), {})
        chiamata.assert_not_called()


class TestSoloReali(unittest.TestCase):
    def test_tiene_fuori_la_grafica_interna(self):
        dentro = {
            "A": {"png": b"x", "credito": "Foto: Tizio / Google", "reale": True},
            "B": {"png": b"y", "credito": foto.CREDITO_GRAFICA_INTERNA,
                  "reale": False},
        }
        self.assertEqual(set(foto.solo_reali(dentro)), {"A"})

    def test_su_valori_strani_non_esplode(self):
        self.assertEqual(foto.solo_reali(None), {})
        self.assertEqual(foto.solo_reali({"A": "non un dizionario"}), {})


class TestPlacesClientMappaLaFoto(unittest.TestCase):
    """Il ref e l'attribuzione devono arrivare fin qui dalla risposta di Google."""

    def test_la_maschera_dei_campi_chiede_le_foto(self):
        """Senza questa riga nella maschera, Google non manda nulla.

        E' un guasto silenzioso: nessun errore, nessun campo, e a valle
        semplicemente non ci sono foto vere da nessuna parte.
        """
        self.assertIn("places.photos", places_client.FIELD_MASK)

    def test_ref_e_credito_arrivano_dentro_il_POI(self):
        risposta = {"places": [{
            "id": "abc", "displayName": {"text": "Duomo"},
            "location": {"latitude": 43.3, "longitude": 11.3},
            "photos": [{
                "name": "places/abc/photos/ref123",
                "authorAttributions": [{"displayName": "Mario Rossi"}],
            }],
        }]}
        pois = places_client.map_places_response(risposta)
        self.assertEqual(pois[0].photo_ref, "places/abc/photos/ref123")
        self.assertIn("Mario Rossi", pois[0].photo_credit)

    def test_una_foto_senza_autore_non_porta_nessun_credito(self):
        risposta = {"places": [{
            "id": "abc", "displayName": {"text": "Duomo"},
            "location": {"latitude": 43.3, "longitude": 11.3},
            "photos": [{"name": "places/abc/photos/ref123"}],
        }]}
        pois = places_client.map_places_response(risposta)
        self.assertIsNone(pois[0].photo_credit)


class TestImmaginiNelDocumento(unittest.TestCase):
    """Dove le immagini possono comparire, e dove non devono."""

    def _html(self, photos):
        itinerario = {"days": [{
            "day": 1, "title": "Centro", "blocks": [{
                "time": "10:00", "location": "Duomo", "poi_id": "A",
                "activity": "Visita", "duration_min": 60,
            }],
        }]}
        return pdf_renderer.render_html(
            itinerario,
            {"destination": "Siena", "date_start": "2026-09-10",
             "date_end": "2026-09-11", "travelers": 2},
            guides=[_guida("A", "Duomo")],
            poi=[{"id": "A", "name": "Duomo", "lat": 43.3, "lng": 11.3,
                  "type": "museum"}],
            photos=photos,
        )

    def test_una_fotografia_vera_apre_la_giornata(self):
        """[AGGIORNATO 2026-08-13 — task #214.]

        Prima qui c'era `assertIn("class='day-foto'")`, cioe' la classe CSS
        dell'unico modo in cui una giornata poteva aprirsi. Da oggi i modi
        sono tre — fotografia centrata, banda a tutta larghezza, mosaico — e
        quale tocchi a questa giornata lo decide il compositore.

        La proprieta' da difendere pero' non era mai stata «quella classe»:
        era **una fotografia vera in apertura, col suo credito**. Scritta
        cosi' la prova vale per tutte e tre le aperture invece che per una,
        cioe' copre piu' di prima e non meno.
        """
        out = self._html({"A": {"png": foto.copertina_interna("Duomo", "museum"),
                                "credito": "Foto: Mario Rossi / Google",
                                "reale": True}})
        aperture = ("class='day-foto'", "class='day-banda'",
                    "class='day-striscia'")
        self.assertTrue(
            any(a in out for a in aperture),
            "la giornata non si apre con nessuna fotografia: nessuna delle "
            f"aperture {aperture} compare nel documento")
        self.assertIn("Mario Rossi", out)

    def test_la_grafica_interna_NON_apre_la_giornata(self):
        """Il controllo centrale di tutto il file.

        La copertina disegnata resta disponibile per la scheda della guida,
        ma in cima al programma della giornata — dove il cliente legge
        "questo e' il posto dove vai" — passa solo una fotografia vera.

        Il filtro sta dentro il renderer e non in chi lo chiama proprio
        perche' questo controllo sia possibile: verificato a monte,
        misurerebbe la disciplina di un chiamante invece della regola.
        """
        out = self._html({"A": {"png": foto.copertina_interna("Duomo", "museum"),
                                "credito": foto.CREDITO_GRAFICA_INTERNA,
                                "reale": False}})
        self.assertNotIn("class='day-foto'", out)

    def test_la_grafica_interna_illustra_pero_la_scheda_della_guida(self):
        out = self._html({"A": {"png": foto.copertina_interna("Duomo", "museum"),
                                "credito": foto.CREDITO_GRAFICA_INTERNA,
                                "reale": False}})
        self.assertIn("class='guide-foto'", out)

    def test_senza_credito_l_immagine_non_si_stampa_da_nessuna_parte(self):
        out = self._html({"A": {"png": foto.copertina_interna("Duomo", "museum"),
                                "credito": "", "reale": True}})
        self.assertNotIn("class='day-foto'", out)
        self.assertNotIn("class='guide-foto'", out)

    def test_senza_immagini_il_documento_esce_lo_stesso(self):
        """Il documento di ieri deve continuare a uscire: niente foto, nessun
        guasto."""
        for valore in (None, {}, {"A": "non un dizionario"}):
            out = self._html(valore)
            self.assertIn("Siena", out)
            self.assertNotIn("class='day-foto'", out)


if __name__ == "__main__":
    unittest.main()
