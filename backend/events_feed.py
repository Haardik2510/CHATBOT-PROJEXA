"""KRMU happenings/news scraper with optional Gemini enrichment."""
import asyncio
import logging
import mimetypes
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency in some envs
    genai = None
    types = None

from document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


class GeminiEventEnhancer:
    """Optional Gemini-powered event summarizer and image interpreter."""

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        self.fallback_models = [
            model.strip()
            for model in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-1.5-flash,gemini-1.5-pro").split(",")
            if model.strip()
        ]
        self.client = genai.Client(api_key=self.api_key) if (self.api_key and genai is not None) else None
        self.is_available = bool(self.client)

    def _candidate_models(self) -> List[str]:
        ordered = []
        for model in [self.model, *self.fallback_models]:
            if model and model not in ordered:
                ordered.append(model)
        return ordered

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
    def _event_sentence(text: str, limit: int = 260) -> str:
        clean = KRMUEventsFeed._clean_event_summary(text or "", limit=limit)
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        for sentence in sentences:
            sentence = sentence.strip(" -|")
            if len(sentence) >= 40:
                return KRMUEventsFeed._clean_text(sentence, limit=limit)
        return KRMUEventsFeed._clean_text(clean, limit=limit)

    @staticmethod
    def _fallback_summary(query: str, events: List[Dict]) -> str:
        if not events:
            return (
                "I couldn't find a matching K.R. Mangalam University event on the official happenings page right now. "
                "Please try naming the event, or ask for the latest/current university events."
            )

        if len(events) == 1:
            event = events[0]
            summary = GeminiEventEnhancer._event_sentence(
                event.get("summary") or event.get("snippet") or "Official event details are available on the linked page.",
                limit=420,
            )
            title = event.get("title", "KRMU event")
            date = event.get("published_at", "")
            lines = [f"{title} is listed on KRMU's official happenings pages."]
            if date:
                lines.append(f"- Published: {date}")
            lines.append(f"- Summary: {summary}")
            lines.append("- Images: I have attached the official visuals I could retrieve below.")
            return "\n".join(lines)

        lines = ["Here are the latest K.R. Mangalam University happenings I found on the official events pages:", ""]
        for event in events[:4]:
            title = event.get("title", "KRMU event")
            date = event.get("published_at", "")
            summary = GeminiEventEnhancer._event_sentence(event.get("summary") or event.get("snippet") or "", limit=260)
            date_text = f" ({date})" if date else ""
            lines.append(f"- {title}{date_text}: {summary or 'official details are available on the linked event page.'}")
        lines.append("")
        lines.append("I’ve attached the relevant official images below when the KRMU page exposes them.")
        return "\n".join(lines)

    @staticmethod
    def _fetch_image_parts(events: List[Dict], max_images: int = 2) -> List[Any]:
        if types is None:
            return []

        image_parts: List[Any] = []

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
                        f"Event {index} snippet: {KRMUEventsFeed._clean_event_summary(event.get('snippet', ''), limit=360)}",
                        f"Event {index} body summary: {KRMUEventsFeed._clean_event_summary(event.get('summary', ''), limit=700)}",
                    ]
                )
            )

        event_context = "\n\n".join(event_blocks)

        prompt = (
            "You are preparing a beautiful but strictly grounded university event response for K.R. Mangalam University.\n"
            "Use ONLY the provided official KRMU event text and images. Do not invent details, dates, speakers, venues, or outcomes.\n"
            "If a detail is missing, say it is not clearly stated on the official page.\n"
            "Write like a polished production chatbot.\n"
            "Do not use headings such as Direct answer, Highlights, Why it matters, or Source.\n"
            "Format multi-event answers as short, clean bullets: '- Event title: one helpful sentence.'\n"
            "Format single-event answers as 1 short intro sentence followed by 2-4 factual bullets.\n"
            "Never paste navigation text, school lists, quick links, repeated titles, or raw page chrome.\n"
            "Keep source citations out of the body because the UI will render sources separately.\n"
            "Keep it elegant, readable, and under 220 words unless the user asked for current events across multiple items.\n\n"
            f"User query: {query}\n"
            f"Recent chat context:\n{history_context or 'None'}\n\n"
            f"Official KRMU event data:\n\n{event_context}"
        )

        contents = [prompt]
        contents.extend(self._fetch_image_parts(events))

        try:
            for model_name in self._candidate_models():
                try:
                    response = self.client.models.generate_content(model=model_name, contents=contents)
                    text = self._safe_response_text(response)
                    if text:
                        self.model = model_name
                        return text
                except Exception as exc:
                    logger.warning("Gemini event summarization failed for %s: %s", model_name, exc)
        except Exception as exc:
            logger.warning("Gemini event summarization failed: %s", exc)

        return self._fallback_summary(query, events)


