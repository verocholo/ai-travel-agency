"""L'impaginazione da brochure (task #232).

PERCHE' QUESTO FILE ESISTE

Lorenzo, con quattro brochure di viaggio in mano: «ti ordino di migliorare
l'impaginazione per renderla sempre luxury ma simile a queste».

Guardandole, quattro cose ricorrono in tutte e quattro — e nessuna era nel
nostro documento:

  1. **la fotografia arriva al bordo del foglio**, non dentro una cornice
     bianca. La copertina E' una fotografia;
  2. **l'indice sta su una pagina sua**, con una fotografia accanto a ogni
     voce;
  3. **gli angoli delle fotografie sono morbidi**, mai vivi;
  4. **il testo lungo sta su due colonne**, come in qualunque rivista.

## Le tre cose che questo motore di stampa NON sa fare, e come sono aggirate

- **al vivo**: non esiste `bleed`, e un'immagine larga 100% si ferma dentro
  la colonna di testo. Si usano margini negativi pari a quelli di `@page`.
  Misurato: si arriva a **tre millimetri e mezzo** dal bordo, non a zero —
  quella e' l'area che wkhtmltopdf tiene per se', e spingere oltre non
  serve (provato) e sopra una certa misura rimpicciolisce l'intera pagina;
- **angoli morbidi**: `border-radius` su un'immagine arrotonda in alto e
  taglia netto in basso. Si ritaglia sui pixel;
- **due colonne**: `column-count` viene ignorato in silenzio. Si usa una
  tabella.

## La regola che ha salvato il documento

Le miniature dell'indice si prendono dalla stessa scorta di fotografie delle
giornate. Alla prima stesura se la mangiavano: sei miniature belle in cima e
tre giornate spoglie dopo. Ora l'indice si serve solo di cio' che avanza
DAVVERO — e se non avanza niente, l'indice resta un elenco pulito.
"""

import io
import re
import unittest


def _jpeg(colore=(40, 110, 130), misure=(1400, 900)) -> bytes:
    from PIL import Image

    fuori = io.BytesIO()
    Image.new("RGB", misure, colore).save(fuori, format="JPEG")
    return fuori.getvalue()


def _scatto(nome, quante=1):
    scatti = [{"png": _jpeg((30 + i * 40, 100, 120)),
               "credito": f"Foto: {nome}{i} / Prova"} for i in range(quante)]
    return {"png": scatti[0]["png"], "credito": scatti[0]["credito"],
            "reale": True, "scatti": scatti}


