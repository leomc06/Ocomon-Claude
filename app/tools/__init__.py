import json
from typing import Any

from pydantic import ValidationError

from app.tickets_api import TicketsApiClient, TicketsApiError
from app.tools import catalogs, listing, people, summaries, tickets
from app.tools.base import Tool

ALL_TOOLS: list[Tool] = [*catalogs.TOOLS, *tickets.TOOLS, *listing.TOOLS, *summaries.TOOLS, *people.TOOLS]
_BY_NAME = {t.name: t for t in ALL_TOOLS}


def anthropic_tool_defs() -> list[dict]:
    return [t.to_anthropic() for t in ALL_TOOLS]


async def execute_tool(client: TicketsApiClient, name: str, raw_args: Any) -> tuple[str, bool]:
    """Executa uma tool. Devolve (conteúdo do tool_result, is_error).

    Erros viram texto para o modelo se corrigir ou explicar; nunca estouram o loop.
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return f"Tool desconhecida: {name}", True
    try:
        args = tool.args_model.model_validate(raw_args or {})
    except ValidationError as error:
        return f"Argumentos inválidos: {error.errors(include_url=False, include_context=False)}", True
    try:
        result = await tool.handler(client, args)
    except TicketsApiError as error:
        return str(error), True
    return json.dumps(result, ensure_ascii=False, default=str), False
