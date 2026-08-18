"""
Fotografie libere e prova delle immagini vere — task #188 e #189.

DUE COSE DIVERSE, PROVATE INSIEME PERCHE' SI TENGONO

`src/wikimedia.py` procura le fotografie che si possono davvero
ridistribuire dentro un PDF venduto. `src/diagnostica_immagini.py` dice, in
dieci secondi e per quattro centesimi, se le cartine e le fotografie vere
funzionano sul server — informazione che prima costava un itinerario intero.

PERCHE' QUESTI CONTROLLI ESISTONO

Il primo motivo e' legale, ed e' il piu' serio del file. Una fotografia con
licenza "CC BY-NC" non si puo' mettere in un documento che il cliente paga.
La sigla `nc` sta dentro la stringa "cc by-nc", che contiene anche "cc by":
una regola scritta cercando solo le licenze AMMESSE accetterebbe proprio
quelle da rifiutare, e nessuno se ne accorgerebbe finche' non arriva una
diffida. Il controllo sulle licenze vietate e' qui per quello.

Il secondo e' di sicurezza. La URL della Static Maps porta la chiave Google
in chiaro come parametro `key=`, e il messaggio d'errore di una chiamata
HTTP fallita porta con se' la URL. Una diagnostica che stampa l'errore
grezzo regala la chiave a chiunque legga la risposta — e questa risposta
nasce per essere copiata e incollata in chat, che e' il posto peggiore.

Il terzo e' economico. La prova delle fotografie costa quindici volte quella
della cartina. Se `?solo=cartina` smettesse silenziosamente di funzionare,
chi ricontrolla le cartine dieci volte di fila pagherebbe dieci volte anche
le fotografie senza accorgersene.
"""
import os
import unittest
from unittest import mock
from unittest.mock import patch

import service
from src import diagnostica_immagini
from src import foto
from src import places_client
from src import wikimedia


CHIAVE_SERVIZIO = "chiave-di-prova-per-i-controlli"
CHIAVE_GOOGLE = "AIzaSyFINTA-non-e-una-chiave-vera-1234567890"

AMBIENTE = {
    "SERVICE_API_KEY": CHIAVE_SERVIZIO,
    "GOOGLE_MAPS_KEY": CHIAVE_GOOGLE,
}


def _scheda(titolo, licenza, autore="Mario Rossi", url="https://esempio/x.jpg"):
    """Una pagina di Commons nella forma in cui arriva davvero."""
    return {
        "title": titolo,
        "imageinfo": [{
            "thumburl": url,
            "descriptionurl": "https://commons.wikimedia.org/wiki/" + titolo,
            "extmetadata": {
                "LicenseShortName": {"value": licenza},
                "Artist": {"value": f"<a href='/wiki/User:X'>{autore}</a>"},
            },
        }],
    }


def _risposta(pagine):
    return {"query": {"pages": {str(i): p for i, p in enumerate(pagine)}}}


class TestLeLicenzeCheNonSiPossonoUsare(unittest.TestCase):
    """La parte di questo giro che puo' costare una diffida.

    Wikimedia Commons ospita anche materiale con licenze che vietano l'uso
    commerciale o le opere derivate. Il nostro PDF e' venduto: quelle non si
    possono usare, e la differenza fra usarle e non usarle sta tutta in una
    riga di codice.
    """

    def test_le_licenze_libere_passano(self):
        for buona in ("CC BY-SA 4.0", "CC0", "Public domain", "PD-old-70",
                      "cc by 2.0"):
            with self.subTest(licenza=buona):
                self.assertTrue(wikimedia.licenza_ammessa(buona))

    def test_non_commerciale_e_non_derivabile_vengono_rifiutate(self):
        """Il controllo per cui esiste tutto il resto.

        "cc by-nc" CONTIENE "cc by": una regola che cerca solo gli ammessi
        la accetta. I divieti vanno cercati per primi, e vanno cercati a
        pezzi separati.
        """
        for cattiva in ("CC BY-NC 3.0", "CC BY-NC-SA 4.0", "CC BY-ND 2.0",
                        "Fair use", "Non-free"):
            with self.subTest(licenza=cattiva):
                self.assertFalse(
                    wikimedia.licenza_ammessa(cattiva),
                    f"«{cattiva}» non si puo' mettere in un documento venduto",
                )

    def test_una_licenza_sconosciuta_viene_scartata_non_accettata(self):
        """L'errore prudente e quello imprudente non costano uguale.

        Una fotografia in meno costa una copertina disegnata. Una fotografia
        di troppo costa una lettera di un avvocato. Davanti a una licenza che
        non si riconosce si sceglie il primo dei due.
        """
        for ignota in ("", "Licenza-Che-Non-Esiste", "Tutti i diritti riservati"):
            with self.subTest(licenza=ignota):
                self.assertFalse(wikimedia.licenza_ammessa(ignota))

    def test_la_scelta_salta_le_fotografie_con_la_licenza_sbagliata(self):
        """La regola giusta applicata al posto giusto.

        Una funzione corretta che nessuno chiama sulla lista vera non
        protegge niente: qui si guarda che la prima della lista, se ha la
        licenza sbagliata, venga davvero scavalcata.
        """
        scelta = wikimedia._prima_utilizzabile([
            _scheda("File:Campo-bella.jpg", "CC BY-NC 4.0"),
            _scheda("File:Campo-libera.jpg", "CC BY-SA 4.0"),
        ])
        self.assertIsNotNone(scelta)
        self.assertEqual(scelta["titolo"], "Campo-libera.jpg")

    def test_se_sono_tutte_vietate_non_si_ripiega_sulla_meno_peggio(self):
        self.assertIsNone(wikimedia._prima_utilizzabile([
            _scheda("File:a.jpg", "CC BY-NC 4.0"),
            _scheda("File:b.jpg", "Fair use"),
        ]))


