"""One run: read the directories, merge them, read the case pages, classify."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from . import config, merge
from .fetch import Fetcher
from .merge import Settlement
from .sources import (CAO_URL, OCA_DIRECTORY_URL, OCA_NO_PROOF_URL, parse_cao_listing,
                      parse_oca_detail, parse_oca_directory, parse_oca_no_proof)


def collect(fetcher: Fetcher, today: date, home_states: list[str],
            progress: Callable[[int, int], None] = lambda done, total: None,
            ) -> tuple[list[Settlement], dict]:
    cao_page = fetcher.get(CAO_URL, config.LISTING_TTL_HOURS)
    oca_page = fetcher.get(OCA_DIRECTORY_URL, config.LISTING_TTL_HOURS)
    strict_page = fetcher.get(OCA_NO_PROOF_URL, config.LISTING_TTL_HOURS)
    if not cao_page and not oca_page:
        raise RuntimeError("Couldn't load either settlement directory "
                           "(no network, or both sites are down). Try again later.")

    cao = parse_cao_listing(cao_page) if cao_page else []
    oca = parse_oca_directory(oca_page) if oca_page else []
    strict = parse_oca_no_proof(strict_page) if strict_page else []

    warnings = []
    for label, page, items in (("ClassAction.org", cao_page, cao),
                               ("OpenClassActions", oca_page, oca)):
        if not page:
            warnings.append(f"{label} couldn't be reached; this report uses the other directory only.")
        elif not items:
            warnings.append(f"{label} loaded but no settlements were found in it. "
                            "The site layout probably changed; the parser needs updating.")

    settlements = merge.build(cao, oca, strict, today, home_states)
    need = [s for s in settlements if s.oca and not s.excluded]
    for done, s in enumerate(need, 1):
        page = fetcher.get(s.oca.url, config.DETAIL_TTL_HOURS)
        if page:
            merge.apply_detail(s, parse_oca_detail(page), today)
        progress(done, len(need))
    settlements = merge.merge_by_site(settlements, today, home_states)

    stats = {"sources": {"cao": len(cao), "oca": len(oca), "strict": len(strict)},
             "detail_pages": len(need), "network": fetcher.network_hits, "warnings": warnings}
    return settlements, stats
