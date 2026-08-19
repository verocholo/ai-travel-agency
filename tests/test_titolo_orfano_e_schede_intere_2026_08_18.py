"""Il titolo non resta ultima cosa della pagina, e le schede non si tagliano.

PERCHE' QUESTO FILE ESISTE

Lorenzo, 18 agosto, sesto giro, sull'anteprima delle guide: «non spezzare la
pagina su due facciate nella guida turistica non mi piace ed evita di mettere
i titoli come ultima cosa della pagina, piuttosto vai alla pagina successiva
ma solo in quel caso».

Sono due difetti diversi, e la frase contiene anche il limite della
riparazione — «ma solo in quel caso» — che qui vale quanto la richiesta.

## Perche' non bastavano le regole che c'erano gia'

`capitoli_da_mandare_a_capo` e `capitoli_con_foto_in_coda` guardano UNA cosa
sola: quanti centimetri restano sotto il titolo. E' una stima, e sbaglia in
tutte e due le direzioni.

- Un titolo che comincia al 40% dell'altezza sembra stare comodo; se pero'
  subito sotto c'e' la fotografia della scheda — dodici centimetri che non si
  spezzano mai — la fotografia scende e il titolo resta li' da solo. Nessuna
  soglia sull'altezza del titolo puo' vederlo.
- Un titolo al 12% con quattro righe di testo sotto non e' orfano, e mandarlo
  a capo regalerebbe un ottavo di pagina bianca.

Quindi non si misura piu' il titolo: si misura DOVE E' FINITA LA PRIMA RIGA
DI TESTO. Se e' su una pagina diversa dal titolo, il titolo e' l'ultima cosa
che si legge su quel foglio — constatato, non stimato. E per il secondo
difetto si misura quanta carta occupa la scheda dall'inizio alla fine: una
scheda tagliata fra due facciate si ripara SOLO se in una facciata ci
starebbe tutta.

## LA REGOLA E' CAMBIATA LO STESSO GIORNO, E QUESTO E' IL PUNTO PIU'
## IMPORTANTE DI QUESTO FILE

Poche ore dopo, Lorenzo in maiuscolo: «NON VOGLIO CHE SPEZZI A META' LE
PAGINE DELLE GUIDE TURISTICHE. NON FARLO».

Non e' la stessa richiesta detta piu' forte: e' una richiesta piu' larga.
Non piu' «ripara i due casi brutti», ma «una facciata non contiene mai due
schede diverse». Da li' in poi ogni scheda comincia su una facciata sua, e le
schede che sbordano si fanno RIENTRARE stringendo la fotografia di apertura
invece di essere spezzate (vedi `poi_pdf.RITAGLI_DI_RIENTRO`).

Le due misure di questo file restano, e restano utili, ma cambiano mestiere:
non sono piu' riparazioni, sono CONTROLLI. Con una scheda per facciata un
titolo orfano o una scheda spezzata inutilmente non possono presentarsi; se
si presentano, vuol dire che la regola nuova si e' rotta da qualche parte, ed
e' esattamente quello che si vuole sapere.

Le classi che difendevano la regola vecchia sono state riscritte, non
cancellate: chi legge deve poter vedere che la decisione e' cambiata e
perche'.
"""

import unittest
from unittest import mock

from src import impaginazione, poi_pdf


def _guida(identificativo, righe=18):
    """La stessa scheda finta degli altri controlli delle guide."""
    return {
        "poi_id": identificativo,
        "poi_name": f"Luogo {identificativo}",
        "title": f"Luogo {identificativo}",
        "history_summary": "Una storia di questo posto. " * righe,
        "what_to_look_for": [f"dettaglio {k}" for k in range(4)],
        "practical_tips": [f"consiglio {k}, lungo quanto basta per girare riga"
                           for k in range(3)],
        "errore_da_evitare": "Arrivare senza biglietto.",
        "best_time_to_visit": "la mattina presto",
        "estimated_visit_duration": "un'ora",
    }


