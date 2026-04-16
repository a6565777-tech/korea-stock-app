"""뉴스 수집 - Google News RSS 기반 (API 키 불필요)"""
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus
import feedparser


GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
)


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime
    summary: str

    def line(self) -> str:
        ts = self.published.strftime("%m/%d %H:%M")
        return f"[{ts}] {self.source} | {self.title}"


def _parse_time(entry) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def search(keywords: list[str], limit: int = 10, recent_hours: int = 48) -> list[NewsItem]:
    """
    키워드 OR 검색으로 최신 뉴스 수집.
    recent_hours: 이 시간 이내 뉴스만 반환.
    """
    q = " OR ".join(f'"{k}"' if " " in k else k for k in keywords)
    url = GOOGLE_NEWS_RSS.format(q=quote_plus(q))

    feed = feedparser.parse(url)
    items: list[NewsItem] = []
    cutoff = datetime.now(timezone.utc).timestamp() - recent_hours * 3600

    for entry in feed.entries:
        published = _parse_time(entry)
        if published.timestamp() < cutoff:
            continue
        source = getattr(entry, "source", {})
        source_name = source.get("title", "") if isinstance(source, dict) else ""
        items.append(
            NewsItem(
                title=entry.title,
                link=entry.link,
                source=source_name or "Google News",
                published=published,
                summary=getattr(entry, "summary", ""),
            )
        )
        if len(items) >= limit:
            break
    return items


def search_macro(limit_per_topic: int = 3) -> dict[str, list[NewsItem]]:
    """거시 주제 뉴스 (한 번에)"""
    topics = {
        "미국증시": ["나스닥", "S&P 500", "뉴욕증시"],
        "엔비디아·AI반도체": ["엔비디아", "NVIDIA", "AI 반도체", "HBM"],
        "환율·원자재": ["원달러 환율", "유가", "WTI"],
        "지정학": ["이란", "중동", "우크라이나", "중국"],
    }
    return {name: search(kws, limit=limit_per_topic, recent_hours=24)
            for name, kws in topics.items()}


if __name__ == "__main__":
    print("=== 삼성전자 관련 뉴스 ===")
    for n in search(["삼성전자", "HBM"], limit=5):
        print(n.line())

    print("\n=== 거시 주제 뉴스 ===")
    for topic, items in search_macro(limit_per_topic=2).items():
        print(f"\n[{topic}]")
        for n in items:
            print(f"  {n.line()}")
