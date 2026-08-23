from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .config import FeedConfig


REQUIRED_FILES = ("agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt")
SERVICE_FILES = ("calendar.txt", "calendar_dates.txt")
DATE_RE = re.compile(r"^\d{8}$")
TIME_RE = re.compile(r"^\d{1,3}:[0-5]\d:[0-5]\d$")


@dataclass(slots=True)
class Issue:
    severity: str
    code: str
    message: str
    table: str | None = None
    row: int | None = None
    sample: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationReport:
    feed_id: str
    municipality: str
    service_name: str
    service_date: str
    status: str = "unknown"
    feed_start_date: str | None = None
    feed_end_date: str | None = None
    feed_version: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    active_service_ids: list[str] = field(default_factory=list)
    active_trip_count: int = 0
    has_shapes: bool = False
    files: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        table: str | None = None,
        row: int | None = None,
        sample: Iterable[str] = (),
    ) -> None:
        self.issues.append(
            Issue(
                severity=severity,
                code=code,
                message=message,
                table=table,
                row=row,
                sample=list(sample)[:20],
            )
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["error_count"] = self.error_count
        result["warning_count"] = self.warning_count
        result["is_valid"] = self.is_valid
        return result


@dataclass(slots=True)
class GtfsData:
    tables: dict[str, list[dict[str, str]]]

    def get(self, name: str) -> list[dict[str, str]]:
        return self.tables.get(name, [])


def _parse_date(value: str) -> date | None:
    if not DATE_RE.fullmatch(value or ""):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_table(path: Path) -> list[dict[str, str]]:
    text = _read_text(path)
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        return []
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {
            str(key).strip(): ("" if value is None else str(value).strip())
            for key, value in row.items()
            if key is not None
        }
        rows.append(normalized)
    return rows


def load_gtfs(directory: str | Path) -> GtfsData:
    root = Path(directory)
    tables: dict[str, list[dict[str, str]]] = {}
    for path in root.glob("*.txt"):
        tables[path.name] = read_csv_table(path)
    return GtfsData(tables=tables)


def _check_unique(
    report: ValidationReport,
    rows: list[dict[str, str]],
    table: str,
    column: str,
) -> set[str]:
    values: list[str] = []
    blank_rows: list[str] = []
    for index, row in enumerate(rows, start=2):
        value = row.get(column, "")
        if value:
            values.append(value)
        else:
            blank_rows.append(str(index))
    if blank_rows:
        report.add(
            "error",
            "blank_primary_id",
            f"{column} is blank in {len(blank_rows)} row(s)",
            table=table,
            sample=blank_rows,
        )
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        report.add(
            "error",
            "duplicate_primary_id",
            f"{column} has {len(duplicates)} duplicate value(s)",
            table=table,
            sample=duplicates,
        )
    return set(values)


def _check_reference(
    report: ValidationReport,
    rows: list[dict[str, str]],
    table: str,
    column: str,
    valid_values: set[str],
    target: str,
    *,
    allow_blank: bool = False,
    severity: str = "error",
) -> None:
    missing: set[str] = set()
    blank_count = 0
    for row in rows:
        value = row.get(column, "")
        if not value:
            blank_count += 1
            continue
        if value not in valid_values:
            missing.add(value)
    if blank_count and not allow_blank:
        report.add(
            severity,
            "blank_foreign_key",
            f"{column} is blank in {blank_count} row(s)",
            table=table,
        )
    if missing:
        report.add(
            severity,
            "missing_reference",
            f"{column} contains {len(missing)} value(s) absent from {target}",
            table=table,
            sample=sorted(missing),
        )


def _service_bounds(data: GtfsData) -> tuple[date | None, date | None, str | None]:
    start: date | None = None
    end: date | None = None
    version: str | None = None
    feed_info = data.get("feed_info.txt")
    if feed_info:
        row = feed_info[0]
        start = _parse_date(row.get("feed_start_date", ""))
        end = _parse_date(row.get("feed_end_date", ""))
        version = row.get("feed_version") or None

    calendar_dates: list[date] = []
    for row in data.get("calendar_dates.txt"):
        parsed = _parse_date(row.get("date", ""))
        if parsed:
            calendar_dates.append(parsed)
    calendar_starts = [
        parsed
        for row in data.get("calendar.txt")
        if (parsed := _parse_date(row.get("start_date", ""))) is not None
    ]
    calendar_ends = [
        parsed
        for row in data.get("calendar.txt")
        if (parsed := _parse_date(row.get("end_date", ""))) is not None
    ]
    candidates_start = [value for value in [start, *calendar_starts, *calendar_dates] if value]
    candidates_end = [value for value in [end, *calendar_ends, *calendar_dates] if value]
    return (
        min(candidates_start) if candidates_start else None,
        max(candidates_end) if candidates_end else None,
        version,
    )


def active_service_ids(data: GtfsData, service_date: date) -> set[str]:
    weekday = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )[service_date.weekday()]
    active: set[str] = set()
    for row in data.get("calendar.txt"):
        start = _parse_date(row.get("start_date", ""))
        end = _parse_date(row.get("end_date", ""))
        if start and end and start <= service_date <= end and row.get(weekday) == "1":
            service_id = row.get("service_id", "")
            if service_id:
                active.add(service_id)

    target = service_date.strftime("%Y%m%d")
    for row in data.get("calendar_dates.txt"):
        if row.get("date") != target:
            continue
        service_id = row.get("service_id", "")
        if row.get("exception_type") == "1" and service_id:
            active.add(service_id)
        elif row.get("exception_type") == "2":
            active.discard(service_id)
    return active


