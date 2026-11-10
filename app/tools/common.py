"""Filtros e carga de tickets compartilhados pelas tools de listagem, resumo e análise."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from app.catalog import (
    Resolution, days_open, in_period, is_closed, is_open, has_no_operator,
    normalize_for_match, resolve_client_name, resolve_name,
)
from app.tickets_api import TicketsApiClient
from app.tools.base import ToolArgs

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

Situacao = Literal["aberto", "fechado", "congelado", "sem_operador"]


class FilterError(Exception):
    """Nome de filtro não encontrado/ambíguo; a mensagem vai para o modelo."""


class TicketFilters(ToolArgs):
    status: str | None = Field(None, max_length=100, description='Nome do status (ex.: "Aberto", "Em Atendimento", "Encerrada"). Aceita nome parcial.')
    area: str | None = Field(None, max_length=100, description="Nome da área. Aceita nome parcial.")
    departamento: str | None = Field(None, max_length=100, description="Nome do departamento. Aceita nome parcial.")
    operador: str | None = Field(None, max_length=100, description="Nome do operador responsável. Aceita nome parcial.")
    cliente: str | None = Field(None, max_length=100, description="Nome do cliente/solicitante (contato). Aceita nome parcial.")
    prioridade: str | None = Field(None, max_length=100, description='Nome da prioridade (ex.: "Alta", "Urgente").')
    situacao: Situacao | None = Field(
        None, description="aberto (em andamento, exclui cancelados), fechado (encerrado), congelado ou sem_operador."
    )
    data_inicio: str | None = Field(None, pattern=DATE_PATTERN, description="Início (inclusive) do período, AAAA-MM-DD.")
    data_fim: str | None = Field(None, pattern=DATE_PATTERN, description="Fim (inclusive) do período, AAAA-MM-DD.")
    periodo_por: Literal["abertura", "fechamento"] = Field(
        "abertura", description="Em qual data o período é aplicado. Use fechamento para 'fechados este mês'."
    )


@dataclass
class Selection:
    tickets: list[dict]
    truncated: bool
    applied: dict = field(default_factory=dict)


async def _resolve(client: TicketsApiClient, kind: str, label: str, value: str | None) -> Resolution:
    r = resolve_name(await client.get_meta(kind), value)
    msg = r.describe(label, value) if value is not None else None
    if msg:
        raise FilterError(msg)
    return r


async def resolve_api_filters(client: TicketsApiClient, f: TicketFilters) -> tuple[dict, dict]:
    """Resolve nomes de catálogo para ids da API. Devolve (filtros da API, nomes canônicos)."""
    status = await _resolve(client, "statuses", "status", f.status)
    area = await _resolve(client, "areas", "área", f.area)
    dept = await _resolve(client, "departments", "departamento", f.departamento)
    oper = await _resolve(client, "users", "operador", f.operador)
    api = {"status": status.id, "area": area.id, "department": dept.id, "operator": oper.id}
    names = {
        k: v for k, v in {
            "status": status.canonical_name, "area": area.canonical_name,
            "departamento": dept.canonical_name, "operador": oper.canonical_name,
        }.items() if v
    }
    return {k: v for k, v in api.items() if v is not None}, names


async def select_tickets(client: TicketsApiClient, f: TicketFilters) -> Selection:
    """Baixa os tickets (filtros da API) e aplica o resto localmente. Levanta FilterError."""
    api, applied = await resolve_api_filters(client, f)
    priority = await _resolve(client, "priorities", "prioridade", f.prioridade)

    by_opening = f.periodo_por == "abertura"
    since = f.data_inicio if by_opening else None
    tickets, truncated = await client.fetch_snapshot(api, since=since)

    target = None
    if f.cliente is not None:
        r = resolve_client_name(tickets, f.cliente)
        msg = r.describe("cliente", f.cliente)
        if msg:
            raise FilterError(msg)
        target = r.id
        applied["cliente"] = r.canonical_name
    if f.prioridade is not None:
        applied["prioridade"] = priority.canonical_name

    date_key = "opening_date" if by_opening else "closure_date"
    out = []
    for t in tickets:
        if priority.canonical_name and t.get("priority") != priority.canonical_name:
            continue
        if target is not None and target not in normalize_for_match(t.get("contact_name")):
            continue
        if (f.data_inicio or f.data_fim) and not in_period(t.get(date_key), f.data_inicio, f.data_fim):
            continue
        if f.situacao == "aberto" and not is_open(t):
            continue
        if f.situacao == "fechado" and not is_closed(t):
            continue
        if f.situacao == "congelado" and t.get("is_frozen") is not True:
            continue
        if f.situacao == "sem_operador" and not has_no_operator(t):
            continue
        out.append(t)

    for key in ("situacao", "data_inicio", "data_fim"):
        if getattr(f, key) is not None:
            applied[key] = getattr(f, key)
    if (f.data_inicio or f.data_fim):
        applied["periodo_por"] = f.periodo_por
    return Selection(out, truncated, applied)


_COMPACT_FIELDS = ("number", "opening_date", "closure_date", "status", "priority", "area", "operator",
                   "contact_name", "issue", "is_frozen")


def compact(ticket: dict) -> dict:
    out = {k: ticket.get(k) for k in _COMPACT_FIELDS}
    if is_open(ticket) and ticket.get("opening_date"):
        out["dias_em_aberto"] = days_open(ticket["opening_date"])
    return out


def paginate(items: list, limit: int, page: int) -> tuple[list, int]:
    pages = max(-(-len(items) // limit), 1)
    start = (page - 1) * limit
    return items[start:start + limit], pages


def not_found(error: FilterError) -> dict:
    return {"encontrado": False, "motivo": str(error)}
