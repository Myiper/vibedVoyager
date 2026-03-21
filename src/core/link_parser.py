from __future__ import annotations

from html.parser import HTMLParser


class HTMLLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self._title_capture = False
        self._title_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.append(value)
        elif tag.lower() == "title":
            self._title_capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._title_capture = False

    def handle_data(self, data: str) -> None:
        if self._title_capture:
            stripped = data.strip()
            if stripped:
                self._title_chunks.append(stripped)

    @property
    def title(self) -> str:
        return " ".join(self._title_chunks).strip()