class TestQuelloCheIlMotoreDiStampaNonSaDisegnare(unittest.TestCase):

    def test_le_immagini_vettoriali_vengono_saltate(self):
        """Un .svg non da' errore: lascia un buco bianco.

        E' il difetto peggiore da trovare, perche' tutti i controlli sono
        verdi e il documento e' sbagliato solo a guardarlo.
        """
        scelta = wikimedia._prima_utilizzabile([
            _scheda("File:stemma.svg", "CC BY-SA 4.0"),
            _scheda("File:foto.jpg", "CC BY-SA 4.0"),
        ])
        self.assertEqual(scelta["titolo"], "foto.jpg")


class TestLaDidascaliaELaLicenza(unittest.TestCase):
    """Non e' decorazione: e' la condizione a cui la foto si puo' usare."""

    def test_dice_autore_fonte_e_licenza(self):
        riga = wikimedia.ImmagineLibera(
            titolo="Campo.jpg", byte=b"x", licenza="CC BY-SA 4.0",
            autore="Mario Rossi", pagina="https://commons.wikimedia.org/x",
        ).didascalia()
        self.assertIn("Mario Rossi", riga)
        self.assertIn("Wikimedia Commons", riga)
        self.assertIn("CC BY-SA 4.0", riga)

    def test_il_nome_dell_autore_non_porta_dentro_marcatori_html(self):
        """Commons restituisce l'autore come HTML, con dentro dei link.

        Infilato nel documento cosi' com'e' non stamperebbe solo dei simboli
        strani: aprirebbe un tag che sbilancia il resto della pagina.
        """
        scelta = wikimedia._prima_utilizzabile(
            [_scheda("File:x.jpg", "CC0", autore="Giulia Bianchi")]
        )
        self.assertEqual(scelta["autore"], "Giulia Bianchi")
        self.assertNotIn("<", scelta["autore"])


class TestUnaFotoMancanteCostaUnaFotoNonIlDocumento(unittest.TestCase):

    def test_senza_rete_non_solleva_e_restituisce_niente(self):
        with patch("src.wikimedia.requests.get",
                   side_effect=OSError("rete assente")):
            self.assertIsNone(wikimedia.cerca_immagine("Duomo", "Siena"))

    def test_una_risposta_inattesa_non_solleva(self):
        class _Finta:
            status_code = 200
            headers = {"Content-Type": "application/json"}

            def raise_for_status(self):
                pass

            def json(self):
                return {"non": "quello che mi aspettavo"}

        with patch("src.wikimedia.requests.get", return_value=_Finta()):
            self.assertIsNone(wikimedia.cerca_immagine("Duomo", "Siena"))

    def test_senza_nome_non_chiama_nemmeno_la_rete(self):
        with patch("src.wikimedia.requests.get") as finta:
            self.assertIsNone(wikimedia.cerca_immagine("", ""))
            finta.assert_not_called()


