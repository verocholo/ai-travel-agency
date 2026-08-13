"""La copertina sta in una pagina, e il meteo non dice cose inutili (task #201).

PERCHE' QUESTO FILE ESISTE

Lorenzo, sul secondo documento uscito dalla catena completa:

    «l'impaginazione della prima e seconda pagina fa schifo, cerca di farci
    stare tutto in una pagina, non voglio che ci sia una pagina iniziata per
    due righe e poi lasciata bianca»

    «nella parte del meteo scrivi 12h e 45 di luce, e' un'informazione inutile
    e brutta da vedere, rimuovila»

## La copertina

Il respiro della copertina e' a tre livelli, scelto sull'altezza dell'indice:
un weekend puo' permettersi spazi larghi, una vacanza di due settimane no. Il
meccanismo era giusto; le soglie erano tarate su un campione **costruito a
mano**, e sul primo documento vero — Bologna, due giorni — hanno scelto il
respiro massimo. La nota di chiusura e' sbordata di due righe sulla pagina
successiva, lasciandola bianca per il resto.

Due righe in cima a una pagina altrimenti vuota sono la prima cosa che si nota
in un documento venduto. La regola, da qui in avanti: **fra una copertina un
po' piu' compatta e una seconda pagina quasi vuota, vince sempre la prima.**

## Il meteo

«12h e 45 di luce» era un dato vero che non risponde a nessuna domanda:
nessuno cambia programma perche' la giornata dura dodici ore e quarantacinque
invece di tredici. Cio' che serve — a che ora fa buio, quando e' l'ora d'oro
per le fotografie — era gia' scritto altrove, in una forma che si usa. Un
documento non migliora aggiungendo dati veri; migliora togliendo quelli che
non servono a decidere.
"""

import re
import unittest

from src.pdf_renderer import _CSS, _render_cover


TRIP = {"destination": "Bologna", "date_start": "2026-09-12",
        "date_end": "2026-09-14", "duration_days": 2, "budget_eur": 600}


def _copertina(giorni: int) -> str:
    itinerario = {
        "destination": "Bologna",
        "days": [{"day": n + 1, "title": f"Giorno {n + 1}", "blocks": []}
                 for n in range(giorni)],
    }
    return _render_cover(itinerario, dict(TRIP, duration_days=giorni),
                         hotels=[{"name": "Hotel", "price_night_eur": 100}])


class TestLaCopertinaNonSbordaMai(unittest.TestCase):

    def _soglie(self):
        """I due numeri che decidono il respiro, letti dal prodotto.

        Si guardano le soglie e non l'HTML di una copertina finta: l'altezza
        dell'indice dipende da quali capitoli esistono davvero in quel
        viaggio, e una copertina costruita a tavolino ne ha meno del vero —
        che e' esattamente l'errore che ha tarato male le soglie la prima
        volta.
        """
        import inspect

        from src import pdf_renderer

        sorgente = inspect.getsource(pdf_renderer._render_cover)
        # [AGGIORNATO 2026-08-13 — task #209] Prima qui si cercava
        # `tallest <= N`, con i due numeri scritti in chiaro nel confronto.
        # Da quando la copertina puo' avere una fotografia in cima, le soglie
        # sono DUE COPPIE — una per la copertina illustrata, una per quella
        # spoglia — e stanno in una riga sola.
        #
        # L'aggiornamento non e' cosmetico: cercando la forma vecchia questo
        # metodo non troverebbe piu' niente e farebbe fallire tutto con «le
        # soglie non sono piu' due», mandando chi legge a cercare un guasto
        # che non c'e'. Qui si leggono tutte e quattro, e si restituiscono le
        # PIU' LARGHE: sono quelle che, se sbagliate, fanno sbordare.
        coppie = re.findall(r"\((\d+),\s*(\d+)\)", sorgente)
        self.assertTrue(coppie, "le soglie del respiro non si leggono piu'")
        numeri = [(int(a), int(b)) for a, b in coppie]
        return [max(n[0] for n in numeri), max(n[1] for n in numeri)]

    def test_le_soglie_sono_piu_strette_di_quelle_che_hanno_sbordato(self):
        """Il caso vero: Bologna, due giorni, indice alto 6, nota sbordata.

        Le soglie erano 8 e 11: con un indice alto 6 la copertina prendeva il
        respiro massimo. Devono stare sotto quel 6, altrimenti lo stesso
        documento sborderebbe di nuovo.
        """
        airy, roomy = self._soglie()
        self.assertLess(airy, 6,
                        "con questa soglia il viaggio di Bologna riprende il "
                        "respiro massimo e la nota torna a sbordare")
        self.assertLess(roomy, 8)

    def test_con_la_fotografia_in_cima_le_soglie_sono_ancora_piu_strette(self):
        """[AGGIUNTO 2026-08-13] La fascia fotografica occupa piu' o meno
        quanto tre voci d'indice: con le stesse soglie di prima la copertina
        del campione sfondava sul foglio dopo, lasciandolo bianco per nove
        decimi. E' lo stesso difetto dell'11 agosto entrato da un'altra porta,
        e questo controllo esiste perche' non rientri da una terza."""
        import inspect
        import re

        from src import pdf_renderer

        sorgente = inspect.getsource(pdf_renderer._render_cover)
        self.assertIn("foto_copertina else", sorgente,
                      "le soglie non distinguono piu' la copertina illustrata "
                      "da quella spoglia: una delle due sbordera'")
        coppie = [(int(a), int(b))
                  for a, b in re.findall(r"\((\d+),\s*(\d+)\)", sorgente)]
        self.assertGreaterEqual(len(coppie), 2)
        con_foto, senza_foto = coppie[0], coppie[1]
        self.assertLess(con_foto[0], senza_foto[0])
        self.assertLess(con_foto[1], senza_foto[1])

    def test_il_respiro_massimo_resta_il_piu_raro(self):
        # Le due soglie devono restare ordinate: se si invertissero, un indice
        # lungo prenderebbe piu' spazio di uno corto — cioe' il contrario di
        # quello che serve.
        airy, roomy = self._soglie()
        self.assertLess(airy, roomy)

    def test_la_nota_di_chiusura_non_si_spezza_a_meta(self):
        """Il difetto esatto: due righe di coda su una pagina vuota.

        Se proprio non ci sta, la nota deve spostarsi INTERA. Meglio una
        copertina un po' piu' corta che una pagina iniziata per due righe.
        """
        regola = _CSS.split(".cover-note {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-inside: avoid", regola)

    def test_la_copertina_resta_una_pagina_a_se(self):
        regola = _CSS.split(".cover {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-after: always", regola)


class TestIlMeteoNonDicePiuLaDurataDelGiorno(unittest.TestCase):

    def test_l_etichetta_della_luce_non_viene_piu_stampata(self):
        """Si guarda il SORGENTE della funzione che costruisce il riquadro.

        Il dato esiste ancora — `src/sun_times.py` lo calcola perche' serve
        all'ora d'oro — e quindi non si puo' controllare che sia sparito dal
        programma: si controlla che non venga piu' MESSO nella pagina.
        """
        import inspect

        from src import pdf_renderer

        sorgente = inspect.getsource(pdf_renderer)
        stampe = re.findall(r"vad-num-small'>\{_esc\(climate\['(\w+)'\]\)\}",
                            sorgente)
        self.assertNotIn("daylight_label", stampe,
                         "la durata del giorno e' tornata nel riquadro del "
                         "meteo: e' un dato vero che non serve a decidere "
                         "niente")


if __name__ == "__main__":
    unittest.main()
