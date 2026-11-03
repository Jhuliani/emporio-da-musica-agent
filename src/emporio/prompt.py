"""System prompt construction (persona and guardrails are refined in the next step)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from emporio.rules import STORE_TZ, WEEKDAY_NAMES

POLICIES_FILE = Path(__file__).resolve().parents[2] / "data" / "policies.md"


def build_system_prompt(now: datetime | None = None) -> str:
    now = (now or datetime.now(STORE_TZ)).astimezone(STORE_TZ)
    policies = POLICIES_FILE.read_text(encoding="utf-8")
    return (
        "Você é o assistente virtual da Empório da Música, loja de instrumentos musicais "
        "em Campo Grande/MS. Responda em português, usando as ferramentas para qualquer "
        "informação de preço, estoque, promoção ou pedido.\n\n"
        f"Agora: {WEEKDAY_NAMES[now.weekday()]}, {now.strftime('%d/%m/%Y %H:%M')} (horário de MS).\n\n"
        f"<manual_de_politicas>\n{policies}\n</manual_de_politicas>"
    )