class TestLaChiaveNonEsceMaiDallaDiagnostica(unittest.TestCase):
    """Il controllo di sicurezza del giro.

    La URL di Static Maps porta la chiave come `key=...`, e l'errore di una
    chiamata fallita porta con se' la URL. Questa risposta nasce per essere
    copiata e incollata in chat da chi sta cercando il guasto: e' il posto
    peggiore dove far comparire una credenziale.
    """

    def test_un_errore_che_contiene_la_chiave_esce_ripulito(self):
        finto = Exception(
            "Google Static Maps ha risposto 403: richiesta a "
            f"https://maps.googleapis.com/maps/api/staticmap?size=200x150&key={CHIAVE_GOOGLE}"
        )
        with patch("src.maps_static.fetch_static_map_png", side_effect=finto):
            esito = diagnostica_immagini.prova_cartina(CHIAVE_GOOGLE)
        self.assertEqual(esito["esito"], "errore")
        self.assertNotIn(
            CHIAVE_GOOGLE, str(esito),
            "la chiave Google e' finita dentro la risposta della diagnostica",
        )

    def test_vale_anche_per_la_prova_delle_fotografie(self):
        with patch("src.places_client.fetch_nearby_raw",
                   side_effect=Exception(f"X-Goog-Api-Key: {CHIAVE_GOOGLE}")):
            esito = diagnostica_immagini.prova_foto_google(CHIAVE_GOOGLE)
        self.assertNotIn(CHIAVE_GOOGLE, str(esito))

    def test_la_chiave_nuda_dentro_una_frase_qualsiasi_non_passa(self):
        """Il caso che le espressioni regolari non possono prevedere.

        `redact_secrets` sa riconoscere le FORME note in cui un segreto
        viaggia: `key=...`, l'intestazione `X-Goog-Api-Key`. Ma la libreria
        che va in errore scrive quello che vuole, e prima o poi scrivera' la
        chiave dentro una frase che nessuno aveva previsto — senza prefisso,
        senza segno di uguale, in mezzo alle parole. Se la diagnostica si
        fidasse solo delle forme note, quel giorno la credenziale finirebbe
        in chat dentro un messaggio d'errore incollato per chiedere aiuto.
        Per questo la difesa sono due: le forme note piu' la sostituzione
        letterale del valore. Questo controllo tiene in vita la seconda.
        """
        frase = (
            "connessione rifiutata dal proxy mentre autenticavo il client "
            f"{CHIAVE_GOOGLE} verso il servizio cartografico"
        )
        with patch("src.maps_static.fetch_static_map_png",
                   side_effect=Exception(frase)):
            cartina = diagnostica_immagini.prova_cartina(CHIAVE_GOOGLE)
        self.assertNotIn(
            CHIAVE_GOOGLE, str(cartina),
            "la chiave nuda dentro una frase qualsiasi e' uscita dalla "
            "diagnostica: resta solo la difesa delle forme note",
        )

        with patch("src.places_client.fetch_nearby_raw",
                   side_effect=Exception(frase)):
            foto = diagnostica_immagini.prova_foto_google(CHIAVE_GOOGLE)
        self.assertNotIn(CHIAVE_GOOGLE, str(foto))


class TestDiceCosaFarePerSistemare(unittest.TestCase):
    """Una diagnosi in inglese e per codici non serve a chi deve agire.

    Chi legge questa risposta deve sapere QUALE casella spuntare nella
    console di Google, non quale costante ha restituito il server.
    """

    def test_riconosce_la_api_non_abilitata(self):
        detto = diagnostica_immagini._leggi_errore_google(
            "Maps Static API has not been used in project 123 before or it is disabled"
        )
        self.assertIsNotNone(detto)
        self.assertIn("Abilita", detto)

    def test_riconosce_la_restrizione_sulla_chiave(self):
        detto = diagnostica_immagini._leggi_errore_google(
            "This API key is not authorized to use this API. API_KEY_SERVICE_BLOCKED"
        )
        self.assertIsNotNone(detto)
        self.assertIn("Restrizioni API", detto)

    def test_riconosce_la_fatturazione_spenta(self):
        detto = diagnostica_immagini._leggi_errore_google(
            "You must enable Billing on the Google Cloud Project"
        )
        self.assertIsNotNone(detto)
        self.assertIn("fatturazione", detto)

    def test_un_errore_che_non_conosco_non_inventa_una_diagnosi(self):
        """Un consiglio sbagliato manda a cercare il guasto nel posto sbagliato.

        Meglio nessuna diagnosi che una plausibile e falsa: la seconda costa
        mezz'ora di console Google a caccia di niente.
        """
        self.assertIsNone(
            diagnostica_immagini._leggi_errore_google("connessione interrotta")
        )


