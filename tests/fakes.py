from types import SimpleNamespace


class FakeClaude:
    """Scripted stand-in for the network boundary: one parsed output per messages.parse call."""

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        o = self.outputs.pop(0)
        return SimpleNamespace(parsed_output=o, content=[SimpleNamespace(type="text", text=o.model_dump_json())])
