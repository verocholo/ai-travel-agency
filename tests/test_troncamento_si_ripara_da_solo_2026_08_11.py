"""Una risposta troncata non e' piu' un fallimento (task #198).

PERCHE' QUESTO FILE ESISTE

L'11 agosto 2026, dopo due giorni di collaudi, la causa vera di tutto e'
finalmente uscita in chiaro dal servizio:

    «il modello non ha prodotto un itinerario utilizzabile (nessuna giornata)
    — Risposta di Claude troncata: ha raggiunto il limite max_tokens=32000
    (output_tokens usati: 32000) prima di completare il JSON»

Un viaggio di due giorni a Siena. La catena si e' fermata dopo 358 secondi di
generazione gia' pagata, e il cliente non avrebbe ricevuto niente.

## Perche' alzare il numero non e' la riparazione

La storia di quel limite: 8192 → 16000 → 32000 → 64000. Quattro volte, sempre
la stessa mossa — raddoppiare — e ogni volta ha retto finche' non ha smesso.
Nessuno puo' sapere in anticipo quanto sara' lunga la risposta del modello per
un viaggio che non ha ancora visto: chi indovina sbaglia, e qui ha gia'
sbagliato tre volte prima di stasera.

Il troncamento pero' e' l'unico errore di questa funzione **che si sa gia'
come si ripara**: serviva piu' spazio. Fino a stasera quella riparazione la
faceva una persona — leggere un log, cambiare una costante, rifare un deploy —
mentre il cliente restava senza documento. Adesso la fa il prodotto: se la
risposta esce tagliata, rifa' la domanda una volta con il doppio del budget,
fino al tetto vero del modello.

## Cosa NON e' stato toccato

La lunghezza del ragionamento del modello. Accorciare lo <scratchpad> avrebbe
risolto il troncamento pagando con la qualita' del documento, ed e'
esattamente il baratto che Lorenzo ha rifiutato: «io voglio tenere alta la
qualita'». Il modello ragiona quanto gli serve; siamo noi a fargli spazio.

## Come si prova senza chiamare nessuno

Il pacchetto `anthropic` non e' installato ovunque e una chiamata vera
costerebbe soldi a ogni esecuzione della suite. Qui si mette al suo posto un
finto pacchetto che risponde quello che vogliamo noi: prima troncato, poi
completo. E' l'unico modo di provare un ritentativo senza pagarlo.
"""

import sys
import types
import unittest
from unittest import mock

from src import claude_engine


class _RispostaFinta:
    def __init__(self, testo, stop_reason, output_tokens):
        self.content = [types.SimpleNamespace(text=testo)]
        self.stop_reason = stop_reason
        self.usage = types.SimpleNamespace(input_tokens=100,
                                           output_tokens=output_tokens)


class _FlussoFinto:
    def __init__(self, risposta):
        self._risposta = risposta

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self._risposta


class _ClienteFinto:
    """Registra i budget richiesti e restituisce le risposte preparate."""

    def __init__(self, risposte, budget_visti):
        # NON una copia: le risposte sono condivise fra il primo tentativo e
        # il ritentativo, che costruisce un cliente nuovo. Con una copia il
        # finto rispondeva la stessa cosa due volte e il test misurava se
        # stesso invece del prodotto.
        self._risposte = risposte
        self._budget_visti = budget_visti
        self.messages = types.SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self._budget_visti.append(kwargs["max_tokens"])
        return _FlussoFinto(self._risposte.pop(0))


class _Base(unittest.TestCase):
    """Mette un finto `anthropic` al posto di quello vero, e poi lo toglie."""

    def _chiama(self, risposte, duration_days=2):
        budget_visti = []

        class _APIError(Exception):
            pass

        finto = types.ModuleType("anthropic")
        finto.APIError = _APIError
        finto.Anthropic = lambda api_key=None: _ClienteFinto(risposte, budget_visti)

        with mock.patch.dict(sys.modules, {"anthropic": finto}), \
             mock.patch.object(claude_engine, "load_system_prompt",
                               create=True, return_value="sistema"), \
             mock.patch.object(claude_engine, "build_user_message",
                               return_value="utente"):
            testo = claude_engine.call_claude(
                {"payload": True}, trip_objective_function="ENERGY_PACING",
                trip_duration_days=duration_days, api_key="finta")
        return testo, budget_visti


