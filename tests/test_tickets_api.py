import httpx
import pytest
import respx

from app.tickets_api import TicketsApiClient, TicketsApiError

BASE = "http://api.test"


async def _nosleep(_):
    pass


def make_client(**kw):
    return TicketsApiClient(BASE, "tok", "log", "app", sleep=_nosleep, **kw)


@respx.mock
async def test_sends_auth_and_filter_headers():
    route = respx.get(f"{BASE}/tickets").mock(return_value=httpx.Response(200, json={"tickets": [], "pages": 1}))
    client = make_client()
    await client.list_tickets(status=3, limit=10, area=None)
    sent = route.calls[0].request.headers
    assert sent["token"] == "tok" and sent["login"] == "log" and sent["app"] == "app"
    assert sent["status"] == "3" and sent["limit"] == "10"
    assert "area" not in sent
    await client.aclose()


@respx.mock
async def test_retries_5xx_then_succeeds():
    route = respx.get(f"{BASE}/tickets/1").mock(
        side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"number": 1})]
    )
    client = make_client()
    assert (await client.get_ticket(1)) == {"number": 1}
    assert route.call_count == 3
    await client.aclose()


@respx.mock
async def test_4xx_not_retried_and_message_extracted():
    route = respx.get(f"{BASE}/tickets/9").mock(
        return_value=httpx.Response(404, json={"errors": [{"message": "não encontrado", "type": "not_found"}]})
    )
    client = make_client()
    with pytest.raises(TicketsApiError) as exc:
        await client.get_ticket(9)
    assert route.call_count == 1
    assert exc.value.status == 404 and exc.value.type == "not_found"
    assert "não encontrado" in str(exc.value)
    await client.aclose()


@respx.mock
async def test_5xx_html_body_keeps_status():
    respx.get(f"{BASE}/tickets/2").mock(return_value=httpx.Response(502, text="<html>bad gateway</html>"))
    client = make_client(max_retries=0)
    with pytest.raises(TicketsApiError) as exc:
        await client.get_ticket(2)
    assert exc.value.status == 502
    await client.aclose()


@respx.mock
async def test_invalid_json_on_200_is_not_retried():
    route = respx.get(f"{BASE}/tickets/3").mock(return_value=httpx.Response(200, text="oops"))
    client = make_client()
    with pytest.raises(TicketsApiError, match="JSON inválido"):
        await client.get_ticket(3)
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_connection_error_retried_then_raises():
    route = respx.get(f"{BASE}/tickets/4").mock(side_effect=httpx.ConnectError("x"))
    client = make_client()
    with pytest.raises(TicketsApiError, match="conectar"):
        await client.get_ticket(4)
    assert route.call_count == 3
    await client.aclose()


@respx.mock
async def test_fetch_all_paginates():
    def handler(request):
        page = int(request.headers["page"])
        return httpx.Response(200, json={"pages": 3, "tickets": [{"number": page, "opening_date": f"2026-0{4 - page}-01"}]})

    respx.get(f"{BASE}/tickets").mock(side_effect=handler)
    client = make_client()
    tickets, truncated = await client.fetch_all_tickets()
    assert [t["number"] for t in tickets] == [1, 2, 3] and not truncated
    await client.aclose()


@respx.mock
async def test_fetch_all_stop_when_and_truncation():
    def handler(request):
        page = int(request.headers["page"])
        return httpx.Response(200, json={"pages": 10, "tickets": [{"number": page, "opening_date": f"2026-12-{20 - page:02d}"}]})

    route = respx.get(f"{BASE}/tickets").mock(side_effect=handler)
    client = make_client()
    tickets, truncated = await client.fetch_all_tickets(stop_when=lambda t: t["number"] >= 2)
    assert len(tickets) == 2 and not truncated
    route.reset()
    tickets, truncated = await client.fetch_all_tickets(max_pages=3)
    assert len(tickets) == 3 and truncated
    await client.aclose()


@respx.mock
async def test_fetch_all_disables_early_stop_when_order_breaks():
    def handler(request):
        page = int(request.headers["page"])
        # datas CRESCENTES entre páginas: contradiz a suposição
        return httpx.Response(200, json={"pages": 3, "tickets": [{"number": page, "opening_date": f"2026-01-0{page}"}]})

    respx.get(f"{BASE}/tickets").mock(side_effect=handler)
    client = make_client()
    tickets, _ = await client.fetch_all_tickets(stop_when=lambda t: t["number"] >= 2)
    assert len(tickets) == 3
    await client.aclose()


@respx.mock
async def test_meta_unwrap_and_cache():
    route = respx.get(f"{BASE}/meta/areas").mock(return_value=httpx.Response(200, json={"areas": [{"id": 1, "name": "WEB"}]}))
    client = make_client()
    assert await client.get_meta("areas") == [{"id": 1, "name": "WEB"}]
    await client.get_meta("areas")
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_meta_unexpected_format_is_empty_list():
    respx.get(f"{BASE}/meta/users").mock(return_value=httpx.Response(200, json={"foo": 1}))
    client = make_client()
    assert await client.get_meta("users") == []
    await client.aclose()
