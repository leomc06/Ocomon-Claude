"""Loop de tool-use: o Claude escolhe as tools, recebe os resultados e redige a resposta."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.config import Settings
from app.presentation import history_note, strip_history_note
from app.prompts import build_system_prompt
from app.tickets_api import TicketsApiClient
from app.tools import anthropic_tool_defs, execute_tool

log = logging.getLogger(__name__)

MAX_ITERATIONS = 8
MAX_TOOL_RESULT_CHARS = 30_000
MAX_TOKENS = 16_000


@dataclass
class AgentResult:
    answer: str
    tools_used: list[str] = field(default_factory=list)
    call_count: int = 0
    iterations: int = 0
    stop_reason: str | None = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    # Cada consulta feita: {name, args, meta, error}; alimenta sugestões e o histórico.
    calls: list[dict] = field(default_factory=list)
    # Histórico para a próxima pergunta da mesma conversa (só texto: pergunta + resposta final).
    history: list[dict] = field(default_factory=list)


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + f"\n[... resultado truncado em {MAX_TOOL_RESULT_CHARS} caracteres]"


def _meta(content: str) -> dict:
    """Campos de paginação/estado do resultado de uma tool (sem guardar os dados)."""
    try:
        data = json.loads(content)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in ("pagina", "paginas", "total", "encontrado", "truncado") if k in data}


def _text_of(content: list) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


class Agent:
    def __init__(
        self,
        settings: Settings,
        tickets: TicketsApiClient,
        llm: anthropic.AsyncAnthropic | None = None,
    ):
        self._settings = settings
        self._tickets = tickets
        self._llm = llm or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            timeout=settings.anthropic_timeout_ms / 1000,
        )
        self._tools = anthropic_tool_defs()

    async def ask(self, question: str, history: list[dict] | None = None) -> AgentResult:
        started = time.monotonic()
        messages: list[dict] = [*(history or []), {"role": "user", "content": question}]
        result = AgentResult(answer="")
        system = [{"type": "text", "text": build_system_prompt(), "cache_control": {"type": "ephemeral"}}]
        extra: dict[str, Any] = {}
        if self._settings.anthropic_effort:
            extra["output_config"] = {"effort": self._settings.anthropic_effort}

        for _ in range(MAX_ITERATIONS):
            result.iterations += 1
            response = await self._llm.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=self._tools,
                messages=messages,
                **extra,
            )
            usage = response.usage
            result.input_tokens += usage.input_tokens or 0
            result.output_tokens += usage.output_tokens or 0
            result.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            result.stop_reason = response.stop_reason

            if response.stop_reason == "tool_use":
                # O conteúdo inteiro (inclusive blocos de thinking) volta sem alteração.
                messages.append({"role": "assistant", "content": response.content})
                calls = [b for b in response.content if b.type == "tool_use"]
                outcomes = await asyncio.gather(*(execute_tool(self._tickets, c.name, c.input) for c in calls))
                for c in calls:
                    result.tools_used.append(c.name)
                result.call_count += len(calls)
                # Todos os tool_result de uma rodada vão numa única mensagem de usuário.
                tool_results = []
                for c, (content, is_error) in zip(calls, outcomes):
                    block = {"type": "tool_result", "tool_use_id": c.id, "content": _clip(content)}
                    if is_error:
                        block["is_error"] = True
                    tool_results.append(block)
                    result.calls.append({"name": c.name, "args": dict(c.input or {}),
                                         "meta": {} if is_error else _meta(content), "error": is_error})
                messages.append({"role": "user", "content": tool_results})
                continue

            text = _text_of(response.content)
            if response.stop_reason == "refusal":
                text = text or "Não posso responder a essa pergunta."
            elif response.stop_reason == "max_tokens":
                text = (text + "\n\n(resposta cortada por limite de tamanho)").strip()
            result.answer = strip_history_note(text)
            break
        else:
            result.answer = (
                "Não consegui concluir a consulta dentro do limite de etapas. "
                "Tente restringir a pergunta (por exemplo, com um período ou uma área)."
            )
            result.stop_reason = "max_iterations"

        result.history = [*(history or []), {"role": "user", "content": question}, {"role": "assistant", "content": result.answer + history_note(result.calls)}]
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result