class TestLEDUESONDEDELLASCHEDA(unittest.TestCase):
    """Le sonde si seminano dove servono, e solo a chi le sa leggere."""

    def _html(self, **extra):
        return poi_pdf.build_guide_html(
            _guida("A"), destination="Siena", ancora_capitolo="capitolo-a",
            photo={"png": b"\xff\xd8finta", "credito": "Foto: a / Prova"},
            **extra)

    def test_senza_richiesta_la_scheda_non_porta_sonde_nuove(self):
        """Le guide PUBBLICATE da sole non hanno nessuno che le ripari.

        Una sonda che nessuno legge e' solo un'annotazione in piu' dentro un
        documento pubblico — la stessa regola gia' scritta per `sonda_banda`.
        """
        html = self._html()
        self.assertNotIn(poi_pdf.nome_sonda_testo("capitolo-a"), html)
        self.assertNotIn(poi_pdf.nome_sonda_fine("capitolo-a"), html)

    def test_quando_richieste_ci_sono_tutte_e_due(self):
        html = self._html(sonde_di_scheda=True)
        self.assertIn(poi_pdf.nome_sonda_testo("capitolo-a"), html)
        self.assertIn(poi_pdf.nome_sonda_fine("capitolo-a"), html)

    def test_la_sonda_del_testo_viaggia_sulla_prima_riga_di_testo(self):
        """Non sul titolo e non sulla fotografia: sulla prima riga di TESTO.

        E' l'unico punto che risponde alla domanda «di questa scheda, sulla
        pagina del titolo, si legge qualcosa?».
        """
        html = self._html(sonde_di_scheda=True)
        sonda = html.index(poi_pdf.nome_sonda_testo("capitolo-a"))
        titolo = html.index("Luogo A")
        testo = html.index("Una storia di questo posto")
        self.assertLess(titolo, sonda, "la sonda e' finita prima del titolo")
        self.assertLess(sonda, testo,
                        "la sonda e' finita dopo la prima riga di testo: "
                        "misurerebbe la seconda pagina di una storia lunga")

    def test_la_sonda_del_testo_non_apre_una_riga_sua(self):
        """Dentro il primo paragrafo, non accanto.

        Un elemento a se' stante, anche invisibile, apre una riga sua e
        sposta di qualche punto tutto quello che segue: qui si sta misurando
        proprio dove cadono le cose, e una misura che sposta cio' che misura
        non serve a niente.
        """
        html = self._html(sonde_di_scheda=True)
        sonda = poi_pdf._sonda(poi_pdf.nome_sonda_testo("capitolo-a"))
        self.assertIn("<p class='corpo'>" + sonda, html)

    def test_la_sonda_di_fine_sta_dentro_l_ultimo_elemento(self):
        """Fuori da una cella un `<span>` non e' HTML valido, e questo motore
        di stampa lo butterebbe via in silenzio: la sonda sparirebbe e la
        riparazione non scatterebbe mai."""
        html = self._html(sonde_di_scheda=True)
        sonda = poi_pdf._sonda(poi_pdf.nome_sonda_fine("capitolo-a"))
        self.assertIn(sonda, html)
        dopo = html.split(sonda, 1)[1]
        self.assertTrue(dopo.lstrip().startswith(("</td>", "</p>", "</div>")),
                        f"la sonda di fine e' rimasta allo scoperto: {dopo[:40]!r}")

    def test_la_sonda_di_fine_e_davvero_in_fondo(self):
        """Il righello ha due estremi: se il secondo si ferma prima della
        fila di fotografie, la scheda risulta piu' corta di com'e' e una
        scheda spezzata sembra starci in una facciata."""
        html = poi_pdf.build_guide_html(
            _guida("A"), destination="Siena", ancora_capitolo="capitolo-a",
            photo={"png": b"\xff\xd8finta", "credito": "Foto: a / Prova"},
            foto_extra=[{"png": b"\xff\xd8uno", "credito": "Foto: 1"},
                        {"png": b"\xff\xd8due", "credito": "Foto: 2"},
                        {"png": b"\xff\xd8tre", "credito": "Foto: 3"},
                        {"png": b"\xff\xd8qua", "credito": "Foto: 4"}],
            sonde_di_scheda=True)
        sonda = html.index(poi_pdf.nome_sonda_fine("capitolo-a"))
        self.assertLess(html.rindex("<img"), sonda,
                        "la sonda di fine e' finita prima dell'ultima "
                        "fotografia: misura una scheda piu' corta del vero")

    def test_le_sonde_non_sono_punti_di_atterraggio(self):
        """Nessun bottone ci porta: il controllo «ogni ancora ha un rimando»
        deve saperlo, o grida senza motivo — ed e' il modo in cui i controlli
        veri smettono di funzionare."""
        self.assertTrue(impaginazione.e_sonda_di_misura("capitolo-a-testo"))
        self.assertTrue(impaginazione.e_sonda_di_misura("capitolo-a-fine"))
        self.assertFalse(impaginazione.e_sonda_di_misura("capitolo-a"))