class TestSiRiprovaConPiuSpazio(_Base):

    def test_una_risposta_troncata_viene_rifatta_col_doppio_del_budget(self):
        """Il guasto vero dell'11 agosto, riprodotto e riparato da solo."""
        testo, budget = self._chiama([
            _RispostaFinta('{"days": [', "max_tokens", 64000),
            _RispostaFinta('{"days": [1]}', "end_turn", 40000),
        ])
        self.assertEqual(testo, '{"days": [1]}',
                         "il troncamento non e' stato recuperato")
        self.assertEqual(len(budget), 2, "non ha riprovato")
        self.assertGreater(budget[1], budget[0],
                           "ha riprovato con lo stesso spazio di prima")

    def test_se_la_prima_risposta_e_completa_non_si_riprova(self):
        # Un ritentativo di troppo e' una generazione pagata due volte.
        testo, budget = self._chiama([
            _RispostaFinta('{"days": [1]}', "end_turn", 20000),
        ])
        self.assertEqual(len(budget), 1)
        self.assertEqual(testo, '{"days": [1]}')

    def test_non_si_riprova_all_infinito(self):
        """Il freno, ed e' la parte che protegge il portafoglio.

        Un ritentativo che si ripete finche' riesce trasforma un errore
        visibile in una bolletta invisibile — un guasto peggiore di quello che
        risolve. Qui si sale fino al tetto del modello e poi ci si ferma con
        un errore leggibile.
        """
        troncate = [_RispostaFinta("{", "max_tokens", 120000) for _ in range(10)]
        with self.assertRaises(claude_engine.ClaudeEngineError) as ctx:
            self._chiama(troncate)
        self.assertIn("tetto massimo", str(ctx.exception))

    def test_l_errore_finale_dice_cosa_fare_e_non_ripete_il_consiglio_vecchio(self):
        # Il vecchio messaggio diceva «aumenta max_tokens»: un consiglio che
        # ora e' gia' stato seguito automaticamente. Ripeterlo manderebbe chi
        # legge a fare una cosa gia' fatta.
        troncate = [_RispostaFinta("{", "max_tokens", 120000) for _ in range(10)]
        with self.assertRaises(claude_engine.ClaudeEngineError) as ctx:
            self._chiama(troncate)
        self.assertNotIn("aumenta max_tokens", str(ctx.exception))
        self.assertIn("spezzato", str(ctx.exception))


class TestIlBudgetDiPartenza(unittest.TestCase):
    """I numeri, fissati per nome: se tornano indietro, tornano in silenzio."""

    def test_parte_da_piu_di_quanto_e_servito_stasera(self):
        # Stasera ne sono serviti piu' di 32.000 per un viaggio di DUE giorni.
        # Ripartire da li' vorrebbe dire ricominciare da capo.
        self.assertGreater(claude_engine.select_max_tokens(2), 32000)

    def test_il_tetto_sta_sotto_al_limite_vero_del_modello(self):
        # Un tetto identico al limite non lascia spazio a un ritentativo: il
        # raddoppio non avrebbe dove salire.
        self.assertLess(claude_engine.MAX_TOKENS_CEILING, 128000)
        self.assertGreater(claude_engine.MAX_TOKENS_CEILING,
                           claude_engine.BASE_MAX_TOKENS)

    def test_un_viaggio_lungo_chiede_piu_spazio_di_uno_corto(self):
        self.assertGreater(claude_engine.select_max_tokens(20),
                           claude_engine.select_max_tokens(2))

    def test_nessun_viaggio_sfonda_il_tetto(self):
        for giorni in (1, 7, 30, 365):
            with self.subTest(giorni=giorni):
                self.assertLessEqual(claude_engine.select_max_tokens(giorni),
                                     claude_engine.MAX_TOKENS_CEILING)


if __name__ == "__main__":
    unittest.main()
