"""L'alloggio che il cliente ha già prenotato non si sostituisce.

PERCHE' QUESTO FILE ESISTE

Primo fascicolo VENDUTO, 19 agosto, Singapore. Il cliente aveva prenotato e lo
aveva scritto. Il documento ha costruito l'intera giornata attorno a un'altra
struttura, dall'altra parte della citta', e lo ha dichiarato in chiaro a
pagina 4:

    «i dati verificati indicano come struttura di riferimento l'Aloft by
    Marriott Singapore Novena, diversa dal nome "MI Rochor" indicato nelle
    note: abbiamo utilizzato l'unica struttura realmente presente nei dati
    forniti»

Il giudizio di Lorenzo, in maiuscolo: «COMPLETAMENTE CANNATO L'ALBERGO PUR
AVENDO INCAMERATO L'INFORMAZIONE SULL'HOTEL GIA' SCELTO, ERRORE GRAVISSIMO
CHE SBALLA TUTTO IL PERCORSO».

## Non era il modello: era l'impianto

Il modello ha fatto la cosa giusta con i dati che aveva. L'alloggio veniva
SEMPRE scelto da `liteapi_client.select_anchor_hotel()` cercando per
coordinate della citta', e il nome scritto dal cliente arrivava soltanto come
testo libero dentro `raw_notes`: nessuna riga di codice lo leggeva.

E non e' un difetto di una riga di testo. L'alloggio e' l'ANCORA: e' il centro
attorno a cui si cercano i ristoranti, da cui partono e a cui tornano le
giornate. Sbagliarlo sposta tutto il resto.

## Cosa difendono i controlli qui sotto

1. il campo esiste e arriva dal modulo, in tutte le forme in cui un modulo lo
   puo' mandare;
2. quando c'e', la struttura del cliente diventa l'unica in elenco e il centro
   del viaggio — non si cerca nessuna alternativa;
3. quando non c'e', tutto resta identico a prima;
4. se il geocoding fallisce non si perde il viaggio: si perde la precisione
   del pallino, non la struttura giusta;
5. il documento smette di proporre alternative a una scelta gia' fatta.
"""

import unittest
from unittest import mock

from src import pdf_renderer, pipeline, triage
from src.schemas import Trip


def _modulo(**extra) -> dict:
    """Il pacchetto che arriva dal modulo Tally, forma minima."""
    base = {
        "email": "cliente@esempio.it",
        "scopo": "relax e visite",
        "destinazione": "Singapore",
        "arrivo": "2026-08-23",
        "partenza": "2026-08-26",
        "budget": 300,
        "note": "niente di particolare",
    }
    base.update(extra)
    return base


class TestILCAMPOARRIVADALMODULO(unittest.TestCase):
    """Punto 1: il dato ha finalmente un posto suo."""

    def test_il_nome_e_l_indirizzo_arrivano_nel_viaggio(self):
        viaggio = triage.normalize_raw_input(
            _modulo(alloggio="MI Hotel Rochor",
                    alloggio_indirizzo="10 Rochor Rd, Singapore"))
        self.assertEqual("MI Hotel Rochor", viaggio.alloggio_nome)
        self.assertEqual("10 Rochor Rd, Singapore", viaggio.alloggio_indirizzo)
        self.assertTrue(viaggio.alloggio_gia_prenotato())

    def test_senza_il_campo_il_viaggio_e_quello_di_sempre(self):
        viaggio = triage.normalize_raw_input(_modulo())
        self.assertEqual("", viaggio.alloggio_nome)
        self.assertFalse(viaggio.alloggio_gia_prenotato())

    def test_il_nome_basta_anche_senza_indirizzo(self):
        """Un cliente che scrive solo «Hotel Rochor» ha comunque deciso dove
        dorme: costruirgli il viaggio attorno a un altro albergo sarebbe lo
        stesso errore, con una scusa migliore."""
        viaggio = triage.normalize_raw_input(_modulo(alloggio="Hotel Rochor"))
        self.assertTrue(viaggio.alloggio_gia_prenotato())

    def test_un_campo_scritto_male_non_fa_saltare_il_viaggio(self):
        """I moduli mandano quello che vogliono: una lista, un numero, un
        campo saltato. Un campo facoltativo malformato non deve impedire a
        un cliente che ha pagato di ricevere il suo itinerario."""
        for valore in ([" Hotel Rochor "], None, 12345, {"a": 1}):
            with self.subTest(valore=valore):
                viaggio = triage.normalize_raw_input(_modulo(alloggio=valore))
                self.assertIsInstance(viaggio.alloggio_nome, str)
        self.assertEqual(
            "Hotel Rochor",
            triage.normalize_raw_input(
                _modulo(alloggio=[" Hotel Rochor "])).alloggio_nome)

    def test_gli_spazi_di_troppo_non_contano_come_prenotazione(self):
        viaggio = triage.normalize_raw_input(_modulo(alloggio="   "))
        self.assertFalse(viaggio.alloggio_gia_prenotato())