class TestNonSiPagaQuelloCheNonSiEChiesto(unittest.TestCase):

    def test_solo_cartina_non_chiama_le_fotografie(self):
        with patch("src.diagnostica_immagini.prova_foto_google") as foto, \
                patch("src.diagnostica_immagini.prova_wikimedia") as wiki, \
                patch("src.diagnostica_immagini.prova_cartina",
                      return_value={"prova": "c", "esito": "ok",
                                    "costo_eur": 0.002}):
            diagnostica_immagini.esegui(CHIAVE_GOOGLE, solo="cartina")
        foto.assert_not_called()
        wiki.assert_not_called()

    def test_una_scelta_che_non_esiste_non_fa_partire_tutto(self):
        """Il modo tipico in cui una protezione sui costi smette di esistere.

        Se `solo=cartna` (scritto male) ricadesse su "fai tutto", chi voleva
        risparmiare pagherebbe di piu' proprio quando sbaglia a scrivere.
        """
        with patch("src.diagnostica_immagini.prova_cartina") as cartina:
            esito = diagnostica_immagini.esegui(CHIAVE_GOOGLE, solo="cartna")
        cartina.assert_not_called()
        self.assertIn("errore", esito)

    def test_il_costo_di_quello_che_si_e_fatto_viene_dichiarato(self):
        with patch("src.diagnostica_immagini.prova_cartina",
                   return_value={"prova": "c", "esito": "ok",
                                 "costo_eur": 0.002}):
            esito = diagnostica_immagini.esegui(CHIAVE_GOOGLE, solo="cartina")
        self.assertEqual(esito["costo_di_questa_verifica_eur"], 0.002)


class TestSenzaChiaveNonSiSpendeENonSiFingeUnErrore(unittest.TestCase):

    def test_senza_chiave_le_prove_google_non_partono(self):
        with patch("src.maps_static.fetch_static_map_png") as rete:
            esito = diagnostica_immagini.prova_cartina(None)
        rete.assert_not_called()
        self.assertEqual(esito["esito"], "non provato")
        self.assertEqual(esito["costo_eur"], 0.0)


class TestLaRottaNasceRiservata(unittest.TestCase):
    """In questo servizio l'autenticazione non e' globale.

    Una rotta nuova nasce pubblica, e questa spende soldi veri a ogni
    chiamata: pubblica sarebbe un rubinetto aperto sulla strada.
    """

    @staticmethod
    def _chiedi(chiave, percorso="/v1/diagnostica/immagini"):
        with patch.dict(os.environ, AMBIENTE, clear=True), \
                patch("src.diagnostica_immagini.esegui",
                      return_value={"prove_riuscite": "0/0"}):
            service.app.config["TESTING"] = True
            testate = {"X-Service-Key": chiave} if chiave is not None else {}
            return service.app.test_client().get(percorso, headers=testate)

    def test_senza_chiave_non_risponde(self):
        self.assertEqual(self._chiedi(None).status_code, 401)

    def test_con_la_chiave_sbagliata_non_risponde(self):
        self.assertEqual(self._chiedi("sbagliata").status_code, 401)

    def test_con_la_chiave_giusta_risponde(self):
        self.assertEqual(self._chiedi(CHIAVE_SERVIZIO).status_code, 200)

    def test_senza_chiave_non_si_spende_niente(self):
        """Il 401 deve arrivare PRIMA delle chiamate a pagamento.

        Una rotta che controlla la chiave dopo aver gia' chiamato Google
        risponde 401 e presenta comunque il conto.
        """
        with patch.dict(os.environ, AMBIENTE, clear=True), \
                patch("src.diagnostica_immagini.esegui") as spesa:
            service.app.config["TESTING"] = True
            service.app.test_client().get("/v1/diagnostica/immagini")
        spesa.assert_not_called()


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Task #189 — la fonte gratuita viene prima, e la sua licenza arriva in fondo
# ---------------------------------------------------------------------------

class _FotoFinta:
    """Una `ImmagineLibera` senza dover costruire un JPEG vero ogni volta."""

    def __init__(self, didascalia="Foto: Tizio / Wikimedia Commons / CC BY-SA 4.0"):
        self.byte = _jpeg_minimo()
        self._didascalia = didascalia

    def didascalia(self):
        return self._didascalia