class TestGLIANGOLIMORBIDI(unittest.TestCase):
    """Si fanno sui pixel. E' la stessa lezione del ritaglio tondo del 13
    agosto: nell'anteprima del browser il foglio di stile funziona, nel PDF
    venduto arrotonda in alto e taglia netto in basso."""

    def test_gli_angoli_prendono_il_colore_del_fondo(self):
        from PIL import Image

        from src import foto

        uscita = foto.angoli_arrotondati(_jpeg((10, 40, 60)), (255, 255, 255))
        self.assertIsNotNone(uscita)
        immagine = Image.open(io.BytesIO(uscita))
        angolo = immagine.getpixel((1, 1))
        centro = immagine.getpixel((immagine.width // 2, immagine.height // 2))
        self.assertGreater(min(angolo), 200, "l'angolo non e' stato ammorbidito")
        self.assertLess(min(centro), 100, "e' stata ammorbidita anche la foto")

    def test_la_fotografia_non_cambia_misura(self):
        """Non ritaglia e non ridimensiona: chi la riceve ha gia' calcolato
        le proporzioni, e cambiarle qui rimetterebbe in gioco tutte le
        garanzie di impaginazione."""
        from PIL import Image

        from src import foto

        grezzo = _jpeg(misure=(800, 600))
        uscita = foto.angoli_arrotondati(grezzo)
        self.assertEqual((800, 600), Image.open(io.BytesIO(uscita)).size)

    def test_su_qualcosa_che_non_e_unimmagine_non_solleva(self):
        from src import foto

        for niente in (None, b"", b"non sono un jpeg", "stringa"):
            with self.subTest(valore=niente):
                self.assertIsNone(foto.angoli_arrotondati(niente))

    def test_un_raggio_troppo_piccolo_lascia_la_foto_com_e(self):
        from src import foto

        grezzo = _jpeg(misure=(20, 20))
        self.assertEqual(grezzo, foto.angoli_arrotondati(grezzo, raggio=0.0))


class TestILRITAGLIOVERTICALE(unittest.TestCase):
    """La gemella di `ritaglia_panoramica` dall'altra parte: quella toglie
    altezza per fare una fascia, questa toglie larghezza per fare una pagina.

    Serve perche' le fotografie che arrivano da Commons e da Google sono
    quasi sempre orizzontali, e una copertina orizzontale non riempie un
    foglio verticale.
    """

    def test_una_foto_orizzontale_diventa_piu_alta(self):
        from PIL import Image

        from src import foto

        uscita = foto.ritaglia_ritratto(_jpeg(misure=(1400, 900)), 1.15)
        larghezza, altezza = Image.open(io.BytesIO(uscita)).size
        self.assertEqual(900, altezza, "l'altezza non si tocca")
        self.assertAlmostEqual(1.15, larghezza / altezza, places=2)

    def test_il_taglio_ha_un_tetto(self):
        """Quello che conta non e' quanto si toglie, e' cosa resta: una
        fotografia panoramica ridotta a una feritoia verticale non e' piu'
        la fotografia di quel posto."""
        from PIL import Image

        from src import foto

        uscita = foto.ritaglia_ritratto(_jpeg(misure=(2000, 400)), 0.6)
        larghezza, _altezza = Image.open(io.BytesIO(uscita)).size
        self.assertGreaterEqual(larghezza, 2000 * (1.0 - foto.TAGLIO_MASSIMO))

    def test_una_foto_gia_verticale_non_si_tocca(self):
        from PIL import Image

        from src import foto

        grezzo = _jpeg(misure=(600, 1400))
        uscita = foto.ritaglia_ritratto(grezzo, 1.15)
        self.assertEqual((600, 1400), Image.open(io.BytesIO(uscita)).size)

    def test_su_byte_che_non_sono_unimmagine_non_solleva(self):
        from src import foto

        self.assertIsNone(foto.ritaglia_ritratto(b"niente"))


class TestLACOPERTINAALVIVO(unittest.TestCase):

    def _html(self):
        import scripts_sample_pdf
        from src.pdf_renderer import render_html

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)
        identificativi = [b.get("poi_id")
                          for g in itinerario["days"] for b in (g.get("blocks") or [])
                          if isinstance(b, dict) and b.get("poi_id")]
        kwargs["photos"] = {p: _scatto(p, 3) for p in identificativi}
        return render_html(itinerario, viaggio, **kwargs)

    def test_la_fotografia_di_copertina_esce_dalla_colonna_di_testo(self):
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".cover-piena {", 1)[1].split("}", 1)[0]
        numeri = re.findall(r"(-?[\d.]+)cm", pezzo)
        self.assertTrue(numeri, "la fotografia di copertina non esce piu' "
                                "dalla colonna: e' tornata dentro la cornice")
        self.assertTrue(any(float(n) < 0 for n in numeri))

    def test_il_margine_negativo_combacia_con_quello_di_pagina(self):
        """[LA MISURA CHE NON PUO' SBAGLIARE DI UN MILLIMETRO.]

        Piu' piccolo e resta una striscia bianca fra fotografia e bordo, che
        si legge come un errore di stampa. Piu' grande e wkhtmltopdf
        rimpicciolisce l'INTERA pagina per far stare l'immagine — testo
        compreso — ed e' un difetto che non solleva niente e si vede solo
        sulla carta.
        """
        from src.pdf_renderer import _CSS

        pagina = re.search(r"@page\s*\{[^}]*margin:\s*[\d.]+cm\s+([\d.]+)cm", _CSS)
        self.assertTrue(pagina)
        laterale = float(pagina.group(1))
        pezzo = _CSS.split(".cover-piena {", 1)[1].split("}", 1)[0]
        misure = re.search(r"margin:\s*(-?[\d.]+)cm\s+(-?[\d.]+)cm\s+[\d.]+px\s+(-?[\d.]+)cm",
                           pezzo)
        self.assertTrue(misure, f"il margine della copertina non si legge: {pezzo}")
        self.assertAlmostEqual(-laterale, float(misure.group(2)), places=3)
        self.assertAlmostEqual(-laterale, float(misure.group(3)), places=3)

    def test_anche_il_blocco_del_titolo_arriva_al_bordo(self):
        html = self._html()
        self.assertIn("cover-al-vivo", html)

    def test_la_copertina_ha_ancora_la_sua_identita(self):
        # Al vivo si', ma senza perdere niente: chi guarda la prima pagina
        # deve sapere dove va, quando, e che il documento e' suo.
        html = self._html()
        prima = html.split("toc-pagina", 1)[0]
        for pezzo in ("cover-piena", "cover-title", "cover-bollo", "cover-fact"):
            with self.subTest(pezzo=pezzo):
                self.assertIn(pezzo, prima)


