import json

import respx

from app.tickets_api import TicketsApiClient
from app.tools import execute_tool
from tests.fakeapi import BASE, install


async def _nosleep(_):
    pass


def client():
    return TicketsApiClient(BASE, "t", "l", "a", sleep=_nosleep, page_size=2)


async def run(name, args):
    c = client()
    try:
        out, err = await execute_tool(c, name, args)
    finally:
        await c.aclose()
    assert not err, out
    return json.loads(out)


@respx.mock
async def test_listar_tickets_catalog_only_uses_api_pagination():
    install()
    r = await run("listar_tickets", {"area": "web", "limite": 2})
    assert r["filtros"] == {"area": "WEB"} and r["total"] == 3 and r["paginas"] == 2
    assert [t["number"] for t in r["tickets"]] == [9, 7]


@respx.mock
async def test_listar_tickets_situacao_aberto_excludes_cancelled_and_adds_days():
    install()
    r = await run("listar_tickets", {"situacao": "aberto"})
    assert [t["number"] for t in r["tickets"]] == [9, 8, 5]
    assert all("dias_em_aberto" in t for t in r["tickets"])


@respx.mock
async def test_listar_tickets_closed_in_period_by_closure_date_oldest_first():
    install()
    r = await run("listar_tickets", {"situacao": "fechado", "data_inicio": "2026-10-01", "periodo_por": "fechamento"})
    assert [t["number"] for t in r["tickets"]] == [7]
    r = await run("listar_tickets", {"situacao": "fechado", "ordenar": "antigos"})
    assert [t["number"] for t in r["tickets"]] == [4, 7]


@respx.mock
async def test_listar_tickets_sem_operador_congelado_prioridade_numero():
    install()
    assert [t["number"] for t in (await run("listar_tickets", {"situacao": "sem_operador"}))["tickets"]] == [5]
    assert [t["number"] for t in (await run("listar_tickets", {"situacao": "congelado"}))["tickets"]] == [8]
    assert [t["number"] for t in (await run("listar_tickets", {"prioridade": "alta"}))["tickets"]] == [9, 5]
    assert (await run("listar_tickets", {"numero": 7}))["total"] == 1


@respx.mock
async def test_listar_tickets_unknown_and_ambiguous_names_explain():
    install()
    r = await run("listar_tickets", {"operador": "zzz"})
    assert r["encontrado"] is False and 'operador "zzz" não encontrado' in r["motivo"]
    r = await run("listar_tickets", {"operador": "ana"})
    assert "ambíguo" in r["motivo"] and "Ana Paula" in r["motivo"]
    r = await run("listar_tickets", {"cliente": "luana", "area": "xxx"})
    assert "área" in r["motivo"]


@respx.mock
async def test_cliente_same_person_different_case_is_not_ambiguous():
    install()
    r = await run("listar_tickets", {"cliente": "fabio"})
    assert r["total"] == 4  # "Fábio Moreira" (3) e "fabio moreira" (1): mesma pessoa


@respx.mock
async def test_cliente_ambiguous_across_people():
    install()
    r = await run("listar_tickets", {"cliente": "ana"})  # Ana Lima e Luana Sabará (esta cai no meio da palavra, mas é substring)
    assert r["encontrado"] is False and "ambíguo" in r["motivo"]


@respx.mock
async def test_filter_with_no_match_is_empty_not_error():
    install()
    r = await run("listar_tickets", {"status": "Em Atendimento", "area": "web"})
    assert r["total"] == 0 and r["tickets"] == []


@respx.mock
async def test_vencidos_checks_real_sla():
    install()
    r = await run("listar_tickets_vencidos", {})
    assert r["quantidade_total"] == 2 and [t["number"] for t in r["tickets"]] == [7, 9]
    r = await run("listar_tickets_vencidos", {"situacao": "aberto"})
    assert [t["number"] for t in r["tickets"]] == [9]


