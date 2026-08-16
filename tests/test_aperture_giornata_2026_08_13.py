"""Nessuna giornata si apre come quella prima (task #214).

PERCHE' QUESTO FILE ESISTE

Lorenzo, 13 agosto 2026: «devi essere tu in grado di diversificare ogni
volta», e poco dopo «ogni giornata deve avere le foto».

Prima ogni giornata si apriva allo stesso identico modo: una fotografia
centrata sotto il titolo. Con un viaggio di cinque giorni erano cinque pagine
gemelle — e il difetto peggiore di un documento venduto non e' che sia brutto,
e' che sembri **automatico**.

## Perche' solo le aperture, e non tutta la pagina

Il compositore sa comporre pagine intere, a colonne. Quelle pero' ridisegnano
la struttura della giornata — titolo, cartina, programma, legenda — e quella
struttura oggi regge sette controlli di impaginazione, fra cui quello che
impedisce a una pagina di restare mezza vuota.

Cambiarla tutta in una volta vorrebbe dire rimettere in gioco sette garanzie
insieme, e questa settimana ha gia' mostrato due volte cosa succede: una
singola immagine in piu' ha fatto sfondare una pagina. Le tre aperture si
impilano tutte allo stesso modo, quindi cambia UN pezzo di HTML nello stesso
punto in cui prima ce n'era uno solo.

## Cosa difendono i controlli qui sotto

Che la varieta' arrivi **davvero nel documento** — non che la funzione sappia
sceglierla. E' la differenza fra una funzione corretta e una funzione
chiamata, e in questo progetto e' gia' costata una fila di fotografie scritta,
provata e mai attaccata alla pagina.
"""

import io
import re
import unittest


def _foto(rgb=(168, 74, 38), larghezza=1200, altezza=800) -> bytes:
    from PIL import Image, ImageDraw

    immagine = Image.new("RGB", (larghezza, altezza), rgb)
    disegno = ImageDraw.Draw(immagine)
    for x in range(0, larghezza, 70):
        disegno.rectangle([x, 0, x + 30, altezza],
                          fill=tuple(max(0, c - 26) for c in rgb))
    fuori = io.BytesIO()
    immagine.save(fuori, format="JPEG", quality=85)
    return fuori.getvalue()


def _blocchi(*identificativi):
    return [{"time": f"1{i}:00", "activity": f"Tappa {p}", "location": "Siena",
             "poi_id": p} for i, p in enumerate(identificativi)]


def _documento(giorni=5, tappe_per_giorno=3, scoperti=(), destinazione="Siena"):
    """Un viaggio di N giornate, con o senza fotografie proprie."""
    from src.pdf_renderer import render_html

    days, photos = [], {}
    for giorno in range(1, giorni + 1):
        identificativi = [f"P{giorno}_{i}" for i in range(tappe_per_giorno)]
        days.append({"day": giorno, "title": f"Giornata {giorno}",
                     "blocks": _blocchi(*identificativi)})
        if giorno in scoperti:
            continue
        for p in identificativi:
            photos[p] = {"png": _foto(), "credito": f"Autore {p} / Prova",
                         "reale": True}
    itinerario = {"destination": destinazione,
                  "executive_summary": "Un viaggio.", "days": days}
    viaggio = {"destination": destinazione, "date_start": "2026-09-14",
               "date_end": "2026-09-20", "duration_days": giorni,
               "budget_eur": 800}
    return render_html(itinerario, viaggio,
                       hotels=[{"name": "Hotel", "price_night_eur": 100}],
                       photos=photos)


# I nomi delle aperture, come compaiono nell'HTML consegnato.
#
# [ESTESI 2026-08-15 — task #219, quando sono entrate le due aperture a
# colonne.] Questo elenco NON e' un dettaglio della prova: se resta indietro,
# una giornata aperta con un'apertura nuova risulta «senza apertura», la
# ricerca scivola sulla fila di chiusura della giornata e la prova segnala
# giornate gemelle che non esistono. E' successo, ed e' il motivo per cui sta
# scritto qui in cima invece che dentro l'espressione.
CLASSI_DI_APERTURA = ("day-larga", "day-banda", "day-striscia", "day-eroe",
                      "day-numerone")
