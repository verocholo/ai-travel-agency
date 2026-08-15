"""
NODO 7 — Payload Assembly. BLUEPRINT_MAKE.md §NODO 7 / DATA_STRUCTURES_MAKE.md
§DS_PAYLOAD_API. Contenitore unico e blindato dato a Claude.
"""
from __future__ import annotations
from .schemas import Trip, Hotel, POI, TravelTime, ApiPayload, build_full_payload


def assemble_payload(
    trip: Trip, hotels: list[Hotel], travel_times: list[TravelTime], poi: list[POI]
) -> dict:
    api_payload = ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)
    return build_full_payload(trip, api_payload)
