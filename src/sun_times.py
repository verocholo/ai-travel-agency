"""
NUOVO 2026-07-31 — luce del giorno: alba, tramonto e "ora d'oro".

Non è stato chiesto esplicitamente: è una delle aggiunte alla richiesta di
Lorenzo "io credo che anche tu abbia delle bellissime idee di miglioramento
oppure qualche funzione da aggiungere per cui aggiungile o migliora,
stupiscimi", e serve direttamente la direttrice "meteo, luce e stagione" degli
architect's tips.

PERCHÉ VALE LA PENA
-------------------
È l'informazione che cambia davvero una giornata di viaggio e che nessuno ha
mai a portata di mano: a Edimburgo a fine giugno fa luce fino quasi alle 22:00
(la cena delle 20:00 è ancora "pomeriggio"), a Siviglia a dicembre buio alle
18:10 (il belvedere delle 18:30 è al buio). Sapere quando tramonta il sole
cambia l'ordine delle attività, non è un dato decorativo.

PERCHÉ È MATEMATICA E NON UNA CHIAMATA API
-------------------------------------------
Alba e tramonto sono astronomia deterministica: dipendono solo da latitudine,
longitudine e data. Zero costo, zero quota, zero dipendenze, zero possibilità
che un fornitore restituisca un dato sbagliato — e quindi anche zero
allucinazione possibile. L'implementazione segue l'equazione del tramonto
standard (NOAA / Astronomical Almanac), con l'altitudine solare convenzionale
di -0.833° che include rifrazione atmosferica e raggio del disco solare.

L'UNICA cosa che la matematica NON dà è il fuso orario locale (che è una
convenzione politica, non astronomica): il calcolo qui produce orari UTC, e il
chiamante applica l'offset. Vedi `local_times()` — se l'offset non è noto,
preferiamo NON mostrare l'orario piuttosto che mostrarne uno sbagliato di
un'ora.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

# Altitudine del centro del disco solare all'alba/tramonto "ufficiali":
# -0.833° tiene conto della rifrazione atmosferica (~34') e del raggio
# apparente del sole (~16').
_SUNRISE_ALTITUDE_DEG = -0.833
# L'ora d'oro finisce/comincia convenzionalmente quando il sole è a 6° sopra
# l'orizzonte: è la finestra in cui la luce è calda e radente (la ragione per
# cui la stessa piazza fotografata alle 19:30 e alle 13:00 sembra due posti
# diversi).
_GOLDEN_HOUR_ALTITUDE_DEG = 6.0

_J2000 = 2451545.0
_OBLIQUITY_DEG = 23.44


class PolarDayNight(Exception):
    """Alle latitudini estreme, in certe date, il sole non sorge o non tramonta
    affatto: l'equazione non ha soluzione. Non è un errore del codice, è un
    fatto astronomico, e va detto al cliente in quei termini."""


def _julian_day(d: date) -> float:
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    jdn = (
        d.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    )
    return jdn - 0.5  # mezzanotte UTC


def _solar_event_julian(
    d: date, lat: float, lng: float, altitude_deg: float, rising: bool
) -> float:
    """Data giuliana (UTC) dell'istante in cui il sole raggiunge
    `altitude_deg` salendo (`rising=True`) o scendendo."""
    n = round(_julian_day(d) - _J2000 + 0.0008)
    j_star = n - lng / 360.0
    m_deg = (357.5291 + 0.98560028 * j_star) % 360.0
    m_rad = math.radians(m_deg)
    c = (
        1.9148 * math.sin(m_rad)
        + 0.0200 * math.sin(2 * m_rad)
        + 0.0003 * math.sin(3 * m_rad)
    )
    lambda_deg = (m_deg + c + 180.0 + 102.9372) % 360.0
    lambda_rad = math.radians(lambda_deg)
    j_transit = _J2000 + j_star + 0.0053 * math.sin(m_rad) - 0.0069 * math.sin(2 * lambda_rad)

    sin_decl = math.sin(lambda_rad) * math.sin(math.radians(_OBLIQUITY_DEG))
    decl = math.asin(sin_decl)
    lat_rad = math.radians(lat)

    numerator = math.sin(math.radians(altitude_deg)) - math.sin(lat_rad) * math.sin(decl)
    denominator = math.cos(lat_rad) * math.cos(decl)
    if denominator == 0:
        raise PolarDayNight("latitudine degenere per il calcolo solare")
    cos_omega = numerator / denominator
    if cos_omega > 1 or cos_omega < -1:
        raise PolarDayNight(
            "in questa data il sole non attraversa questa altitudine a questa latitudine"
        )
    omega_deg = math.degrees(math.acos(cos_omega))
    return j_transit + (omega_deg if not rising else -omega_deg) / 360.0


def _julian_to_datetime_utc(jd: float) -> datetime:
    return datetime(2000, 1, 1, 12, 0, 0) + timedelta(days=jd - _J2000)


def sun_events_utc(d: date, lat: float, lng: float) -> dict:
    """Alba, tramonto e confini dell'ora d'oro in UTC, per una data e un punto.

    Ritorna `{"sunrise", "sunset", "golden_morning_end", "golden_evening_start",
    "daylight_minutes"}` — datetime UTC, oppure `None` per i singoli eventi che
    in quella data a quella latitudine non avvengono (sole di mezzanotte /
    notte polare). Non solleva: il chiamante non deve gestire eccezioni per un
    dato accessorio.
    """
    def _safe(altitude, rising):
        try:
            return _julian_to_datetime_utc(_solar_event_julian(d, lat, lng, altitude, rising))
        except (PolarDayNight, ValueError):
            return None

    sunrise = _safe(_SUNRISE_ALTITUDE_DEG, True)
    sunset = _safe(_SUNRISE_ALTITUDE_DEG, False)
    daylight = None
    if sunrise and sunset and sunset > sunrise:
        daylight = round((sunset - sunrise).total_seconds() / 60)
    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "golden_morning_end": _safe(_GOLDEN_HOUR_ALTITUDE_DEG, True),
        "golden_evening_start": _safe(_GOLDEN_HOUR_ALTITUDE_DEG, False),
        "daylight_minutes": daylight,
    }


def local_times(events: dict, utc_offset_hours: float | None) -> dict:
    """Converte gli eventi UTC in stringhe `HH:MM` di ORARIO LOCALE.

    Se `utc_offset_hours` è `None` NON indoviniamo (un tramonto sbagliato di
    un'ora è peggio di nessun tramonto): ritorna tutte stringhe vuote e il
    renderer omette la riga. Il fuso è una convenzione politica, non un dato
    astronomico: va preso da una fonte vera (vedi `estimate_utc_offset_hours`
    per il ripiego, esplicitamente marcato come approssimato).
    """
    if utc_offset_hours is None:
        return {k: "" for k in ("sunrise", "sunset", "golden_morning_end", "golden_evening_start")}
    delta = timedelta(hours=utc_offset_hours)
    out = {}
    for key in ("sunrise", "sunset", "golden_morning_end", "golden_evening_start"):
        value = events.get(key)
        out[key] = (value + delta).strftime("%H:%M") if value else ""
    return out


def estimate_utc_offset_hours(lng: float) -> float:
    """Ripiego dichiaratamente APPROSSIMATO: 15° di longitudine = 1 ora.

    Corretto entro ±1h per la gran parte d'Europa in ora solare, sbagliato di
    un'ora quando è in vigore l'ora legale e in tutti i paesi il cui fuso non
    segue la longitudine (Spagna, Cina, Argentina...). Chi lo usa DEVE
    marcarlo come approssimato nel documento: vedi `describe_light()`.
    """
    return round(lng / 15.0)


def describe_light(d: date, lat: float, lng: float, utc_offset_hours: float | None = None) -> dict:
    """Riga pronta per il PDF: `{"sunrise", "sunset", "golden_evening_start",
    "daylight_label", "approximate": bool, "available": bool}`.

    Se l'offset non è fornito usa la stima da longitudine e alza
    `approximate=True`, così il documento può scrivere "orari indicativi" invece
    di spacciarli per esatti — l'alternativa (tacere del tutto) toglierebbe al
    cliente un'informazione utile per una precisione che, per decidere se il
    belvedere è meglio alle 18 o alle 20, non gli serve.
    """
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return {"available": False}
    approximate = utc_offset_hours is None
    offset = estimate_utc_offset_hours(lng_f) if approximate else utc_offset_hours
    events = sun_events_utc(d, lat_f, lng_f)
    times = local_times(events, offset)
    if not times.get("sunrise") and not times.get("sunset"):
        return {"available": False}
    minutes = events.get("daylight_minutes")
    return {
        "available": True,
        "approximate": approximate,
        "sunrise": times["sunrise"],
        "sunset": times["sunset"],
        "golden_evening_start": times["golden_evening_start"],
        "daylight_label": (
            f"{minutes // 60}h{minutes % 60:02d} di luce" if minutes else ""
        ),
    }
