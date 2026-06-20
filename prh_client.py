"""PRH BIS v1 API client for fetching recently registered Finnish B2B companies."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://avoindata.prh.fi/bis/v1"
REFERENCE_END_DATE = date(2024, 5, 20)  # Used when system clock is ahead of real time
CHUNK_DAYS = 9  # 10-day inclusive intervals (7–10 day chunks)
REQUEST_DELAY = 0.5
MAX_RESULTS = 1000
REQUEST_TIMEOUT = 120

B2B_PATTERNS = (
    "osakeyhtiö",
    "oy",
    "yksityinen elinkeinonharjoittaja",
    "tmi",
    "toiminimi",
    "kommandiittiyhtiö",
    "ky",
    "avoin yhtiö",
    "ay",
)

B2B_CODES = frozenset({"oy", "oyj", "tmi", "ky", "ay", "ltd"})

EXCLUDE_PATTERNS = (
    "aoy",
    "asunto-osakeyhtiö",
    "asunto osakeyhtiö",
    "bostadsaktiebolag",
    "housing corporation",
    "säätiö",
    "saatio",
    "foundation",
    "yhdistys",
    "association",
    "seurakunta",
)


@dataclass
class SearchProgress:
    """Progress snapshot emitted while searching."""

    current_interval: int
    total_intervals: int
    date_from: str
    date_to: str
    found_in_interval: int
    total_found: int


@dataclass
class SearchResult:
    """Final search result."""

    companies: list[dict[str, str]]
    days_back: int
    date_from: str
    date_to: str
    intervals_searched: int
    intervals_with_data: int
    errors: list[str] = field(default_factory=list)


class PRHClient:
    """Client for the Finnish PRH BIS v1 open data API."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        chunk_days: int = CHUNK_DAYS,
        request_delay: float = REQUEST_DELAY,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chunk_days = chunk_days
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "FinnishLeadGenerator/1.0",
            }
        )

    def fetch_companies(self, days_back: int) -> SearchResult:
        """Fetch B2B companies registered within the last *days_back* days."""
        companies: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        errors: list[str] = []
        intervals_with_data = 0

        end_date, start_date = _get_search_date_range(days_back)
        intervals = list(_iter_date_chunks(start_date, end_date, self.chunk_days))

        for index, (chunk_start, chunk_end) in enumerate(intervals, start=1):
            date_from = chunk_start.isoformat()
            date_to = chunk_end.isoformat()
            found_in_interval = 0

            try:
                raw_results = self._fetch_interval(date_from, date_to)
            except requests.RequestException as exc:
                message = f"{date_from} – {date_to}: {exc}"
                logger.warning(message)
                errors.append(message)
                time.sleep(self.request_delay)
                continue

            if raw_results:
                intervals_with_data += 1

            for raw in raw_results:
                company = _normalize_company(raw)
                if not company:
                    continue
                if not is_b2b_company(company["companyForm"]):
                    continue
                business_id = company["businessId"]
                if business_id in seen_ids:
                    continue
                seen_ids.add(business_id)
                companies.append(company)
                found_in_interval += 1

            logger.info(
                "Interval %s/%s (%s – %s): %s B2B companies",
                index,
                len(intervals),
                date_from,
                date_to,
                found_in_interval,
            )

            if index < len(intervals):
                time.sleep(self.request_delay)

        return SearchResult(
            companies=companies,
            days_back=days_back,
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            intervals_searched=len(intervals),
            intervals_with_data=intervals_with_data,
            errors=errors,
        )

    def fetch_companies_with_progress(
        self, days_back: int
    ) -> Iterator[SearchProgress | SearchResult]:
        """Yield progress updates, then the final :class:`SearchResult`."""
        companies: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        errors: list[str] = []
        intervals_with_data = 0

        end_date, start_date = _get_search_date_range(days_back)
        intervals = list(_iter_date_chunks(start_date, end_date, self.chunk_days))

        for index, (chunk_start, chunk_end) in enumerate(intervals, start=1):
            date_from = chunk_start.isoformat()
            date_to = chunk_end.isoformat()
            found_in_interval = 0

            try:
                raw_results = self._fetch_interval(date_from, date_to)
            except requests.RequestException as exc:
                message = f"{date_from} – {date_to}: {exc}"
                logger.warning(message)
                errors.append(message)
                yield SearchProgress(
                    current_interval=index,
                    total_intervals=len(intervals),
                    date_from=date_from,
                    date_to=date_to,
                    found_in_interval=0,
                    total_found=len(companies),
                )
                if index < len(intervals):
                    time.sleep(self.request_delay)
                continue

            if raw_results:
                intervals_with_data += 1

            for raw in raw_results:
                company = _normalize_company(raw)
                if not company:
                    continue
                if not is_b2b_company(company["companyForm"]):
                    continue
                business_id = company["businessId"]
                if business_id in seen_ids:
                    continue
                seen_ids.add(business_id)
                companies.append(company)
                found_in_interval += 1

            yield SearchProgress(
                current_interval=index,
                total_intervals=len(intervals),
                date_from=date_from,
                date_to=date_to,
                found_in_interval=found_in_interval,
                total_found=len(companies),
            )

            if index < len(intervals):
                time.sleep(self.request_delay)

        yield SearchResult(
            companies=companies,
            days_back=days_back,
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            intervals_searched=len(intervals),
            intervals_with_data=intervals_with_data,
            errors=errors,
        )

    def _fetch_interval(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        """Fetch all companies for a single date interval, following pagination."""
        params: dict[str, str | int] | None = {
            "companyRegistrationFrom": date_from,
            "companyRegistrationTo": date_to,
            "maxResults": MAX_RESULTS,
            "totalResults": "false",
        }
        url: str | None = self.base_url
        results: list[dict[str, Any]] = []

        while url:
            response = self._get(url, params=params)
            params = None

            if response.status_code == 404:
                return results

            if response.status_code != 200:
                response.raise_for_status()

            payload = response.json()
            batch = payload.get("results", [])
            if isinstance(batch, list):
                results.extend(batch)

            url = payload.get("nextResultsUri")
            if url:
                time.sleep(self.request_delay)

        return results

    def _get(self, url: str, params: dict[str, str | int] | None = None) -> requests.Response:
        return self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)


