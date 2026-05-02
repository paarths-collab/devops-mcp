"""
Web search tools for Observable Agent Control Panel.
"""

from typing import Dict, List
import requests

API_URL = "https://api.stackexchange.com/2.3/search/advanced"
MAX_RESULTS = 5


def search_stackexchange(query: str) -> Dict:
    """
    Search StackExchange (Stack Overflow) for relevant threads.
    Returns top results with title, link, score, and answer count.
    NOTE: The 'withbody' filter causes API issues — intentionally omitted.
    """
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": MAX_RESULTS,
    }

    try:
        resp = requests.get(API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])

        if not items:
            return {
                "status": "empty",
                "message": f"No StackExchange results for query '{query}'.",
                "results": [],
            }

        results: List[Dict] = []
        for item in items[:MAX_RESULTS]:
            results.append(
                {
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "score": item.get("score", 0),
                    "answer_count": item.get("answer_count", 0),
                    "is_answered": item.get("is_answered", False),
                    "tags": item.get("tags", []),
                }
            )

        return {
            "status": "success",
            "results": results,
            "quota_remaining": data.get("quota_remaining"),
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"StackExchange API request failed: {str(e)}",
            "results": [],
        }
