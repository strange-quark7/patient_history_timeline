import json
from types import SimpleNamespace

from medtimeline.extract.claude import ClaudeExtractor
from medtimeline.ingest import PageInput
from medtimeline.schema import PageExtraction

MINIMAL = {"doc_type": "prescription", "script": "typed", "encounter": {}, "patient": {}}


class FakeMessages:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=PageExtraction.model_validate(MINIMAL))


def test_sends_image_and_text_layer_with_schema():
    fake = SimpleNamespace(messages=FakeMessages())
    ex = ClaudeExtractor(client=fake)
    out = ex.extract(PageInput("p1", "a.pdf", 1, b"\x89PNGfake", "Tab Pan 40"))
    assert out.doc_type.value == "prescription"
    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is PageExtraction
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert "Tab Pan 40" in blocks[1]["text"]


def test_refusal_raises():
    import pytest

    from medtimeline.extract import ExtractionError

    class Refusing(FakeMessages):
        def parse(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    ex = ClaudeExtractor(client=SimpleNamespace(messages=Refusing()))
    with pytest.raises(ExtractionError):
        ex.extract(PageInput("p1", "a.png", 1, b"x"))
