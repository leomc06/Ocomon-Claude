"""Normalização de texto e resolução de nomes contra os catálogos do OcoMon."""

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def normalize_for_match(value: Any) -> str:
    """Minúsculas, sem acento, sem entidade HTML, sem pontuação final, espaços colapsados."""
    text = str(value if value is not None else "")
    for _ in range(3):  # entidades duplamente escapadas (&amp;ccedil;)
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[.,]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_gender_suffix(value: str) -> str:
    return re.sub(r"(os|as|o|a)$", "", value)


def _is_anchored(candidate: str, target: str) -> bool:
    """O alvo casa no início da string ou logo após um espaço (início de alguma palavra)."""
    idx = candidate.find(target)
    while idx != -1:
        if idx == 0 or candidate[idx - 1] == " ":
            return True
        idx = candidate.find(target, idx + 1)
    return False


@dataclass
class Resolution:
    id: Any = None
    canonical_name: str | None = None
    not_found: bool = False
    ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)

    def describe(self, label: str, value: str) -> str | None:
        """Mensagem para o modelo quando o nome não resolveu; None se resolveu."""
        if not self.not_found:
            return None
        if self.ambiguous:
            return f'{label} "{value}" é ambíguo (pode ser: {", ".join(self.candidates)})'
        return f'{label} "{value}" não encontrado'


def resolve_name(items: list[dict], name: str | None) -> Resolution:
    """Igualdade > substring (ancorada se for único) > igualdade sem sufixo de gênero.

    Mais de um candidato no mesmo nível vira ambíguo, nunca uma escolha silenciosa.
    """
    if name is None:
        return Resolution()

    target = normalize_for_match(name)
    normalized = [normalize_for_match(i.get("name")) for i in items]

    exact = [i for i, n in zip(items, normalized) if n == target]
    substring = [] if exact else [i for i, n in zip(items, normalized) if target in n]
    # Único candidato que cai no MEIO de uma palavra ("ana" em "Luana") é coincidência.
    if len(substring) == 1 and not _is_anchored(normalize_for_match(substring[0].get("name")), target):
        substring = []
    suffix = (
        []
        if exact or substring
        else [i for i, n in zip(items, normalized) if _strip_gender_suffix(n) == _strip_gender_suffix(target)]
    )

    candidates = exact or substring or suffix
    if not candidates:
        return Resolution(not_found=True)
    if len(candidates) > 1:
        return Resolution(not_found=True, ambiguous=True, candidates=[c.get("name") for c in candidates])
    return Resolution(id=candidates[0].get("id"), canonical_name=candidates[0].get("name"))


# --- Regras de negócio sobre tickets --------------------------------------------------------

_CLOSED_NAMES = {"encerrada", "encerrado", "fechada", "fechado", "concluida", "concluido",
                 "finalizada", "finalizado", "resolvida", "resolvido", "solucionada", "solucionado"}


def is_cancelled(ticket: dict) -> bool:
    return normalize_for_match(ticket.get("status")) in {"cancelado", "cancelada"}


def is_open(ticket: dict) -> bool:
    """Aberto = sem data de fechamento e não cancelado (cancelado nunca preenche closure_date)."""
    return not ticket.get("closure_date") and not is_cancelled(ticket)


def is_closed(ticket: dict) -> bool:
    return bool(ticket.get("closure_date"))


def has_no_operator(ticket: dict) -> bool:
    return not (ticket.get("operator") or "").strip()


def days_open(opening_date: str, now: "datetime | None" = None) -> int:
    from datetime import datetime

    opened = datetime.fromisoformat(opening_date.replace(" ", "T"))
    return max(((now or datetime.now()) - opened).days, 0)


def in_period(value: str | None, start: str | None, end: str | None) -> bool:
    """Datas 'AAAA-MM-DD HH:MM:SS' comparam lexicograficamente com 'AAAA-MM-DD' (fim inclusivo)."""
    value = value or ""
    if start is not None and value < start:
        return False
    if end is not None and value > f"{end} 23:59:59":
        return False
    return True


def resolve_client_name(tickets: list[dict], query: str) -> Resolution:
    """Cliente não tem catálogo: casa por substring em contact_name.

    'fabio gali' e 'Fabio Gali' contam como a mesma pessoa; pessoas distintas vira ambíguo.
    """
    target = normalize_for_match(query)
    distinct: dict[str, str] = {}
    for t in tickets:
        n = normalize_for_match(t.get("contact_name"))
        if target in n and n not in distinct:
            distinct[n] = t.get("contact_name") or ""
    if not distinct:
        return Resolution(not_found=True)
    if len(distinct) > 1:
        return Resolution(not_found=True, ambiguous=True, candidates=list(distinct.values()))
    return Resolution(id=target, canonical_name=next(iter(distinct.values())))


def group_by_normalized_name(tickets: list[dict], getter) -> list[dict]:
    """Conta por nome ignorando caixa/acento; o rótulo é a grafia mais usada do grupo."""
    groups: dict[str, dict] = {}
    for t in tickets:
        original = getter(t)
        g = groups.setdefault(normalize_for_match(original), {"n": 0, "labels": {}})
        g["n"] += 1
        g["labels"][original] = g["labels"].get(original, 0) + 1
    return [
        {"chave": max(g["labels"], key=g["labels"].get), "quantidade": g["n"]} for g in groups.values()
    ]
