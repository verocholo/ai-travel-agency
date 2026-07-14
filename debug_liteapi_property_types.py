#!/usr/bin/env python3
"""
Script di DEBUG, non fa parte della pipeline (main.py). Nato da una domanda
di prodotto di Lorenzo — vedi prototipo-status.md/CHANGELOG.md 2026-07-11:
"vorrei che il software fosse collegato non solo a Booking ma anche ad altre
piattaforme di alloggio (es. Airbnb...)".

Prima di proporre soluzioni, ho verificato con una ricerca web cosa è
davvero fattibile (le fonti sono in CHANGELOG.md):
- Airbnb: NON ha un'API self-service per cercare/prenotare come terze parti
  — solo un "API Program" su invito, pensato per software di gestione host,
  che nei suoi stessi Termini di Servizio VIETA di costruire "un prodotto o
  servizio che compete con o offre funzionalità simili" al programma
  stesso. Non è un gate temporaneo come Amadeus: è un muro strutturale per
  una startup come la nostra.
- Vrbo (Expedia Rapid API, include affitti vacanza): tecnicamente più
  aperto di Airbnb ma stesso identico problema di gate di Booking.com
  Affiliate (già scartato a suo tempo per questo): niente self-service,
  serve una domanda con fatturato/volume e revisione caso per caso.
- LiteAPI (quello che usiamo già): si presenta pubblicamente come
  aggregatore di "300+ fornitori, 2.6M+ hotel", ma la documentazione usa
  quasi sempre terminologia hotel-specifica. C'è però un indizio concreto:
  l'endpoint `data/hotels` accetta un parametro `hotelTypeIds` per
  filtrare — il che implica che i risultati SONO già classificati per
  tipo di proprietà, non solo "hotel" genericamente. Se tra questi tipi
  ci fossero anche appartamenti/ville/aparthotel, avremmo già oggi,
  senza nessuna nuova partnership, un'offerta di alloggio più ampia del
  solo hotel tradizionale — semplicemente non lo sappiamo ancora, perché
  nessuna chiamata reale lo ha mai verificato (stesso principio di onestà
  già applicato a tutto il resto di questo prototipo: MAI fidarsi della
  sola documentazione quando è ambigua).

Questo script verifica ESATTAMENTE questo, con due chiamate reali:
1. `GET /data/hotelTypes` — la lista completa e statica dei tipi di
   proprietà che LiteAPI conosce (es. "Hotel", "Apartment", "Villa",
   "Hostel", ...). Nessuna chiamata di questo tipo era mai stata fatta
   prima in questo progetto.
2. `GET /data/hotels` (stesso endpoint già usato dalla pipeline reale) su
   una destinazione a scelta, per vedere se le entry reali riportano un
   campo di tipo proprietà (`hotelTypeId` o simile — il nome esatto non è
   documentato in modo affidabile, lo scopriamo qui) e, se sì, quanti tipi
   diversi da "Hotel" compaiono davvero in una ricerca reale.

Uso:
  python debug_liteapi_property_types.py
  python debug_liteapi_property_types.py "Lisbona, Portogallo" --radius-km 8

Richiede GOOGLE_MAPS_KEY e LITEAPI_KEY nel tuo .env (le stesse della pipeline).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import SETTINGS
from src.geocoding import geocode_full, is_imprecise_match, GeocodingError

BASE_URL = "https://api.liteapi.travel/v3.0"
HOTEL_TYPES_URL = f"{BASE_URL}/data/hotelTypes"
HOTELS_BY_GEOCODE_URL = f"{BASE_URL}/data/hotels"

# Nomi di campo plausibili per il tipo di proprietà in una entry di
# `data/hotels` — non documentati in modo affidabile, quindi ne proviamo
# più di uno invece di assumerne uno solo "alla cieca" (stesso principio
# già applicato in _extract_total_price() per retailRate.total).
_CANDIDATE_TYPE_FIELDS = ("hotelTypeId", "hotelType", "type", "propertyType", "accommodationType")


def _fetch_hotel_types(api_key: str) -> dict:
    resp = requests.get(HOTEL_TYPES_URL, headers={"X-API-Key": api_key, "accept": "application/json"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_hotels(lat: float, lng: float, radius_km: int, api_key: str, hotel_type_ids: str | None = None) -> list[dict]:
    params = {"latitude": lat, "longitude": lng, "radius": max(radius_km * 1000, 1000), "limit": 20}
    if hotel_type_ids:
        # [AGGIUNTO 2026-07-11 — secondo giro, dopo il primo test dal vivo su
        # Lisbona] La prima versione di questo script cercava senza filtro e
        # su Lisbona centro ha trovato 20/20 "Hotels" — non conclusivo: non
        # dimostra che LiteAPI non abbia altri tipi disponibili, solo che il
        # comportamento di default (senza filtro esplicito) privilegia gli
        # hotel tradizionali in una zona di centro città turistico. Questo
        # parametro permette di chiedere ESPLICITAMENTE solo certi tipi
        # (es. "201,213,220,250" per Apartments/Villas/Holiday homes/Private
        # vacation home) per vedere se esiste offerta reale per quei tipi,
        # non solo se la tassonomia li conosce.
        params["hotelTypeIds"] = hotel_type_ids
    resp = requests.get(
        HOTELS_BY_GEOCODE_URL,
        headers={"X-API-Key": api_key, "accept": "application/json"},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("destination", nargs="?", default="Lisbona, Portogallo",
                         help='es. "Lisbona, Portogallo" (default se omesso)')
    parser.add_argument("--radius-km", type=int, default=5)
    parser.add_argument("--hotel-type-ids", default=None,
                         help='es. "201,213,220,250" per forzare solo Apartments/Villas/Holiday '
                              'homes/Private vacation home — vedi lista completa allo step 1')
    args = parser.parse_args()

    if not SETTINGS.liteapi_key:
        print("❌ LITEAPI_KEY mancante nel .env")
        sys.exit(1)
    if not SETTINGS.google_maps_key:
        print("❌ GOOGLE_MAPS_KEY mancante nel .env")
        sys.exit(1)

    print(f"\n{'=' * 70}\n1) LITEAPI — GET /data/hotelTypes (lista completa dei tipi di proprietà)\n{'=' * 70}")
    try:
        hotel_types_resp = _fetch_hotel_types(SETTINGS.liteapi_key)
    except requests.exceptions.RequestException as e:
        print(f"❌ Chiamata fallita: {e}")
        sys.exit(1)
    hotel_types = hotel_types_resp.get("data", hotel_types_resp)
    print(json.dumps(hotel_types, indent=2, ensure_ascii=False)[:4000])
    if isinstance(hotel_types, list):
        names = [str(t.get("name", t)) if isinstance(t, dict) else str(t) for t in hotel_types]
        non_hotel_like = [n for n in names if n.strip().lower() not in ("hotel", "hotels")]
        print(f"\n📋 {len(names)} tipi di proprietà totali conosciuti da LiteAPI.")
        print(f"📋 Di questi, {len(non_hotel_like)} NON si chiamano genericamente 'Hotel' "
              f"(es. potenziali appartamenti/ville/hostel/aparthotel/ecc.):")
        for n in non_hotel_like[:40]:
            print(f"   - {n}")
        if len(non_hotel_like) > 40:
            print(f"   ... e altri {len(non_hotel_like) - 40}")
    else:
        print("⚠️  Forma della risposta inattesa (non è una lista) — vedi JSON sopra per il dettaglio.")

    print(f"\n{'=' * 70}\n2) GEOCODING — {args.destination!r}\n{'=' * 70}")
    try:
        geo = geocode_full(args.destination, SETTINGS.google_maps_key)
    except GeocodingError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"lat={geo['lat']}, lng={geo['lng']}, location_type={geo['location_type']}")
    if is_imprecise_match(geo["location_type"]):
        print(f"⚠️  MATCH IMPRECISO — le coordinate potrebbero non rappresentare bene il luogo.")

    filter_note = f" (filtrato su hotelTypeIds={args.hotel_type_ids})" if args.hotel_type_ids else " (nessun filtro di tipo — comportamento di default)"
    print(f"\n{'=' * 70}\n3) LITEAPI — GET /data/hotels su {args.destination!r} "
          f"(raggio {args.radius_km}km){filter_note} — quali TIPI compaiono davvero?\n{'=' * 70}")
    try:
        hotels = _fetch_hotels(geo["lat"], geo["lng"], args.radius_km, SETTINGS.liteapi_key, args.hotel_type_ids)
    except requests.exceptions.RequestException as e:
        print(f"❌ Chiamata fallita: {e}")
        sys.exit(1)
    print(f"Trovati {len(hotels)} candidati reali.")
    if not hotels:
        if args.hotel_type_ids:
            print(
                f"⚠️  Zero candidati per i tipi {args.hotel_type_ids!r} in questo raggio/destinazione — "
                f"potrebbe voler dire che LiteAPI non ha offerta reale per questi tipi qui (non solo che "
                f"la tassonomia li conosce), oppure che il raggio è troppo piccolo. Prova un raggio più "
                f"ampio o un'altra destinazione (es. una zona di campagna/costa dove gli affitti vacanza "
                f"sono più comuni degli hotel) prima di concludere che manca offerta reale."
            )
        else:
            print("⚠️  Zero candidati in questo raggio — prova un raggio più ampio o un'altra destinazione.")
        return

    print(f"\nPrime 3 entry COMPLETE (per vedere ogni campo presente, non solo quelli già mappati in "
          f"src/liteapi_client.py):")
    print(json.dumps(hotels[:3], indent=2, ensure_ascii=False))

    print(f"\n{'=' * 70}\n4) RIEPILOGO — quale campo indica il tipo di proprietà, e quanti tipi diversi\n{'=' * 70}")
    found_field = None
    for candidate in _CANDIDATE_TYPE_FIELDS:
        if any(candidate in h for h in hotels):
            found_field = candidate
            break

    if found_field is None:
        print(
            f"⚠️  Nessuno dei campi candidati {_CANDIDATE_TYPE_FIELDS} è presente nelle entry reali "
            f"restituite da data/hotels per questa destinazione. Non significa necessariamente che "
            f"LiteAPI non classifichi i tipi di proprietà (potrebbe essere un campo con un nome "
            f"diverso, o omesso quando non richiesto esplicitamente) — guarda il JSON completo sopra "
            f"per cercare un campo plausibile con un nome diverso da quelli provati qui."
        )
        return

    print(f"✅ Campo tipo-proprietà trovato: {found_field!r}")
    type_id_counts: dict = {}
    for h in hotels:
        type_id = h.get(found_field, "[assente]")
        type_id_counts[type_id] = type_id_counts.get(type_id, 0) + 1

    # Prova a tradurre gli id numerici nei nomi leggibili dallo step 1, se possibile
    id_to_name = {}
    if isinstance(hotel_types, list):
        for t in hotel_types:
            if isinstance(t, dict) and "id" in t:
                id_to_name[t["id"]] = t.get("name", t["id"])

    for type_id, count in sorted(type_id_counts.items(), key=lambda x: -x[1]):
        label = id_to_name.get(type_id, type_id)
        print(f"   - tipo {type_id!r} ({label}): {count} hotel su {len(hotels)}")

    non_hotel_count = sum(
        count for type_id, count in type_id_counts.items()
        if str(id_to_name.get(type_id, type_id)).strip().lower() not in ("hotel", "hotels", "[assente]")
    )
    if non_hotel_count:
        print(
            f"\n✅ BUONA NOTIZIA: {non_hotel_count}/{len(hotels)} candidati in questa ricerca reale NON "
            f"sono classificati genericamente come 'Hotel' — LiteAPI sembra già includere altri tipi di "
            f"alloggio nel suo network di fornitori, senza bisogno di una nuova integrazione."
        )
    else:
        print(
            f"\nℹ️  In questa destinazione specifica, tutti i {len(hotels)} candidati risultano "
            f"classificati come 'Hotel'. Non è detto che LiteAPI non copra altri tipi altrove — prova "
            f"con un'altra destinazione (specialmente una zona turistica con molti B&B/appartamenti) "
            f"prima di concludere che la copertura è limitata ai soli hotel tradizionali."
        )


if __name__ == "__main__":
    main()