class TestLINDICEILLUSTRATO(unittest.TestCase):

    def _html(self, quante_foto):
        import scripts_sample_pdf
        from src.pdf_renderer import render_html

        itinerario, viaggio, kwargs, _ = scripts_sample_pdf.build_sample_render_kwargs()
        kwargs = dict(kwargs)
        kwargs.pop("output_path", None)
        identificativi = [b.get("poi_id")
                          for g in itinerario["days"] for b in (g.get("blocks") or [])
                          if isinstance(b, dict) and b.get("poi_id")]
        kwargs["photos"] = ({p: _scatto(p, quante_foto) for p in identificativi}
                            if quante_foto else {})
        return render_html(itinerario, viaggio, **kwargs)

    def test_l_indice_sta_su_una_pagina_sua(self):
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".toc-pagina {", 1)[1].split("}", 1)[0]
        self.assertIn("page-break-before: always", pezzo)

    def test_con_le_fotografie_in_abbondanza_l_indice_e_illustrato(self):
        html = self._html(4)
        indice = html.split("class='toc-pagina'", 1)[1]
        self.assertIn("toc-mini", indice)
        self.assertIn("<img", indice.split("</table>", 1)[0])

    def test_senza_fotografie_l_indice_resta_un_elenco_pulito(self):
        """Un documento senza immagini non deve peggiorare: deve solo
        restare quello di ieri. E' la regola di tutto il progetto."""
        html = self._html(0)
        indice = html.split("class='toc-pagina'", 1)[1]
        self.assertIn("toc-voce", indice)
        self.assertNotIn("<img", indice.split("</table>", 1)[0])

    def test_le_voci_senza_fotografia_prendono_tutta_la_riga(self):
        # Una colonna di riquadri vuoti sotto una colonna di fotografie si
        # legge come «qui manca qualcosa».
        html = self._html(4)
        indice = html.split("class='toc-pagina'", 1)[1]
        self.assertIn("colspan='2'", indice)

    def test_L_INDICE_NON_SVUOTA_LE_GIORNATE(self):
        """[LA PROVA PIU' IMPORTANTE DI QUESTO FILE.]

        Le miniature vengono dalla stessa scorta delle giornate. Alla prima
        stesura se la mangiavano: sei miniature in cima e tre giornate senza
        fila di chiusura. Misurato, e riparato facendo si' che l'indice si
        serva solo di cio' che avanza davvero.
        """
        with_foto = self._html(2)
        # Sull'ATTRIBUTO, non sul nome della classe: il nome compare anche
        # nel foglio di stile, e tagliare li' vorrebbe dire guardare il CSS
        # invece dell'indice. Ci sono cascato scrivendo questa prova.
        indice = with_foto.split("class='toc-pagina'", 1)[1]
        prima_tabella = indice.split("</table>", 1)[0]
        self.assertNotIn("<img", prima_tabella,
                         "con due fotografie per luogo l'indice se ne prende "
                         "una: le giornate restano senza fila di chiusura")
        self.assertIn("day-striscia", with_foto,
                      "la fila di chiusura delle giornate e' sparita")


