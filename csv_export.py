"""CSV export utilities for company search results."""

from __future__ import annotations

import csv
import io
from typing import Iterable


CSV_COLUMNS = ("businessId", "name", "companyForm", "registrationDate")
CSV_HEADERS = ("Y-tunnus", "Company Name", "Company Form", "Registration Date")


def companies_to_csv_bytes(companies: Iterable[dict[str, str]]) -> bytes:
    """Serialize companies to CSV bytes using utf-8-sig and semicolon delimiter."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_HEADERS)

    for company in companies:
        writer.writerow([company.get(column, "") for column in CSV_COLUMNS])

    return buffer.getvalue().encode("utf-8-sig")