class _Impostazioni:
    google_maps_key = "CHIAVE-FINTA"
    liteapi_key = "CHIAVE-FINTA"


def _viaggio(**extra) -> Trip:
    return triage.normalize_raw_input(_modulo(**extra))


class TestLASTRUTTURADELCLIENTEDIVENTALANCORA(unittest.TestCase):
    """Punti 2, 3 e 4: quello che cambia davvero nell'itinerario."""

    GEO_CITTA = {"lat": 1.3521, "lng": 103.8198, "location_type": "APPROXIMATE",
                 "formatted_address": "Singapore"}
    GEO_ALBERGO = {"lat": 1.3039, "lng": 103.8554, "location_type": "ROOFTOP",
                   "formatted_address": "10 Rochor Rd, Singapore"}

    def test_diventa_l_unica_struttura_e_il_centro_del_viaggio(self):
        viaggio = _viaggio(alloggio="MI Hotel Rochor",
                           alloggio_indirizzo="10 Rochor Rd")
        with mock.patch.object(pipeline.geocoding, "geocode_full",
                               return_value=self.GEO_ALBERGO):
            struttura = pipeline._alloggio_del_cliente(
                viaggio, _Impostazioni(), self.GEO_CITTA)
        self.assertIsNotNone(struttura)
        self.assertEqual("MI Hotel Rochor", struttura.name)
        self.assertEqual(pipeline.ID_ALLOGGIO_DEL_CLIENTE, struttura.id)
        self.assertAlmostEqual(self.GEO_ALBERGO["lat"], struttura.lat)
        self.assertAlmostEqual(self.GEO_ALBERGO["lng"], struttura.lng)
        self.assertIn("gia_prenotato_dal_cliente", struttura.tags)

    def test_si_cerca_col_nome_l_indirizzo_e_la_citta(self):
        """Il nome da solo, su una catena internazionale, cade in un altro
        continente; l'indirizzo da solo perde il nome nel documento."""
        viaggio = _viaggio(alloggio="Aloft", alloggio_indirizzo="16 Ah Hood Rd")
        with mock.patch.object(pipeline.geocoding, "geocode_full",
                               return_value=self.GEO_ALBERGO) as cercato:
            pipeline._alloggio_del_cliente(viaggio, _Impostazioni(), self.GEO_CITTA)
        query = cercato.call_args[0][0]
        for pezzo in ("Aloft", "16 Ah Hood Rd", "Singapore"):
            self.assertIn(pezzo, query)

    def test_niente_prezzo_inventato(self):
        """Il cliente il suo prezzo lo conosce: stimarlo — o mostrargli il
        listino di stanotte — e' l'unico modo di sbagliare un dato che non
        avevamo bisogno di dare."""
        viaggio = _viaggio(alloggio="MI Hotel Rochor")
        with mock.patch.object(pipeline.geocoding, "geocode_full",
                               return_value=self.GEO_ALBERGO):
            struttura = pipeline._alloggio_del_cliente(
                viaggio, _Impostazioni(), self.GEO_CITTA)
        self.assertIsNone(struttura.price_night_eur)
        self.assertEqual("", struttura.affiliate_url)

    def test_se_il_geocoding_non_riesce_si_tiene_la_struttura(self):
        """Meglio l'alloggio giusto nel posto approssimativo che l'alloggio
        sbagliato nel posto preciso. E soprattutto: nessuna eccezione — un
        itinerario non consegnato e' un rimborso."""
        viaggio = _viaggio(alloggio="MI Hotel Rochor")
        with mock.patch.object(pipeline.geocoding, "geocode_full",
                               side_effect=RuntimeError("rete giu'")):
            struttura = pipeline._alloggio_del_cliente(
                viaggio, _Impostazioni(), self.GEO_CITTA)
        self.assertIsNotNone(struttura)
        self.assertEqual("MI Hotel Rochor", struttura.name)
        self.assertAlmostEqual(self.GEO_CITTA["lat"], struttura.lat)

    def test_senza_prenotazione_non_si_costruisce_niente(self):
        with mock.patch.object(pipeline.geocoding, "geocode_full") as cercato:
            struttura = pipeline._alloggio_del_cliente(
                _viaggio(), _Impostazioni(), self.GEO_CITTA)
        self.assertIsNone(struttura)
        cercato.assert_not_called()


