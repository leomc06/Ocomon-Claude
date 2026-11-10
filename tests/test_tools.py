import json

import httpx
import respx

from app.tickets_api import TicketsApiClient
from app.tools import anthropic_tool_defs, execute_tool

BASE = "http://api.test"


async def _nosleep(_):
    pass


def client():
    return TicketsApiClient(BASE, "t", "l", "a", sleep=_nosleep)


def test_tool_defs_are_valid_anthropic_shape():
    defs = anthropic_tool_defs()
    names = {d["name"] for d in defs}
    assert {"listar_catalogo", "buscar_usuarios_por_nome", "buscar_ticket_por_numero"} <= names
    for d in defs:
        assert d["description"] and d["input_schema"]["type"] == "object"
        assert d["input_schema"]["additionalProperties"] is False
    enum = next(d for d in defs if d["name"] == "listar_catalogo")["input_schema"]["properties"]["tipo"]["enum"]
    assert "status" in enum and len(enum) == 6


@respx.mock
async def test_listar_catalogo():
    respx.get(f"{BASE}/meta/statuses").mock(return_value=httpx.Response(200, json={"statuses": [{"id": 1, "name": "Aberta"}]}))
    out, err = await execute_tool(client(), "listar_catalogo", {"tipo": "status"})
    assert not err
    assert json.loads(out) == {"tipo": "status", "quantidade": 1, "itens": [{"id": 1, "name": "Aberta"}]}


@respx.mock
async def test_buscar_usuarios_por_nome_matches_name_or_login_ignoring_accents():
    respx.get(f"{BASE}/meta/users").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "José Silva", "login": "jsilva"}, {"id": 2, "name": "Maria", "login": "mar"}])
    )
    out, _ = await execute_tool(client(), "buscar_usuarios_por_nome", {"nome": "jose"})
    assert json.loads(out)["quantidade"] == 1
    out, _ = await execute_tool(client(), "buscar_usuarios_por_nome", {"nome": "jsil"})
    assert json.loads(out)["usuarios"][0]["id"] == 1


@respx.mock
async def test_buscar_ticket_found_and_not_found():
    respx.get(f"{BASE}/tickets/10").mock(return_value=httpx.Response(200, json={"number": 10}))
    respx.get(f"{BASE}/tickets/11").mock(return_value=httpx.Response(404, json={"errors": [{"message": "x", "type": "not_found"}]}))
    out, err = await execute_tool(client(), "buscar_ticket_por_numero", {"numero": 10})
    assert not err and json.loads(out) == {"encontrado": True, "ticket": {"number": 10}}
    out, err = await execute_tool(client(), "buscar_ticket_por_numero", {"numero": 11})
    assert not err and json.loads(out) == {"encontrado": False, "ticket": None}


@respx.mock
async def test_api_failure_becomes_error_result():
    respx.get(f"{BASE}/tickets/12").mock(return_value=httpx.Response(400, json={"errors": [{"message": "ruim"}]}))
    out, err = await execute_tool(client(), "buscar_ticket_por_numero", {"numero": 12})
    assert err and "ruim" in out


async def test_invalid_args_and_unknown_tool():
    c = client()
    for name, args in [
        ("buscar_ticket_por_numero", {"numero": -1}),
        ("buscar_ticket_por_numero", {"numero": 1, "extra": 1}),
        ("listar_catalogo", {"tipo": "foo"}),
    ]:
        out, err = await execute_tool(c, name, args)
        assert err and out.startswith("Argumentos inválidos")
    out, err = await execute_tool(c, "nao_existe", {})
    assert err and "desconhecida" in out
