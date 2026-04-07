"""KRMU happenings/news scraper with optional Gemini enrichment."""
import asyncio
import logging
import mimetypes
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


class GeminiEventEnhancer:
    """Optional Gemini-powered event summarizer and image interpreter."""

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.is_available = bool(self.client)

    @staticmethod
    def _safe_response_text(response) -> str:
        text = getattr(response, "text", "") or ""
        return text.strip()

    @staticmethod
    def _build_history_context(conversation_history: Optional[List[Dict]]) -> str:
        if not conversation_history:
            return ""

        fragments = []
        for message in conversation_history[-4:]:
            role = (message.get("role") or "").strip().lower()
            content = (message.get("content") or "").strip()
            if not content:
                continue
            fragments.append(f"{role}: {content[:320]}")
        return "\n".join(fragments)

    @staticmethod
    def _fallback_summary(query: str, events: List[Dict]) -> str:
        if not events:
            return (
                "I couldn't find a matching K.R. Mangalam University event on the official happenings page right now. "
                "Please try naming the event, or ask for the latest/current university events."
            )

        if len(events) == 1:
            event = events[0]
            summary = event.get("summary") or event.get("snippet") or "Official event details are available on the linked page."
            return (
                f"Direct answer: {event.get('title', 'KRMU event')}\n\n"
                f"Key points:\n- {summary}\n\n"
                f"Source:\n- {event.get('url', 'Official KRMU happenings page')}"
            )

        lines = ["Direct answer: Here are the current KRMU happenings I found on the official university events pages.", "", "Key points:"]
        for event in events[:3]:
            summary = event.get("summary") or event.get("snippet") or "Official event details are available on the linked page."
            lines.append(f"- {event.get('title', 'KRMU event')}: {summary}")
        lines.extend(["", "Source:"])
        for event in events[:3]:
            lines.append(f"- {event.get('title', 'KRMU event')}: {event.get('url', 'Official KRMU happenings page')}")
        return "\n".join(lines)

    @staticmethod
    def _fetch_image_parts(events: List[Dict], max_images: int = 2) -> List[types.Part]:
        image_parts: List[types.Part] = []

        for event in events:
            for image in event.get("images", [])[:max_images]:
                image_url = (image.get("url") or "").strip()
                if not image_url:
                    continue

                try:
                    response = requests.get(
                        image_url,
                        timeout=15,
                        headers={"User-Agent": KRMUEventsFeed.USER_AGENT},
                    )
                    response.raise_for_status()
                    mime_type = (
                        response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                        or mimetypes.guess_type(image_url)[0]
                        or "image/jpeg"
                    )
                    image_parts.append(types.Part.from_bytes(data=response.content, mime_type=mime_type))
                except Exception as exc:
                    logger.debug("Skipping Gemini image enrichment for %s: %s", image_url, exc)

                if len(image_parts) >= max_images:
                    return image_parts

        return image_parts

    def summarize_events(
        self,
        query: str,
        events: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """Create a polished event summary using Gemini when configured."""
        if not events:
            return self._fallback_summary(query, events)

        if not self.is_available:
            return self._fallback_summary(query, events)

        history_context = self._build_history_context(conversation_history)
        event_blocks = []
        for index, event in enumerate(events[:3], start=1):
            event_blocks.append(
                "\n".join(
                    [
                        f"Event {index} title: {event.get('title', '')}",
                        f"Event {index} url: {event.get('url', '')}",
                        f"Event {index} published: {event.get('published_at', '')}",
                        f"Event {index} snippet: {event.get('snippet', '')}",
                        f"Event {index} body summary: {event.get('summary', '')}",
                    ]
                )
            )

        prompt = (
            "You are preparing a beautiful but strictly grounded university event response for K.R. Mangalam University.\n"
            "Use ONLY the provided official KRMU event text and images. Do not invent details, dates, speakers, venues, or outcomes.\n"
            "If a detail is missing, say it is not clearly stated on the official page.\n"
            "Respond in this exact structure:\n"
            "Direct answer: <1 concise paragraph>\n\n"
            "Highlights:\n"
            "- <2 to 4 crisp bullets>\n\n"
            "Why it matters:\n"
            "- <1 or 2 bullets>\n\n"
            "Source:\n"
            "- <event title>: <event url>\n"
            "Keep it elegant, readable, and under 220 words unless the user asked for current events across multiple items.\n\n"
            f"User query: {query}\n"
            f"Recent chat context:\n{history_context or 'None'}\n\n"
            f"Official KRMU event data:\n\n{'\n\n'.join(event_blocks)}"
        )

        contents = [prompt]
        contents.extend(self._fetch_image_parts(events))

        try:
            response = self.client.models.generate_content(model=self.model, contents=contents)
            text = self._safe_response_text(response)
            return text or self._fallback_summary(query, events)
        except Exception as exc:
            logger.warning("Gemini event summarization failed: %s", exc)
            return self._fallback_summary(query, events)


class KRMUEventsFeed:
    """Scrape official KRMU happenings/news pages and prepare chat-ready results."""

    INDEX_URL = "https://www.krmangalam.edu.in/happenings/news-and-events"
    DOMAIN = "www.krmangalam.edu.in"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    EVENT_KEYWORDS = {
        "event",
        "events",
        "happening",
        "happenings",
        "latest",
        "current",
        "news",
        "fest",
        "festival",
        "workshop",
        "seminar",
        "conference",
        "competition",
        "celebration",
        "webinar",
        "conclave",
        "hackathon",
    }
    _gemini = GeminiEventEnhancer()

    @classmethod
    def is_event_query(cls, query: str) -> bool:
        lowered = (query or "").lower()
        if not lowered.strip():
            return False
        return any(keyword in lowered for keyword in cls.EVENT_KEYWORDS)

    @classmethod
    def _get_soup(cls, url: str) -> Optional[BeautifulSoup]:
        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": cls.USER_AGENT},
            )
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except Exception as exc:
            logger.warning("KRMU events fetch failed for %s: %s", url, exc)
            return None

    @classmethod
    def _extract_domain(cls, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    @classmethod
    def _is_official_event_link(cls, url: str) -> bool:
        domain = cls._extract_domain(url)
        return bool(url) and domain.endswith("krmangalam.edu.in") and "/happenings/" in url

    @classmethod
    def _clean_text(cls, text: str, limit: int = 500) -> str:
        cleaned = DocumentProcessor.clean_text(text or "")
        if len(cleaned) > limit:
            return f"{cleaned[:limit].rstrip()}..."
        return cleaned

    @classmethod
    def _extract_published_at(cls, soup: BeautifulSoup) -> str:
        if not soup:
            return ""

        for selector, attr in (
            ('meta[property="article:published_time"]', "content"),
            ('meta[name="publish-date"]', "content"),
            ("time[datetime]", "datetime"),
        ):
            tag = soup.select_one(selector)
            if tag and tag.get(attr):
                return tag.get(attr).strip()

        time_tag = soup.find("time")
        if time_tag:
            return cls._clean_text(time_tag.get_text(" ", strip=True), limit=80)

        return ""

    @classmethod
    def _extract_body_summary(cls, soup: BeautifulSoup) -> str:
        if not soup:
            return ""

        container = soup.find("article") or soup.find("main") or soup.find("body")
        if not container:
            return ""

        blocks = []
        for element in container.find_all(["p", "li"], limit=40):
            text = cls._clean_text(element.get_text(" ", strip=True), limit=240)
            if len(text) < 40:
                continue
            blocks.append(text)
            if len(" ".join(blocks)) >= 1200:
                break

        return cls._clean_text(" ".join(blocks), limit=1200)

    @classmethod
    def _extract_listing_candidates(cls, soup: BeautifulSoup) -> List[Dict]:
        candidates = []
        seen_urls = set()

        if not soup:
            return candidates

        for anchor in soup.select("a[href]"):
            href = urljoin(cls.INDEX_URL, anchor.get("href", "").strip())
            if not cls._is_official_event_link(href):
                continue
            if href.rstrip("/") == cls.INDEX_URL.rstrip("/") or href in seen_urls:
                continue

            title = cls._clean_text(anchor.get_text(" ", strip=True), limit=160)
            if len(title) < 12:
                continue

            parent = anchor.find_parent(["article", "li", "div", "section"])
            context_text = cls._clean_text(parent.get_text(" ", strip=True) if parent else title, limit=320)
            seen_urls.add(href)
            candidates.append({"title": title, "url": href, "snippet": context_text})

        return candidates

    @classmethod
    def _parse_event_page(cls, url: str, fallback_title: str, fallback_snippet: str) -> Optional[Dict]:
        soup = cls._get_soup(url)
        if not soup:
            return None

        title = cls._clean_text(
            (
                soup.select_one("h1") and soup.select_one("h1").get_text(" ", strip=True)
            )
            or (
                soup.title.get_text(" ", strip=True) if soup.title else ""
            )
            or fallback_title,
            limit=180,
        )
        summary = cls._extract_body_summary(soup) or fallback_snippet
        images = DocumentProcessor.extract_html_images(soup, url, source_title=title, max_images=3)

        return {
            "title": title or fallback_title,
            "url": url,
            "snippet": fallback_snippet,
            "summary": summary,
            "published_at": cls._extract_published_at(soup),
            "images": images,
        }

    @classmethod
    def _build_query_context(cls, query: str, conversation_history: Optional[List[Dict]]) -> str:
        query = (query or "").strip()
        lowered = query.lower()
        if not conversation_history:
            return query

        if any(token in lowered for token in ("this event", "that event", "latest one", "this one")):
            history = []
            for message in conversation_history[-4:]:
                content = (message.get("content") or "").strip()
                if content:
                    history.append(content[:280])
            if history:
                return f"{query}\n\nRecent chat context:\n" + "\n".join(history)

        return query

    @classmethod
    def _score_event(cls, query_context: str, event: Dict, ordinal: int) -> float:
        haystack = " ".join(
            [
                event.get("title", ""),
                event.get("snippet", ""),
                event.get("summary", ""),
            ]
        ).lower()
        query_terms = {term for term in re.findall(r"[a-z0-9]+", query_context.lower()) if len(term) > 2}
        if not query_terms:
            return 1.0

        overlap = len(query_terms & set(re.findall(r"[a-z0-9]+", haystack))) / max(len(query_terms), 1)
        score = overlap * 7

        if any(term in query_context.lower() for term in ("latest", "current", "recent", "happenings")):
            score += max(0, 3 - ordinal) * 0.6

        if event.get("published_at"):
            score += 0.5

        return score

    @classmethod
    def _sync_search_events(
        cls,
        query: str,
        conversation_history: Optional[List[Dict]] = None,
        max_events: int = 3,
    ) -> List[Dict]:
        soup = cls._get_soup(cls.INDEX_URL)
        candidates = cls._extract_listing_candidates(soup)
        if not candidates:
            return []

        parsed_events = []
        for ordinal, candidate in enumerate(candidates[:8]):
            event = cls._parse_event_page(candidate["url"], candidate["title"], candidate["snippet"])
            if not event:
                event = {
                    "title": candidate["title"],
                    "url": candidate["url"],
                    "snippet": candidate["snippet"],
                    "summary": candidate["snippet"],
                    "published_at": "",
                    "images": [],
                }
            event["score"] = cls._score_event(cls._build_query_context(query, conversation_history), event, ordinal)
            parsed_events.append(event)

        parsed_events.sort(key=lambda item: item.get("score", 0), reverse=True)
        return parsed_events[:max_events]

    @classmethod
    async def search_events(
        cls,
        query: str,
        conversation_history: Optional[List[Dict]] = None,
        max_events: int = 3,
    ) -> List[Dict]:
        return await asyncio.to_thread(cls._sync_search_events, query, conversation_history, max_events)

    @classmethod
    def build_sources(cls, events: List[Dict]) -> List[Dict]:
        sources = []
        for index, event in enumerate(events[:3], start=1):
            excerpt = event.get("summary") or event.get("snippet") or ""
            sources.append(
                {
                    "document_id": f"krmu_event_{index}",
                    "document_title": event.get("title", "KRMU Event"),
                    "chunk_text": cls._clean_text(excerpt, limit=220),
                    "relevance_score": min(max(float(event.get("score", 0)) / 10, 0.52), 0.92),
                    "is_web_result": True,
                    "url": event.get("url"),
                }
            )
        return sources

    @classmethod
    def build_image_payload(cls, events: List[Dict], max_images: int = 4) -> List[Dict]:
        payload = []
        seen = set()

        for event in events:
            for image in event.get("images", []):
                image_url = (image.get("url") or "").strip()
                if not image_url or image_url in seen:
                    continue
                payload.append(
                    {
                        **image,
                        "source_title": image.get("source_title") or event.get("title", "KRMU Event"),
                        "source_url": image.get("source_url") or event.get("url"),
                        "origin": "website",
                    }
                )
                seen.add(image_url)
                if len(payload) >= max_images:
                    return payload

        return payload

    @classmethod
    def summarize_events(
        cls,
        query: str,
        events: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        return cls._gemini.summarize_events(query, events, conversation_history=conversation_history)

    @classmethod
    def gemini_status(cls) -> Dict[str, Optional[str]]:
        return {
            "configured": cls._gemini.is_available,
            "model": cls._gemini.model if cls._gemini.is_available else None,
        }
