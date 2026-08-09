"""
DIAGNOSTICA: cosa e' acceso in produzione, senza pagare — task #185, 2026-08-03.

Segnalazione di Lorenzo: «il link di tally non funziona ancora».

Il collegamento era rotto per un motivo banale e istruttivo: la variabile
`FEEDBACK_FORM_URL` non era impostata sul server. Il codice era giusto, i
controlli erano verdi, il documento usciva regolarmente — semplicemente senza
quel pezzo. E l'unico modo di accorgersene era generare un itinerario vero:
un euro e mezzo e quattro minuti per scoprire una variabile vuota.

E' il difetto che questo progetto produce piu' spesso, per una ragione di
struttura: ogni sezione e' best-effort per scelta, quindi un pezzo che manca
non fa rumore. Ci sono sei variabili opzionali, cioe' sei modi di consegnare
in silenzio un prodotto piu' povero di quello che si crede di avere online.

`GET /v1/diagnostica` li rende visibili tutti in una volta. Questi controlli
difendono le tre cose che la rendono utile invece che decorativa:

  1. che sia AUTENTICATA — e' la mappa di dove il servizio e' scoperto;
  2. che distingua «manca» da «c'e' ma non puo' funzionare» — sono due
     difetti diversi che si sistemano in due modi diversi, ed e' esattamente
     la coppia che Lorenzo ha incontrato;
  3. che non restituisca MAI i valori — meta' di quelle variabili sono
     segreti, e una rotta che stampa il proprio segreto lo regala al primo
     log condiviso per sbaglio.
"""
import os
import unittest
from unittest.mock import patch

import service


CHIAVE = "chiave-di-prova-per-i-controlli"

# Valori finti ma della forma giusta. Nessuno di questi e' un segreto vero:
# stanno qui perche' la rotta va provata anche da configurata, e i controlli
# sul fatto che i valori non escano non misurerebbero niente se i valori
# fossero vuoti.
AMBIENTE_COMPLETO = {
    "SERVICE_API_KEY": CHIAVE,
    "FEEDBACK_FORM_URL": "https://tally.so/r/w4b9Qp",
    "FEEDBACK_REF_SECRET": "frase-lunga-inventata-per-la-prova",
    # L'ospitalita' vuole DUE variabili: l'indirizzo pubblico e la cartella
    # su disco. Metterne una sola qui e' il modo piu' facile di scrivere un
    # controllo che passa mentre il prodotto non funziona.
    "PUBLIC_BASE_URL": "https://esempio-di-servizio.onrender.com",
    "PUBLIC_FILES_DIR": "/tmp/documenti-di-prova",
    "ALERT_WEBHOOK_URL": "https://hooks.esempio.it/servizi/abc123",
    "CHECKLIST_SHEET_TEMPLATE_URL": "https://docs.google.com/spreadsheets/d/xyz",
    "GOOGLE_MAPS_KEY": "chiave-google-finta",
}

SOLO_CHIAVE = {"SERVICE_API_KEY": CHIAVE}


def _client():
    service.app.config["TESTING"] = True
    return service.app.test_client()


def _chiedi(ambiente, chiave=CHIAVE):
    """La risposta della rotta con quell'ambiente. `clear=True` di proposito:
    senza, le variabili della macchina su cui girano i controlli entrerebbero
    nella prova e il risultato dipenderebbe da chi la esegue."""
    with patch.dict(os.environ, ambiente, clear=True):
        intestazioni = {"X-Service-Key": chiave} if chiave is not None else {}
        return _client().get("/v1/diagnostica", headers=intestazioni)


class TestLaRottaNonERegalataAChiunque(unittest.TestCase):
    """E' l'elenco dei punti scoperti del servizio.

    In questo file l'autenticazione NON e' globale: si controlla dentro ogni
    funzione, quindi una rotta nuova nasce pubblica e lo resta finche' non ci
    si mette la riga. E' successo abbastanza spesso, in progetti come questo,
    da meritare un controllo suo.
    """

    def test_senza_chiave_non_risponde(self):
        self.assertEqual(_chiedi(AMBIENTE_COMPLETO, chiave=None).status_code, 401)

    def test_con_la_chiave_sbagliata_non_risponde(self):
        self.assertEqual(
            _chiedi(AMBIENTE_COMPLETO, chiave="chiave-sbagliata").status_code, 401
        )

    def test_con_la_chiave_giusta_risponde(self):
        self.assertEqual(_chiedi(AMBIENTE_COMPLETO).status_code, 200)


