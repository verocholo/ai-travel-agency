"""Le fotografie non si deformano (task #199).

PERCHE' QUESTO FILE ESISTE

Lorenzo, guardando il primo documento uscito davvero dalla catena completa:
«le foto sono stretchate o in bassa risoluzione».

Aveva ragione su tutti e due i punti, ed erano due difetti diversi con due
cause diverse.

## Lo schiacciamento

Nel foglio di stile c'era, per la foto di apertura di ogni giornata:

    .day-foto img { width: 100%; max-height: 150px; }

Sono due ordini che si contraddicono. Il primo dice «larga quanto la pagina»,
il secondo «alta al massimo cosi'», e il motore di stampa obbedisce a tutti e
due: tiene la larghezza e taglia l'altezza, **senza toccare le proporzioni
dell'immagine originale**. Una torre diventava tozza, un viale alberato una
fessura.

La regola giusta e' dichiarare solo i LIMITI (`max-width`, `max-height`) e
lasciare che sia l'immagine a scegliere le proprie proporzioni dentro quei
limiti. Una foto orizzontale riempie la fascia; una verticale resta stretta e
centrata, con del bianco ai lati — che in una pagina impaginata bene non e' un
difetto, e' respiro.

`object-fit: cover`, che risolverebbe ritagliando invece che restringendo, non
esiste nel motore di stampa: e' una di quelle proprieta' che funzionano
nell'anteprima del browser e vengono ignorate in silenzio nel PDF venduto.

## La bassa risoluzione

Le immagini erano ridotte a 800 pixel di larghezza. Su una pagina A4 coprono
circa diciotto centimetri, cioe' poco piu' di 110 punti per pollice: sotto la
soglia in cui una fotografia comincia a sembrare sgranata. Il limite non era
un capriccio — era il peso, perche' le foto venivano salvate in PNG, un
formato fatto per i disegni a tinte piatte che su una fotografia costa dieci
volte tanto.

Passando al JPEG si porta il doppio della risoluzione pesando meno di prima.
E' la stessa lezione di sempre in questo progetto: il vincolo non era dove
sembrava.
"""

import re
import unittest

from src.pdf_renderer import _CSS


def _senza_commenti(css: str) -> str:
    """Il foglio di stile con dentro solo le REGOLE.

    [SCRITTO DUE VOLTE, 2026-08-11 — e la seconda versione vale piu' della
    prima.] Il controllo su `object-fit` qui sotto e' nato rosso: la stringa
    c'era, ma dentro il commento che spiega **perche' quella proprieta' non
    si usa**. Cioe' il controllo scritto per impedire un errore falliva a
    causa della documentazione scritta per impedire lo stesso errore.

    E' la quinta volta che questo progetto ci casca: era gia' successo con
    `class='criterio`, con «Come si legge», con `rgba(` e con `openpyxl`
    dentro `requirements.txt`. La regola, ormai imparata a caro prezzo: **un
    controllo non deve mai cercare dentro il testo grezzo di un file che
    contiene commenti.** Qui i commenti si tolgono prima di guardare.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


_REGOLE = _senza_commenti(_CSS)


def _regola(nome: str) -> str:
    """Il contenuto di una regola del foglio di stile, senza le graffe."""
    if nome + " {" not in _REGOLE:
        return ""
    return _REGOLE.split(nome + " {", 1)[1].split("}", 1)[0]


class TestNessunaImmagineVieneSchiacciata(unittest.TestCase):
    """[REGRESSIONE 2026-08-11 — difetto visto sulla pagina, non nel codice.]

    Nessun controllo poteva accorgersene prima: l'HTML era valido, l'immagine
    c'era, il collegamento funzionava. Si vedeva solo guardando la fotografia
    di una torre diventata tozza.
    """

    REGOLE_CON_IMMAGINE = (".day-foto img", ".guide-foto img")

    def test_nessuna_regola_impone_insieme_larghezza_piena_e_altezza_massima(self):
        for nome in self.REGOLE_CON_IMMAGINE:
            with self.subTest(regola=nome):
                regola = _regola(nome)
                self.assertTrue(regola, f"{nome}: regola sparita dal foglio di stile")
                # `(?<![-\w])` NON e' pedanteria: senza, questo controllo
                # trova «width» dentro «max-width» e fallisce proprio sulla
                # regola CORRETTA. Sarebbe stato rosso per sempre, e il modo
                # piu' rapido per far cancellare un controllo e' renderlo
                # rosso quando il prodotto e' giusto.
                impone_larghezza = re.search(r"(?<![-\w])width:\s*100%", regola)
                schiaccia = bool(impone_larghezza) and "max-height" in regola
                self.assertFalse(
                    schiaccia,
                    f"{nome} impone larghezza piena E altezza massima: il motore "
                    "obbedisce a entrambe e deforma la fotografia")

    def test_i_limiti_ci_sono_comunque(self):
        # Senza un tetto all'altezza, una foto verticale si prende una pagina
        # intera e sposta tutto il resto: il difetto opposto, e sarebbe peggio.
        for nome in self.REGOLE_CON_IMMAGINE:
            with self.subTest(regola=nome):
                regola = _regola(nome)
                self.assertIn("max-width", regola)
                self.assertIn("max-height", regola)

    def test_una_foto_stretta_resta_al_centro_e_non_a_sinistra(self):
        # Con i soli limiti, un'immagine verticale diventa piu' stretta della
        # colonna. Appoggiata a sinistra sembrerebbe un errore di
        # impaginazione; centrata sembra una scelta.
        for nome in (".day-foto", ".guide-foto"):
            with self.subTest(regola=nome):
                self.assertIn("text-align: center", _regola(nome))

    def test_object_fit_non_viene_usato_perche_non_esiste_qui(self):
        """La scorciatoia che sembra la soluzione e non funziona.

        `object-fit: cover` e' la risposta giusta in un browser. Il motore di
        stampa di questo progetto la ignora senza dire niente: chi la
        scrivesse vedrebbe l'anteprima perfetta e il PDF venduto sbagliato.
        """
        self.assertNotIn("object-fit", _REGOLE)


class TestLeImmaginiSonoAbbastanzaGrandiDaStampare(unittest.TestCase):

    def test_la_fascia_della_giornata_non_e_una_striscia(self):
        # 150 pixel su una pagina alta 1120: la foto era un francobollo
        # allungato. Non e' una regola di gusto — sotto una certa altezza
        # un'immagine smette di raccontare il posto e diventa decorazione.
        altezze = re.findall(r"max-height:\s*(\d+)px", _regola(".day-foto img"))
        self.assertTrue(altezze)
        self.assertGreaterEqual(int(altezze[0]), 180)


if __name__ == "__main__":
    unittest.main()