class TestILTITOLONONRESTAULTIMACOSADELLAPAGINA(unittest.TestCase):
    """`titoli_orfani()`: il difetto si constata, non si stima."""

    def _con(self, finte):
        coppie = [(a, poi_pdf.nome_sonda_testo(a))
                  for a in ("capitolo-uno", "capitolo-due")]
        with mock.patch.object(impaginazione, "posizioni", lambda _d: finte):
            return impaginazione.titoli_orfani(b"finto", coppie)

    def test_il_testo_sulla_pagina_dopo_e_un_titolo_orfano(self):
        alta = impaginazione.ALTEZZA_A4_PT * 0.40
        orfani = self._con({
            # Il titolo comincia al 40% dell'altezza: una soglia direbbe che
            # sta comodo. Ma il testo e' finito sul foglio dopo — sotto il
            # titolo era rimasta solo la fotografia, che non ci stava.
            "capitolo-uno": (2, alta),
            "capitolo-uno-testo": (3, impaginazione.ALTEZZA_A4_PT * 0.90),
            "capitolo-due": (4, alta),
            "capitolo-due-testo": (4, alta - 60.0),
        })
        self.assertEqual({"capitolo-uno"}, orfani)

    def test_un_titolo_basso_col_testo_sotto_non_si_tocca(self):
        """«Ma solo in quel caso»: un titolo al 12% con quattro righe di
        testo sotto non e' orfano, e' l'inizio di un pezzo. Mandarlo a capo
        regalerebbe un ottavo di pagina bianca."""
        basso = impaginazione.ALTEZZA_A4_PT * 0.12
        orfani = self._con({
            "capitolo-uno": (1, basso),
            "capitolo-uno-testo": (1, basso - 40.0),
            "capitolo-due": (1, basso),
            "capitolo-due-testo": (1, basso - 40.0),
        })
        self.assertEqual(set(), orfani)

    def test_una_scheda_senza_sonda_non_inventa_un_difetto(self):
        """Una scheda senza storia non semina la sonda del testo. Meglio
        nessuna riparazione che una riparazione decisa al buio."""
        orfani = self._con({"capitolo-uno": (1, 100.0)})
        self.assertEqual(set(), orfani)

    def test_senza_sonde_non_si_ripara_niente(self):
        self.assertEqual(set(), impaginazione.titoli_orfani(
            b"non un pdf", [("x", "x-testo")]))


class TestUNASCHEDANONSITAGLIAFRADUEFACCIATE(unittest.TestCase):
    """`schede_spezzate()`: si ripara solo cio' che ci starebbe intero."""

    ALTA = impaginazione.ALTEZZA_A4_PT
    MARGINE = impaginazione.MARGINE_VERTICALE_GUIDA_PT
    UTILE = impaginazione.ALTEZZA_A4_PT - 2 * impaginazione.MARGINE_VERTICALE_GUIDA_PT

    def _con(self, finte):
        with mock.patch.object(impaginazione, "posizioni", lambda _d: finte):
            return impaginazione.schede_spezzate(
                b"finto", [("capitolo-uno", "capitolo-uno-fine")])

    def test_una_scheda_corta_tagliata_a_meta_si_ripara(self):
        """Un terzo di facciata sotto e un terzo sopra: mezza facciata in
        tutto, spezzata in due solo perche' e' cominciata in fondo."""
        spezzate = self._con({
            "capitolo-uno": (1, self.MARGINE + self.UTILE * 0.25),
            "capitolo-uno-fine": (2, self.ALTA - self.MARGINE - self.UTILE * 0.25),
        })
        self.assertEqual({"capitolo-uno"}, spezzate)

    def test_una_scheda_piu_lunga_di_una_facciata_si_lascia_stare(self):
        """Si spezzerebbe comunque, in questo come in qualunque libro:
        mandarla a capo sposterebbe il taglio di qualche riga e lascerebbe
        indietro mezzo foglio bianco."""
        spezzate = self._con({
            "capitolo-uno": (1, self.MARGINE + self.UTILE * 0.80),
            "capitolo-uno-fine": (2, self.ALTA - self.MARGINE - self.UTILE * 0.50),
        })
        self.assertEqual(set(), spezzate)

    def test_una_scheda_lunghissima_non_e_un_difetto(self):
        """Tre facciate: il conto la esclude da solo, senza un caso a parte —
        una facciata intera in mezzo basta gia' a sforare."""
        spezzate = self._con({
            "capitolo-uno": (1, self.MARGINE + self.UTILE * 0.90),
            "capitolo-uno-fine": (3, self.ALTA - self.MARGINE - self.UTILE * 0.30),
        })
        self.assertEqual(set(), spezzate)

    def test_una_scheda_tutta_in_una_facciata_non_si_tocca(self):
        spezzate = self._con({
            "capitolo-uno": (1, self.MARGINE + self.UTILE * 0.90),
            "capitolo-uno-fine": (1, self.MARGINE + self.UTILE * 0.20),
        })
        self.assertEqual(set(), spezzate)

    def test_senza_sonde_non_si_ripara_niente(self):
        self.assertEqual(set(), impaginazione.schede_spezzate(
            b"non un pdf", [("x", "x-fine")]))