class TestLAPROSADELLESCHEDESTAINCOLONNE(unittest.TestCase):

    def _scheda(self, paragrafi):
        from src import poi_pdf

        storia = "\n\n".join(f"Paragrafo numero {i}, con abbastanza parole da "
                             "occupare qualche riga di stampa vera."
                             for i in range(paragrafi))
        return poi_pdf.build_guide_html(
            {"poi_id": "A", "poi_name": "Duomo", "title": "Il Duomo",
             "history_summary": storia,
             "curiosita": ["una curiosita'", "due curiosita'"],
             "practical_tips": ["un consiglio", "due consigli"]},
            destination="Siena")

    @staticmethod
    def _solo_la_storia(html):
        """Il contenuto del riquadro della storia, e nient'altro.

        Serve tagliare stretto: SOTTO la storia c'e' il corpo della scheda,
        che sta su due colonne da sempre. Guardando una finestra piu' larga
        si troverebbe quella tabella e si crederebbe che la storia sia gia'
        in colonne — ci sono cascato scrivendo questa prova, ed e' il modo
        piu' rapido di scrivere un controllo sempre verde.
        """
        dentro = html.split("<div class='corpo'>", 1)[1]
        return dentro.split("</div><table class='guida-colonne'", 1)[0]

    def test_la_storia_sta_SEMPRE_su_una_colonna(self):
        """[RIBALTATA 2026-08-18, secondo giro — richiesta di Lorenzo:
        «ottimizza al massimo il layout per il mobile».]

        Stamattina questa prova pretendeva il contrario, e la ragione era
        buona: una riga larga quanto un A4 e' faticosa, ed e' il motivo per
        cui le riviste sono in colonne da un secolo e mezzo.

        Vale sulla CARTA. Questo documento si legge da un telefono — lo dice
        il documento stesso nella lista della valigia — e un A4 a due
        colonne su uno schermo da sei pollici obbliga a ingrandire, leggere
        mezza pagina, tornare su e rileggere l'altra meta'. Su schermo le
        colonne non dimezzano la fatica: la raddoppiano.

        Restano a due colonne gli ELENCHI corti sotto la storia: voci di
        poche righe, dove l'occhio non torna indietro.
        """
        for quanti in (1, 4):
            with self.subTest(paragrafi=quanti):
                self.assertNotIn("guida-colonne",
                                 self._solo_la_storia(self._scheda(quanti)))

    def test_gli_elenchi_corti_restano_su_due_colonne(self):
        # Li' le colonne dimezzano l'altezza senza costare niente a chi
        # legge: sono voci brevi, non un testo continuo.
        self.assertIn("guida-colonne", self._scheda(4))

    def test_con_un_paragrafo_solo_non_si_divide_niente(self):
        """Mezza colonna di testo e mezza vuota sarebbe peggio di una riga
        larga: le colonne servono a dimezzare l'altezza, non a fare scena.

        Si cerca la classe delle due colonne e non un `<td>` qualunque: il
        paragrafo viaggia comunque dentro una tabella a una cella, quella
        che gli impedisce di spezzarsi fra due pagine. Ci sono cascato
        scrivendo questa prova.
        """
        storia = self._solo_la_storia(self._scheda(1))
        self.assertNotIn("guida-colonne", storia)

    def test_gli_elenchi_restano_dentro_il_loro_elenco(self):
        """[CORREZIONE DI UN DIFETTO VERO, non un abbellimento.]

        Le voci finivano in `parti` mentre l'elenco che le contiene finiva
        in `corpo`: i pallini uscivano FUORI dal loro `<ul>` e fuori dalle
        due colonne, stampati a tutta larghezza in fondo alla scheda,
        staccati dal titolo che li annunciava. Un refuso di una lettera.
        """
        html = self._scheda(3)
        self.assertTrue(re.search(r"<ul>(?:<li>[^<]*</li>)+</ul>", html),
                        "i pallini sono di nuovo fuori dal loro elenco")

    def test_i_consigli_restano_dentro_il_loro_riquadro(self):
        html = self._scheda(3)
        riquadro = html.split("class='riquadro'", 1)[1].split("</div>", 1)[0]
        self.assertIn("<li>", riquadro)


if __name__ == "__main__":
    unittest.main()


