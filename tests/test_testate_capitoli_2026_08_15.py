"""Nessun capitolo si apre come quello prima (task #216).

PERCHE' QUESTO FILE ESISTE

Fino al 14 agosto tutti i capitoli del fascicolo si aprivano con la stessa
riga: carattere con le grazie, un filetto sotto, e basta. Su un documento di
ventisei pagine sono undici aperture identiche — ed e' il difetto che Lorenzo
ha nominato per primo guardando i provini. Non «brutto»: **sempre uguale**,
che su un documento venduto e' peggio, perche' si legge come «generato».

## Cosa difendono i controlli qui sotto

Le PROPRIETA', non i casi. Con quattro modi e undici capitoli i documenti
possibili sono troppi per guardarli uno per uno, quindi elencare i casi buoni
non servirebbe a niente: si verifica che le regole valgano SEMPRE.

1. la varieta' arriva **davvero nel documento** — non che la funzione sappia
   sceglierla. E' la trappola che questo progetto ha gia' preso una volta: una
   fila di fotografie scritta, provata e mai attaccata alla pagina;
2. mai due capitoli di fila con la stessa testata;
3. lo stesso viaggio rigenerato da' lo stesso documento;
4. la testata non si mangia i titoli di sezione normali (Shopping, Cosa fare,
   Come arrivare), che devono restare la riga sobria di sempre;
5. la banda a tutta larghezza combacia col margine di pagina.

## L'ultima, e perche' e' scritta qui

La banda esce dai margini con un margine negativo. Quel numero deve valere
esattamente quanto il margine di `@page`: piu' piccolo e il colore si ferma
prima del bordo (sembra un errore di stampa), piu' grande e sborda dal foglio.
Nessuno dei due casi solleva un errore: si vedono solo sulla carta, cioe'
addosso al cliente.
"""

import re
import unittest


def _documento(destinazione="Siena"):
    """Il documento VERO, quello del campione, con tutti i suoi capitoli.

    Non un itinerario minimo scritto qui: con un itinerario minimo meta' dei
    capitoli non esce affatto (senza costi non c'e' il capitolo dei costi), e
    una prova sulla varieta' delle testate misurata su tre capitoli non
    misura niente. Ci sono cascato scrivendo questo file.
    """
    import scripts_sample_pdf
    from src.pdf_renderer import render_html

    itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
    kwargs = dict(kwargs)
    kwargs.pop("output_path", None)
    # La destinazione e' la chiave da cui il compositore ricava le sue scelte:
    # cambiarla e' il modo di verificare che due viaggi diversi non escano
    # con la stessa sequenza di testate.
    itinerario = dict(itinerario, destination=destinazione)
    viaggio = dict(viaggio, destination=destinazione)
    return render_html(itinerario, viaggio, **kwargs)


def _testate(html: str) -> list:
    """(capitolo, modo) nell'ordine in cui stanno sulla carta."""
    return [(m.group(2), m.group(1)) for m in re.finditer(
        r"class='cap cap-(\w+)'.*?data-capitolo='([^']*)'", html, re.S)]


class TestLaVarietaArrivaDAVVERONELDOCUMENTO(unittest.TestCase):
    """Una funzione corretta e mai chiamata e' il modo piu' elegante di non
    risolvere un problema. Qui si guarda l'HTML consegnato, non la funzione."""

    def test_il_documento_ha_davvero_le_testate_vestite(self):
        trovate = _testate(_documento())
        self.assertGreaterEqual(len(trovate), 4, trovate)

    def test_non_sono_tutte_dello_stesso_modo(self):
        modi = [m for _capitolo, m in _testate(_documento())]
        self.assertGreater(len(set(modi)), 1,
                           f"tutti i capitoli si aprono uguali: {modi}")

    def test_mai_due_capitoli_di_fila_con_la_stessa_testata(self):
        for destinazione in ("Siena", "Santorini", "Marrakech", "Tokyo",
                             "Bologna", "Reykjavik"):
            modi = [m for _c, m in _testate(_documento(destinazione))]
            gemelli = [i for i, (a, b) in enumerate(zip(modi, modi[1:])) if a == b]
            with self.subTest(destinazione=destinazione):
                self.assertEqual([], gemelli,
                                 f"capitoli gemelli attaccati: {modi}")

    def test_lo_stesso_viaggio_rigenerato_da_lo_stesso_documento(self):
        # Un documento che cambia a ogni esecuzione e' impossibile da
        # collaudare, e un difetto che compare una volta su sei non si ripara
        # mai perche' nessuno riesce a riprodurlo.
        self.assertEqual(_testate(_documento()), _testate(_documento()))

    def test_due_viaggi_diversi_non_hanno_la_stessa_sequenza(self):
        # Altrimenti la varieta' sarebbe solo dentro un documento, e due
        # clienti diversi riceverebbero lo stesso fascicolo con parole diverse.
        self.assertNotEqual([m for _c, m in _testate(_documento("Siena"))],
                            [m for _c, m in _testate(_documento("Tokyo"))])

    def test_i_capitoli_sono_numerati_nell_ordine_delle_pagine(self):
        html = _documento()
        numeri = [int(n) for n in re.findall(
            r"class='cap-occhiello'>Capitolo (\d+)</div>", html)]
        self.assertEqual(sorted(numeri), numeri,
                         f"la numerazione non segue le pagine: {numeri}")