@respx.mock
async def test_vencidos_refuses_too_many(monkeypatch):
    import app.tools.listing as listing

    monkeypatch.setattr(listing, "SLA_CHECK_LIMIT", 3)
    calls = install()
    r = await run("listar_tickets_vencidos", {})
    assert r["muitos_para_verificar"] is True and calls["detail"] == 0


@respx.mock
async def test_buscar_texto_ignores_accents():
    install()
    r = await run("buscar_tickets_por_texto", {"texto": "IMPRESSORA"})
    assert r["total"] == 1 and r["tickets"][0]["number"] == 9 and "impressora" in r["tickets"][0]["trecho"]


@respx.mock
async def test_resumo_por_status_ranking_and_percent():
    install()
    r = await run("resumo_tickets", {"agrupar_por": "status"})
    assert r["total"] == 6
    top = r["grupos"][0]
    assert top["quantidade"] == 2 and top["percentual"] == 33.3
    r = await run("resumo_tickets", {"agrupar_por": "operador", "limite": 1})
    assert len(r["grupos"]) == 1 and r["grupos"][0]["quantidade"] == 2
    r = await run("resumo_tickets", {"agrupar_por": "operador", "ordem": "asc"})
    assert r["grupos"][0]["quantidade"] == 1
    sem = [g for g in r["grupos"] if g["chave"] == "Sem operador"]
    assert sem and sem[0]["quantidade"] == 1


@respx.mock
async def test_resumo_cliente_merges_spelling_variants():
    install()
    r = await run("resumo_tickets", {"agrupar_por": "cliente"})
    by = {g["chave"]: g["quantidade"] for g in r["grupos"]}
    assert by["Fábio Moreira"] == 4 and len(by) == 3  # rótulo = grafia mais usada


@respx.mock
async def test_resumo_departamento_counts_per_catalog_item_and_rejects_local_filters():
    install()
    r = await run("resumo_tickets", {"agrupar_por": "departamento"})
    assert r["agrupado_por"] == "departamento"
    r = await run("resumo_tickets", {"agrupar_por": "departamento", "situacao": "aberto"})
    assert r["encontrado"] is False and "departamento" in r["motivo"]


@respx.mock
async def test_resumo_operacional():
    install()
    r = await run("resumo_operacional_tickets", {})
    assert (r["total"], r["abertos"], r["fechados"], r["sem_operador"], r["congelados"]) == (6, 3, 2, 1, 1)
    assert [t["numero"] for t in r["mais_antigos_em_aberto"]] == [5, 8, 9]


@respx.mock
async def test_analisar_carga_operador():
    install()
    r = await run("analisar_carga_operador", {"operador": "carlos"})
    assert r["operador"] == "Carlos Eduardo" and r["total"] == 2 and r["abertos"] == 1 and r["congelados"] == 1
    assert r["prioridade_alta_ou_urgente_abertos"] == 1 and r["mais_antigo_aberto"]["numero"] == 8
    r = await run("analisar_carga_operador", {"operador": "ana"})
    assert r["encontrado"] is False and "ambíguo" in r["motivo"]


@respx.mock
async def test_analisar_atividade_cliente_with_period():
    install()
    r = await run("analisar_atividade_cliente", {"cliente": "fabio"})
    assert r["cliente"] in {"Fábio Moreira", "fabio moreira"} and r["total"] == 4
    r = await run("analisar_atividade_cliente", {"cliente": "fabio", "data_inicio": "2026-10-01"})
    assert r["total"] == 2 and r["periodo"]["data_inicio"] == "2026-10-01"
    r = await run("analisar_atividade_cliente", {"cliente": "inexistente"})
    assert r["encontrado"] is False


@respx.mock
async def test_snapshot_cache_avoids_repeat_downloads():
    calls = install()
    c = client()
    await execute_tool(c, "resumo_tickets", {"agrupar_por": "status"})
    n = calls["list"]
    await execute_tool(c, "resumo_tickets", {"agrupar_por": "area"})
    assert calls["list"] == n
    await c.aclose()