class TestDiceCosaMancaEInQuantiSono(unittest.TestCase):

    def test_con_tutto_configurato_non_manca_niente(self):
        dati = _chiedi(AMBIENTE_COMPLETO).get_json()
        self.assertEqual(dati["variabili_mancanti"], [])
        quanti, su = dati["pezzi_attivi"].split("/")
        self.assertEqual(quanti, su)

    def test_senza_niente_configurato_li_elenca_tutti(self):
        dati = _chiedi(SOLO_CHIAVE).get_json()
        self.assertIn("FEEDBACK_FORM_URL", dati["variabili_mancanti"])
        self.assertIn("PUBLIC_BASE_URL", dati["variabili_mancanti"])
        self.assertIn("PUBLIC_FILES_DIR", dati["variabili_mancanti"])
        self.assertTrue(dati["pezzi_attivi"].startswith("0/"))

    def test_il_conteggio_e_l_elenco_dicono_la_stessa_cosa(self):
        """Due numeri che si contraddicono sono peggio di un numero solo."""
        for ambiente in (AMBIENTE_COMPLETO, SOLO_CHIAVE,
                         dict(SOLO_CHIAVE, PUBLIC_BASE_URL="https://x.onrender.com")):
            with self.subTest(ambiente=sorted(ambiente)):
                dati = _chiedi(ambiente).get_json()
                attivi, totale = (int(n) for n in dati["pezzi_attivi"].split("/"))
                self.assertEqual(totale, len(dati["dettaglio"]))
                # Il conto va rifatto sul dettaglio, non solo confrontato con
                # l'elenco delle variabili: il difetto vero era che i due
                # numeri venivano da unita' diverse (pezzi meno variabili) e
                # con niente configurato usciva "-1/6". Un controllo che
                # guarda solo l'elenco lo lascia passare, perche' l'elenco
                # era giusto: sbagliato era il numero davanti.
                self.assertEqual(
                    attivi, sum(1 for v in dati["dettaglio"] if v["attivo"]),
                    "il numero in cima non conta i pezzi accesi elencati sotto",
                )
                self.assertGreaterEqual(attivi, 0, "conteggio impossibile")
                # Un pezzo spento puo' avere piu' di una variabile mancante
                # (l'ospitalita' ne ha due), quindi i due numeri non sono
                # uguali: l'elenco non e' mai piu' corto del conto degli
                # spenti, ed e' vuoto se e solo se non manca niente.
                spenti = totale - attivi
                self.assertGreaterEqual(len(dati["variabili_mancanti"]), spenti)
                self.assertEqual(spenti == 0, dati["variabili_mancanti"] == [])

    def test_ogni_voce_dice_anche_cosa_perde_il_cliente_e_come_si_sistema(self):
        """Un "false" da solo non aiuta chi la variabile la deve digitare.

        La legge Lorenzo, che non e' uno sviluppatore. Se la risposta non dice
        cosa succede al cliente e cosa fare, non e' una diagnosi: e' un'altra
        cosa da chiedere a me.
        """
        for voce in _chiedi(SOLO_CHIAVE).get_json()["dettaglio"]:
            with self.subTest(voce=voce["variabili"]):
                self.assertTrue(voce["senza_questo"].strip())
                self.assertTrue(voce["come_si_sistema"].strip())
                self.assertIn("attivo", voce)


class TestDistingueQuelloCheMancaDaQuelloCheEsbagliato(unittest.TestCase):
    """La coppia di difetti che Lorenzo ha incontrato davvero.

    «Non l'ho impostata» e «l'ho impostata ma porta al 404 di Tally» danno
    tutti e due un capitolo senza link, e si sistemano in due modi diversi.
    Una rotta che li appiattisce su un booleano manda a cercare nel posto
    sbagliato proprio chi ha appena incollato qualcosa.
    """

    def test_il_segnaposto_di_esempio_non_conta_come_configurato(self):
        dati = _chiedi(dict(SOLO_CHIAVE,
                            FEEDBACK_FORM_URL="https://tally.so/r/ESEMPIO")).get_json()
        modulo = [v for v in dati["dettaglio"]
                  if "FEEDBACK_FORM_URL" in v["variabili"]][0]
        self.assertFalse(modulo["attivo"])
        self.assertIn("NON utilizzabile", modulo["stato"])

    def test_un_indirizzo_senza_schema_viene_detto_sbagliato_non_assente(self):
        dati = _chiedi(dict(SOLO_CHIAVE,
                            FEEDBACK_FORM_URL="tally.so/r/w4b9Qp")).get_json()
        modulo = [v for v in dati["dettaglio"]
                  if "FEEDBACK_FORM_URL" in v["variabili"]][0]
        self.assertFalse(modulo["attivo"])
        self.assertIn("NON utilizzabile", modulo["stato"])

    def test_la_variabile_davvero_assente_si_chiama_non_configurato(self):
        dati = _chiedi(SOLO_CHIAVE).get_json()
        modulo = [v for v in dati["dettaglio"]
                  if "FEEDBACK_FORM_URL" in v["variabili"]][0]
        self.assertEqual(modulo["stato"], "non configurato")

    def test_una_url_vera_risulta_attiva(self):
        dati = _chiedi(AMBIENTE_COMPLETO).get_json()
        modulo = [v for v in dati["dettaglio"]
                  if "FEEDBACK_FORM_URL" in v["variabili"]][0]
        self.assertTrue(modulo["attivo"])
        self.assertEqual(modulo["stato"], "attivo")