def is_b2b_company(company_form: str) -> bool:
    """Return True when the company form matches allowed B2B types."""
    form = (company_form or "").strip().lower()
    if not form:
        return False

    if any(pattern in form for pattern in EXCLUDE_PATTERNS):
        return False

    if "asunto" in form and "osakeyhtiö" in form:
        return False

    if form in B2B_CODES:
        return True

    return any(pattern in form for pattern in B2B_PATTERNS)


def _normalize_company(raw: dict[str, Any]) -> dict[str, str] | None:
    """Convert a raw API record into a flat company dictionary."""
    business_id = raw.get("businessId")
    if isinstance(business_id, dict):
        business_id = business_id.get("value")
    business_id = str(business_id or "").strip()
    if not business_id:
        return None

    name = str(raw.get("name") or "").strip()
    company_form = str(raw.get("companyForm") or "").strip()
    registration_date = str(raw.get("registrationDate") or "").strip()

    return {
        "businessId": business_id,
        "name": name,
        "companyForm": company_form,
        "registrationDate": registration_date,
    }


def _get_search_date_range(days_back: int) -> tuple[date, date]:
    """Return (end_date, start_date), clamping end to a known-good date when clock is ahead."""
    today = date.today()
    end_date = REFERENCE_END_DATE if today.year > 2024 else today
    start_date = end_date - timedelta(days=days_back)
    return end_date, start_date


def _iter_date_chunks(
    start_date: date, end_date: date, chunk_days: int
) -> Iterator[tuple[date, date]]:
    """Yield inclusive date intervals covering [start_date, end_date]."""
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)
