"""Cliente assíncrono da API HTTP de tickets que fica na frente do OcoMon."""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger(__name__)

META_ENDPOINTS = {
    "areas": "/meta/areas",
    "priorities": "/meta/priorities",
    "channels": "/meta/channels",
    "statuses": "/meta/statuses",
    "departments": "/meta/departments",
    "users": "/meta/users",
}

# Teto de segurança de paginação (o loop sempre para no `pages` real da API).
DEFAULT_MAX_PAGES = 400


class TicketsApiError(Exception):
    def __init__(self, message: str, status: int | None = None, type_: str | None = None):
        super().__init__(message)
        self.status = status
        self.type = type_


def _is_retryable(error: TicketsApiError) -> bool:
    if error.status is None:
        # Sem status = erro de rede/timeout (JSON inválido não é retryable).
        return error.type in {"timeout", "connection"}
    return error.status == 429 or error.status >= 500


def _unwrap_list(body: Any, key: str) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in (key, "items", "results"):
            if isinstance(body.get(k), list):
                return body[k]
    log.error("API de tickets: metadado em formato inesperado (chave %r), tratando como lista vazia.", key)
    return []


def _compact_headers(values: dict[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in values.items() if v is not None}


def _respects_descending_order(page: list[dict], previous_max: str | None) -> bool:
    """A parada antecipada só é segura se a API devolve em ordem decrescente de abertura."""
    if previous_max is not None and page and page[0].get("opening_date", "") > previous_max:
        return False
    for i in range(1, len(page)):
        if page[i].get("opening_date", "") > page[i - 1].get("opening_date", ""):
            return False
    return True


class TicketsApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        login: str,
        app: str,
        timeout_s: float = 15.0,
        max_retries: int = 2,
        retry_delay_s: float = 0.3,
        metadata_ttl_s: float = 600.0,
        page_size: int = 100,
        concurrency: int = 5,
        snapshot_ttl_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers={"accept": "application/json", "token": token, "login": login, "app": app},
        )
        self._max_retries = max_retries
        self._retry_delay_s = retry_delay_s
        self._metadata_ttl_s = metadata_ttl_s
        self._sleep = sleep
        self._meta_cache: dict[str, tuple[float, list]] = {}
        self._page_size = page_size
        self.concurrency = concurrency
        self._snapshot_ttl_s = snapshot_ttl_s
        self._snapshots: dict[tuple, tuple[float, tuple[list[dict], bool]]] = {}

    @classmethod
    def from_settings(cls, s: Any, **kw: Any) -> "TicketsApiClient":
        return cls(
            s.tickets_api_base_url, s.tickets_api_token, s.tickets_api_login, s.tickets_api_app,
            timeout_s=s.tickets_api_timeout_ms / 1000,
            metadata_ttl_s=s.tickets_api_metadata_cache_ttl_ms / 1000,
            concurrency=s.tickets_api_fan_out_concurrency,
            **kw,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request_once(self, path: str, headers: dict[str, str] | None = None) -> Any:
        try:
            response = await self._http.get(path, headers=headers)
        except httpx.TimeoutException:
            raise TicketsApiError("Timeout ao consultar a API de tickets.", type_="timeout")
        except httpx.HTTPError:
            raise TicketsApiError("Não foi possível conectar à API de tickets.", type_="connection")

        body: Any = None
        parse_failed = False
        try:
            body = response.json()
        except ValueError:
            parse_failed = True

        # Checa o status ANTES do parse: 5xx com corpo HTML não vira "JSON inválido".
        if not response.is_success:
            if parse_failed:
                raise TicketsApiError(
                    f"API de tickets retornou erro: HTTP {response.status_code}", status=response.status_code
                )
            errors = body.get("errors") if isinstance(body, dict) else None
            entry = errors[0] if isinstance(errors, list) and errors else errors
            entry = entry if isinstance(entry, dict) else {}
            raise TicketsApiError(
                f"API de tickets retornou erro: {entry.get('message') or f'HTTP {response.status_code}'}",
                status=response.status_code,
                type_=entry.get("type"),
            )
        if parse_failed:
            raise TicketsApiError("API de tickets retornou JSON inválido.")
        return body

    async def _request(self, path: str, headers: dict[str, str] | None = None) -> Any:
        for attempt in range(self._max_retries + 1):
            try:
                return await self._request_once(path, headers)
            except TicketsApiError as error:
                if attempt >= self._max_retries or not _is_retryable(error):
                    raise
                await self._sleep(self._retry_delay_s * 2**attempt)
        raise AssertionError("inalcançável")

    async def list_tickets(
        self,
        *,
        column: str | None = None,
        status: Any = None,
        area: Any = None,
        number: Any = None,
        department: Any = None,
        operator: Any = None,
        limit: int | None = None,
        page: int | None = None,
    ) -> dict:
        headers = _compact_headers(
            dict(
                column=column, status=status, area=area, number=number,
                department=department, operator=operator, limit=limit, page=page,
            )
        )
        return await self._request("/tickets", headers)

    async def list_page(self, filters: dict, page: int, limit: int | None = None) -> dict:
        try:
            return await self.list_tickets(**filters, limit=limit or self._page_size, page=page)
        except TicketsApiError as error:
            # A API responde 400 not_found quando o filtro não casa nenhum ticket: é lista vazia.
            if error.status == 400 and error.type == "not_found":
                return {"results": 0, "page": page, "pages": 1, "tickets": []}
            raise

    async def count_tickets(self, filters: dict | None = None) -> int:
        """Total exato de tickets para os filtros, sem baixar o corpo (limit=1)."""
        data = await self.list_page(filters or {}, 1, limit=1)
        return data.get("results") or 0

    async def fetch_all_tickets(
        self,
        filters: dict | None = None,
        *,
        max_pages: int | None = None,
        stop_when: Callable[[dict], bool] | None = None,
    ) -> tuple[list[dict], bool]:
        """Pagina tudo. Devolve (tickets, truncado).

        Sem `stop_when`, as páginas depois da primeira são baixadas em paralelo.
        Com `stop_when` (corte por data de abertura), é sequencial: a parada antecipada
        depende da ordem decrescente de abertura, verificada a cada página.
        """
        filters = filters or {}
        limit_pages = max_pages or DEFAULT_MAX_PAGES
        first = await self.list_page(filters, 1)
        page = first.get("tickets") or []
        pages = first.get("pages") or 1

        if stop_when is None:
            last = min(pages, limit_pages)
            sem = asyncio.Semaphore(self.concurrency)

            async def fetch(n: int) -> list[dict]:
                async with sem:
                    return (await self.list_page(filters, n)).get("tickets") or []

            rest = await asyncio.gather(*(fetch(n) for n in range(2, last + 1)))
            tickets = list(page)
            for chunk in rest:
                tickets.extend(chunk)
            return tickets, pages > limit_pages

        tickets: list[dict] = []
        page_no = 1
        truncated = False
        stop_reliable = True
        previous_max: str | None = None

        while True:
            if page_no > 1:
                data = await self.list_page(filters, page_no)
                page = data.get("tickets") or []
                pages = data.get("pages") or 1

            if stop_reliable and not _respects_descending_order(page, previous_max):
                stop_reliable = False
                log.error("fetch_all_tickets: página fora de ordem decrescente; parada antecipada desativada.")
            if page:
                previous_max = page[-1].get("opening_date")

            tickets.extend(page)

            if page_no >= pages or not page:
                break
            if stop_reliable and stop_when(page[-1]):
                break
            if page_no >= limit_pages:
                truncated = True
                break
            page_no += 1

        return tickets, truncated

    async def fetch_snapshot(self, filters: dict | None = None, *, since: str | None = None) -> tuple[list[dict], bool]:
        """fetch_all com cache curto (perguntas seguidas repetem a mesma busca).

        `since` (AAAA-MM-DD) permite parar quando os tickets ficam mais antigos que a data
        de abertura pedida. Quem recebe o resultado não deve alterá-lo.
        """
        filters = filters or {}
        key = (tuple(sorted((k, str(v)) for k, v in filters.items() if v is not None)), since)
        now = time.monotonic()
        hit = self._snapshots.get(key)
        if hit and now - hit[0] < self._snapshot_ttl_s:
            return hit[1]
        stop = (lambda t: (t.get("opening_date") or "") < since) if since else None
        result = await self.fetch_all_tickets({k: v for k, v in filters.items() if v is not None}, stop_when=stop)
        if len(self._snapshots) >= 16:
            self._snapshots.pop(min(self._snapshots, key=lambda k: self._snapshots[k][0]))
        self._snapshots[key] = (now, result)
        return result

    async def get_ticket(self, number: int | str) -> dict:
        return await self._request(f"/tickets/{number}")

    async def get_meta(self, kind: str) -> list:
        """Catálogo (areas/priorities/channels/statuses/departments/users) com cache TTL."""
        now = time.monotonic()
        cached = self._meta_cache.get(kind)
        if cached and now - cached[0] < self._metadata_ttl_s:
            return cached[1]
        items = _unwrap_list(await self._request(META_ENDPOINTS[kind]), kind)
        self._meta_cache[kind] = (now, items)
        return items
