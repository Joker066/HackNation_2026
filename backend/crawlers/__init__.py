"""Source crawlers. Register every adapter here so `python -m crawlers.run` can find it."""

from .base import Crawler
from .cert import CertCrawler
from .govpl import GOVPL_CRAWLERS
from .kgsok import KgsokCrawler
from .rcb import RcbDailyReport
from .umgdy import UmgdyCrawler
from .policjaCrawler import PolicjaCrawler

REGISTRY: dict[str, type[Crawler]] = {
    cls.name: cls
    for cls in [
        RcbDailyReport,
        # add new adapters here
        PolicjaCrawler,
        CertCrawler,
        KgsokCrawler,
        UmgdyCrawler,
        *GOVPL_CRAWLERS,
    ]
}