class TestLACOLONNADELLALEGENDANONRESTAVUOTA(unittest.TestCase):
    """[Segnalazione di Lorenzo sull'anteprima: «dopo il titolo Basilica di
    San Domenico c'e' uno spazio bianco orribile».]

    Aveva ragione e il difetto era strutturale, non estetico: la cartina sta
    a sinistra e la legenda a destra, ma la legenda e' alta un terzo della
    cartina — sotto le sue righe restava mezza colonna bianca, su OGNI
    giornata di OGNI documento.

    La fotografia messa li' non allunga niente: occupa spazio che c'era gia'
    ed era vuoto. Ed e' l'impianto delle brochure — cartina e immagini
    affiancate, non una sotto l'altra.
    """

    def _cartina(self, quante_tappe=4):
        from PIL import Image

        fuori = io.BytesIO()
        Image.new("RGB", (640, 400), (200, 210, 200)).save(fuori, format="PNG")
        return {
            "png": fuori.getvalue(),
            "hotel_point": (43.3, 11.3),
            "stops": [{"poi_id": f"P{i}", "label": str(i + 1),
                       "name": f"Tappa {i}", "color": "blue"}
                      for i in range(quante_tappe)],
        }

    def test_con_una_legenda_corta_la_colonna_si_riempie(self):
        from src import pdf_renderer as R

        photos = {f"P{i}": _scatto(f"p{i}", 3) for i in range(4)}
        uscita = R._riempi_la_colonna_della_legenda(self._cartina(4), photos, set())
        self.assertIn("<img", uscita)
        self.assertIn("key-foto", uscita)

    def test_con_una_legenda_lunga_non_si_infila_niente(self):
        """Se le tappe sono tante la colonna e' gia' piena: una fotografia
        li' allungherebbe il blocco invece di riempire un vuoto, ed e' il
        difetto opposto — gia' misurato il 18 agosto attaccando la
        fotografia alla cartina."""
        from src import pdf_renderer as R

        photos = {f"P{i}": _scatto(f"p{i}", 3) for i in range(14)}
        self.assertEqual(
            "", R._riempi_la_colonna_della_legenda(self._cartina(14), photos, set()))

    def test_senza_fotografie_libere_la_colonna_resta_com_era(self):
        from src import pdf_renderer as R

        photos = {f"P{i}": _scatto(f"p{i}", 1) for i in range(4)}
        usate = {R._impronta(photos[f"P{i}"]["scatti"][0]["png"]) for i in range(4)}
        self.assertEqual(
            "", R._riempi_la_colonna_della_legenda(self._cartina(4), photos, usate))

    def test_senza_cartina_non_si_inventa_una_colonna(self):
        from src import pdf_renderer as R

        for niente in (None, {}, {"stops": []}):
            with self.subTest(valore=niente):
                self.assertEqual(
                    "", R._riempi_la_colonna_della_legenda(niente, {}, set()))

    def test_la_fotografia_esce_dal_registro_quindi_non_si_ripete(self):
        from src import pdf_renderer as R

        photos = {f"P{i}": _scatto(f"p{i}", 3) for i in range(4)}
        usate = set()
        prima = R._riempi_la_colonna_della_legenda(self._cartina(4), photos, usate)
        dopo = R._riempi_la_colonna_della_legenda(self._cartina(4), photos, usate)
        self.assertTrue(prima and dopo)
        self.assertNotEqual(prima, dopo)


class TestLEFASCEDIAPERTURACAPITOLO(unittest.TestCase):
    """Le brochure aprono le sezioni con una fotografia a tutta larghezza e
    sotto il numero col titolo. Qui la stessa cosa, con due limiti misurati.
    """

    def test_al_massimo_tre_e_non_una_per_capitolo(self):
        """Undici fotografie di apertura su undici capitoli non sono una
        rivista, sono un catalogo — e ogni fascia costa foglio."""
        from src import pdf_renderer as R

        self.assertLessEqual(R.FASCE_DI_CAPITOLO, 4)
        self.assertGreaterEqual(R.FASCE_DI_CAPITOLO, 1)

    def test_la_fascia_e_bassa_e_larga(self):
        """[MISURATO, e la misura e' costata una pagina all'8.8%.]

        Con un rapporto di 3.2 — cioe' una fascia alta cinque centimetri e
        mezzo — il blocco «fotografia piu' titolo» non entrava piu' sotto la
        testata del documento e scendeva alla pagina dopo, lasciando indietro
        un foglio con sopra solo l'intestazione. A 5.5 entra.
        """
        from src import pdf_renderer as R

        self.assertGreaterEqual(R.RAPPORTO_FASCIA_CAPITOLO, 4.5)

    def test_fotografia_e_titolo_non_si_separano_mai(self):
        from src import pdf_renderer as R

        vestita = R._disegna_testata("fascia", "costi", "Costi", 3,
                                     fascia_foto="<img src='x'>")
        self.assertTrue(vestita.startswith("<table class='keep"),
                        "la fotografia puo' restare da sola in cima a un "
                        "foglio col titolo altrove")
        self.assertIn("cap-fascia", vestita)

    def test_senza_fotografia_la_testata_resta_quella_di_sempre(self):
        from src import pdf_renderer as R

        self.assertEqual(
            R._disegna_testata("fascia", "costi", "Costi", 3),
            R._disegna_testata("fascia", "costi", "Costi", 3, fascia_foto=""))

    def test_la_fascia_non_esce_dalla_colonna(self):
        """[LA MISURA CHE HA COSTATO DUE GIRI.]

        Dentro una cella di tabella un margine negativo rende la tabella
        piu' larga della pagina: il motore la sposta al foglio dopo e lascia
        indietro una pagina all'8%. Misurato due volte, in tutte e due le
        direzioni. La fascia resta larga quanto la colonna.
        """
        from src.pdf_renderer import _CSS

        pezzo = _CSS.split(".cap-fascia-foto {", 1)[1].split("}", 1)[0]
        self.assertNotIn("-1.8cm", pezzo)
