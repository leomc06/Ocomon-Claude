import json
from types import SimpleNamespace as NS

import httpx
import respx

from app.agent import MAX_ITERATIONS, MAX_TOOL_RESULT_CHARS, Agent
from app.config import Settings
from app.tickets_api import TicketsApiClient

BASE = "http://api.test"


async def _nosleep(_):
    pass


def usage():
    return NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)


def text_msg(text, stop="end_turn"):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop, usage=usage())


def tool_msg(*calls):
    blocks = [NS(type="tool_use", id=f"tu_{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
    return NS(content=blocks, stop_reason="tool_use", usage=usage())


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    async def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=lambda o: getattr(o, "__dict__", str(o)))))
        return self.responses.pop(0) if self.responses else tool_msg(("buscar_ticket_por_numero", {"numero": 1}))


def make(llm):
    tickets = TicketsApiClient(BASE, "t", "l", "a", sleep=_nosleep)
    return Agent(Settings(anthropic_model="m"), tickets, llm=llm), tickets


@respx.mock
async def test_single_tool_roundtrip():
    respx.get(f"{BASE}/tickets/4830").mock(return_value=httpx.Response(200, json={"number": 4830}))
    llm = FakeLLM([tool_msg(("buscar_ticket_por_numero", {"numero": 4830})), text_msg("Ticket 4830 encontrado.")])
    agent, tickets = make(llm)
    r = await agent.ask("ticket 4830?")
    assert r.answer == "Ticket 4830 encontrado."
    assert r.tools_used == ["buscar_ticket_por_numero"] and r.call_count == 1 and r.iterations == 2
    second = llm.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert json.loads(second[-1]["content"][0]["content"])["encontrado"] is True
    assert r.input_tokens == 20 and r.output_tokens == 10
    assert r.history[0] == {"role": "user", "content": "ticket 4830?"}
    note = r.history[1]["content"]
    assert note.startswith("Ticket 4830 encontrado.") and 'buscar_ticket_por_numero({"numero":4830})' in note
    assert r.calls == [{"name": "buscar_ticket_por_numero", "args": {"numero": 4830},
                        "meta": {"encontrado": True}, "error": False}]
    await tickets.aclose()


@respx.mock
async def test_parallel_calls_return_results_in_one_message():
    respx.get(f"{BASE}/tickets/1").mock(return_value=httpx.Response(200, json={"number": 1}))
    respx.get(f"{BASE}/tickets/2").mock(return_value=httpx.Response(200, json={"number": 2}))
    llm = FakeLLM([
        tool_msg(("buscar_ticket_por_numero", {"numero": 1}), ("buscar_ticket_por_numero", {"numero": 2})),
        text_msg("ok"),
    ])
    agent, tickets = make(llm)
    r = await agent.ask("compare 1 e 2")
    results = llm.requests[1]["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["tu_0", "tu_1"]
    assert r.call_count == 2
    await tickets.aclose()


async def test_invalid_tool_args_become_error_result_and_loop_continues():
    llm = FakeLLM([tool_msg(("buscar_ticket_por_numero", {"numero": "abc"})), text_msg("Preciso do número.")])
    agent, tickets = make(llm)
    r = await agent.ask("x")
    block = llm.requests[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True and "inválidos" in block["content"]
    assert r.answer == "Preciso do número."
    await tickets.aclose()


@respx.mock
async def test_large_tool_result_is_clipped():
    respx.get(f"{BASE}/tickets/9").mock(return_value=httpx.Response(200, json={"d": "x" * (MAX_TOOL_RESULT_CHARS * 2)}))
    llm = FakeLLM([tool_msg(("buscar_ticket_por_numero", {"numero": 9})), text_msg("ok")])
    agent, tickets = make(llm)
    await agent.ask("x")
    content = llm.requests[1]["messages"][-1]["content"][0]["content"]
    assert len(content) < MAX_TOOL_RESULT_CHARS + 200 and "truncado" in content
    await tickets.aclose()


@respx.mock
async def test_iteration_limit():
    respx.get(f"{BASE}/tickets/1").mock(return_value=httpx.Response(200, json={"number": 1}))
    llm = FakeLLM([])
    agent, tickets = make(llm)
    r = await agent.ask("loop")
    assert r.stop_reason == "max_iterations" and r.iterations == MAX_ITERATIONS
    assert "limite de etapas" in r.answer
    await tickets.aclose()


async def test_no_tool_answer_and_refusal_and_history():
    llm = FakeLLM([text_msg("Este sistema faz somente consultas."), NS(content=[], stop_reason="refusal", usage=usage())])
    agent, tickets = make(llm)
    r1 = await agent.ask("Cancele o ticket 4830.")
    assert r1.tools_used == [] and "somente consultas" in r1.answer
    r2 = await agent.ask("e o 4831?", r1.history)
    assert llm.requests[1]["messages"][:2] == r1.history
    assert r2.stop_reason == "refusal" and r2.answer
    await tickets.aclose()


async def test_request_shape_has_cached_system_and_tools():
    llm = FakeLLM([text_msg("oi")])
    agent, tickets = make(llm)
    await agent.ask("oi")
    req = llm.requests[0]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "somente leitura" in req["system"][0]["text"]
    assert {t["name"] for t in req["tools"]} >= {"listar_catalogo", "buscar_ticket_por_numero"}
    assert req["model"] == "m" and "tool_choice" not in req
    await tickets.aclose()
