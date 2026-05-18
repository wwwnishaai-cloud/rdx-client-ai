import httpx
from typing import Optional


class Tools:
    @staticmethod
    async def web_search(query: str, num_results: int = 5) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.duckduckgo.com",
                    params={"q": query, "format": "json", "no_html": 1},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    for topic in data.get("RelatedTopics", [])[:num_results]:
                        if "Text" in topic and "FirstURL" in topic:
                            results.append({
                                "title": topic.get("Text", "").split(" - ")[0],
                                "snippet": topic.get("Text", ""),
                                "url": topic.get("FirstURL", ""),
                            })
                    return results
        except Exception:
            pass

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/html",
                    params={"q": query},
                )
                if response.status_code == 200:
                    text = response.text
                    results = []
                    import re
                    for match in re.finditer(
                        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                        text,
                    )[:num_results]:
                        results.append({
                            "title": re.sub(r"<[^>]+>", "", match.group(2)),
                            "url": match.group(1),
                        })
                    return results
        except Exception:
            pass

        return []

    @staticmethod
    def format_search_results(results: list[dict]) -> str:
        if not results:
            return "No search results found."
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(f"{i}. {r.get('title', 'Unknown')}")
            if r.get("snippet"):
                formatted.append(f"   {r['snippet']}")
            if r.get("url"):
                formatted.append(f"   Source: {r['url']}")
        return "\n".join(formatted)


tools = Tools()
