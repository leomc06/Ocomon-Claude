from pydantic import Field

from app.tickets_api import TicketsApiClient, TicketsApiError
from app.tools.base import Tool, ToolArgs


class BuscarTicketArgs(ToolArgs):
    numero: int = Field(gt=0, le=2147483647, description="Número identificador do ticket (chamado).")


async def buscar_ticket_por_numero(client: TicketsApiClient, args: BuscarTicketArgs) -> dict:
    try:
        ticket = await client.get_ticket(args.numero)
    except TicketsApiError as error:
        if error.status == 404 or error.type == "not_found":
            return {"encontrado": False, "ticket": None}
        raise
    return {"encontrado": True, "ticket": ticket}


TOOLS = [
    Tool(
        name="buscar_ticket_por_numero",
        description=(
            "Busca o detalhe completo de um ticket (chamado) pelo número, incluindo SLA, comentários e anexos. "
            "Use sempre que a pergunta citar um número de ticket específico."
        ),
        args_model=BuscarTicketArgs,
        handler=buscar_ticket_por_numero,
    ),
]