def validate_gtfs(
    feed: FeedConfig,
    directory: str | Path,
    *,
    service_date: date,
) -> tuple[ValidationReport, GtfsData]:
    root = Path(directory)
    report = ValidationReport(
        feed_id=feed.id,
        municipality=feed.municipality,
        service_name=feed.service_name,
        service_date=service_date.isoformat(),
    )
    report.files = sorted(path.name for path in root.glob("*.txt"))

    for filename in REQUIRED_FILES:
        if not (root / filename).is_file():
            report.add("error", "missing_required_file", f"Missing {filename}", table=filename)
    if not any((root / filename).is_file() for filename in SERVICE_FILES):
        report.add(
            "error",
            "missing_service_calendar",
            "At least one of calendar.txt or calendar_dates.txt is required",
        )

    data = load_gtfs(root)
    report.counts = {name: len(rows) for name, rows in sorted(data.tables.items())}
    report.has_shapes = bool(data.get("shapes.txt"))
    if not report.has_shapes:
        report.add(
            "warning",
            "missing_shapes",
            "shapes.txt is absent; route geometry will be reconstructed from representative stop sequences",
            table="shapes.txt",
        )

    if report.error_count:
        report.status = "invalid"
        return report, data

    routes = data.get("routes.txt")
    stops = data.get("stops.txt")
    trips = data.get("trips.txt")
    stop_times = data.get("stop_times.txt")
    agency = data.get("agency.txt")

    route_ids = _check_unique(report, routes, "routes.txt", "route_id")
    stop_ids = _check_unique(report, stops, "stops.txt", "stop_id")
    trip_ids = _check_unique(report, trips, "trips.txt", "trip_id")

    agency_ids = {row.get("agency_id", "") for row in agency if row.get("agency_id")}
    if agency_ids:
        _check_reference(
            report,
            routes,
            "routes.txt",
            "agency_id",
            agency_ids,
            "agency.txt.agency_id",
            allow_blank=len(agency_ids) == 1,
        )
    _check_reference(report, trips, "trips.txt", "route_id", route_ids, "routes.txt.route_id")
    _check_reference(
        report,
        stop_times,
        "stop_times.txt",
        "trip_id",
        trip_ids,
        "trips.txt.trip_id",
    )
    _check_reference(
        report,
        stop_times,
        "stop_times.txt",
        "stop_id",
        stop_ids,
        "stops.txt.stop_id",
    )

    shape_ids = {
        row.get("shape_id", "") for row in data.get("shapes.txt") if row.get("shape_id")
    }
    if shape_ids:
        _check_reference(
            report,
            trips,
            "trips.txt",
            "shape_id",
            shape_ids,
            "shapes.txt.shape_id",
            allow_blank=True,
            severity="warning",
        )

    invalid_coordinates: list[str] = []
    for index, row in enumerate(stops, start=2):
        lat_text = row.get("stop_lat", "")
        lon_text = row.get("stop_lon", "")
        if not lat_text and not lon_text and row.get("location_type") in {"1", "2", "3", "4"}:
            continue
        try:
            lat = float(lat_text)
            lon = float(lon_text)
        except ValueError:
            invalid_coordinates.append(str(index))
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            invalid_coordinates.append(str(index))
    if invalid_coordinates:
        report.add(
            "error",
            "invalid_stop_coordinate",
            f"Invalid stop coordinates in {len(invalid_coordinates)} row(s)",
            table="stops.txt",
            sample=invalid_coordinates,
        )

    invalid_sequences: list[str] = []
    sequences_by_trip: dict[str, list[int]] = defaultdict(list)
    invalid_times: list[str] = []
    for index, row in enumerate(stop_times, start=2):
        sequence_text = row.get("stop_sequence", "")
        try:
            sequence = int(sequence_text)
            sequences_by_trip[row.get("trip_id", "")].append(sequence)
        except ValueError:
            invalid_sequences.append(str(index))
        for field_name in ("arrival_time", "departure_time"):
            value = row.get(field_name, "")
            if value and not TIME_RE.fullmatch(value):
                invalid_times.append(f"{index}:{field_name}={value}")
    for trip_id, sequence_values in sequences_by_trip.items():
        if any(value < 0 for value in sequence_values) or len(sequence_values) != len(set(sequence_values)):
            invalid_sequences.append(trip_id)
    if invalid_sequences:
        report.add(
            "error",
            "invalid_stop_sequence",
            f"Invalid, negative or duplicate stop_sequence in {len(invalid_sequences)} item(s)",
            table="stop_times.txt",
            sample=invalid_sequences,
        )
    if invalid_times:
        report.add(
            "error",
            "invalid_time",
            f"Invalid GTFS time in {len(invalid_times)} field(s)",
            table="stop_times.txt",
            sample=invalid_times,
        )

    start, end, version = _service_bounds(data)
    report.feed_start_date = start.isoformat() if start else None
    report.feed_end_date = end.isoformat() if end else None
    report.feed_version = version
    if start and service_date < start:
        report.status = "not-yet-active"
        report.add(
            "warning",
            "feed_not_yet_active",
            f"Service date {service_date} is before feed start {start}",
        )
    elif end and service_date > end:
        report.status = "expired"
        report.add(
            "error",
            "feed_expired",
            f"Service date {service_date} is after feed end {end}",
        )
    else:
        report.status = "valid" if report.error_count == 0 else "invalid"

    active = active_service_ids(data, service_date)
    report.active_service_ids = sorted(active)
    report.active_trip_count = sum(row.get("service_id") in active for row in trips)
    if not active:
        report.add(
            "warning",
            "no_active_service",
            f"No active service_id found for {service_date.isoformat()}",
        )
    return report, data


def write_report(path: str | Path, report: ValidationReport) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
