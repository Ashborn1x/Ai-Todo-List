from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

def fetch_json(url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "Voice-Controlled-Task-Manager/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def web_search(query: str) -> dict[str, Any]:
    cleaned = query.strip()
    if not cleaned:
        return {"ok": False, "message": "Search query is required."}

    results: list[dict[str, str]] = []

    try:
        ddg_url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {
                "q": cleaned,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            }
        )
        ddg = fetch_json(ddg_url)
        abstract = ddg.get("AbstractText", "").strip()
        abstract_url = ddg.get("AbstractURL", "").strip()
        heading = ddg.get("Heading", "").strip() or cleaned

        if abstract:
            results.append(
                {
                    "title": heading,
                    "snippet": abstract,
                    "url": abstract_url or "https://duckduckgo.com/",
                    "source": "duckduckgo_instant_answer",
                }
            )

        for topic in ddg.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": topic.get("FirstURL", cleaned).rsplit("/", 1)[-1].replace("_", " "),
                        "snippet": topic["Text"],
                        "url": topic.get("FirstURL", "https://duckduckgo.com/"),
                        "source": "duckduckgo_related_topic",
                    }
                )
            elif isinstance(topic, dict):
                for child in topic.get("Topics", [])[:3]:
                    if child.get("Text"):
                        results.append(
                            {
                                "title": child.get("FirstURL", cleaned).rsplit("/", 1)[-1].replace("_", " "),
                                "snippet": child["Text"],
                                "url": child.get("FirstURL", "https://duckduckgo.com/"),
                                "source": "duckduckgo_related_topic",
                            }
                        )
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)

    if not results:
        try:
            wiki_search_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": cleaned,
                    "format": "json",
                    "utf8": 1,
                }
            )
            wiki_search = fetch_json(wiki_search_url)
            hits = wiki_search.get("query", {}).get("search", [])
            for hit in hits[:3]:
                title = hit.get("title", cleaned)
                summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
                try:
                    summary = fetch_json(summary_url)
                except Exception:
                    continue
                extract = summary.get("extract", "").strip()
                if extract:
                    results.append(
                        {
                            "title": summary.get("title", title),
                            "snippet": extract,
                            "url": summary.get("content_urls", {})
                            .get("desktop", {})
                            .get("page", f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"),
                            "source": "wikipedia_summary",
                        }
                    )
        except Exception as exc:
            logger.warning("Wikipedia search failed: %s", exc)

    if not results:
        return {
            "ok": False,
            "message": "No web results found or the network request failed.",
        }

    return {
        "ok": True,
        "query": cleaned,
        "results": [
            {
                "index": index + 1,
                **item,
            }
            for index, item in enumerate(results[:5])
        ],
    }