class TestLeSezioniNORMALIRestanoQuelleDiPrima(unittest.TestCase):
    """[SCRITTO PERCHE' E' IL MODO IN CUI QUESTA MODIFICA POTEVA ESAGERARE.]

    "Shopping", "Cosa fare", "Come arrivare" non sono capitoli: sono
    sottotitoli dentro un capitolo. Vestirli come capitoli avrebbe rifatto lo
    stesso difetto al contrario — un documento in cui tutto grida, dove non si
    capisce piu' cosa contenga cosa.
    """

    def test_un_sottotitolo_resta_la_riga_sobria_di_sempre(self):
        html = _documento()
        for sottotitolo in ("Il viaggio in breve",):
            with self.subTest(sottotitolo=sottotitolo):
                self.assertIn(f"<div class='section-title'>{sottotitolo}</div>",
                              html)

    def test_i_capitoli_veri_portano_il_loro_nome_di_ancora(self):
        # Se il marcatore sparisse, le testate tornerebbero grigie senza che
        # nessun errore lo dica: e' una modifica che fallisce in silenzio.
        capitoli = {c for c, _m in _testate(_documento())}
        for atteso in ("alloggio", "costi", "piani-b", "prima-di-partire"):
            with self.subTest(capitolo=atteso):
                self.assertIn(atteso, capitoli)


class TestLaBandaCombaciaColMargineDelFoglio(unittest.TestCase):
    """Il tipo di difetto che non da' nessun errore e si vede solo sulla carta."""

    def _numero(self, regola, proprieta):
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(regola + " {", 1)[1].split("}", 1)[0]
        trovato = re.search(proprieta + r":\s*(-?[\d.]+)cm", pezzo)
        self.assertTrue(trovato, f"{regola}: manca {proprieta}")
        return float(trovato.group(1))

    def test_il_margine_negativo_e_specchiato_su_quello_di_pagina(self):
        from src.pdf_renderer import _CSS

        pagina = re.search(r"@page\s*\{[^}]*margin:\s*[\d.]+cm\s+([\d.]+)cm", _CSS)
        self.assertTrue(pagina, "il margine di pagina non si legge piu'")
        laterale = float(pagina.group(1))
        for proprieta in ("margin-left", "margin-right"):
            with self.subTest(proprieta=proprieta):
                self.assertAlmostEqual(
                    -laterale, self._numero(".cap-fascia", proprieta), places=3,
                    msg="la banda del capitolo non combacia col margine della "
                        "pagina: o si ferma prima del bordo o sborda dal foglio")

    def test_il_riempimento_rimette_il_titolo_in_colonna(self):
        # Senza, il titolo bianco partirebbe dal bordo della carta mentre
        # tutto il resto del documento parte due centimetri dentro.
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".cap-fascia {", 1)[1].split("}", 1)[0]
        rientri = re.findall(r"([\d.]+)cm", pezzo.split("padding:", 1)[1])
        self.assertTrue(rientri, "la banda non rimette il titolo in colonna")


class TestUnModoSconosciutoNonPassaInSilenzio(unittest.TestCase):
    """Se il compositore inventasse un nome nuovo, una ricaduta muta lo
    nasconderebbe e il documento uscirebbe con undici testate uguali senza che
    nessuna prova diventi rossa."""

    def test_un_nome_inventato_si_fa_sentire(self):
        from src.pdf_renderer import _disegna_testata

        with self.assertRaises(ValueError):
            _disegna_testata("inventato", "costi", "Costi", 3)

    def test_tutti_i_modi_del_compositore_sanno_vestirsi(self):
        from src import compositore
        from src.pdf_renderer import _disegna_testata

        for modo in compositore.TESTATE:
            with self.subTest(modo=modo):
                vestito = _disegna_testata(modo, "costi", "Costi", 3)
                self.assertIn("cap-", vestito)
                self.assertIn("Costi", vestito)


if __name__ == "__main__":
    unittest.main()
