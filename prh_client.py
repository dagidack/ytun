# ... existing code ...
logger = logging.getLogger(__name__)

BASE_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
REFERENCE_END_DATE = date(2024, 5, 20)  # Used when system clock is ahead of real time
REQUEST_DELAY = 0.5
MAX_RESULTS = 1000
REQUEST_TIMEOUT = 120

B2B_PATTERNS = (
    "osakeyhtiö",
# ... existing code ...
    "ay",
)

B2B_CODES = frozenset({"16", "26", "13", "14", "oy", "oyj", "tmi", "ky", "ay", "ltd"})

EXCLUDE_PATTERNS = (
# ... existing code ...
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
    """Client for the Finnish PRH YTJ v3 open data API."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        request_delay: float = REQUEST_DELAY,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "FinnishLeadGenerator/2.0",
            }
        )

    def fetch_companies(self, days_back: int) -> SearchResult:
        """Fetch B2B companies registered within the last *days_back* days."""
        result = None
        for event in self.fetch_companies_with_progress(days_back):
            if isinstance(event, SearchResult):
                result = event
        return result or SearchResult([], days_back, "", "", 0, 0)

    def fetch_companies_with_progress(
        self, days_back: int
    ) -> Iterator[SearchProgress | SearchResult]:
        """Yield progress updates, then the final :class:`SearchResult`."""
        companies: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        errors: list[str] = []
        intervals_with_data = 0

        end_date, start_date = _get_search_date_range(days_back)
        start_date_str = start_date.isoformat()

        import urllib.parse
        params = {
            "businessIdStart": "3350000-0",  # Гарантирует свежие регистрации за 2023-2026
            "maxResults": MAX_RESULTS
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        
        current_page = 1
        max_pages = 50

        while url and current_page <= max_pages:
            found_in_interval = 0

            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 404:
                    break
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                message = f"Page {current_page}: {exc}"
                logger.warning(message)
                errors.append(message)
                yield SearchProgress(
                    current_interval=current_page,
                    total_intervals=max_pages,
                    date_from=start_date_str,
                    date_to=end_date.isoformat(),
                    found_in_interval=0,
                    total_found=len(companies),
                )
                current_page += 1
                time.sleep(self.request_delay)
                continue

            batch = payload.get("companies", payload.get("results", []))
            if batch:
                intervals_with_data += 1

            for raw in batch:
                reg_date = str(raw.get("registrationDate") or "").strip()
                # Фильтруем по дате локально, т.к. v3 этого не умеет
                if reg_date and reg_date >= start_date_str:
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
                current_interval=current_page,
                total_intervals=max_pages,
                date_from=start_date_str,
                date_to=end_date.isoformat(),
                found_in_interval=found_in_interval,
                total_found=len(companies),
            )

            next_url = payload.get("nextResultsUri")
            if not next_url and "links" in payload:
                for link in payload["links"]:
                    if link.get("rel") == "next":
                        next_url = link.get("href")
                        break
            url = next_url

            current_page += 1
            if url:
                time.sleep(self.request_delay)

        yield SearchResult(
            companies=companies,
            days_back=days_back,
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
            intervals_searched=current_page - 1,
            intervals_with_data=intervals_with_data,
            errors=errors,
        )


def is_b2b_company(company_form: str) -> bool:
# ... existing code ...
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

    # В v3 имя может лежать в массиве names
    name = str(raw.get("name") or "").strip()
    if not name and "names" in raw:
        names = raw.get("names", [])
        if names and isinstance(names, list):
            name = str(names[0].get("name") or "").strip()

    # В v3 форма собственности может лежать в массиве companyForms
    company_form = str(raw.get("companyForm") or "").strip()
    if not company_form and "companyForms" in raw:
        forms = raw.get("companyForms", [])
        if forms and isinstance(forms, list):
            company_form = str(forms[0].get("type") or "").strip()

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
