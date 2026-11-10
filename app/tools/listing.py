import asyncio
from typing import Literal

from pydantic import Field

from app.catalog import normalize_for_match
from app.tickets_api import TicketsApiClient
from app.tools.base import Tool
from app.tools.common import (
    FilterError, TicketFilters, compact, not_found, paginate, resolve_api_filters, select_tickets,
)

SLA_CHECK_LIMIT = 1000
SLA_BREACHED = 4  # valor de lifetime.result_sla_* para SLA estourado


class ListarTicketsArgs(TicketFilters):
    numero: int | None = Field(None, gt=0, le=2147483647, description="Número do ticket.")
    ordenar: Literal["recentes", "antigos"] = Field("recentes", description="Ordem pela data de abertura.")
    limite: int = Field(20, ge=1, le=50, description="Itens por página.")
    pagina: int = Field(1, ge=1, description="Página, começando em 1.")


async def listar_tickets(client: TicketsApiClient, a: ListarTicketsArgs) -> dict:
    try:
        local = any([a.cliente, a.prioridade, a.situacao, a.data_inicio, a.data_fim, a.numero,
                     a.ordenar != "recentes"])
        if not local:
            # Só filtros de catálogo: a própria API pagina e informa o total exato.
            api, names = await resolve_api_filters(client, a)
            data = await client.list_page(api, a.pagina, limit=a.limite)
            return {"filtros": names, "total": data.get("results", 0), "pagina": data.get("page", a.pagina),
                    "paginas": data.get("pages", 1), "tickets": [compact(t) for t in data.get("tickets") or []]}
        sel = await select_tickets(client, a)
    except FilterError as e:
        return not_found(e)
    tickets = [t for t in sel.tickets if a.numero is None or t.get("number") == a.numero]
    tickets = sorted(tickets, key=lambda t: t.get("opening_date") or "", reverse=a.ordenar == "recentes")
    page, pages = paginate(tickets, a.limite, a.pagina)
    return {"filtros": sel.applied, "total": len(tickets), "pagina": a.pagina, "paginas": pages,
            "truncado": sel.truncated, "tickets": [compact(t) for t in page]}


class VencidosArgs(TicketFilters):
    limite: int = Field(10, ge=1, le=50, description="Itens por página.")
    pagina: int = Field(1, ge=1, description="Página, começando em 1.")


async def listar_tickets_vencidos(client: TicketsApiClient, a: VencidosArgs) -> dict:
    try:
        sel = await select_tickets(client, a)
    except FilterError as e:
        return not_found(e)
    if len(sel.tickets) > SLA_CHECK_LIMIT:
        return {"muitos_para_verificar": True, "quantidade_candidatos": len(sel.tickets),
                "limite_verificacao": SLA_CHECK_LIMIT,
                "dica": "Restrinja por área, operador, situação ou período."}

    sem = asyncio.Semaphore(client.concurrency)
    failures = 0

    async def check(t: dict) -> dict | None:
        nonlocal failures
        async with sem:
            try:
                return await client.get_ticket(t["number"])
            except Exception:  # um ticket com erro não derruba o lote; é contado e avisado
                failures += 1
                return None

    details = await asyncio.gather(*(check(t) for t in sel.tickets))
    breached = []
    for t, d in zip(sel.tickets, details):
        life = (d or {}).get("lifetime") or {}
        if life.get("result_sla_response") == SLA_BREACHED or life.get("result_sla_solution") == SLA_BREACHED:
            breached.append({**compact(t), "lifetime": life})
    breached.sort(key=lambda t: t.get("opening_date") or "")
    page, pages = paginate(breached, a.limite, a.pagina)
    out = {"filtros": sel.applied, "quantidade_total": len(breached), "pagina": a.pagina, "paginas": pages,
           "truncado": sel.truncated, "tickets": page}
    if failures:
        out["tickets_nao_verificados"] = failures
    return out


class BuscarTextoArgs(TicketFilters):
    texto: str = Field(min_length=2, max_length=100, description="Texto a procurar no assunto e na descrição.")
    limite: int = Field(10, ge=1, le=50, description="Itens por página.")
    pagina: int = Field(1, ge=1, description="Página, começando em 1.")


async def buscar_tickets_por_texto(client: TicketsApiClient, a: BuscarTextoArgs) -> dict:
    try:
        sel = await select_tickets(client, a)
    except FilterError as e:
        return not_found(e)
    target = normalize_for_match(a.texto)
    hits = [t for t in sel.tickets
            if target in normalize_for_match(t.get("issue")) or target in normalize_for_match(t.get("description"))]
    hits.sort(key=lambda t: t.get("opening_date") or "", reverse=True)
    page, pages = paginate(hits, a.limite, a.pagina)
    return {"filtros": {**sel.applied, "texto": a.texto}, "total": len(hits), "pagina": a.pagina, "paginas": pages,
            "truncado": sel.truncated,
            "tickets": [{**compact(t), "trecho": (t.get("description") or "")[:200]} for t in page]}


TOOLS = [
    Tool(
        "listar_tickets",
        "Lista tickets (chamados) com filtros opcionais: status, área, departamento, operador, cliente, prioridade, "
        "situação (aberto/fechado/congelado/sem_operador), número e período (de abertura, ou de fechamento com "
        "periodo_por=fechamento). Serve para 'abertos', 'fechados', 'sem operador', 'congelados', 'mais antigos' "
        "(ordenar=antigos) e 'mais recentes'. Para contar ou agrupar ('quantos', 'por área'), use resumo_tickets; "
        "para um número só, use limite=1 e leia 'total'.",
        ListarTicketsArgs, listar_tickets,
    ),
    Tool(
        "listar_tickets_vencidos",
        "Lista tickets que realmente estouraram o SLA (de resposta ou de solução), checando o SLA de cada ticket, "
        "inclusive os já encerrados fora do prazo. Aceita os mesmos filtros de listar_tickets. Se houver candidatos "
        "demais, pede para restringir o filtro.",
        VencidosArgs, listar_tickets_vencidos,
    ),
    Tool(
        "buscar_tickets_por_texto",
        "Procura um texto no assunto e na descrição dos tickets, com os mesmos filtros de listar_tickets.",
        BuscarTextoArgs, buscar_tickets_por_texto,
    ),
]
