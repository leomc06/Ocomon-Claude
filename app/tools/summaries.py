from typing import Literal

from pydantic import Field

from app.catalog import days_open, group_by_normalized_name, has_no_operator, is_closed, is_open
from app.tickets_api import TicketsApiClient
from app.tools.base import Tool
from app.tools.common import FilterError, TicketFilters, not_found, resolve_api_filters, select_tickets

GROUPERS = {
    "status": lambda t: t.get("status") or "sem status",
    "prioridade": lambda t: t.get("priority") or "não definida",
    "area": lambda t: t.get("area") or "sem área",
    "operador": lambda t: (t.get("operator") or "").strip() or "Sem operador",
    "cliente": lambda t: (t.get("contact_name") or "").strip() or "sem cliente",
}


class ResumoArgs(TicketFilters):
    agrupar_por: Literal["status", "prioridade", "area", "operador", "departamento", "cliente"] = Field(
        description="Dimensão do agrupamento."
    )
    ordem: Literal["desc", "asc"] = Field("desc", description="desc = quem tem mais; asc = quem tem menos.")
    limite: int | None = Field(None, ge=1, le=100, description="Top N (opcional).")


def rank(groups: list[dict], total: int, order: str, limit: int | None) -> list[dict]:
    ranked = sorted(groups, key=lambda g: g["quantidade"], reverse=order == "desc")
    for g in ranked:
        g["percentual"] = round(g["quantidade"] / total * 100, 1) if total else 0
    return ranked[:limit] if limit else ranked


async def resumo_tickets(client: TicketsApiClient, a: ResumoArgs) -> dict:
    try:
        if a.agrupar_por == "departamento":
            return await _by_department(client, a)
        sel = await select_tickets(client, a)
    except FilterError as e:
        return not_found(e)
    if a.agrupar_por == "cliente":
        groups = group_by_normalized_name(sel.tickets, GROUPERS["cliente"])
    else:
        counts: dict[str, int] = {}
        for t in sel.tickets:
            key = GROUPERS[a.agrupar_por](t)
            counts[key] = counts.get(key, 0) + 1
        groups = [{"chave": k, "quantidade": v} for k, v in counts.items()]
    return {"agrupado_por": a.agrupar_por, "filtros": sel.applied, "total": len(sel.tickets),
            "truncado": sel.truncated, "grupos": rank(groups, len(sel.tickets), a.ordem, a.limite)}


async def _by_department(client: TicketsApiClient, a: ResumoArgs) -> dict:
    # A listagem não traz o departamento de cada ticket: só dá para contar por filtro da API.
    if any([a.cliente, a.prioridade, a.situacao, a.data_inicio, a.data_fim, a.departamento]):
        return {"encontrado": False, "motivo": "O agrupamento por departamento só aceita os filtros status, "
                "área e operador (os demais não podem ser combinados)."}
    import asyncio

    api, names = await resolve_api_filters(client, a)
    depts = await client.get_meta("departments")
    sem = asyncio.Semaphore(client.concurrency)
    failures = 0

    async def count(d: dict) -> dict | None:
        nonlocal failures
        async with sem:
            try:
                return {"chave": d["name"], "quantidade": await client.count_tickets({**api, "department": d["id"]})}
            except Exception:
                failures += 1
                return None

    groups = [g for g in await asyncio.gather(*(count(d) for d in depts)) if g]
    total = sum(g["quantidade"] for g in groups)
    out = {"agrupado_por": "departamento", "filtros": names, "total": total,
           "grupos": rank(groups, total, a.ordem, a.limite)}
    if failures:
        out["departamentos_nao_contados"] = failures
    return out


class OperacionalArgs(TicketFilters):
    pass


async def resumo_operacional_tickets(client: TicketsApiClient, a: OperacionalArgs) -> dict:
    try:
        sel = await select_tickets(client, a)
    except FilterError as e:
        return not_found(e)
    tickets = sel.tickets
    opened = [t for t in tickets if is_open(t)]
    by_priority: dict[str, int] = {}
    for t in tickets:
        key = t.get("priority") or "não definida"
        by_priority[key] = by_priority.get(key, 0) + 1
    oldest = sorted(opened, key=lambda t: t.get("opening_date") or "")[:5]
    return {
        "filtros": sel.applied, "truncado": sel.truncated, "total": len(tickets),
        "abertos": len(opened), "fechados": sum(is_closed(t) for t in tickets),
        "sem_operador": sum(has_no_operator(t) for t in tickets),
        "congelados": sum(t.get("is_frozen") is True for t in tickets),
        "por_prioridade": [{"chave": k, "quantidade": v} for k, v in by_priority.items()],
        "abertos_com_mais_de_7_dias": sum(days_open(t["opening_date"]) > 7 for t in opened),
        "mais_antigos_em_aberto": [
            {"numero": t["number"], "issue": t.get("issue"), "opening_date": t["opening_date"],
             "dias_em_aberto": days_open(t["opening_date"])} for t in oldest
        ],
    }


TOOLS = [
    Tool(
        "resumo_tickets",
        "Conta e agrupa tickets por uma dimensão (status, prioridade, area, operador, departamento ou cliente), com "
        "percentual, ranking (ordem desc/asc, limite = top N) e os mesmos filtros de listar_tickets. Use para "
        "'quantos', 'por status', 'quem tem mais tickets'. Agrupa POR essa dimensão: para UMA pessoa nomeada use "
        "analisar_carga_operador ou analisar_atividade_cliente. O agrupamento por departamento só aceita filtros "
        "de status, área e operador.",
        ResumoArgs, resumo_tickets,
    ),
    Tool(
        "resumo_operacional_tickets",
        "Retrato geral da operação: total, abertos, fechados, sem operador, congelados, distribuição por prioridade, "
        "abertos há mais de 7 dias e os 5 abertos mais antigos. Para 'como está a operação?'. Aceita filtros de área, "
        "operador, período etc.",
        OperacionalArgs, resumo_operacional_tickets,
    ),
]
