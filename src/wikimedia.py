"""
Fotografie libere da Wikimedia Commons — task #189.

PERCHE' NON BASTAVANO LE FOTO DI GOOGLE

Le fotografie di Google Places sono ottime e sempre pertinenti, ma le
condizioni d'uso di Google Maps Platform limitano quanto a lungo si possono
conservare e in che forma si possono ridistribuire. Il nostro prodotto e' un
PDF che il cliente paga, scarica e tiene per sempre: e' esattamente il caso
in cui quel limite pesa di piu'. Non e' un problema teorico — e' la
differenza fra un prodotto che si puo' vendere a mille persone e uno che si
puo' vendere finche' nessuno guarda.

Wikimedia Commons contiene solo materiale con licenza libera: si puo'
ridistribuire, anche a pagamento, anche modificato, a una condizione sola —
che l'autore e la licenza siano scritti accanto all'immagine. Per questo
`cerca_immagine()` non restituisce mai dei byte da soli: restituisce sempre
anche l'attribuzione, e chi la usa senza stamparla sta violando la licenza.
La didascalia non e' decorazione, e' la licenza.

IL LIMITE, DETTO SUBITO

Su Commons ci sono milioni di fotografie di monumenti e quasi nessuna di
trattorie. Per le attrazioni vere questa fonte copre quasi tutto; per un
ristorante di quartiere non trovera' niente, e li' si ripiega su Google e poi
sulla grafica disegnata in casa. E' una scala di ripieghi dichiarata, non un
tentativo di far sembrare che ci siano foto ovunque.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass

import requests


API = "https://commons.wikimedia.org/w/api.php"

# Le licenze che permettono la ridistribuzione commerciale. L'elenco e' una
# lista di ammessi, non di vietati: una licenza nuova o sconosciuta viene
# scartata invece di essere accettata per distrazione. Il rischio dei due
# errori non e' simmetrico — una foto in meno costa una copertina disegnata,
# una foto di troppo costa una diffida.
LICENZE_AMMESSE = (
    "cc0", "cc-zero", "public domain", "pd-", "cc by", "cc-by",
)

# Le sigle che compaiono nelle licenze NON commerciali o non derivabili.
# Vanno cercate PRIMA di quelle ammesse, perche' "cc by-nc" contiene "cc by":
# controllare solo gli ammessi accetterebbe proprio quelle da rifiutare.
LICENZE_VIETATE = ("nc", "nd", "fair use", "non-free", "nonfree")

# wkhtmltopdf non sa disegnare un'immagine vettoriale: un file .svg messo
# nel documento non da' errore, semplicemente lascia un buco bianco.
ESTENSIONI_BUONE = (".jpg", ".jpeg", ".png")

LARGHEZZA = 900

# --- L'interruttore automatico ---------------------------------------------
#
# Quando Commons non risponde, non risponde per TUTTE le attrazioni, non per
# una. Senza questo interruttore un itinerario da venti tappe aspetterebbe
# venti volte la stessa attesa massima prima di arrendersi: fino a quattro
# minuti buttati, dentro uno scenario Make che ne ha 300 secondi in tutto e
# che ne ha gia' sforati (356 s misurati). Il cliente perderebbe l'itinerario
# che ha pagato per colpa di fotografie che erano un di piu'.
#
# Quindi: dopo MAX_GUASTI_DI_RETE guasti di RETE consecutivi la fonte si
# spegne da sola e le chiamate successive tornano subito `None`. Un guasto di
# rete non e' la stessa cosa di "questa trattoria su Commons non c'e'": il
# secondo e' un esito normale e non spegne niente, altrimenti tre ristoranti
# di fila basterebbero a far sparire le fotografie dei monumenti che seguono.
#
# L'interruttore si riarma da solo dopo RIPROVA_DOPO_SECONDI, perche' questo
# processo serve molte richieste: un'interruzione di trenta secondi non deve
# lasciare senza fotografie tutti gli itinerari del resto della giornata.
MAX_GUASTI_DI_RETE = 2
RIPROVA_DOPO_SECONDI = 300

_guasti_di_rete = 0
_spento_da: float | None = None


def azzera_interruttore() -> None:
    """Riaccende la fonte a mano. Serve ai controlli, e a un riavvio pulito."""
    global _guasti_di_rete, _spento_da
    _guasti_di_rete = 0
    _spento_da = None


def fonte_spenta() -> bool:
    """Vero finche' l'interruttore e' scattato e non si e' ancora riarmato."""
    global _guasti_di_rete, _spento_da
    if _spento_da is None:
        return False
    if (time.monotonic() - _spento_da) >= RIPROVA_DOPO_SECONDI:
        azzera_interruttore()
        return False
    return True


def _segna_guasto_di_rete() -> None:
    global _guasti_di_rete, _spento_da
    _guasti_di_rete += 1
    if _guasti_di_rete >= MAX_GUASTI_DI_RETE and _spento_da is None:
        _spento_da = time.monotonic()


@dataclass(frozen=True)
class ImmagineLibera:
    """Una fotografia con dentro tutto quello che serve per pubblicarla."""
    titolo: str
    byte: bytes
    licenza: str
    autore: str
    pagina: str

    def didascalia(self) -> str:
        """La riga che DEVE comparire sotto la fotografia.

        Non e' un commento sulla foto: e' la condizione a cui la foto si puo'
        usare. Se un giorno qualcuno la togliesse per motivi di grafica,
        toglierebbe la licenza insieme alla riga.
        """
        pezzi = []
        if self.autore:
            pezzi.append(self.autore)
        pezzi.append("Wikimedia Commons")
        if self.licenza:
            pezzi.append(self.licenza)
        return "Foto: " + " / ".join(pezzi)


def _testo_semplice(grezzo: object) -> str:
    """Il campo autore di Commons arriva come HTML, con dentro dei link.

    Infilato in un PDF cosi' com'e' stamperebbe i marcatori, oppure — molto
    peggio — aprirebbe un tag che sbilancia il resto della pagina.
    """
    senza_tag = re.sub(r"<[^>]+>", " ", str(grezzo or ""))
    return re.sub(r"\s+", " ", html.unescape(senza_tag)).strip()[:120]


def licenza_ammessa(licenza: str) -> bool:
    """Vero solo per le licenze che permettono di vendere il documento."""
    testo = (licenza or "").strip().lower()
    if not testo:
        return False
    # I divieti si cercano a pezzi separati, non come sottostringhe: "nc"
    # dentro "Encyclopedia" non e' una licenza non commerciale.
    pezzi = re.split(r"[\s\-_/]+", testo)
    if any(p in LICENZE_VIETATE for p in pezzi):
        return False
    if any(v in testo for v in ("fair use", "non-free", "nonfree")):
        return False
    return any(a in testo for a in LICENZE_AMMESSE)


def _candidati(dati: dict) -> list[dict]:
    pagine = ((dati or {}).get("query") or {}).get("pages") or {}
    if isinstance(pagine, dict):
        elenco = list(pagine.values())
    else:
        elenco = list(pagine)
    # L'ordine che Commons restituisce e' quello di pertinenza della ricerca:
    # va conservato, e un dizionario in Python 3.7+ lo conserva gia'.
    return [p for p in elenco if isinstance(p, dict)]


def _prima_utilizzabile(pagine: list[dict]) -> dict | None:
    """La scheda della prima fotografia scaricabile, senza scaricarla.

    Separare la SCELTA dallo SCARICAMENTO serve a poter provare la regola
    delle licenze — che e' la parte rischiosa — su una risposta finta, senza
    rete e senza scaricare niente. Ritorna una scheda con dentro anche
    l'indirizzo da cui prendere i byte, che non e' un dato della fotografia
    ma un passaggio intermedio, e infatti nella fotografia finita non c'e'.
    """
    for pagina in pagine:
        titolo = str(pagina.get("title") or "")
        if not titolo.lower().endswith(ESTENSIONI_BUONE):
            continue
        info = (pagina.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licenza = _testo_semplice((meta.get("LicenseShortName") or {}).get("value"))
        if not licenza_ammessa(licenza):
            continue
        indirizzo = info.get("thumburl") or info.get("url")
        if not indirizzo:
            continue
        return {
            "titolo": titolo[5:] if titolo.lower().startswith("file:") else titolo,
            "licenza": licenza,
            "autore": _testo_semplice((meta.get("Artist") or {}).get("value")),
            "pagina": str(info.get("descriptionurl") or indirizzo),
            "indirizzo": str(indirizzo),
        }
    return None


def cerca_immagine(nome: str, contesto: str = "",
                   timeout: int = 12) -> ImmagineLibera | None:
    """La prima fotografia libera e utilizzabile per questo luogo, o niente.

    Non solleva mai: una fotografia mancante deve costare una fotografia, mai
    il documento. Ogni intoppo — rete assente, Commons lento, risposta
    inattesa, nessun risultato, solo risultati con licenza sbagliata — esce
    dalla stessa porta, `None`, e il chiamante ripiega.
    """
    termine = " ".join(p for p in (str(nome or "").strip(),
                                   str(contesto or "").strip()) if p)
    if not termine:
        return None
    if fonte_spenta():
        return None
    try:
        risposta = requests.get(
            API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": termine,
                "gsrnamespace": "6",   # 6 = spazio dei File
                "gsrlimit": "8",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": str(LARGHEZZA),
            },
            headers={"User-Agent": "AI-Travel-Agency/1.0 (itinerari personalizzati)"},
            timeout=timeout,
        )
        risposta.raise_for_status()
        # Commons ha risposto: qualunque cosa abbia detto, la rete c'e'.
        # L'interruttore si riarma qui e solo qui.
        azzera_interruttore()
        scelta = _prima_utilizzabile(_candidati(risposta.json()))
        if scelta is None:
            # Nessuna fotografia utilizzabile NON e' un guasto: e' l'esito
            # normale per una trattoria. Non deve spegnere niente.
            return None
        scaricata = requests.get(
            scelta["indirizzo"],
            headers={"User-Agent": "AI-Travel-Agency/1.0 (itinerari personalizzati)"},
            timeout=timeout,
        )
        scaricata.raise_for_status()
        if not str(scaricata.headers.get("Content-Type") or "").startswith("image/"):
            return None
        if not scaricata.content:
            return None
        return ImmagineLibera(
            titolo=scelta["titolo"],
            byte=scaricata.content,
            licenza=scelta["licenza"],
            autore=scelta["autore"],
            pagina=scelta["pagina"],
        )
    except requests.RequestException as e:
        # Rete assente, DNS muto, Commons lento o irraggiungibile: e' il caso
        # che vale per tutte le attrazioni insieme, e l'unico che deve far
        # scattare l'interruttore.
        _segna_guasto_di_rete()
        print(f"⚠️  wikimedia: rete non raggiungibile per «{termine}» — "
              f"{type(e).__name__}: {e}")
        return None
    except Exception as e:  # noqa: BLE001 — vedi docstring
        # Risposta inattesa, JSON malformato, campo mancante: e' un problema
        # di QUESTA ricerca, non della rete. Si ripiega e si prosegue.
        print(f"⚠️  wikimedia: nessuna foto per «{termine}» — "
              f"{type(e).__name__}: {e}")
        return None
