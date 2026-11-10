from typing import Literal

from pydantic import Field

from app.catalog import normalize_for_match
from app.tickets_api import TicketsApiClient
from app.tools.base import Tool, ToolArgs

# Nome amigável (o que o modelo envia) -> chave do endpoint /meta/*.
CATALOG_KINDS = {
    "areas": "areas",
    "prioridades": "priorities",
    "canais": "channels",
    "status": "statuses",
    "departamentos": "departments",
    "usuarios": "users",
}


class ListarCatalogoArgs(ToolArgs):
    tipo: Literal["areas", "prioridades", "canais", "status", "departamentos", "usuarios"] = Field(
        description="Qual catálogo listar."
    )


async def listar_catalogo(client: TicketsApiClient, args: ListarCatalogoArgs) -> dict:
    items = await client.get_meta(CATALOG_KINDS[args.tipo])
    return {"tipo": args.tipo, "quantidade": len(items), "itens": items}


class BuscarUsuariosArgs(ToolArgs):
    nome: str = Field(min_length=1, max_length=100, description="Nome ou login (completo ou parcial) do usuário.")


async def buscar_usuarios_por_nome(client: TicketsApiClient, args: BuscarUsuariosArgs) -> dict:
    users = await client.get_meta("users")
    target = normalize_for_match(args.nome)
    found = [
        u for u in users
        if target in normalize_for_match(u.get("name")) or target in normalize_for_match(u.get("login"))
    ]
    return {"quantidade": len(found), "usuarios": found}


TOOLS = [
    Tool(
        name="listar_catalogo",
        description=(
            "Lista os itens cadastrados de um catálogo do sistema de tickets: áreas, prioridades, "
            "canais de entrada, status, departamentos ou usuários (operadores)."
        ),
        args_model=ListarCatalogoArgs,
        handler=listar_catalogo,
    ),
    Tool(
        name="buscar_usuarios_por_nome",
        description="Busca usuários (operadores) cujo nome ou login contenham o texto informado.",
        args_model=BuscarUsuariosArgs,
        handler=buscar_usuarios_por_nome,
    ),
]