_QUALUNQUE_APERTURA = "class='(" + "|".join(CLASSI_DI_APERTURA) + ")'"


def _aperture(html: str) -> list:
    """Le aperture nell'ordine in cui compaiono nel documento."""
    trovate = re.findall(_QUALUNQUE_APERTURA, html)
    # `day-striscia` e' usata sia dal mosaico d'apertura sia dalla fila di
    # chiusura della giornata: qui contano solo quelle in apertura, cioe' le
    # prime di ogni giornata. Si separa il documento per titolo di giornata.
    fuori = []
    for pezzo in html.split("class='day-title'")[1:]:
        m = re.search(_QUALUNQUE_APERTURA, pezzo)
        if m:
            fuori.append(m.group(1))
    return fuori or trovate


class TestLaVarietaArrivaDAVVERONELDOCUMENTO(unittest.TestCase):
    """La trappola che questo progetto ha gia' preso: una funzione corretta e
    mai chiamata e' il modo piu' elegante di non risolvere un problema."""

    def test_un_viaggio_di_cinque_giorni_non_ha_cinque_aperture_uguali(self):
        aperture = _aperture(_documento(giorni=5))
        self.assertGreaterEqual(len(aperture), 4, aperture)
        self.assertGreater(
            len(set(aperture)), 1,
            f"tutte le giornate si aprono allo stesso modo: {aperture}")

    def test_mai_due_giornate_di_fila_con_la_stessa_apertura(self):
        for destinazione in ("Siena", "Santorini", "Marrakech", "Bologna"):
            aperture = _aperture(_documento(giorni=6, destinazione=destinazione))
            gemelle = [i for i, (a, b) in enumerate(zip(aperture, aperture[1:]))
                       if a == b]
            with self.subTest(destinazione=destinazione):
                self.assertEqual([], gemelle,
                                 f"giornate gemelle attaccate: {aperture}")

    def test_due_viaggi_diversi_non_hanno_la_stessa_sequenza(self):
        self.assertNotEqual(_aperture(_documento(giorni=6, destinazione="Siena")),
                            _aperture(_documento(giorni=6, destinazione="Tokyo")))

    def test_lo_stesso_viaggio_rigenerato_da_lo_stesso_documento(self):
        # Un documento che cambia a ogni esecuzione e' impossibile da
        # collaudare, e un difetto che compare una volta su sei non si ripara
        # mai perche' nessuno riesce a riprodurlo.
        self.assertEqual(_aperture(_documento(giorni=6)),
                         _aperture(_documento(giorni=6)))


