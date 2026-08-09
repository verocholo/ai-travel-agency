"""Ogni libreria che il prodotto importa è dichiarata in `requirements.txt`.

PERCHÉ QUESTO FILE ESISTE

Il 5 agosto 2026, al primo deploy dopo quattro giorni, è saltato fuori che
`openpyxl` non era mai stato messo in `requirements.txt`. Lo importa
`src/checklist_xlsx.py`, cioè il modulo che costruisce il foglio della
valigia.

Cosa succedeva in produzione: la libreria non c'era, l'import falliva, e
`build_checklist_xlsx()` — che cattura ogni eccezione di proposito, perché un
errore nel foglio non deve poter togliere il PDF a chi l'ha pagato —
restituiva `None`. Il PDF usciva senza il riquadro del foglio, la mail partiva
senza allegato, e **non c'era nessun errore da nessuna parte**: né nei log, né
nella risposta, né in un test rosso.

Il difetto è durato dal giorno in cui il foglio è stato scritto fino al giorno
in cui qualcuno è andato a leggere `requirements.txt` per un altro motivo.

## Perché nessun test lo prendeva

Qui le librerie ci sono tutte: l'ambiente di sviluppo se le è trovate
installate per conto suo. La suite era verde, e sarebbe rimasta verde per
sempre. La differenza fra questa macchina e il contenitore di produzione non
la vede nessun test che gira solo qui — a meno che non guardi proprio quella
differenza, che è ciò che fa questo file.

## La forma del difetto, che è quella che conta

È lo stesso schema di tutti i guasti seri di questo progetto: **degradano
invece di rompersi**. La cartina che ripiega sullo schema, la guida che non
viene pubblicata, il collegamento che non salta, il foglio che non nasce.
Nessuno di questi fa cadere il servizio; tutti tolgono qualcosa al cliente
senza dirlo. Un errore rumoroso si sistema in un pomeriggio; uno silenzioso
resta finché qualcuno non lo cerca.
"""

import ast
import pathlib
import sys
import unittest


RADICE = pathlib.Path(__file__).resolve().parent.parent

# I file che finiscono in produzione. Gli script di prova (`debug_*.py`) e i
# test NON contano: se un giorno un test avesse bisogno di una libreria in
# più, quella non deve diventare un obbligo per il contenitore del cliente.
SORGENTI_DEL_PRODOTTO = ["service.py", "main.py"]

# Nome dell'import -> nome del pacchetto su PyPI, quando non coincidono.
# Sono pochi e vale la pena elencarli a mano: dedurli automaticamente
# richiederebbe interrogare PyPI, cioè avere rete, cioè un controllo che si
# salta da solo proprio nell'ambiente in cui deve girare.
NOME_SU_PYPI = {
    "PIL": "pillow",
    "dotenv": "python-dotenv",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
}

# Librerie che arrivano SEMPRE insieme a un'altra già dichiarata, e che quindi
# non serve elencare. Solo casi certi e documentati: werkzeug è una dipendenza
# obbligatoria di Flask, non un pacchetto che si possa trovare assente con
# Flask presente.
TIRATE_DENTRO_DA_ALTRE = {
    "werkzeug": "flask",
    "jinja2": "flask",
    "click": "flask",
}


def _moduli_esterni(percorso: pathlib.Path) -> set[str]:
    """I nomi di primo livello importati da un file, escluse le librerie
    standard e i moduli di questo progetto.

    Si legge l'albero sintattico invece del testo: un `import` dentro un
    commento o dentro una stringa non conta, e un import scritto dentro una
    funzione — che è come `checklist_xlsx` importa openpyxl, proprio il caso
    del difetto — conta eccome.
    """
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    nomi: set[str] = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nomi.add(alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom):
            # `from . import x` e `from .modulo import x` sono relativi:
            # `level` maggiore di zero, nessun modulo esterno coinvolto.
            if nodo.level == 0 and nodo.module:
                nomi.add(nodo.module.split(".")[0])
    return nomi


def _tutti_i_moduli_del_prodotto() -> dict[str, set[str]]:
    """`{nome_libreria: {file che la importano}}`."""
    interni = {p.stem for p in (RADICE / "src").glob("*.py")}
    interni |= {"src", "tests", "service", "main", "scripts_sample_pdf"}
    standard = set(sys.stdlib_module_names)

    fuori: dict[str, set[str]] = {}
    percorsi = [RADICE / n for n in SORGENTI_DEL_PRODOTTO]
    percorsi += sorted((RADICE / "src").glob("*.py"))
    for percorso in percorsi:
        if not percorso.exists():
            continue
        for nome in _moduli_esterni(percorso):
            if nome in standard or nome in interni or nome.startswith("_"):
                continue
            fuori.setdefault(nome, set()).add(
                str(percorso.relative_to(RADICE)))
    return fuori