def _stampa_il_blocco(lunghezze, riparando: bool):
    """Il blocco delle guide, con o senza la riparazione nuova.

    Spegnere la riparazione invece di confrontarsi con un numero scritto a
    mano e' l'unico modo perche' il confronto resti vero anche fra sei mesi:
    un numero fisso misura il documento di oggi, questo misura la differenza
    che fa la riparazione — che e' la cosa di cui si discute.
    """
    guide = [_guida(f"P{i}", righe=r) for i, r in enumerate(lunghezze)]
    foto = {f"P{i}": {"png": b"\xff\xd8finta" + bytes([i]),
                      "credito": f"Foto: {i} / Prova"}
            for i in range(len(guide))}

    def _costruisci():
        return poi_pdf.costruisci_capitoli(guide, destination="Siena",
                                           photos=foto)

    if riparando:
        capitoli = _costruisci()
    else:
        with mock.patch.object(impaginazione, "titoli_orfani",
                               lambda *a, **k: set()), \
             mock.patch.object(impaginazione, "schede_spezzate",
                               lambda *a, **k: set()):
            capitoli = _costruisci()
    blob = next((c["pdf"] for c in capitoli if c["pdf"]), b"")
    return blob, [c["ancora"] for c in capitoli]


def _difetti(blob, ancore):
    """I due difetti misurati sul documento stampato, come li vede chi ripara."""
    riparabili = ancore[1:]
    return (impaginazione.titoli_orfani(
                blob, [(a, poi_pdf.nome_sonda_testo(a)) for a in riparabili])
            | impaginazione.schede_spezzate(
                blob, [(a, poi_pdf.nome_sonda_fine(a)) for a in riparabili]))


