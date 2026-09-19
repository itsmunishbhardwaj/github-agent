import functools

import anthropic

MODEL = "claude-sonnet-5"


@functools.cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # lazy: .env must be loaded before the key is read
