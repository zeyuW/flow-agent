"""天气与 AI 新闻基础能力的内置 MCP stdio 服务。"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import certifi


USER_AGENT = "FlowAgent-Builtin-MCP/1.0"
WEATHER_LABELS = {
    0: "晴朗", 1: "大致晴朗", 2: "局部多云", 3: "阴天", 45: "雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 61: "小雨",
    63: "中雨", 65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "强阵雨", 95: "雷暴",
}
AI_KEYWORDS = (
    "artificial intelligence", "generative", "chatgpt", "openai", "anthropic",
    "claude", "gemini", "deepmind", "llm", "language model", "machine learning",
    "kimi", "deepseek", "qwen", "mistral", "copilot", "人工智能", "生成式",
    "大模型", "语言模型", "机器学习", "智能体",
)
AI_FEEDS = (
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("MIT Technology Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("OpenAI News", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
)
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def request_bytes(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(
                request,
                timeout=20,
                context=SSL_CONTEXT,
            ) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"请求新闻源失败: {last_error}")


def request_json(url: str) -> dict[str, Any]:
    value = json.loads(request_bytes(url).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("外部服务返回了无效 JSON")
    return value


def get_weather(city: str) -> str:
    clean_city = city.strip()
    if not clean_city:
        raise ValueError("city 不能为空")
    geo_query = urllib.parse.urlencode({
        "name": clean_city, "count": 1, "language": "zh", "format": "json",
    })
    places = request_json(
        f"https://geocoding-api.open-meteo.com/v1/search?{geo_query}"
    ).get("results", [])
    if not isinstance(places, list) or not places:
        return json.dumps({"found": False, "city": clean_city}, ensure_ascii=False)
    place = places[0]
    forecast_query = urllib.parse.urlencode({
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": (
            "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,wind_speed_10m"
        ),
        "timezone": "auto",
    })
    weather = request_json(
        f"https://api.open-meteo.com/v1/forecast?{forecast_query}"
    )
    current = weather.get("current", {})
    code = int(current.get("weather_code", -1))
    return json.dumps({
        "found": True,
        "city": place.get("name", clean_city),
        "region": place.get("admin1", ""),
        "country": place.get("country", ""),
        "weather": WEATHER_LABELS.get(code, f"天气代码 {code}"),
        "temperature_c": current.get("temperature_2m"),
        "apparent_temperature_c": current.get("apparent_temperature"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "observed_at": current.get("time"),
        "timezone": weather.get("timezone", ""),
        "source": "https://open-meteo.com/",
    }, ensure_ascii=False)


def get_ai_news(limit: int = 10, hours: int = 24) -> str:
    clean_limit = max(1, min(30, int(limit)))
    clean_hours = max(1, min(168, int(hours)))
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(AI_FEEDS)) as executor:
        batches = list(executor.map(
            lambda source: fetch_feed(source[0], source[1], clean_hours),
            AI_FEEDS,
        ))
    candidates: list[dict[str, Any]] = []
    for source, (items, error) in zip(AI_FEEDS, batches):
        candidates.extend(items)
        if error:
            errors.append(f"{source[0]}: {error}")
    if len(deduplicate(candidates)) < clean_limit:
        try:
            candidates.extend(fetch_gdelt_news(clean_hours, clean_limit))
        except Exception as exc:
            errors.append(f"GDELT: {exc}")
    if len(deduplicate(candidates)) < clean_limit:
        try:
            candidates.extend(fetch_google_news(clean_hours, clean_limit))
        except Exception as exc:
            errors.append(f"Google News RSS: {exc}")
    candidates.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    items = deduplicate(candidates)[:clean_limit]
    return json.dumps({
        "topic": "AI",
        "period_hours": clean_hours,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": items,
        "provider_errors": errors,
        "usage_note": "保留每条 url；summary 为空时只能概述标题，不能编造正文。",
    }, ensure_ascii=False)


def fetch_feed(
    source: str,
    url: str,
    hours: int,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        root = ET.fromstring(request_bytes(url))
    except Exception as exc:
        return [], str(exc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = clean(item.findtext("title"))
        link = clean(item.findtext("link"))
        summary = strip_html(item.findtext("description") or item.findtext("{*}encoded"))
        published = parse_time(clean(item.findtext("pubDate") or item.findtext("{*}date")))
        append_news(results, source, title, link, summary, published, cutoff, "Direct RSS")
    for entry in root.findall(".//{*}entry"):
        title = clean(entry.findtext("{*}title"))
        summary = strip_html(entry.findtext("{*}summary") or entry.findtext("{*}content"))
        published = parse_time(clean(
            entry.findtext("{*}published") or entry.findtext("{*}updated")
        ))
        link = next((
            clean(node.attrib.get("href"))
            for node in entry.findall("{*}link")
            if node.attrib.get("rel", "alternate") == "alternate"
        ), "")
        append_news(results, source, title, link, summary, published, cutoff, "Direct RSS")
    return results, None


def fetch_gdelt_news(hours: int, limit: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "query": (
            '("artificial intelligence" OR OpenAI OR Anthropic OR ChatGPT '
            'OR Gemini OR DeepSeek OR "large language model")'
        ),
        "mode": "artlist",
        "maxrecords": min(250, max(limit * 5, 50)),
        "format": "json",
        "timespan": f"{hours}h",
        "sort": "HybridRel",
    })
    payload = request_json(f"https://api.gdeltproject.org/api/v2/doc/doc?{query}")
    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        raise ValueError("GDELT 返回了无效文章列表")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results: list[dict[str, Any]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        append_news(
            results,
            clean(article.get("domain") or "GDELT"),
            clean(article.get("title")),
            clean(article.get("url")),
            "",
            parse_time(clean(article.get("seendate"))),
            cutoff,
            "GDELT",
        )
    return results


def fetch_google_news(hours: int, limit: int) -> list[dict[str, Any]]:
    period = "1d" if hours <= 24 else "7d"
    query = urllib.parse.quote_plus(f"artificial intelligence when:{period}")
    root = ET.fromstring(request_bytes(
        "https://news.google.com/rss/search"
        f"?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    ))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    results: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[: max(limit * 3, limit)]:
        source_node = item.find("source")
        append_news(
            results,
            clean(source_node.text if source_node is not None else "Google News"),
            clean(item.findtext("title")),
            clean(item.findtext("link")),
            "",
            parse_time(clean(item.findtext("pubDate"))),
            cutoff,
            "Google News RSS",
        )
    return results


def append_news(
    results: list[dict[str, Any]],
    source: str,
    title: str,
    url: str,
    summary: str,
    published: datetime | None,
    cutoff: datetime,
    provider: str,
) -> None:
    if not title or not url.startswith(("http://", "https://")):
        return
    if published is None or not cutoff <= published <= datetime.now(timezone.utc) + timedelta(hours=1):
        return
    if not looks_ai_related(f"{title} {summary}"):
        return
    results.append({
        "title": title,
        "url": url,
        "summary": summary[:600],
        "source": source,
        "published_at": published.isoformat(),
        "provider": provider,
    })


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", item["title"].lower())
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


def looks_ai_related(value: str) -> bool:
    lowered = value.lower()
    return bool(re.search(r"\bai\b", lowered)) or any(
        keyword in lowered for keyword in AI_KEYWORDS
    )


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def strip_html(value: Any) -> str:
    return clean(re.sub(r"<[^>]+>", " ", str(value or "")))


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc,
                )
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def tools_for(profile: str) -> list[dict[str, Any]]:
    if profile == "weather":
        return [{
            "name": "get_weather",
            "description": "查询城市当前真实天气；回答应注明观测时间和 Open-Meteo 来源",
            "inputSchema": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名称"}},
                "required": ["city"],
            },
        }]
    if profile == "ai-news":
        return [{
            "name": "get_ai_news",
            "description": "查询最近 AI 新闻并返回媒体、摘要、发布时间和链接；最终回答必须保留链接",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    "hours": {"type": "integer", "minimum": 1, "maximum": 168, "default": 24},
                },
            },
        }]
    raise ValueError(f"未知内置 MCP profile: {profile}")


def call_tool(profile: str, name: str, arguments: dict[str, Any]) -> str:
    if profile == "weather" and name == "get_weather":
        return get_weather(str(arguments.get("city", "")))
    if profile == "ai-news" and name == "get_ai_news":
        return get_ai_news(arguments.get("limit", 10), arguments.get("hours", 24))
    raise ValueError(f"未知内置 MCP 工具: {name}")


def send(request_id: Any, *, result: Any = None, error: Exception | None = None) -> None:
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = {"code": -32000, "message": str(error)}
    else:
        payload["result"] = result
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=("weather", "ai-news"))
    profile = parser.parse_args().profile
    for line in sys.stdin:
        request_id: Any = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                send(request_id, result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": profile, "version": "1.0.0"},
                })
            elif method == "tools/list":
                send(request_id, result={"tools": tools_for(profile)})
            elif method == "tools/call":
                params = request.get("params", {})
                arguments = params.get("arguments", {})
                text = call_tool(profile, str(params.get("name", "")), arguments)
                send(request_id, result={"content": [{"type": "text", "text": text}]})
        except Exception as exc:
            if request_id is not None:
                send(request_id, error=exc)


if __name__ == "__main__":
    main()
