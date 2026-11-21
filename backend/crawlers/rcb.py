"""RCB daily report (Raport dobowy) — Rządowe Centrum Bezpieczeństwa.

One gov.pl page that RCB overwrites every day with: active meteorological and hydrological
warnings, alarm water levels, air quality, carbon-monoxide and hypothermia deaths, and the
exact text of every RCB SMS alert sent the previous day. Ideal evidence for rumours such as
"RCB sent an evacuation SMS" or "there is a flood alert in X".
"""

from .base import Document, SnapshotCrawler
from .dates import parse_polish_date

# The same intro paragraph opens every report; it carries no facts about the day.
INTRO_PREFIX = "RAPORT DOBOWY powstaje w Rządowym Centrum Bezpieczeństwa"


class RcbDailyReport(SnapshotCrawler):
    name = "rcb"
    catalog_id = 4  # corpus/sources.csv: Rządowe Centrum Bezpieczeństwa, raport dobowy
    page_url = "https://www.gov.pl/web/rcb/raport-dobowy3"
    license = "Public sector information published on gov.pl (terms: to_verify)"

    def parse_snapshot(self, html: str) -> Document:
        soup = self.soup(html)
        article = soup.select_one("article.article-area__article") or soup.find("article")
        if article is None:
            raise ValueError("report article not found (page layout changed?)")
        lines = self.clean_text(article).splitlines()
        lines = [line for line in lines if not line.startswith(INTRO_PREFIX)]
        if lines and lines[0].lower() == "raport dobowy":
            lines = lines[1:]
        # The report date is the first line that contains a date ("21 listopada 2026 r.").
        published_at = next((d for d in map(parse_polish_date, lines[:5]) if d), None)
        day = published_at.strftime("%d.%m.%Y") if published_at else "?"
        return Document(
            url=self.page_url,
            title=f"Raport dobowy RCB z dnia {day}",
            text="\n".join(lines),
            published_at=published_at,
        )
