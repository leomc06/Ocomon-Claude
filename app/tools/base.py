from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from app.tickets_api import TicketsApiClient


class ToolArgs(BaseModel):
    """Base dos argumentos: campos desconhecidos são rejeitados."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Handler = Callable[[TicketsApiClient, Any], Awaitable[dict]]


def _simplify(node):
    """Enxuga o JSON Schema do pydantic: sem title, sem default null, Optional[X] vira X."""
    if isinstance(node, list):
        return [_simplify(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "title" and isinstance(v, str):
            continue
        if k == "default" and v is None:
            continue
        out[k] = _simplify(v)
    options = out.get("anyOf")
    if options:
        rest = [o for o in options if o != {"type": "null"}]
        if len(rest) == 1:
            del out["anyOf"]
            out = {**rest[0], **out}
    return out


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Handler

    def to_anthropic(self) -> dict:
        schema = _simplify(self.args_model.model_json_schema())
        return {"name": self.name, "description": self.description, "input_schema": schema}