class TestOgniGiornataHaLeSueFotografie(unittest.TestCase):
    """Richiesta secca di Lorenzo. La garanzia e' costruita, non dichiarata."""

    def test_una_giornata_senza_foto_proprie_resta_illustrata(self):
        """Il caso vero: per quelle tappe Google non ha restituito niente.

        Al cliente non interessa il perche': vede una pagina spoglia in mezzo
        a cinque illustrate. Si prende in prestito da un'altra tappa dello
        stesso viaggio — e la didascalia continua a dire di CHI e' la
        fotografia e quindi che luogo mostra, perche' la regola di questo
        prodotto e' che non si inventa niente.
        """
        aperture = _aperture(_documento(giorni=5, scoperti=(3,)))
        self.assertEqual(5, len(aperture),
                         f"una giornata e' rimasta senza apertura: {aperture}")

    def test_nemmeno_due_giornate_scoperte_restano_spoglie(self):
        aperture = _aperture(_documento(giorni=6, scoperti=(2, 5)))
        self.assertEqual(6, len(aperture), aperture)

    def test_senza_nessuna_fotografia_il_documento_esce_lo_stesso(self):
        """Succede se manca la chiave di Google: un guasto di configurazione,
        non una giornata sfortunata. Un fascicolo che non parte e' peggio di
        uno senza fotografie."""
        html = _documento(giorni=3, scoperti=(1, 2, 3))
        self.assertEqual([], _aperture(html))
        self.assertIn("Giornata 1", html)
        self.assertIn("Giornata 3", html)

    def test_la_fotografia_prestata_porta_il_suo_credito(self):
        # Nessuna immagine senza chi l'ha fatta: vale doppio quando l'immagine
        # arriva da un'altra tappa.
        html = _documento(giorni=4, scoperti=(2,))
        # Si taglia sui TITOLI DI GIORNATA del corpo, non sulla prima
        # occorrenza del nome: quella sta nell'indice di copertina, e
        # cercare li' misurerebbe la copertina invece del programma. Ci sono
        # cascato scrivendo questo file.
        giornate = html.split("class='day-title'")[1:]
        seconda = next(g for g in giornate if "giorno-2" in g[:200])
        # Si guarda TUTTA la sezione, non i primi mille caratteri: la
        # didascalia sta subito dopo l'immagine, e l'immagine e' un centinaio
        # di migliaia di caratteri di base64. Una finestra corta qui non
        # trovava niente e sembrava un difetto del prodotto.
        self.assertIn("Foto:", seconda,
                      "la giornata senza fotografie proprie non ha ricevuto "
                      "nessuna immagine in prestito")
        # E deve essere una fotografia PRESA IN PRESTITO, cioe' di una tappa
        # che non e' di questa giornata: se comparisse un autore "P2_*"
        # vorrebbe dire che le foto proprie c'erano e la prova non sta
        # misurando il caso che dice di misurare.
        self.assertNotIn("Autore P2_", seconda)


class TestLaBandaEsceDaiMarginiEsattamenteQuantoDeve(unittest.TestCase):
    """[SCRITTO PERCHE' E' IL TIPO DI DIFETTO CHE NON DA' NESSUN ERRORE.]

    La fotografia a tutta larghezza esce dai margini con un margine negativo.
    Quel numero deve valere ESATTAMENTE quanto il margine di pagina: piu'
    piccolo e la foto si ferma prima del bordo (sembra un errore di stampa),
    piu' grande e sborda fuori dal foglio e viene tagliata.

    Nessuno dei due casi solleva un errore. Si vedono solo sulla carta, cioe'
    addosso al cliente.
    """

    def _numero(self, regola, proprieta):
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(regola + " {", 1)[1].split("}", 1)[0]
        trovato = re.search(proprieta + r":\s*(-?[\d.]+)cm", pezzo)
        self.assertTrue(trovato, f"{regola}: manca {proprieta}")
        return float(trovato.group(1))

    def test_il_margine_negativo_e_specchiato_su_quello_di_pagina(self):
        from src.pdf_renderer import _CSS

        pagina = re.search(r"@page\s*\{[^}]*margin:\s*[\d.]+cm\s+([\d.]+)cm",
                           _CSS)
        self.assertTrue(pagina, "il margine di pagina non si legge piu'")
        laterale = float(pagina.group(1))
        for proprieta in ("margin-left", "margin-right"):
            with self.subTest(proprieta=proprieta):
                self.assertAlmostEqual(
                    -laterale, self._numero(".day-banda", proprieta), places=3,
                    msg="la fotografia a tutta larghezza non combacia col "
                        "margine della pagina: o si ferma prima del bordo o "
                        "sborda dal foglio, e nessuno dei due da' errore")

    def test_la_didascalia_rientra_nella_colonna_del_testo(self):
        # Senza il rientro, il credito finirebbe attaccato al bordo del foglio
        # insieme alla fotografia: leggibile, ma chiaramente sbagliato.
        self.assertGreater(self._numero(".day-banda .didascalia", "margin-left"), 0)


if __name__ == "__main__":
    unittest.main()
