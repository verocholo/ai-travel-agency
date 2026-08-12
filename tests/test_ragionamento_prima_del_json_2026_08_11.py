"""Il ragionamento del modello non fa piu' perdere l'itinerario (task #200).

PERCHE' QUESTO FILE ESISTE

11 agosto 2026, dal servizio in produzione, parola per parola:

    «il modello non ha prodotto un itinerario utilizzabile (nessuna giornata)
    — Output di Claude non è JSON valido: Expecting value: line 1 column 1
    (char 0)»

con `token_out: 35445`. Cioe': il modello aveva scritto trentacinquemila
token, e il primo carattere non era una graffa.

Non era un errore del modello. Il prompt gli **chiede** di ragionare a voce
alta in uno `<scratchpad>` prima di rispondere, ed e' quel ragionamento a
tenere alta la qualita' dell'itinerario. Il lettore invece pretendeva che la
risposta fosse SOLO l'oggetto JSON, dal primo carattere.

## Perche' e' saltato fuori proprio adesso

Il giorno prima il budget di scrittura era 32.000 token e le risposte si
troncavano. L'abbiamo alzato a 64.000 per riparare quel guasto — e il modello,
finalmente con spazio, ha ragionato davvero. La riparazione precedente ha reso
visibile il difetto successivo, che era li' da sempre e aspettava solo di
avere abbastanza aria.

## La riparazione sbagliata, e perche' e' stata scartata

Nel codice esiste gia' `use_prefill`, che mette una graffa in bocca al modello
e lo obbliga a partire dal JSON. Risolve il parsing in una riga — e gli toglie
il ragionamento, cioe' paga con la qualita' del documento. E' lo stesso
baratto rifiutato per i troncamenti: «io voglio tenere alta la qualita'».

La riparazione giusta e' che sia il LETTORE a saper trovare l'oggetto dentro
la risposta, invece di pretendere che la risposta sia solo l'oggetto.

## Perche' non basta «dalla prima graffa all'ultima»

Il ragionamento contiene graffe sue («se {questo} allora quello»), e una
stringa dentro l'itinerario puo' contenerne che non aprono niente («orario:
10:00 {chiuso}»). Le prove qui sotto fissano tutti e due i casi: sono la
differenza fra un lettore che funziona e uno che funziona finche' nessuno
scrive una parentesi.
"""

import unittest

from src.validator import ParseError, parse_claude_output


SCRATCHPAD = (
    "<scratchpad>\n"
    "Verifico l'incastro temporale. Se {la Torre} chiude alle 19:00 allora la\n"
    "cena va spostata. Nota: \"vegetariana\" e' un vincolo forte.\n"
    "</scratchpad>\n\n"
)


class TestIlRagionamentoNonNascondePiuLItinerario(unittest.TestCase):

    def test_il_caso_vero_dell_undici_agosto(self):
        """Ragionamento prima, oggetto dopo: si legge l'oggetto."""
        grezzo = SCRATCHPAD + '{"days": [{"day": 1, "title": "Arrivo"}]}'
        letto = parse_claude_output(grezzo)
        self.assertEqual(len(letto["days"]), 1)
        self.assertEqual(letto["days"][0]["title"], "Arrivo")

    def test_le_graffe_dentro_il_ragionamento_non_ingannano(self):
        """Il difetto che una versione ingenua avrebbe avuto.

        `{la Torre}` compare PRIMA dell'itinerario ed e' la prima graffa del
        testo. Un lettore che prendesse la prima graffa e basta leggerebbe
        quella, fallirebbe, e direbbe che l'itinerario non c'e'.
        """
        letto = parse_claude_output(SCRATCHPAD + '{"days": [1, 2]}')
        self.assertEqual(letto["days"], [1, 2])

    def test_le_graffe_dentro_una_stringa_dell_itinerario_non_lo_troncano(self):
        # «10:00 {chiuso}» dentro un valore: se si contassero le graffe senza
        # distinguere le stringhe, l'oggetto risulterebbe chiuso troppo presto
        # e uscirebbe un itinerario tagliato a meta' — peggio di nessuno,
        # perche' sembrerebbe valido.
        grezzo = SCRATCHPAD + '{"days": [{"nota": "orario 10:00 {chiuso} oggi"}]}'
        self.assertEqual(parse_claude_output(grezzo)["days"][0]["nota"],
                         "orario 10:00 {chiuso} oggi")

    def test_una_virgoletta_scappata_non_confonde_il_conteggio(self):
        grezzo = SCRATCHPAD + '{"days": [{"nota": "il \\"gelato\\" di {via}"}]}'
        self.assertIn("gelato", parse_claude_output(grezzo)["days"][0]["nota"])

    def test_il_testo_dopo_l_oggetto_non_da_fastidio(self):
        grezzo = SCRATCHPAD + '{"days": []}\n\nSpero vada bene, fammi sapere.'
        self.assertEqual(parse_claude_output(grezzo)["days"], [])

    def test_una_risposta_gia_pulita_si_legge_come_sempre(self):
        # La strada di prima non deve cambiare di una virgola: e' quella che
        # ha funzionato in ogni vendita fino a ieri.
        self.assertEqual(parse_claude_output('{"days": [1]}')["days"], [1])

    def test_la_fence_markdown_continua_a_funzionare(self):
        grezzo = '```json\n{"days": [1]}\n```'
        self.assertEqual(parse_claude_output(grezzo)["days"], [1])

    def test_senza_nessun_oggetto_l_errore_resta_leggibile(self):
        # Se davvero non c'e' niente da leggere, il messaggio deve restare
        # quello di prima: un lettore piu' tollerante non deve trasformare
        # un fallimento chiaro in un silenzio.
        for testo in ("nessun oggetto qui", "", "<scratchpad>solo pensieri</scratchpad>"):
            with self.subTest(testo=testo[:20]):
                with self.assertRaises(ParseError):
                    parse_claude_output(testo)

    def test_un_array_in_cima_non_viene_scambiato_per_un_itinerario(self):
        # `[1,2,3]` e' JSON validissimo e non e' un itinerario. Questo
        # controllo esisteva gia' e deve sopravvivere alla tolleranza nuova.
        with self.assertRaises(ParseError):
            parse_claude_output("[1, 2, 3]")


class TestIlRagionamentoResta(unittest.TestCase):
    """La riparazione non deve costare la qualita'.

    C'era una scorciatoia: `use_prefill`, che forza il modello a cominciare
    dalla graffa e quindi gli impedisce di ragionare. Avrebbe risolto il
    parsing pagando con il documento. Questo controllo esiste perche' quella
    scorciatoia non venga presa la prossima volta che qualcuno ha fretta.
    """

    def test_la_scorciatoia_che_toglie_il_ragionamento_resta_spenta(self):
        import inspect

        from src import claude_engine

        firma = inspect.signature(claude_engine.call_claude)
        self.assertIs(
            firma.parameters["use_prefill"].default, False,
            "il prefill forza il JSON dal primo carattere e toglie al modello "
            "lo spazio per ragionare: risolve il parsing pagando con la "
            "qualita' dell'itinerario")


if __name__ == "__main__":
    unittest.main()
