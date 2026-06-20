"""Flask web application for the Finnish B2B Lead Generator."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass

from flask import Flask, Response, jsonify, render_template, request

from csv_export import companies_to_csv_bytes
from prh_client import PRHClient, SearchProgress, SearchResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = Flask(__name__)
client = PRHClient()


def _serialize_event(event: SearchProgress | SearchResult) -> str:
    if is_dataclass(event):
        payload = asdict(event)
        payload["type"] = event.__class__.__name__
        return json.dumps(payload, ensure_ascii=False)
    raise TypeError(f"Unsupported event type: {type(event)!r}")


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.post("/api/search")
def search() -> Response:
    payload = request.get_json(silent=True) or {}
    days_back = payload.get("days_back", 30)

    try:
        days_back = int(days_back)
    except (TypeError, ValueError):
        return jsonify({"error": "Days back must be a whole number."}), 400

    if days_back < 1 or days_back > 730:
        return jsonify({"error": "Days back must be between 1 and 730."}), 400

    stream = payload.get("stream", False)
    if stream:

        def generate() -> str:
            for event in client.fetch_companies_with_progress(days_back):
                yield f"data: {_serialize_event(event)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    result = client.fetch_companies(days_back)
    return jsonify(
        {
            "companies": result.companies,
            "count": len(result.companies),
            "meta": {
                "days_back": result.days_back,
                "date_from": result.date_from,
                "date_to": result.date_to,
                "intervals_searched": result.intervals_searched,
                "intervals_with_data": result.intervals_with_data,
                "errors": result.errors,
            },
        }
    )


@app.post("/api/export")
def export_csv() -> Response:
    payload = request.get_json(silent=True) or {}
    companies = payload.get("companies")

    if not isinstance(companies, list) or not companies:
        return jsonify({"error": "No companies to export."}), 400

    csv_bytes = companies_to_csv_bytes(companies)
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="finnish_b2b_leads.csv"'},
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
