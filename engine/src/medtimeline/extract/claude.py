"""Cloud extractor: Claude vision with structured output.

Reads one page image (plus its text layer, if any) and returns a validated
PageExtraction. Used for v1; replaced by a local model later.
"""

from __future__ import annotations

import base64

from medtimeline.extract.base import ExtractionError, register
from medtimeline.ingest import PageInput
from medtimeline.schema import PageExtraction

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You read scanned medical documents (prescriptions, case sheets, lab reports, \
discharge summaries), many of them handwritten, and transcribe their contents into a structured record.

Rules:
- Transcribe only what is on the page. Never infer a diagnosis, drug or value that is not written.
- Keep abbreviations as written in source_text (e.g. "T. Pan 40 1-0-0 x 5d"), and expand them in the structured fields when the meaning is clear.
- Dates are DD/MM/YYYY unless the page clearly shows otherwise. Set date_ambiguous when day and month could be swapped or the year is missing.
- Set confidence honestly. Handwriting you are unsure of gets a low confidence; text you cannot read goes in illegible_notes, not into a guessed field.
- If the page has an embedded text layer, prefer it for typed text, but trust the image for handwriting and layout."""


@register("claude")
class ClaudeExtractor:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "high", client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.name = f"claude:{model}"

    def _content(self, page: PageInput) -> list[dict]:
        content: list[dict] = []
        if page.image_png:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(page.image_png).decode("ascii"),
                    },
                }
            )
        instruction = "Extract this page into the schema."
        if page.text_layer:
            instruction += f"\n\nEmbedded text layer from the file:\n<text_layer>\n{page.text_layer}\n</text_layer>"
        content.append({"type": "text", "text": instruction})
        return content

    def extract(self, page: PageInput) -> PageExtraction:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": self._content(page)}],
            output_format=PageExtraction,
        )
        if response.stop_reason == "refusal":
            raise ExtractionError(f"Model declined page {page.page_id}")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ExtractionError(f"Incomplete extraction for page {page.page_id} ({response.stop_reason})")
        return response.parsed_output
