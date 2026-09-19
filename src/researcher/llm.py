import functools
import json
from typing import TypeVar

import anthropic
from pydantic import BaseModel

MODEL = "claude-sonnet-5"


@functools.cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # lazy: .env must be loaded before the key is read


T = TypeVar("T", bound=BaseModel)


def ask(system: str, payload: BaseModel | dict, schema: type[T], max_tokens: int = 16000) -> T:
    content = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload)
    resp = get_client().messages.parse(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}], output_format=schema,
    )
    return resp.parsed_output
