"""Config centralizzata — legge le chiavi da variabili d'ambiente (.env)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv opzionale: se assente, si legge solo l'env di sistema


@dataclass
class Settings:
    # [CORRETTO 2026-07-11 — audit qualità pre-lancio] I default di una
    # dataclass sono valutati UNA VOLTA, a definizione di classe (import
    # time), non a ogni istanziazione. Con `os.getenv(...)` diretto come
    # default, `Settings()` chiamato una seconda volta (es. nei test, o in
    # un futuro script che modifica l'ambiente a runtime prima di rileggere
    # le chiavi) restituirebbe silenziosamente i valori letti al primo
    # import, non quelli correnti. Oggi non si manifesta (SETTINGS=Settings()
    # in fondo al file è l'unica istanza, creata subito dopo load_dotenv()),
    # ma è un difetto latente da chiudere ora, non quando qualcuno lo scopre
    # scrivendo un test che sembra inspiegabilmente "non vedere" una chiave.
    # Fix: default_factory rivaluta os.getenv() a ogni Settings() reale.
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    google_maps_key: str | None = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_KEY"))
    # [AGGIORNATO 2026-07-10] Amadeus (AMADEUS_KEY + AMADEUS_SECRET, OAuth2) è
    # stato sostituito da LiteAPI (una sola chiave, header X-API-Key) — vedi
    # CHANGELOG.md. Una chiave in meno da gestire.
    liteapi_key: str | None = field(default_factory=lambda: os.getenv("LITEAPI_KEY"))

    def missing_for_live_mode(self) -> list[str]:
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.google_maps_key:
            missing.append("GOOGLE_MAPS_KEY")
        if not self.liteapi_key:
            missing.append("LITEAPI_KEY")
        return missing

    def missing_for_mock_mode(self) -> list[str]:
        # in mock mode servono solo dati RAG finti + la chiave Claude vera
        # (l'unico pezzo che vogliamo davvero testare dal vivo)
        return [] if self.anthropic_api_key else ["ANTHROPIC_API_KEY"]


SETTINGS = Settings()
