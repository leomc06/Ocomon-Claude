"""API HTTP: POST /api/ia/consultar-os, GET /health e o chat web (web/)."""

import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent import Agent
from app.config import Settings, get_settings
from app.presentation import build_suggestions, detect_visualization
from app.ratelimit import SlidingWindowLimiter
from app.sessions import SessionStore
from app.tickets_api import TicketsApiClient

log = logging.getLogger(__name__)
audit_log = logging.getLogger("audit")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
USER_ID_PATTERN = re.compile(r"^[\w.@-]{1,64}$")
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class AskBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    pergunta: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(None, pattern=SESSION_ID_PATTERN)


def _error(status: int, code: str, message: str, request_id: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"erro": code, "mensagem": message, "requestId": request_id}, status_code=status, headers=headers
    )


def create_app(settings: Settings | None = None, agent: Agent | None = None) -> FastAPI:
    settings = settings or get_settings()
    limiter = SlidingWindowLimiter(settings.agent_rate_limit_window_ms / 1000, settings.agent_rate_limit_max_requests)
    sessions = SessionStore()
    state = {"inflight": 0}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tickets = None
        if agent is None:
            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY não definida: o servidor não sobe sem ela.")
            tickets = TicketsApiClient.from_settings(settings)
            app.state.agent = Agent(settings, tickets)
        else:
            app.state.agent = agent
        yield
        if tickets is not None:
            await tickets.aclose()

    app = FastAPI(title="ocomon-claude", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
        return _error(422, "requisicao_invalida", f"Requisição inválida (campos: {', '.join(fields) or 'corpo'}).",
                      uuid.uuid4().hex[:12])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "rota_nao_encontrada", 405: "metodo_nao_permitido"}
        return _error(exc.status_code, codes.get(exc.status_code, "erro_http"), str(exc.detail), uuid.uuid4().hex[:12])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/ia/consultar-os")
    async def consultar(body: AskBody, request: Request):
        request_id = uuid.uuid4().hex[:12]
        ip = request.client.host if request.client else "desconhecido"
        user = request.headers.get("x-user-id", "anonimo")
        outcome = {"requestId": request_id, "usuario": user, "ip": ip, "perguntaChars": len(body.pergunta)}

        def reply(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
            audit_log.info(json.dumps({**outcome, "resultado": "erro", "codigoErro": code}, ensure_ascii=False))
            return _error(status, code, message, request_id, headers)

        if not USER_ID_PATTERN.match(user):
            return reply(400, "usuario_invalido", "Cabeçalho X-User-Id inválido.")
        wait = limiter.check(ip)
        if wait:
            return reply(429, "limite_de_requisicoes", "Muitas requisições. Tente novamente em instantes.",
                         {"Retry-After": str(int(wait) + 1)})
        if state["inflight"] >= settings.agent_max_concurrent_requests:
            return reply(429, "agente_ocupado", "O agente está ocupado com outra consulta. Tente novamente em instantes.",
                         {"Retry-After": "5"})

        session_id = body.session_id or uuid.uuid4().hex
        state["inflight"] += 1
        try:
            result = await asyncio.wait_for(
                request.app.state.agent.ask(body.pergunta, sessions.get(session_id)),
                timeout=settings.agent_request_timeout_ms / 1000,
            )
        except (asyncio.TimeoutError, anthropic.APITimeoutError):
            return reply(504, "tempo_excedido", "A consulta demorou demais. Tente restringir a pergunta.")
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            log.error("[%s] falha na API do Claude: %s", request_id, type(e).__name__)
            return reply(502, "falha_no_modelo", "Não foi possível consultar o modelo agora. Tente novamente.")
        except Exception:
            log.exception("[%s] erro interno", request_id)
            return reply(500, "erro_interno", "Erro interno ao processar a consulta.")
        finally:
            state["inflight"] -= 1

        sessions.put(session_id, result.history)
        audit_log.info(json.dumps({
            **outcome, "resultado": "ok", "tools": result.tools_used, "iteracoes": result.iterations,
            "duracaoMs": result.duration_ms, "tokensEntrada": result.input_tokens,
            "tokensSaida": result.output_tokens,
        }, ensure_ascii=False))
        return {
            "resposta": result.answer,
            "toolsUtilizadas": result.tools_used,
            "quantidadeChamadas": result.call_count,
            "duracaoMs": result.duration_ms,
            "visualizacaoPreferida": detect_visualization(body.pergunta),
            "sugestoes": build_suggestions(getattr(result, "calls", [])),
            "sessionId": session_id,
            "requestId": request_id,
        }

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    uvicorn.run(create_app(s), host=s.agent_host, port=s.agent_port, log_level="info")


if __name__ == "__main__":
    run()
