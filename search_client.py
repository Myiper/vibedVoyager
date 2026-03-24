from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# Edit these values directly in this file.
HOST = "localhost"
PORT = 3600
TERM = "ve"
LIMIT = 500
RUN_ID = ""  # Keep empty for global search.
TIMEOUT_SECONDS = 10.0


def main() -> None:
    params: dict[str, str] = {"q": TERM, "limit": str(LIMIT)}
    if RUN_ID.strip():
        params["run_id"] = RUN_ID.strip()

    query = urlencode(params)
    url = f"http://{HOST}:{PORT}/search?{query}"

    try:
        with urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
            print(json.dumps(payload, indent=2, ensure_ascii=False))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTPError {exc.code}: {exc.reason}")
        if body:
            print(body)
    except URLError as exc:
        print(f"URLError: {exc.reason}")


if __name__ == "__main__":
    main()