def _jpeg_minimo(larghezza=400, altezza=300) -> bytes:
    from PIL import Image
    import io as _io

    buf = _io.BytesIO()
    Image.new("RGB", (larghezza, altezza), (120, 160, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def _guida(identificativo, nome):
    return {"poi_id": identificativo, "poi_name": nome}


def _poi(identificativo, nome, tipo="museum"):
    return {
        "id": identificativo, "name": nome, "type": tipo,
        "photo_ref": "places/x/photos/y", "photo_credit": "Foto: Caio / Google",
    }


class TestLaFonteGratuitaVienePrima(unittest.TestCase):
    """L'ordine delle sorgenti non e' una preferenza estetica.

    Wikimedia si puo' ridistribuire dentro un documento venduto; una foto di
    Google Places, dentro lo stesso documento, ci mette in una posizione che
    dipende dalle condizioni d'uso di qualcun altro. Se un giorno qualcuno
    invertisse l'ordine «perche' le foto di Google sono piu' pertinenti», il
    prodotto continuerebbe a funzionare benissimo e a essere piu' bello — e
    sarebbe piu' difficile da vendere a mille persone. Nessun controllo
    visivo se ne accorgerebbe. Questo si'.
    """

    def test_se_wikimedia_trova_google_non_viene_nemmeno_chiamato(self):
        with mock.patch.object(wikimedia, "cerca_immagini",
                               return_value=[_FotoFinta()]) as gratis, \
             mock.patch.object(places_client, "fetch_place_photo") as pagata:
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [_poi("A", "Duomo")],
                api_key="finta", citta="Siena",
            )
        self.assertEqual(gratis.call_count, 1)
        pagata.assert_not_called()
        self.assertTrue(uscita["A"]["reale"])
        self.assertEqual(uscita["A"]["fonte"], "wikimedia")

    def test_la_licenza_arriva_fino_al_documento(self):
        """La didascalia NON e' decorazione: e' la condizione d'uso.

        Se il credito si perdesse per strada fra `wikimedia.cerca_immagine` e
        il dizionario che il renderer stampa, il documento uscirebbe con una
        fotografia bellissima e senza il nome di chi l'ha scattata — che e'
        esattamente la violazione che scegliere Wikimedia doveva evitare. Il
        controllo guarda il CONTENUTO della riga, non che esista una riga.
        """
        with mock.patch.object(
            wikimedia, "cerca_immagini",
            return_value=[_FotoFinta("Foto: Ada Lovelace / Wikimedia Commons / CC BY 4.0")],
        ):
            uscita = foto.raccogli_foto(
                [_guida("A", "Duomo")], [_poi("A", "Duomo")], citta="Siena",
            )
        credito = uscita["A"]["credito"]
        self.assertIn("Ada Lovelace", credito)
        self.assertIn("Wikimedia Commons", credito)
        self.assertIn("CC BY 4.0", credito)

    def test_una_foto_gratuita_non_consuma_il_tetto_di_spesa(self):
        """Il tetto e' un limite di SOLDI, non di fotografie.

        Contare le foto libere dentro `massimo` sarebbe l'errore esattamente
        contrario a quello che il tetto serve a evitare: si smetterebbe di
        illustrare il documento dopo dodici fotografie che non sono costate
        niente, e le attrazioni successive perderebbero anche la riserva a
        pagamento che il tetto avrebbe ancora tutta disponibile.
        """
        guide = [_guida(f"P{i}", f"Luogo {i}") for i in range(5)]
        pois = [_poi(f"P{i}", f"Luogo {i}") for i in range(5)]
        # Le prime due gratuite, le altre no.
        risposte = [[_FotoFinta()], [_FotoFinta()], [], [], []]
        with mock.patch.object(wikimedia, "cerca_immagini", side_effect=risposte), \
             mock.patch.object(places_client, "fetch_place_photo",
                               return_value=_jpeg_minimo()) as pagata:
            uscita = foto.raccogli_foto(guide, pois, api_key="finta",
                                        massimo=3, citta="Siena")
        # Tre a pagamento erano il budget e tre sono state comprate: le due
        # gratuite non hanno eroso niente.
        self.assertEqual(pagata.call_count, 3)
        self.assertEqual(sum(1 for v in uscita.values()
                             if v["fonte"] == "wikimedia"), 2)
        self.assertEqual(sum(1 for v in uscita.values()
                             if v["fonte"] == "google"), 3)

    def test_il_nome_della_citta_entra_nella_ricerca(self):
        """«Duomo» da solo su Commons restituisce il duomo sbagliato.

        E' l'unico modo in cui questa funzione puo' produrre una fotografia
        VERA di un posto SBAGLIATO — il difetto peggiore possibile qui,
        perche' non sembra un difetto: sembra una bella foto.
        """
        with mock.patch.object(wikimedia, "cerca_immagini",
                               return_value=[]) as gratis:
            foto.raccogli_foto([_guida("A", "Duomo")], [_poi("A", "Duomo")],
                               citta="Siena")
        self.assertEqual(gratis.call_args.args[0], "Duomo")
        self.assertEqual(gratis.call_args.args[1], "Siena")


class TestIlCronometroDelleFotoGratuite(unittest.TestCase):
    """Il tetto della fonte gratuita e' il tempo, non il denaro.

    Lo scenario Make ha un limite di esecuzione di 300 secondi e due
    esecuzioni vere sono durate 239 e 356 secondi: la seconda ha gia'
    sforato. Venti ricerche lente su Commons basterebbero a far perdere
    l'intero itinerario a un cliente che ha pagato — per delle fotografie
    che erano un di piu'. Fra «bello» e «consegnato» l'ordine e' uno solo.
    """

    def test_scaduto_il_tempo_si_smette_di_cercare_e_il_documento_esce_lo_stesso(self):
        guide = [_guida(f"P{i}", f"Luogo {i}") for i in range(6)]
        pois = [_poi(f"P{i}", f"Luogo {i}") for i in range(6)]
        # Un orologio finto: il tempo salta oltre il budget dopo la seconda
        # lettura, cioe' dopo la prima ricerca.
        istanti = iter([0.0, 1.0, 2.0] + [foto.SECONDI_MASSIMI_LIBERE + 1.0] * 50)
        with mock.patch.object(foto.time, "monotonic",
                               side_effect=lambda: next(istanti)), \
             mock.patch.object(wikimedia, "cerca_immagini",
                               return_value=[]) as gratis, \
             mock.patch.object(places_client, "fetch_place_photo",
                               return_value=None):
            uscita = foto.raccogli_foto(guide, pois, citta="Siena")
        self.assertLess(
            gratis.call_count, 6,
            "il cronometro non ha fermato niente: con una rete lenta questo "
            "e' un itinerario pagato e mai consegnato",
        )
        # E la cosa che conta davvero: il documento esce comunque, illustrato.
        self.assertEqual(len(uscita), 6)
        self.assertTrue(all(v["png"] for v in uscita.values()))


class TestICchiamantiPassanoLaCitta(unittest.TestCase):
    """Una funzione che accetta la citta' e tre chiamanti che non la passano.

    E' il tipo di difetto che non fa fallire niente: il documento esce, le
    foto ci sono, sono solo di un'altra citta'. Il controllo guarda il
    sorgente perche' il guasto vive li' — nel punto di chiamata, non nella
    funzione chiamata.
    """

    def test_tutti_e_tre_i_chiamanti_passano_citta(self):
        import pathlib

        radice = pathlib.Path(__file__).resolve().parent.parent
        for nome in ("service.py", "main.py", "scripts_sample_pdf.py"):
            sorgente = (radice / nome).read_text(encoding="utf-8")
            inizio = sorgente.find("raccogli_foto(")
            self.assertNotEqual(inizio, -1, f"{nome} non chiama piu' raccogli_foto")
            chiamata = sorgente[inizio:inizio + 400]
            self.assertIn(
                "citta=", chiamata,
                f"{nome} chiama raccogli_foto senza dire di quale citta' si "
                f"tratta: le fotografie saranno vere e del posto sbagliato",
            )


class TestLInterruttoreDellaFonteGratuita(unittest.TestCase):
    """Quando Commons non risponde, non risponde per tutti.

    Il difetto che questo interruttore evita non e' visibile in nessun
    documento: e' visibile solo nel cronometro. Venti attrazioni x sei
    secondi di attesa massima fanno due minuti spesi ad aspettare una
    risposta che non arrivera' — dentro uno scenario che ne ha 300 in tutto
    e che ne ha gia' sforati (356 s misurati su un'esecuzione vera). Il
    risultato non e' un documento piu' brutto: e' un cliente che ha pagato
    4,90 € e non riceve niente.
    """

    def setUp(self):
        wikimedia.azzera_interruttore()
        self.addCleanup(wikimedia.azzera_interruttore)

    def test_dopo_due_guasti_di_rete_la_terza_ricerca_non_tocca_la_rete(self):
        import requests as _requests

        guasto = _requests.ConnectionError("nessuna rotta verso l'host")
        with mock.patch.object(wikimedia.requests, "get",
                               side_effect=guasto) as chiamata:
            for _ in range(4):
                self.assertIsNone(wikimedia.cerca_immagine("Duomo", "Siena"))
        self.assertEqual(
            chiamata.call_count, wikimedia.MAX_GUASTI_DI_RETE,
            "la fonte ha continuato a bussare a una porta che non apre: con "
            "venti attrazioni sono minuti di attesa dentro un tetto di 300 "
            "secondi gia' sforato una volta",
        )

    def test_nessun_risultato_non_e_un_guasto_e_non_spegne_niente(self):
        """La differenza che rende l'interruttore utilizzabile.

        Su Commons ci sono milioni di monumenti e quasi nessuna trattoria.
        Se «non trovato» spegnesse la fonte, tre ristoranti di fila
        basterebbero a far sparire le fotografie di tutti i monumenti che
        vengono dopo — e sarebbero proprio quelle che Commons aveva.
        """
        vuota = mock.Mock()
        vuota.raise_for_status = mock.Mock()
        vuota.json = mock.Mock(return_value={"query": {"pages": {}}})
        with mock.patch.object(wikimedia.requests, "get",
                               return_value=vuota) as chiamata:
            for _ in range(5):
                self.assertIsNone(wikimedia.cerca_immagine("Trattoria", "Siena"))
        self.assertEqual(chiamata.call_count, 5)
        self.assertFalse(wikimedia.fonte_spenta())

    def test_una_risposta_buona_riarma_l_interruttore(self):
        """Un guasto isolato non deve costare le fotografie del resto."""
        import requests as _requests

        vuota = mock.Mock()
        vuota.raise_for_status = mock.Mock()
        vuota.json = mock.Mock(return_value={"query": {"pages": {}}})
        risposte = [_requests.ConnectionError("blip"), vuota,
                    _requests.ConnectionError("blip")]
        with mock.patch.object(wikimedia.requests, "get",
                               side_effect=risposte) as chiamata:
            for _ in range(3):
                wikimedia.cerca_immagine("Duomo", "Siena")
        # Se il guasto isolato non fosse stato azzerato dalla risposta buona,
        # il secondo guasto avrebbe fatto scattare l'interruttore.
        self.assertEqual(chiamata.call_count, 3)
        self.assertFalse(wikimedia.fonte_spenta())

    def test_l_interruttore_si_riarma_da_solo_dopo_l_attesa(self):
        """Questo processo serve molte richieste, non una.

        Un'interruzione di rete di trenta secondi non deve lasciare senza
        fotografie tutti gli itinerari del resto della giornata.
        """
        import requests as _requests

        # L'orologio finto e' una scatola che il controllo sposta a mano.
        # Un elenco di istanti prefissati non funzionerebbe: `fonte_spenta()`
        # guarda l'ora solo quando l'interruttore e' gia' scattato, quindi
        # non si sa in anticipo quante volte verra' letta.
        orologio = [0.0]
        with mock.patch.object(wikimedia.time, "monotonic",
                               side_effect=lambda: orologio[0]), \
             mock.patch.object(wikimedia.requests, "get",
                               side_effect=_requests.ConnectionError("giu")) as chiamata:
            for _ in range(3):
                wikimedia.cerca_immagine("Duomo", "Siena")
            self.assertTrue(
                wikimedia.fonte_spenta(),
                "dopo tre guasti di rete l'interruttore doveva essere scattato",
            )
            chiamate_a_freddo = chiamata.call_count

            # Passa l'attesa prevista: la fonte deve riprovare da sola.
            orologio[0] = wikimedia.RIPROVA_DOPO_SECONDI + 1.0
            wikimedia.cerca_immagine("Duomo", "Siena")

        self.assertGreater(
            chiamata.call_count, chiamate_a_freddo,
            "l'interruttore non si e' mai piu' riarmato: una interruzione "
            "di rete di pochi minuti spegnerebbe le fotografie per sempre",
        )