def _dichiarate() -> set[str]:
    """I nomi dei pacchetti DAVVERO dichiarati, senza i commenti.

    [CORRETTO 2026-08-05, dieci minuti dopo aver scritto questo file — e la
    correzione vale più del file stesso.]

    La prima versione restituiva il testo intero di `requirements.txt` e i
    controlli facevano `in`. Sembrava sensato. Messo alla prova commentando
    la riga `openpyxl>=3.1`, il controllo è rimasto VERDE: la parola
    «openpyxl» compare una dozzina di volte nei commenti che spiegano perché
    quella riga è importante.

    Cioè: il controllo scritto per impedire un guasto silenzioso era esso
    stesso silenziosamente inutile, e lo era proprio a causa della
    documentazione scritta per proteggerlo.

    È la terza volta che questo progetto ci casca — era già successo con
    `class='criterio` che trovava la regola del foglio di stile, e con «Come
    si legge» che si trovava dentro un commento. La regola, ormai: **un
    controllo non deve mai cercare dentro il testo grezzo di un file che
    contiene commenti.** Si legge la struttura, non le lettere.
    """
    nomi = set()
    for riga in (RADICE / "requirements.txt").read_text(encoding="utf-8").splitlines():
        riga = riga.split("#", 1)[0].strip()
        if not riga:
            continue
        # `pacchetto>=1.2`, `pacchetto==1.2`, `pacchetto[extra]`, `pacchetto`
        nome = riga
        for separatore in (">=", "==", "<=", "~=", ">", "<", "!=", "[", ";", " "):
            nome = nome.split(separatore, 1)[0]
        if nome:
            nomi.add(nome.strip().lower())
    return nomi


class TestQuelloCheIlProdottoImportaEDichiarato(unittest.TestCase):
    """Il controllo che il 5 agosto sarebbe costato dieci secondi."""

    def test_ogni_libreria_importata_e_in_requirements(self):
        dichiarate = _dichiarate()
        mancanti = []
        for nome, files in sorted(_tutti_i_moduli_del_prodotto().items()):
            if nome in TIRATE_DENTRO_DA_ALTRE:
                continue
            pacchetto = NOME_SU_PYPI.get(nome, nome).lower()
            if pacchetto not in dichiarate:
                mancanti.append(f"{pacchetto} (importata da {', '.join(sorted(files))})")
        self.assertEqual(
            mancanti, [],
            "queste librerie non sono in requirements.txt: in produzione non "
            "verranno installate, l'import fallirà, e siccome il prodotto "
            "cattura le eccezioni per non rompersi il cliente riceverà un "
            "documento incompleto SENZA nessun errore da nessuna parte:\n  "
            + "\n  ".join(mancanti),
        )

    def test_openpyxl_in_particolare(self):
        """Il caso vero, fissato per nome.

        Il controllo generale qui sopra è quello che conta, ma un giorno
        qualcuno potrebbe allargare `TIRATE_DENTRO_DA_ALTRE` o toccare la
        lista dei sorgenti e disattivarlo senza accorgersene. Questa riga non
        si può disattivare per sbaglio: nomina la libreria e il difetto.
        """
        self.assertIn("openpyxl", _dichiarate(),
                      "senza openpyxl il foglio della valigia non nasce, in "
                      "silenzio: è già successo, per quattro giorni")

    def test_pypdf_non_e_piu_una_dipendenza_dei_soli_test(self):
        """`src/fascicolo.py` lo importa: se manca, il fascicolo si scuce.

        E si scuce in silenzio — `unisci()` cattura l'eccezione e torna il
        documento principale senza capitoli. Il cliente riceve un PDF che
        sembra completo.
        """
        importatori = _tutti_i_moduli_del_prodotto().get("pypdf", set())
        self.assertTrue(
            importatori,
            "se il prodotto non importa più pypdf, questo controllo va "
            "riscritto invece che cancellato",
        )
        self.assertIn("pypdf", _dichiarate())

    def test_gli_script_di_prova_non_impongono_niente_al_prodotto(self):
        # Il controllo guarda solo i file che finiscono nel contenitore. Se
        # guardasse anche `debug_*.py` o i test, una libreria comoda per una
        # prova diventerebbe un obbligo per il cliente.
        self.assertNotIn("scripts_sample_pdf.py", SORGENTI_DEL_PRODOTTO)
        for nome in SORGENTI_DEL_PRODOTTO:
            with self.subTest(nome=nome):
                self.assertFalse(nome.startswith("debug_"))
                self.assertFalse(nome.startswith("test_"))

    def test_il_controllo_vede_gli_import_dentro_le_funzioni(self):
        """La parte che rendeva il difetto invisibile.

        `checklist_xlsx` importa openpyxl DENTRO la funzione, non in cima al
        file. Un controllo che legge solo le prime righe di ogni sorgente non
        l'avrebbe mai visto — e sarebbe stato verde, il che è peggio che non
        averlo.
        """
        trovate = _tutti_i_moduli_del_prodotto()
        self.assertIn(
            "openpyxl", trovate,
            "l'import dentro la funzione non viene visto: questo controllo "
            "sarebbe verde su un prodotto rotto",
        )
        self.assertTrue(
            any("checklist_xlsx" in f for f in trovate["openpyxl"]))


if __name__ == "__main__":
    unittest.main()
