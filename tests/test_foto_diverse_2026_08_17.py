"""Foto diverse, non le solite ripetute (task #226).

PERCHE' QUESTO FILE ESISTE

Direttiva di Lorenzo, sul fascicolo di Bologna: «foto diverse (non usare
sempre le solite tre ripetute)».

Con un solo scatto scaricato per luogo, un luogo che compare in piu' punti
del documento — la sua guida, e le bande "altre tappe" delle guide vicine
(`poi_pdf._altre_foto`) — mostrava sempre la STESSA immagine identica. Su un
itinerario piccolo (5-6 luoghi illustrati) e' il caso normale, non
l'eccezione: le due torri di Bologna comparivano identiche in piu' schede
diverse dello stesso fascicolo.

La riparazione, in tre pezzi:

  1. `places_client` estrae anche la SECONDA fotografia di Google, quando
     c'e' — gratis, arriva nella stessa risposta della prima;
  2. `foto.raccogli_foto()` la scarica separatamente, entro un tetto di
     spesa suo (`MAX_FOTO_SECONDARIA`), SOLO per i luoghi con gia' una
     fotografia vera;
  3. `poi_pdf._altre_foto()` la usa al posto della principale quando
     presta un luogo alle guide vicine.
"""

import io
import unittest
from unittest import mock

from src import foto
from src import places_client
from src import poi_pdf
from src import wikimedia


def _jpeg_finto(seme=0) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 150), (100 + seme, 90, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def _poi(identificativo, nome, ref2=None, credito2=None):
    dati = {
        "id": identificativo, "name": nome, "type": "museum",
        "photo_ref": "places/x/photos/uno",
        "photo_credit": "Foto: Mario Rossi / Google",
    }
    if ref2 is not None:
        dati["photo_ref_2"] = ref2
    if credito2 is not None:
        dati["photo_credit_2"] = credito2
    return dati


def _guida(identificativo, nome):
    return {"poi_id": identificativo, "poi_name": nome, "title": nome,
            "history_summary": "Due righe di storia."}


class TestPlacesClientEstraeAncheLaSecondaFoto(unittest.TestCase):

    def _risposta(self, *nomi_foto):
        return {
            "photos": [
                {"name": nome, "authorAttributions": [{"displayName": "Tizio"}]}
                for nome in nomi_foto
            ]
        }

    def test_con_due_foto_disponibili_prende_entrambe(self):
        item = self._risposta("places/x/photos/uno", "places/x/photos/due")
        self.assertEqual("places/x/photos/uno", places_client._photo_ref(item, 0))
        self.assertEqual("places/x/photos/due", places_client._photo_ref(item, 1))

    def test_con_una_sola_foto_la_seconda_e_assente(self):
        item = self._risposta("places/x/photos/uno")
        self.assertEqual("places/x/photos/uno", places_client._photo_ref(item, 0))
        self.assertIsNone(places_client._photo_ref(item, 1))

    def test_senza_foto_nessuna_delle_due(self):
        item = {"photos": []}
        self.assertIsNone(places_client._photo_ref(item, 0))
        self.assertIsNone(places_client._photo_ref(item, 1))

    def test_il_credito_segue_lo_stesso_indice(self):
        item = self._risposta("places/x/photos/uno", "places/x/photos/due")
        self.assertIn("Tizio", places_client._photo_credit(item, 0))
        self.assertIn("Tizio", places_client._photo_credit(item, 1))


class TestRaccogliFotoScaricaLaSeconda(unittest.TestCase):

    def setUp(self):
        spenta = mock.patch.object(wikimedia, "cerca_immagine", return_value=None)
        self.wikimedia_spenta = spenta.start()
        self.addCleanup(spenta.stop)

    def test_un_luogo_con_due_riferimenti_riceve_png_alt(self):
        poi = _poi("A", "Duomo", ref2="places/x/photos/due",
                   credito2="Foto: Caio / Google")
        with mock.patch.object(
            places_client, "fetch_place_photo",
            side_effect=[_jpeg_finto(0), _jpeg_finto(50)],
        ):
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [poi], api_key="finta")
        self.assertTrue(uscita["A"]["reale"])
        self.assertIn("png_alt", uscita["A"])
        self.assertEqual(uscita["A"]["credito_alt"], "Foto: Caio / Google")

    def test_senza_secondo_riferimento_niente_png_alt(self):
        poi = _poi("A", "Duomo")  # nessun ref2/credito2
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=_jpeg_finto(0),
        ):
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [poi], api_key="finta")
        self.assertNotIn("png_alt", uscita["A"])

    def test_un_luogo_con_solo_la_grafica_disegnata_non_compra_una_seconda_foto(self):
        """Non ha senso comprare una seconda immagine per un luogo la cui
        prima fotografia non e' nemmeno arrivata: la grafica disegnata in
        casa resta l'unica cosa da stampare."""
        poi = _poi("A", "Duomo", ref2="places/x/photos/due",
                   credito2="Foto: Caio / Google")
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=None,
        ) as chiamata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [poi], api_key="finta")
        self.assertFalse(uscita["A"]["reale"])
        self.assertNotIn("png_alt", uscita["A"])
        # Una sola chiamata tentata (la principale), non due: comprare una
        # riserva per un luogo senza immagine principale sarebbe soldi
        # buttati.
        self.assertEqual(chiamata.call_count, 1)

    def test_il_tetto_della_seconda_foto_e_rispettato(self):
        guide = [_guida(f"P{i}", f"Luogo {i}") for i in range(10)]
        pois = [_poi(f"P{i}", f"Luogo {i}", ref2=f"places/x/photos/due{i}",
                     credito2="Foto: Caio / Google") for i in range(10)]
        with mock.patch.object(
            places_client, "fetch_place_photo", return_value=_jpeg_finto(0),
        ) as chiamata:
            uscita = foto.raccogli_foto(guide, pois, api_key="finta")
        con_alt = sum(1 for v in uscita.values() if "png_alt" in v)
        self.assertEqual(con_alt, foto.MAX_FOTO_SECONDARIA)
        # Dieci principali + le seconde entro il tetto.
        self.assertEqual(chiamata.call_count, 10 + foto.MAX_FOTO_SECONDARIA)

    def test_senza_chiave_nessuna_chiamata_ne_principale_ne_secondaria(self):
        poi = _poi("A", "Duomo", ref2="places/x/photos/due",
                   credito2="Foto: Caio / Google")
        with mock.patch.object(places_client, "fetch_place_photo") as chiamata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [poi], api_key=None)
        chiamata.assert_not_called()
        self.assertNotIn("png_alt", uscita["A"])