class TestUNASCHEDAUNAFACCIATA(unittest.TestCase):
    """La prova vera: si stampa il blocco delle guide e lo si rimisura.

    [RISCRITTA 2026-08-18, settimo giro, e il motivo va scritto.] Stamattina
    questa classe verificava che le due riparazioni non costassero pagine,
    perche' la regola di allora era «piuttosto accorpa». Poi Lorenzo, in
    maiuscolo: «NON VOGLIO CHE SPEZZI A META' LE PAGINE DELLE GUIDE
    TURISTICHE. NON FARLO».

    Adesso la regola e' un'altra e le due misure di sopra restano vere ma
    diventano CONTROLLI invece che riparazioni: con una scheda per facciata,
    un titolo orfano o una scheda spezzata inutilmente non possono nemmeno
    presentarsi. Se si presentassero, vorrebbe dire che la regola nuova si e'
    rotta da qualche parte — ed e' proprio quello che si vuole sapere.

    Le lunghezze delle schede sono diverse apposta: schede tutte uguali
    cadrebbero tutte nello stesso punto della pagina e i difetti non si
    presenterebbero mai. Una prova che non puo' fallire non protegge niente.
    """

    LUNGHEZZE = (40, 55, 35, 70, 45, 60)

    @classmethod
    def setUpClass(cls):
        cls.dopo, cls.ancore = _stampa_il_blocco(cls.LUNGHEZZE, riparando=True)
        cls.dove = impaginazione.posizioni(cls.dopo)

    def test_nessuna_facciata_contiene_due_schede(self):
        """Il difetto segnalato, detto con precisione: una facciata con la
        coda di una scheda e la testa di un'altra."""
        partenze = [self.dove[a][0] for a in self.ancore if a in self.dove]
        self.assertTrue(partenze, "nessuna ancora misurabile")
        self.assertEqual(len(partenze), len(set(partenze)),
                         f"due schede sulla stessa facciata: {partenze}")

    def test_nessun_difetto_di_impaginazione_resta(self):
        rimasti = _difetti(self.dopo, self.ancore)
        self.assertEqual(set(), rimasti, f"difetti rimasti: {sorted(rimasti)}")

    def test_le_schede_rientrano_invece_di_sbordare(self):
        """La meta' che rende la regola sostenibile.

        Una scheda per facciata, da sola, riporterebbe il difetto di
        partenza: schede lunghe una facciata e un quinto, e un foglio su due
        riempito al 20%. Il rientro (`RITAGLI_DI_RIENTRO`) le fa entrare
        stringendo la fotografia di apertura, senza togliere una parola.
        """
        misure = poi_pdf._misura_le_schede(self.dopo, self.ancore)
        self.assertTrue(misure, "nessuna scheda misurabile")
        sbordano = [a for a, (facciate, _av, _coda) in misure.items() if facciate]
        self.assertEqual([], sbordano,
                         f"schede che sbordano sulla facciata dopo: {sbordano}")

    def test_il_blocco_non_costa_piu_di_una_facciata_a_scheda(self):
        """Il conto che tiene onesta la regola: nove schede, nove facciate.

        Se il blocco costasse due facciate a scheda vorrebbe dire che il
        rientro non funziona e si sta solo sprecando carta — il difetto che
        Lorenzo aveva segnalato tre giri fa.
        """
        pagine = impaginazione.quante_pagine(self.dopo)
        self.assertLessEqual(pagine, len(self.ancore) + 1,
                             f"{pagine} facciate per {len(self.ancore)} schede")

    def test_le_sonde_si_leggono_davvero_sul_documento_stampato(self):
        """Il controllo che protegge tutti gli altri dall'essere vuoti.

        Se le sonde non finissero nel PDF — nome sbagliato, `<span>` buttato
        via dal motore, sonda seminata solo in teoria — le due misure
        tornerebbero l'insieme vuoto e i controlli qui sopra passerebbero
        senza guardare niente. E' gia' successo tre volte su questo prodotto,
        in tre modi diversi.
        """
        dove = impaginazione.posizioni(self.dopo)
        for ancora in self.ancore:
            with self.subTest(scheda=ancora):
                self.assertIn(poi_pdf.nome_sonda_testo(ancora), dove)
                self.assertIn(poi_pdf.nome_sonda_fine(ancora), dove)


class TestSCHEDECORTEQUANDOAVANZAFOGLIO(unittest.TestCase):
    """Schede corte: la facciata avanza, e il bianco si riempie di fotografie.

    [MISURATO il 18 agosto, settimo giro.] Con una scheda per facciata, una
    scheda che occupa mezzo foglio ne lascia mezzo bianco. Non si allunga il
    testo e non si allargano i margini: si mette in fondo la fila di
    fotografie del posto, che e' la risposta di sempre di questo prodotto
    allo spazio vuoto — la stessa gia' usata per le giornate del documento
    principale.

    Il ciclo che decide sta in `costruisci_capitoli`; qui si controlla che
    non faccia il danno opposto, cioe' che la fila di chiusura non faccia
    sbordare la scheda che doveva riempire.
    """

    LUNGHEZZE = (6, 22, 9, 30, 7, 14, 5, 25)

    @classmethod
    def setUpClass(cls):
        cls.dopo, cls.ancore = _stampa_il_blocco(cls.LUNGHEZZE, riparando=True)

    def test_nessuna_scheda_sborda(self):
        misure = poi_pdf._misura_le_schede(self.dopo, self.ancore)
        self.assertTrue(misure)
        sbordano = [a for a, (facciate, _av, _coda) in misure.items() if facciate]
        self.assertEqual([], sbordano,
                         f"la fila di riempimento ha fatto sbordare: {sbordano}")

    def test_ogni_scheda_ha_la_sua_facciata(self):
        dove = impaginazione.posizioni(self.dopo)
        partenze = [dove[a][0] for a in self.ancore if a in dove]
        self.assertEqual(len(partenze), len(set(partenze)),
                         f"due schede sulla stessa facciata: {partenze}")

    def test_la_soglia_di_riempimento_e_dichiarata_e_sensata(self):
        """Sotto il 28% di foglio avanzato non si aggiunge niente: la fila e'
        alta circa un quarto di facciata, e chiederla quando ne avanza meno
        vorrebbe dire creare il difetto che si stava togliendo."""
        self.assertGreater(poi_pdf.QUOTA_DI_RIEMPIMENTO, 0.25)
        self.assertLess(poi_pdf.QUOTA_DI_RIEMPIMENTO, 0.40)
