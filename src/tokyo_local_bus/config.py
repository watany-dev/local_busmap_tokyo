from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class FeedConfig:
    id: str
    slug: str
    municipality: str
    service_name: str
    url: str
    license: str
    priority: str = "A"
    realtime: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "FeedConfig":
        realtime = value.get("realtime") or {}
        if not isinstance(realtime, dict):
            raise ValueError("realtime must be an object")
        return cls(
            id=str(value.get("id", "")).strip(),
            slug=str(value.get("slug", "")).strip(),
            municipality=str(value.get("municipality", "")).strip(),
            service_name=str(value.get("service_name", "")).strip(),
            url=str(value.get("url", "")).strip(),
            license=str(value.get("license", "")).strip(),
            priority=str(value.get("priority", "A")).strip().upper(),
            realtime={str(k): str(v) for k, v in realtime.items()},
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("id is required")
        if not _SLUG_RE.fullmatch(self.slug):
            errors.append(f"invalid slug: {self.slug!r}")
        if not self.municipality:
            errors.append("municipality is required")
        if not self.service_name:
            errors.append("service_name is required")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"invalid url: {self.url!r}")
        if not self.license:
            errors.append("license is required")
        if self.priority not in {"A", "B", "C", "D"}:
            errors.append(f"invalid priority: {self.priority!r}")
        for key, url in self.realtime.items():
            rt_parsed = urlparse(url)
            if rt_parsed.scheme not in {"http", "https"} or not rt_parsed.netloc:
                errors.append(f"invalid realtime URL ({key}): {url!r}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "slug": self.slug,
            "municipality": self.municipality,
            "service_name": self.service_name,
            "url": self.url,
            "license": self.license,
            "priority": self.priority,
        }
        if self.realtime:
            result["realtime"] = dict(self.realtime)
        return result


def load_feeds(path: str | Path) -> list[FeedConfig]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    raw_feeds = payload.get("feeds")
    if not isinstance(raw_feeds, list):
        raise ValueError(f"{source}: feeds must be an array")

    feeds = [FeedConfig.from_mapping(item) for item in raw_feeds]
    errors: list[str] = []
    ids: set[str] = set()
    slugs: set[str] = set()
    for index, feed in enumerate(feeds, start=1):
        for message in feed.validate():
            errors.append(f"feeds[{index}] {feed.id or '<no-id>'}: {message}")
        if feed.id in ids:
            errors.append(f"duplicate feed id: {feed.id}")
        if feed.slug in slugs:
            errors.append(f"duplicate feed slug: {feed.slug}")
        ids.add(feed.id)
        slugs.add(feed.slug)

    if errors:
        raise ValueError("Invalid feed config:\n- " + "\n- ".join(errors))
    return feeds
