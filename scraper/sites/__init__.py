"""Quiz site scrapers — plugin registry.

Each site module implements a BaseScraper subclass for a specific quiz website.
Register new sites here to make them available via --site CLI flag.
"""

from scraper.sites.ckl import CKLScraper
from scraper.sites.westacademic import WestAcademicScraper

# Registry mapping site name → scraper class.
# Add new sites here as they are implemented.
SITE_SCRAPERS = {
    "ckl": CKLScraper,
    "westacademic": WestAcademicScraper,
}

DEFAULT_SITE = "ckl"
