from pydantic import Field

from app.catalog import days_open, is_closed, is_frozen_open, is_open, normalize_for_match, resolve_client_name, resolve_name
from app.tickets_api import TicketsApiClient
from app.tools.base import Tool, ToolArgs
from app.tools.common import DATE_PATTERN


def profile(tickets: list[dict]) -> dict:
    opened = [t for t in tickets if is_open(t)]
    oldest = min(opened, key=lambda t: t.get("opening_date") or "", default=None)
    return {
        "total": len(tickets),
        "abertos": len(opened),
        "fechados": sum(is_closed(t) for t in tickets),
        "congelados": sum(is_frozen_open(t) for t in tickets),
        "prioridade_alta_ou_urgente_abertos": sum(t.get("priority") in {"Alta", "Urgente"} for t in opened),
        "mais_antigo_aberto": None if oldest is None else {
            "numero": oldest["number"], "opening_date": oldest["opening_date"],
            "dias_em_aberto": days_open(oldest["opening_date"]),
        },
    }


class CargaOperadorArgs(ToolArgs):
    operador: str = Field(min_length=1, max_length=100, description="Nome do operador. Aceita nome parcial.")


async def analisar_carga_operador(client: TicketsApiClient, a: CargaOperadorArgs) -> dict:
    r = resolve_name(await client.get_meta("users"), a.operador)
    if msg := r.describe("operador", a.operador):
        return {"encontrado": False, "motivo": msg}
    tickets, truncated = await client.fetch_snapshot({"operator": r.id})
    return {"operador": r.canonical_name, "truncado": truncated, **profile(tickets)}


class AtividadeClienteArgs(ToolArgs):
    cliente: str = Field(min_length=1, max_length=100, description="Nome do cliente/solicitante. Aceita nome parcial.")
    data_inicio: str | None = Field(None, pattern=DATE_PATTERN, description="Início (inclusive) da abertura, AAAA-MM-DD.")
    data_fim: str | None = Field(None, pattern=DATE_PATTERN, description="Fim (inclusive) da abertura, AAAA-MM-DD.")


async def analisar_atividade_cliente(client: TicketsApiClient, a: AtividadeClienteArgs) -> dict:
    from app.catalog import in_period

    tickets, truncated = await client.fetch_snapshot({}, since=a.data_inicio)
    scoped = [t for t in tickets if in_period(t.get("opening_date"), a.data_inicio, a.data_fim)]
    r = resolve_client_name(scoped, a.cliente)
    if msg := r.describe("cliente", a.cliente):
        return {"encontrado": False, "motivo": msg}
    mine = [t for t in scoped if r.id in normalize_for_match(t.get("contact_name"))]
    out = {"cliente": r.canonical_name, "truncado": truncated, **profile(mine)}
    if a.data_inicio or a.data_fim:
        out["periodo"] = {"data_inicio": a.data_inicio, "data_fim": a.data_fim}
    return out


TOOLS = [
    Tool(
        "analisar_carga_operador",
        "Carga de trabalho de UM operador nomeado: total, abertos, fechados, congelados, abertos de prioridade "
        "alta/urgente e o ticket aberto mais antigo. Para 'o Fábio está sobrecarregado?' e comparações entre "
        "operadores (uma chamada por operador).",
        CargaOperadorArgs, analisar_carga_operador,
    ),
    Tool(
        "analisar_atividade_cliente",
        "Atividade de UM cliente/solicitante nomeado (com período opcional): total, abertos, fechados, congelados, "
        "abertos de prioridade alta/urgente e o ticket aberto mais antigo. Para 'o cliente X abre muito chamado?' e "
        "comparações entre clientes (uma chamada por cliente).",
        AtividadeClienteArgs, analisar_atividade_cliente,
    ),
]