class TestNessunValoreEsceDaQui(unittest.TestCase):
    """Il controllo che vale piu' di tutti gli altri messi insieme.

    `FEEDBACK_REF_SECRET` deriva i codici delle recensioni, `ALERT_WEBHOOK_URL`
    e' a sua volta una credenziale, `SERVICE_API_KEY` apre tutto il servizio.
    Aggiungere il valore accanto al nome, un giorno, "per comodita' di
    controllo", sarebbe la cosa piu' naturale del mondo e regalerebbe quei
    segreti al primo screenshot condiviso.
    """

    def test_nessuna_delle_variabili_compare_nel_corpo_della_risposta(self):
        corpo = _chiedi(AMBIENTE_COMPLETO).get_data(as_text=True)
        for nome, valore in AMBIENTE_COMPLETO.items():
            with self.subTest(variabile=nome):
                self.assertNotIn(valore, corpo,
                                 f"il valore di {nome} esce dalla diagnostica")

    def test_escono_i_nomi_delle_variabili_non_il_loro_contenuto(self):
        """Il nome serve: e' quello che Lorenzo cerca nel pannello di Render."""
        corpo = _chiedi(AMBIENTE_COMPLETO).get_data(as_text=True)
        self.assertIn("FEEDBACK_FORM_URL", corpo)
        self.assertIn("PUBLIC_BASE_URL", corpo)


class TestNonPuoRompereIlServizio(unittest.TestCase):
    """Una rotta di diagnosi che cade e' il peggior tipo di rotta di diagnosi:
    si guarda esattamente quando qualcosa gia' non va."""

    def test_valori_malformati_non_fanno_cadere_la_rotta(self):
        risposta = _chiedi(dict(
            SOLO_CHIAVE,
            FEEDBACK_FORM_URL="https://[non-chiuso",
            PUBLIC_BASE_URL="   ",
            ALERT_WEBHOOK_URL="\\n",
        ))
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("dettaglio", risposta.get_json())

    def test_la_rotta_e_dichiarata_anche_nell_elenco_in_cima_al_file(self):
        """L'elenco degli endpoint e' la prima cosa che si legge.

        Una rotta che c'e' e non e' elencata e' una rotta che nessuno usa; un
        elenco che mente su un punto smette di essere creduto su tutti.
        """
        import pathlib

        sorgente = (pathlib.Path(service.__file__)).read_text(encoding="utf-8")
        apertura = sorgente.find('"""')
        chiusura = sorgente.find('"""', apertura + 3)
        self.assertGreater(chiusura, apertura, "il file non ha piu' un cappello")
        intestazione = sorgente[apertura:chiusura]
        self.assertIn("/v1/diagnostica", intestazione)

    def test_le_istruzioni_di_installazione_spiegano_come_chiamarla(self):
        """Una rotta che esiste e che Lorenzo non sa di avere non serve.

        Questa non e' una rotta per sviluppatori: e' l'unico modo che ha
        lui, che sviluppatore non e', di sapere cosa ha dimenticato di
        digitare sul pannello di Render senza pagare un itinerario per
        scoprirlo. Se non e' scritta in `DEPLOY.md` — il foglio che apre
        quando tocca le variabili — non verra' mai chiamata, e il difetto
        di partenza («l'ho impostata e non si vede niente») tornera'
        identico al prossimo giro.
        """
        import pathlib

        radice = pathlib.Path(service.__file__).resolve().parent
        istruzioni = (radice / "DEPLOY.md").read_text(encoding="utf-8")
        self.assertIn("/v1/diagnostica", istruzioni,
                      "le istruzioni non dicono che la diagnostica esiste")
        # Serve anche il COME: la rotta e' autenticata, e senza l'intestazione
        # risponde 401 — cioe' sembra rotta proprio a chi la prova la prima
        # volta.
        posizione = istruzioni.find("/v1/diagnostica")
        self.assertIn("X-Service-Key", istruzioni[posizione:posizione + 900],
                      "le istruzioni non dicono che va chiamata con la chiave")


if __name__ == "__main__":
    unittest.main()
