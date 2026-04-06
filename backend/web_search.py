"""Web search fallback for RAG when no relevant documents found"""
import httpx
import logging
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class WebSearchFallback:
    """Simple web search fallback using DuckDuckGo HTML"""
    
    SEARCH_URL = "https://html.duckduckgo.com/html/"
    PREFERRED_DOMAINS = {
        "krmangalam.edu.in",
        "krmangalamuniversity.edu.in",
        "ugc.gov.in",
        "aicte-india.org",
        "nirfindia.org",
        "swayam.gov.in",
        "coursera.org",
        "edx.org",
    }

    @classmethod
    def _extract_domain(cls, url: str) -> str:
        try:
            return urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            return ""

    @classmethod
    def _term_overlap_score(cls, query: str, text: str) -> float:
        query_terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
        text_terms = set(re.findall(r"[a-z0-9]+", text.lower()))
        if not query_terms:
            return 0.0
        return len(query_terms & text_terms) / len(query_terms)

    @classmethod
    def _score_result(cls, query: str, result: Dict) -> float:
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        url = result.get("url", "")
        domain = cls._extract_domain(url)

        score = 0.0
        overlap = cls._term_overlap_score(query, f"{title} {snippet}")
        score += overlap * 4

        if domain in cls.PREFERRED_DOMAINS:
            score += 5
        elif domain.endswith(".edu") or domain.endswith(".edu.in"):
            score += 3
        elif domain.endswith(".gov.in") or domain.endswith(".gov"):
            score += 3

        if url.startswith("https://"):
            score += 0.5

        lowered = f"{title} {snippet}".lower()
        if "admission" in query.lower() and "admission" in lowered:
            score += 1
        if "curriculum" in query.lower() and "curriculum" in lowered:
            score += 1
        if "fees" in query.lower() and "fee" in lowered:
            score += 1

        return score

    @classmethod
    def _filter_and_rank_results(cls, query: str, results: List[Dict], num_results: int) -> List[Dict]:
        ranked_results = []
        seen_urls = set()

        for result in results:
            url = result.get("url", "")
            if not url or url in seen_urls:
                continue

            score = cls._score_result(query, result)
            if score < 1.5:
                continue

            enriched = {**result, "quality_score": round(score, 2)}
            ranked_results.append(enriched)
            seen_urls.add(url)

        ranked_results.sort(key=lambda item: item["quality_score"], reverse=True)
        return ranked_results[:num_results]
    
    @classmethod
    async def search(cls, query: str, num_results: int = 3) -> List[Dict]:
        """Search the web for relevant information"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    cls.SEARCH_URL,
                    data={"q": query},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, "lxml")
                results = []
                
                # Parse DuckDuckGo HTML results
                for result in soup.select(".result")[: max(num_results * 4, 8)]:
                    title_elem = result.select_one(".result__title a")
                    snippet_elem = result.select_one(".result__snippet")
                    
                    if title_elem and snippet_elem:
                        title = title_elem.get_text(strip=True)
                        snippet = snippet_elem.get_text(strip=True)
                        url = title_elem.get("href", "")
                        
                        # Clean up DuckDuckGo redirect URL
                        if "uddg=" in url:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                            url = parsed.get("uddg", [url])[0]
                        
                        results.append({
                            "title": title,
                            "snippet": snippet,
                            "url": url
                        })

                filtered_results = cls._filter_and_rank_results(query, results, num_results)
                logger.info(
                    "Web search found %s raw results and kept %s ranked results for: %s",
                    len(results),
                    len(filtered_results),
                    query
                )
                return filtered_results
                
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []
    
    @classmethod
    def format_search_response(cls, query: str, results: List[Dict]) -> str:
        """Format web search results into a readable response"""
        if not results:
            return (
                "I couldn't find relevant information in the knowledge base or through web search. "
                "Please try rephrasing your question or contact the SET administration for assistance."
            )
        
        response_parts = [
            "I couldn't find a strong answer in the uploaded SET documents, so I checked reliable web sources.\n"
        ]
        
        for i, result in enumerate(results, 1):
            response_parts.append(
                f"\n**{i}. {result['title']}**\n"
                f"{result['snippet']}\n"
                f"*Source: {result['url']}*\n"
            )
        
        response_parts.append(
            "\n*Note: These results are filtered web sources, not uploaded SET documents. "
            "Please confirm important details from the official university source before relying on them.*"
        )
        
        return "".join(response_parts)

    @classmethod
    def build_sources(cls, results: List[Dict]) -> List[Dict]:
        """Convert ranked web results into chat source citations."""
        return [
            {
                "document_id": f"web_{i}",
                "document_title": f"Web: {r['title'][:50]}...",
                "chunk_text": r["snippet"][:200],
                "relevance_score": 0.5,
                "is_web_result": True,
                "url": r["url"],
            }
            for i, r in enumerate(results)
        ]


# For RAG integration
async def get_web_search_fallback(query: str) -> Dict:
    """Get web search results when RAG has no relevant documents"""
    results = await WebSearchFallback.search(query)
    response = WebSearchFallback.format_search_response(query, results)

    sources = WebSearchFallback.build_sources(results)

    return {
        "response": response,
        "sources": sources,
        "is_web_fallback": True
    }
