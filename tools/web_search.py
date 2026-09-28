"""
Web search and page-fetch helper for the web.* tools.

Uses DuckDuckGo's HTML endpoint (no API key required) for search and
returns readable text for fetch. Results are dicts with success/error
so the tool runtime can speak them naturally.
"""

import re
import urllib.parse
import urllib.request

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

_TIMEOUT = 10


class WebSearcher:
    """Deterministic web search/fetch without browser UI."""

    def search(self, query: str) -> dict:
        query = (query or "").strip()

        if not query:
            return {
                "success": False,
                "error": "No search query was provided.",
            }

        url = (
            "https://html.duckduckgo.com/html/?q="
            + urllib.parse.quote(query)
        )

        try:
            html = self._get(url)
        except Exception as error:
            return {
                "success": False,
                "error": f"Web search failed: {error}",
            }

        results = self._parse_results(html)

        if not results:
            return {
                "success": True,
                "results": [],
                "message": "No results found.",
            }

        return {
            "success": True,
            "results": results,
            "message": (
                f"Found {len(results)} results. "
                f"Top result: {results[0]['title']} - "
                f"{results[0]['snippet']}"
            ),
        }

    def fetch(self, url: str) -> dict:
        url = (url or "").strip()

        if not url:
            return {
                "success": False,
                "error": "No URL was provided.",
            }

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            html = self._get(url)
        except Exception as error:
            return {
                "success": False,
                "error": f"Could not fetch the page: {error}",
            }

        text = self._html_to_text(html)

        if not text:
            return {
                "success": True,
                "text": "",
                "message": "The page loaded but contains no readable text.",
            }

        return {
            "success": True,
            "text": text[:5000],
            "message": text[:1000],
        }

    # ==================================================
    # INTERNALS
    # ==================================================

    def _get(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )

        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.read().decode("utf-8", errors="ignore")

    @staticmethod
    def _parse_results(html: str) -> list:
        results = []

        blocks = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for index, (href, title) in enumerate(blocks[:5]):
            # DuckDuckGo wraps URLs in a redirect; unwrap if present.
            match = re.search(r"uddg=([^&]+)", href)

            if match:
                href = urllib.parse.unquote(match.group(1))

            snippet = (
                WebSearcher._strip_tags(snippets[index])
                if index < len(snippets)
                else ""
            )

            results.append(
                {
                    "title": WebSearcher._strip_tags(title),
                    "url": href,
                    "snippet": snippet,
                }
            )

        return results

    @staticmethod
    def _html_to_text(html: str) -> str:
        html = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            " ",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    @staticmethod
    def _strip_tags(value: str) -> str:
        value = re.sub(r"<[^>]+>", "", value)
        return re.sub(r"\s+", " ", value).strip()
