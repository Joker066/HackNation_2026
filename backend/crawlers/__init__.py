"""Source crawlers. Register every adapter here so `python -m crawlers.run` can find it."""

from .base import Crawler
from .rcb import RcbDailyReport

REGISTRY: dict[str, type[Crawler]] = {
    cls.name: cls
    for cls in [
        RcbDailyReport,
        # add new adapters here
    ]
}
