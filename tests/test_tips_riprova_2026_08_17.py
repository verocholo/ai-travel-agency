"""Un secondo tentativo prima di arrendersi (task #229).

PERCHE' QUESTO FILE ESISTE

Secondo incidente identico al primo (1 agosto): un cliente ha ricevuto tre
righe di consigli generici al posto di quattordici sezioni, e i piani B
sono spariti del tutto. La prima volta la causa era il troncamento a
max_tokens=6000 (già corretto, alzato a 16000). Questa volta il tetto non
c'entra: quello che mancava era un secondo tentativo — una singola chiamata
al modello che fallisce per una ragione transitoria (rete, sovraccarico
momentaneo, un output che quella particolare generazione non è riuscita a
rendere JSON valido) degradava IMMEDIATAMENTE, senza che nessuno avesse mai
riprovato.

`generate_architect_tips` ora tenta fino a `tentativi_massimi` (default 2)
volte prima di rilanciare l'errore al chiamante — che a sua volta, se
anche il secondo tentativo fallisce, continua a degradare con la lista
base (comportamento invariato, e già testato altrove:
`tests/test_collaudo_2026_08_01.py::TestDegradoRumoroso`).
"""

import unittest
from unittest.mock import MagicMock, patch

from src import tips_generator


def _trip():
    from src.schemas import Trip

    return Trip(email="a@b.it", destination="Siena", date_start="2026-09-01",
                date_end="2026-09-03", duration_days=3, budget_eur=800,
                budget_mode="LIMITED", objective_function="BALANCED")


def _itinerario():
    return {"days": [{"day": 1, "blocks": []}]}


def _risposta_valida():
    risposta = MagicMock()
    risposta.stop_reason = "end_turn"
    risposta.usage = None
    blocco = MagicMock()
    blocco.text = (
        '{"sections": [{"category_id": "biglietti_e_prenotazioni", '
        '"tips": ["Prenota in anticipo."]}], "rain_plans": []}'
    )
    risposta.content = [blocco]
    return risposta


class TestUnSecondoTentativoPrimaDiArrendersi(unittest.TestCase):

    def _con_client_finto(self, side_effect):
        client_finto = MagicMock()
        client_finto.messages.create.side_effect = side_effect
        classe_finta = MagicMock(return_value=client_finto)
        return patch("anthropic.Anthropic", classe_finta), client_finto

    def test_il_primo_tentativo_fallito_non_arriva_al_chiamante_se_il_secondo_riesce(self):
        """Il caso vero: la prima chiamata si spezza (rete, sovraccarico), la
        seconda va a buon fine — il chiamante non deve vedere nessun errore."""
        errore_di_rete = ConnectionError("timeout verso Anthropic")
        patcher, client_finto = self._con_client_finto(
            [errore_di_rete, _risposta_valida()])
        with patcher:
            risultato = tips_generator.generate_architect_tips(
                _trip(), _itinerario(), api_key="finta")
        self.assertEqual(2, client_finto.messages.create.call_count,
                         "doveva riprovare esattamente una volta")
        self.assertTrue(risultato["sections"])

    def test_se_falliscono_entrambi_i_tentativi_lerrore_arriva_al_chiamante(self):
        """Cosi' il ripiego rumoroso di `pdf_extras.build_pdf_sections`
        (già testato altrove) continua a funzionare: deve ricevere
        DAVVERO un errore quando la generazione non riesce."""
        errore = RuntimeError("l'API non risponde")
        patcher, client_finto = self._con_client_finto([errore, errore])
        with patcher:
            with self.assertRaises(RuntimeError):
                tips_generator.generate_architect_tips(
                    _trip(), _itinerario(), api_key="finta")
        self.assertEqual(2, client_finto.messages.create.call_count)

    def test_di_default_i_tentativi_sono_due_non_di_piu(self):
        """[Deliberatamente basso — vedi il commento nel codice.] Un terzo
        tentativo costerebbe tempo dentro il tetto dei 300 secondi per
        chiamata che tutta la pipeline Make rispetta, per un guadagno
        marginale: se due tentativi falliscono entrambi, il problema quasi
        certamente non è transitorio."""
        errore = RuntimeError("guasto persistente")
        patcher, client_finto = self._con_client_finto(
            [errore, errore, _risposta_valida()])
        with patcher:
            with self.assertRaises(RuntimeError):
                tips_generator.generate_architect_tips(
                    _trip(), _itinerario(), api_key="finta")
        self.assertEqual(2, client_finto.messages.create.call_count,
                         "non deve arrivare al terzo tentativo, mai chiamato "
                         "in questa prova")

    def test_il_primo_tentativo_riuscito_non_chiama_una_seconda_volta(self):
        """Il caso normale, quello di sempre: nessun costo aggiunto quando
        tutto va bene al primo colpo."""
        patcher, client_finto = self._con_client_finto([_risposta_valida()])
        with patcher:
            tips_generator.generate_architect_tips(
                _trip(), _itinerario(), api_key="finta")
        self.assertEqual(1, client_finto.messages.create.call_count)

    def test_il_troncamento_a_max_tokens_viene_ritentato_anche_lui(self):
        """Il troncamento non è per forza deterministico — la stessa
        richiesta può non troncarsi al secondo tentativo, anche a parità
        di max_tokens (la generazione non è identica a ogni chiamata).
        Deve rientrare nello stesso meccanismo di riprova."""
        risposta_troncata = MagicMock()
        risposta_troncata.stop_reason = "max_tokens"
        risposta_troncata.usage = None
        blocco_troncato = MagicMock()
        blocco_troncato.text = '{"sections": ['
        risposta_troncata.content = [blocco_troncato]

        patcher, client_finto = self._con_client_finto(
            [risposta_troncata, _risposta_valida()])
        with patcher:
            risultato = tips_generator.generate_architect_tips(
                _trip(), _itinerario(), api_key="finta")
        self.assertEqual(2, client_finto.messages.create.call_count)
        self.assertTrue(risultato["sections"])

    def test_tentativi_massimi_e_configurabile(self):
        errore = RuntimeError("guasto")
        patcher, client_finto = self._con_client_finto(
            [errore, errore, errore, _risposta_valida()])
        with patcher:
            risultato = tips_generator.generate_architect_tips(
                _trip(), _itinerario(), api_key="finta", tentativi_massimi=4)
        self.assertEqual(4, client_finto.messages.create.call_count)
        self.assertTrue(risultato["sections"])


if __name__ == "__main__":
    unittest.main()