class TestILDOCUMENTONONPROPONEALTERNATIVE(unittest.TestCase):
    """Punto 5: il capitolo «Il tuo alloggio» cambia mestiere."""

    def test_la_struttura_del_cliente_si_riconosce_dal_suo_segno(self):
        self.assertTrue(pdf_renderer._alloggio_e_del_cliente(
            [{"name": "X", "tags": ["gia_prenotato_dal_cliente"]}]))
        self.assertFalse(pdf_renderer._alloggio_e_del_cliente(
            [{"name": "X", "tags": ["centrale"]}]))

    def test_dati_di_forma_imprevista_non_fanno_saltare_la_stampa(self):
        for strano in (None, [], [None], ["stringa"], [{"tags": "non una lista"}]):
            with self.subTest(dati=strano):
                self.assertFalse(pdf_renderer._alloggio_e_del_cliente(strano))

    def test_il_prompt_dichiara_il_vincolo(self):
        """Il vincolo deve stare anche nel prompt: il codice sceglie la
        struttura, ma e' il modello a scrivere le giornate, e senza istruzione
        potrebbe comunque commentare la scelta o proporne altre."""
        from src.claude_engine import load_system_prompt

        prompt = load_system_prompt()
        self.assertIn("alloggio_nome", prompt)
        self.assertIn(pipeline.ID_ALLOGGIO_DEL_CLIENTE, prompt)


if __name__ == "__main__":
    unittest.main()


class TestLARICERCASISALTADELTUTTO(unittest.TestCase):
    """La prova che il vincolo agisce PRIMA della ricerca, non dopo.

    Sembra un dettaglio e non lo e': se la ricerca girasse comunque e poi si
    sostituisse il risultato, il documento sarebbe giusto ma il viaggio no —
    i ristoranti vengono cercati attorno all'ancora, e l'ancora si decide
    esattamente li'. Oltre a questo si pagherebbe una chiamata a un fornitore
    per buttarne via il risultato.
    """

    def test_la_struttura_del_cliente_si_decide_prima_di_cercare(self):
        import inspect

        sorgente = inspect.getsource(pipeline.run_live_from_raw)
        self.assertIn("alloggio_gia_prenotato()", sorgente)
        decisione = sorgente.index("alloggio_del_cliente = _alloggio_del_cliente")
        ricerca = sorgente.index("search_hotels_by_geocode")
        self.assertLess(decisione, ricerca,
                        "la ricerca degli alberghi gira prima di guardare se "
                        "il cliente ha gia' prenotato")

    def test_il_centro_del_viaggio_diventa_l_alloggio(self):
        """E' la riga che cambia l'itinerario invece del solo testo: da li'
        parte la ricerca dei ristoranti e da li' partono le giornate."""
        import inspect

        sorgente = inspect.getsource(pipeline.run_live_from_raw)
        pezzo = sorgente.split("if alloggio_del_cliente is not None:", 1)[1]
        pezzo = pezzo.split("else:", 1)[0]
        self.assertIn("lat, lng = alloggio_del_cliente.lat", pezzo)
        self.assertIn("hotels = [alloggio_del_cliente]", pezzo)
