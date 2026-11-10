import asyncio

import anthropic
import httpx
from fastapi.testclient import TestClient

from app.agent import AgentResult
from app.config import Settings
from app.main import create_app
from app.ratelimit import SlidingWindowLimiter
from app.sessions import SessionStore


class FakeAgent:
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior

    async def ask(self, question, history=None):
        self.calls.append((question, list(history or [])))
        if self.behavior:
            return await self.behavior(question)
        answer = f"resp:{question}"
        return AgentResult(answer=answer, tools_used=["listar_tickets"], call_count=1, iterations=2, duration_ms=5,
                           history=[*(history or []), {"role": "user", "content": question},
                                    {"role": "assistant", "content": answer}])


def make(agent=None, **settings):
    settings.setdefault("agent_max_concurrent_requests", 4)
    agent = agent or FakeAgent()
    return TestClient(create_app(Settings(**settings), agent=agent)), agent


def ask(client, q="oi", **kw):
    return client.post("/api/ia/consultar-os", json={"pergunta": q, **kw.pop("body", {})}, **kw)


def test_health_and_static_index_with_security_headers():
    with make()[0] as c:
        assert c.get("/health").json() == {"status": "ok"}
        r = c.get("/")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert r.headers["x-content-type-options"] == "nosniff" and "default-src 'self'" in r.headers["content-security-policy"]


def test_ok_response_shape():
    with make()[0] as c:
        r = ask(c, "  quantos tickets?  ")
        d = r.json()
        assert r.status_code == 200
        assert d["resposta"] == "resp:quantos tickets?" and d["toolsUtilizadas"] == ["listar_tickets"]
        assert d["quantidadeChamadas"] == 1 and d["sessionId"] and d["requestId"]
        assert d["visualizacaoPreferida"] is None and d["sugestoes"] == []
        assert ask(c, "quantos por área? em gráfico").json()["visualizacaoPreferida"] == "barras"


def test_session_keeps_history_between_requests():
    c, agent = make()
    with c:
        first = ask(c, "primeira").json()
        ask(c, "segunda", body={"session_id": first["sessionId"]})
        assert agent.calls[1][1][0] == {"role": "user", "content": "primeira"}
        ask(c, "outra sessão")
        assert agent.calls[2][1] == []


def test_validation_errors():
    with make()[0] as c:
        assert ask(c, "").status_code == 422
        assert ask(c, "x" * 2001).status_code == 422
        assert c.post("/api/ia/consultar-os", json={"pergunta": "a", "extra": 1}).status_code == 422
        assert ask(c, "a", body={"session_id": "../etc"}).status_code == 422
        r = c.post("/api/ia/consultar-os", content="não é json", headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["erro"] == "requisicao_invalida"
        assert c.get("/api/ia/consultar-os").status_code in (404, 405)  # GET não é aceito nessa rota
        assert c.get("/nao/existe").status_code == 404


def test_invalid_user_id_header():
    with make()[0] as c:
        r = ask(c, headers={"X-User-Id": "bad user!"})
        assert r.status_code == 400 and r.json()["erro"] == "usuario_invalido"
        assert ask(c, headers={"X-User-Id": "leo@x.com"}).status_code == 200


def test_rate_limit_returns_429_with_retry_after():
    with make(agent_rate_limit_max_requests=2)[0] as c:
        assert ask(c).status_code == 200 and ask(c).status_code == 200
        r = ask(c)
        assert r.status_code == 429 and r.json()["erro"] == "limite_de_requisicoes" and "retry-after" in r.headers


def test_busy_agent_returns_429():
    gate = {}

    async def slow(question):
        gate["started"].set()
        await gate["release"].wait()
        return AgentResult(answer="ok", history=[])

    async def scenario():
        gate["started"], gate["release"] = asyncio.Event(), asyncio.Event()
        app = create_app(Settings(agent_max_concurrent_requests=1), agent=FakeAgent(slow))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                first = asyncio.create_task(c.post("/api/ia/consultar-os", json={"pergunta": "a"}))
                await gate["started"].wait()
                busy = await c.post("/api/ia/consultar-os", json={"pergunta": "b"})
                gate["release"].set()
                return busy, await first

    busy, first = asyncio.run(scenario())
    assert busy.status_code == 429 and busy.json()["erro"] == "agente_ocupado"
    assert first.status_code == 200


def test_error_mapping_and_slot_released():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    async def timeout(_): raise asyncio.TimeoutError()
    async def api_timeout(_): raise anthropic.APITimeoutError(request=req)
    async def api_500(_): raise anthropic.InternalServerError("boom", response=httpx.Response(500, request=req), body=None)
    async def conn(_): raise anthropic.APIConnectionError(request=req)
    async def bug(_): raise ValueError("segredo interno")

    for behavior, status, code in [(timeout, 504, "tempo_excedido"), (api_timeout, 504, "tempo_excedido"),
                                   (api_500, 502, "falha_no_modelo"), (conn, 502, "falha_no_modelo"),
                                   (bug, 500, "erro_interno")]:
        c, _ = make(FakeAgent(behavior), agent_max_concurrent_requests=1)
        with c:
            for _ in range(2):  # o segundo pedido prova que o slot de concorrência foi liberado
                r = ask(c)
                assert r.status_code == status and r.json()["erro"] == code
                assert "segredo" not in r.text and "boom" not in r.text


def test_timeout_setting_is_enforced():
    async def hang(_): await asyncio.sleep(5)

    c, _ = make(FakeAgent(hang), agent_request_timeout_ms=50)
    with c:
        assert ask(c).status_code == 504


def test_missing_api_key_refuses_to_start():
    import pytest

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        with TestClient(create_app(Settings(anthropic_api_key=""))):
            pass


def test_limiter_and_session_store_units():
    t = [0.0]
    lim = SlidingWindowLimiter(10, 2, clock=lambda: t[0])
    assert lim.check("a") == 0 and lim.check("a") == 0 and lim.check("a") > 0 and lim.check("b") == 0
    t[0] = 11
    assert lim.check("a") == 0

    s = SessionStore(ttl_s=10, max_sessions=2, clock=lambda: t[0])
    h = [{"role": "user", "content": str(i)} if i % 2 == 0 else {"role": "assistant", "content": str(i)} for i in range(25)]
    s.put("x", h)
    got = s.get("x")
    assert len(got) <= 20 and got[0]["role"] == "user"
    t[0] += 11
    assert s.get("x") == []
    s.put("a", h[:2]); s.put("b", h[:2]); s.put("c", h[:2])
    assert s.get("c") and sum(bool(s.get(k)) for k in "abc") == 2
