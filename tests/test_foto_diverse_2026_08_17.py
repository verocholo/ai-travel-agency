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
  3. `poi_pdf._altre_foto()` la stampa in fondo alla scheda del SUO luogo.

## IL PUNTO 3 E' STATO RISCRITTO IL 18 AGOSTO, E VALE LA PENA DIRE PERCHE'

Nella prima stesura il punto 3 diceva un'altra cosa: la seconda fotografia
serviva a PRESTARE un luogo alle guide vicine senza ripetere lo scatto gia'
usato nella sua apertura. Due sessioni stavano riparando lo stesso difetto
nello stesso momento, e quella era la riparazione dell'altra.

Lorenzo ha bocciato il prestito in blocco, guardando il fascicolo vero:
«le foto sono messe a caso senza alcun ordine (cosa c'entra il tortellino)»
e, subito dopo, «per scegliere le foto devi scegliere tra una scelta molto
piu' ampia andando a scegliere foto **inerenti ai testi**». Una seconda
fotografia del tortellino nella scheda delle Due Torri resta una fotografia
del tortellino nella scheda delle Due Torri: cambia lo scatto, non il difetto.

Quindi la REGOLA e' «una fotografia sta nella pagina di cui parla, o non
c'e'», e il MECCANISMO (`png_alt`) resta — applicato al luogo giusto. I
controlli qui sotto difendono la regola nuova, e uno di essi e' scritto
apposta per fallire se il prestito dovesse tornare dentro di nascosto.
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


class TestAltreFotoStampaLaSecondaDELSUOLUOGO(unittest.TestCase):
    """`poi_pdf._altre_foto()`: la scheda di un luogo chiude con la SECONDA
    fotografia di QUEL luogo, quando esiste. Con nient'altro, mai.

    Il terzo parametro si chiama ancora `escluso` per ragioni di storia — era
    «il luogo da NON prestare» quando la funzione prestava. Oggi e' il
    contrario: e' l'unico luogo ammesso. Il nome resta perche' cambiarlo
    tocca tre punti di chiamata senza cambiare niente di cio' che si vede
    sulla carta; questo commento e' li' per chi lo legge fra sei mesi.
    """

    def _scatto(self, nome, con_alt=False):
        base = {"png": f"principale-{nome}".encode(),
                "credito": f"Foto: {nome} / Prova"}
        if con_alt:
            base["png_alt"] = f"alternativa-{nome}".encode()
            base["credito_alt"] = f"Foto alt: {nome} / Prova"
        return base

    def test_con_una_seconda_foto_sua_la_scheda_chiude_con_quella(self):
        tutte = {
            "A": self._scatto("a", con_alt=True),
            "B": self._scatto("b", con_alt=True),
        }
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        self.assertEqual([b"alternativa-a"], [r["png"] for r in risultato])
        self.assertEqual(["Foto alt: a / Prova"],
                         [r["credito"] for r in risultato])

    def test_lo_scatto_di_apertura_non_si_ripete_in_fondo(self):
        """Chiudere la scheda con la stessa immagine con cui si apre e' il
        difetto originale — «si ripetono ancora» — solo spostato in fondo."""
        tutte = {"A": self._scatto("a", con_alt=True)}
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        self.assertNotIn(b"principale-a", {r["png"] for r in risultato})

    def test_senza_seconda_foto_la_scheda_non_chiude_con_niente(self):
        """La regola vecchia («meglio una foto ripetuta che nessuna foto»)
        e' stata annullata da Lorenzo, non dimenticata: una pagina che
        finisce senza fila di immagini e' corretta."""
        tutte = {"A": self._scatto("a"), "B": self._scatto("b"),
                 "C": self._scatto("c")}
        self.assertEqual([], poi_pdf._altre_foto(tutte, escluso="A", giro=0))

    def test_NESSUNA_foto_di_un_altro_luogo_entra_mai_qui(self):
        """[IL CONTROLLO CHE VALE PIU' DI TUTTI GLI ALTRI IN QUESTO FILE.]

        E' il tortellino. Se qualcuno rimettesse dentro il prestito — per
        riempire una pagina, per «non sprecare» immagini gia' pagate, o
        semplicemente ripescando la versione vecchia di questo file — questo
        controllo diventa rosso e dice perche'.
        """
        tutte = {
            "A": self._scatto("a"),  # la scheda in esame: NIENTE seconda foto
            "B": self._scatto("b", con_alt=True),
            "C": self._scatto("c", con_alt=True),
        }
        risultato = poi_pdf._altre_foto(tutte, escluso="A", giro=0)
        estranee = {b"principale-b", b"alternativa-b",
                    b"principale-c", b"alternativa-c"}
        self.assertEqual(
            set(), {r["png"] for r in risultato} & estranee,
            "e' rientrata la fotografia di un altro luogo: e' il difetto "
            "che Lorenzo ha chiamato «cosa c'entra il tortellino»")

    def test_un_luogo_senza_foto_vera_non_ne_presta_una_alternativa(self):
        """Se la principale non e' arrivata, la scheda mostra la grafica
        disegnata in casa: attaccarci sotto una fila di fotografie vere
        farebbe sembrare la grafica un errore di caricamento."""
        tutte = {"A": {"png_alt": b"alternativa-a",
                       "credito_alt": "Foto alt: a / Prova"}}
        self.assertEqual([], poi_pdf._altre_foto(tutte, escluso="A", giro=0))

    def test_una_seconda_foto_senza_credito_non_si_stampa(self):
        """Stampare una fotografia di Google senza attribuzione e' un
        problema di licenza, non di estetica: meglio non stamparla."""
        tutte = {"A": {"png": b"principale-a", "credito": "Foto: a / Prova",
                       "png_alt": b"alternativa-a"}}  # manca credito_alt
        self.assertEqual([], poi_pdf._altre_foto(tutte, escluso="A", giro=0))

    def test_un_luogo_sconosciuto_non_fa_saltare_la_stampa(self):
        """Il fascicolo si costruisce anche quando la raccolta foto ha
        saltato un luogo: qui si ritorna vuoto, non si solleva niente."""
        for tutte in ({}, {"B": self._scatto("b", con_alt=True)}, None):
            with self.subTest(tutte=tutte):
                self.assertEqual(
                    [], poi_pdf._altre_foto(tutte, escluso="A", giro=0))


if __name__ == "__main__":
    unittest.main()