class KRMUEventsFeed:
    """Scrape official KRMU happenings/news pages and prepare chat-ready results."""

    INDEX_URL = "https://www.krmangalam.edu.in/happenings/news-and-events"
    SOURCE_PAGES = (
        "https://www.krmangalam.edu.in/happenings/news-and-events",
        "https://www.krmangalam.edu.in/happenings/gallery-image",
        "https://www.krmangalam.edu.in/happenings/print-coverage",
    )
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
    GENERIC_TITLES = {
        "news and events",
        "vibrant events at krmu",
        "image gallery",
        "print coverage",
        "gallery",
        "overview",
        "about us",
        "know more",
        "view more",
        "read more",
    }
    _gemini = GeminiEventEnhancer()

    @classmethod
    def _http_session(cls) -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": cls.USER_AGENT})
        return session

    @classmethod
    def is_event_query(cls, query: str) -> bool:
        lowered = (query or "").lower()
        if not lowered.strip():
            return False
        return any(keyword in lowered for keyword in cls.EVENT_KEYWORDS)

    @classmethod
    def _get_soup(cls, url: str) -> Optional[BeautifulSoup]:
        try:
            with cls._http_session() as session:
                response = session.get(url, timeout=20)
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
        cleaned = re.sub(r"\b(view|read)\s+more\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        if len(cleaned) > limit:
            return f"{cleaned[:limit].rstrip()}..."
        return cleaned

    @classmethod
    def _clean_event_summary(cls, text: str, limit: int = 700) -> str:
        """Remove site chrome/nav text so event answers read like summaries."""
        cleaned = cls._clean_text(text, limit=max(limit * 3, 1200))
        noise_markers = (
            "quick links",
            "browse programmes",
            "placements",
            "life at krmu",
            "library lms erp",
            "mandatory disclosures",
            "feedback",
            "transport route",
            "campus mandate",
            "about krmu",
            "academic schools",
            "school of ",
            "published on:",
        )
        parts = re.split(r"(?<=[.!?])\s+|\s{2,}", cleaned)
        useful_parts = []
        for part in parts:
            normalized = cls._normalize_match_text(part)
            if len(part) < 35:
                continue
            if any(marker in normalized for marker in noise_markers):
                continue
            if normalized.count("published on") > 0:
                continue
            useful_parts.append(part.strip())
            if len(" ".join(useful_parts)) >= limit:
                break

        if useful_parts:
            return cls._clean_text(" ".join(useful_parts), limit=limit)

        cleaned = re.split(r"\bQuick Links\b|\bAbout KRMU\b|\bBrowse Programmes\b", cleaned, maxsplit=1)[0]
        cleaned = re.sub(r"\bPublished On:\s*[^.]{0,80}", "", cleaned, flags=re.IGNORECASE)
        return cls._clean_text(cleaned, limit=limit)

    @classmethod
    def _normalize_match_text(cls, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    @classmethod
    def _is_generic_title(cls, title: str) -> bool:
        return cls._normalize_match_text(title) in cls.GENERIC_TITLES

    @classmethod
    def _looks_like_event_title(cls, title: str) -> bool:
        clean = cls._clean_text(title, limit=180)
        if len(clean) < 5 or len(clean) > 120:
            return False
        if cls._is_generic_title(clean):
            return False
        if clean.count(" ") > 18:
            return False
        return True

    @classmethod
    def _extract_date_from_text(cls, text: str) -> str:
        clean = " ".join((text or "").split())
        patterns = [
            r"\b\d{1,2}\s+[A-Za-z]+\s*,?\s+\d{4}\b",
            r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, clean)
            if match:
                return match.group(0)
        return ""

    @classmethod
    def _parse_date_value(cls, value: str) -> Optional[datetime]:
        if not value:
            return None
        normalized = value.replace(",", "").strip()
        formats = [
            "%d %B %Y",
            "%d %b %Y",
            "%B %d %Y",
            "%b %d %Y",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue
        return None

    @classmethod
    def _extract_block_images(cls, block, page_url: str, source_title: str, max_images: int = 2) -> List[Dict]:
        images = []
        seen = set()

        for image in block.find_all("img"):
            src = image.get("src") or image.get("data-src") or image.get("data-lazy-src") or ""
            if not src:
                continue
            absolute_url = urljoin(page_url, src.strip())
            if absolute_url in seen:
                continue
            if not DocumentProcessor._looks_like_content_image_url(absolute_url):
                continue

            seen.add(absolute_url)
            images.append(
                {
                    "url": absolute_url,
                    "alt": cls._clean_text(image.get("alt") or source_title, limit=160),
                    "source_title": source_title,
                    "source_url": page_url,
                    "origin": "website",
                }
            )
            if len(images) >= max_images:
                break

        return images

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
    def _extract_page_events(cls, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        events = []
        seen = set()

        if not soup:
            return events

        container = soup.find("main") or soup.find("body")
        if not container:
            return events

        blocks = container.find_all(["article", "section", "li", "div"], limit=500)
        for block in blocks:
            heading = block.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if not heading:
                continue

            title = cls._clean_text(heading.get_text(" ", strip=True), limit=180)
            if not cls._looks_like_event_title(title):
                continue

            link = ""
            anchor = block.find("a", href=True)
            if anchor:
                candidate_link = urljoin(page_url, anchor.get("href", "").strip())
                if candidate_link and cls._extract_domain(candidate_link).endswith("krmangalam.edu.in"):
                    link = candidate_link

            block_text = cls._clean_text(block.get_text(" ", strip=True), limit=1200)
            if len(block_text) < 30:
                continue

            paragraph_bits = []
            for element in block.find_all(["p", "li"], limit=10):
                text = cls._clean_text(element.get_text(" ", strip=True), limit=220)
                if len(text) < 20:
                    continue
                if cls._normalize_match_text(text) in cls.GENERIC_TITLES:
                    continue
                paragraph_bits.append(text)

            summary = cls._clean_text(" ".join(paragraph_bits) or block_text, limit=700)
            published_at = cls._extract_date_from_text(block_text)
            images = cls._extract_block_images(block, page_url, title, max_images=2)
            dedupe_key = (cls._normalize_match_text(title), link or page_url)
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            events.append(
                {
                    "title": title,
                    "url": link or page_url,
                    "source_page": page_url,
                    "snippet": cls._clean_text(block_text, limit=320),
                    "summary": summary,
                    "published_at": published_at,
                    "images": images,
                }
            )

        return events

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
        summary = cls._clean_event_summary(cls._extract_body_summary(soup) or fallback_snippet)
        images = DocumentProcessor.extract_html_images(soup, url, source_title=title, max_images=3)
        if cls._is_generic_title(title) or title.lower().startswith("vibrant events"):
            title = fallback_title

        return {
            "title": title or fallback_title,
            "url": url,
            "source_page": url,
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
        normalized_query = cls._normalize_match_text(query_context)
        normalized_title = cls._normalize_match_text(event.get("title", ""))
        query_terms = {term for term in re.findall(r"[a-z0-9]+", normalized_query) if len(term) > 2}
        if not query_terms:
            return 1.0

        overlap = len(query_terms & set(re.findall(r"[a-z0-9]+", haystack))) / max(len(query_terms), 1)
        score = overlap * 7

        if normalized_title and normalized_title in normalized_query:
            score += 8
        elif normalized_query and normalized_query in normalized_title:
            score += 6

        title_terms = [term for term in normalized_title.split() if len(term) > 2]
        if title_terms:
            title_overlap = len(set(title_terms) & query_terms) / max(len(set(title_terms)), 1)
            score += title_overlap * 5

        if any(term in normalized_query for term in ("tell me about", "about this event", "event summary")) and normalized_title:
            score += 0.8

        if any(term in normalized_query for term in ("latest", "current", "recent", "happenings")):
            score += max(0, 3 - ordinal) * 0.6

        parsed_date = cls._parse_date_value(event.get("published_at", ""))
        if parsed_date:
            age_days = max((datetime.utcnow() - parsed_date).days, 0)
            score += max(0, 2.5 - min(age_days / 180, 2.5))

        return score

    @classmethod
    def _sync_search_events(
        cls,
        query: str,
        conversation_history: Optional[List[Dict]] = None,
        max_events: int = 3,
    ) -> List[Dict]:
        query_context = cls._build_query_context(query, conversation_history)
        broad_query = any(term in query_context.lower() for term in ("latest", "current", "recent", "happenings", "events", "news"))

        scraped_events = []
        for page_url in cls.SOURCE_PAGES:
            soup = cls._get_soup(page_url)
            page_events = cls._extract_page_events(soup, page_url)
            scraped_events.extend(page_events)

        if not scraped_events:
            return []

        parsed_events = []
        for ordinal, event in enumerate(scraped_events):
            detail_url = event.get("url", "")
            if detail_url and detail_url != event.get("source_page") and "/happenings/" in detail_url:
                enriched = cls._parse_event_page(detail_url, event["title"], event["summary"])
                if enriched:
                    if len(enriched.get("summary", "")) < 80 and len(event.get("summary", "")) > len(enriched.get("summary", "")):
                        enriched["summary"] = event["summary"]
                    if len(enriched.get("snippet", "")) < 60 and len(event.get("snippet", "")) > len(enriched.get("snippet", "")):
                        enriched["snippet"] = event["snippet"]
                    if not enriched.get("images") and event.get("images"):
                        enriched["images"] = event["images"]
                    event = {**event, **enriched}

            event["score"] = cls._score_event(query_context, event, ordinal)
            if not broad_query and event["score"] < 2.6:
                continue
            parsed_events.append(event)

        parsed_events.sort(key=lambda item: item.get("score", 0), reverse=True)
        if not broad_query:
            exactish = [
                item for item in parsed_events
                if cls._normalize_match_text(item.get("title", "")) in cls._normalize_match_text(query_context)
                or any(
                    token in cls._normalize_match_text(item.get("title", ""))
                    for token in [term for term in cls._normalize_match_text(query_context).split() if len(term) > 3]
                )
            ]
            if exactish:
                parsed_events = exactish + [item for item in parsed_events if item not in exactish]

        deduped = []
        seen = set()
        for item in parsed_events:
            key = (cls._normalize_match_text(item.get("title", "")), item.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max_events:
                break

        if not broad_query and deduped:
            lead_title = cls._normalize_match_text(deduped[0].get("title", ""))
            normalized_query = cls._normalize_match_text(query_context)
            if lead_title and (lead_title in normalized_query or deduped[0].get("score", 0) >= 6):
                return [deduped[0]]

        return deduped

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
            "fallback_models": cls._gemini.fallback_models if cls._gemini.is_available else [],
        }