class TestAltreFotoPreferisceLaSeconda(unittest.TestCase):
    """`poi_pdf._altre_foto()`: quando un luogo presta se stesso alle guide
    vicine, deve prestare la SUA seconda foto se ce l'ha — non quella gia'
    usata come apertura della sua guida."""

    def _scatto(self, nome, con_alt=False):
        base = {"png": f"principale-{nome}".encode(),
                "credito": f"Foto: {nome} / Prova"}
        if con_alt:
            base["png_alt"] = f"alternativa-{nome}".encode()
            base["credito_alt"] = f"Foto alt: {nome} / Prova"
        return base

    def test_con_una_seconda_foto_disponibile_viene_usata_quella(self):
        tutte = {
            "A": self._scatto("a"),
            "B": self._scatto("b", con_alt=True),
            "C": self._scatto("c"),
        }
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        per_png = {r["png"] for r in risultato}
        self.assertIn(b"alternativa-b", per_png,
                      "il luogo B ha una seconda foto: deve essere quella "
                      "prestata, non la principale gia' usata nella sua "
                      "guida")
        self.assertNotIn(b"principale-b", per_png)

    def test_senza_seconda_foto_si_usa_comunque_la_principale(self):
        """Meglio una foto ripetuta che nessuna foto: la regola vecchia
        resta la rete di sicurezza quando la nuova non si applica."""
        tutte = {"A": self._scatto("a"), "B": self._scatto("b"),
                 "C": self._scatto("c")}
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        per_png = {r["png"] for r in risultato}
        self.assertIn(b"principale-b", per_png)
        self.assertIn(b"principale-c", per_png)

    def test_il_luogo_escluso_resta_escluso_anche_con_una_seconda_foto(self):
        tutte = {
            "A": self._scatto("a", con_alt=True),
            "B": self._scatto("b", con_alt=True),
            "C": self._scatto("c", con_alt=True),
        }
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        per_png = {r["png"] for r in risultato}
        self.assertNotIn(b"principale-a", per_png)
        self.assertNotIn(b"alternativa-a", per_png)
        self.assertIn(b"alternativa-b", per_png)
        self.assertIn(b"alternativa-c", per_png)


if __name__ == "__main__":
    unittest.main()
