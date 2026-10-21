"""Playwright crawler: breadth-first, same-origin, one snapshot + screenshot per page."""
from __future__ import annotations

import contextlib
import logging
import re
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .chatbot import build_chat_widget
from .config import EXTRACT_JS, context_options
from .models import Component, PageSnapshot

log = logging.getLogger(__name__)

_SKIP_EXT = re.compile(r"\.(pdf|png|jpe?g|gif|svg|webp|zip|css|js|xml|json|ico|mp4|mp3)$", re.I)


def canonical_url(url: str) -> str:
    """Drop query/fragment and collapse ``/index.html`` to ``/`` so each page is visited once."""
    parts = urlparse(url)
    path = parts.path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    return urlunparse((parts.scheme, parts.netloc, path, "", "", ""))


def url_path(url: str) -> str:
    return urlparse(canonical_url(url)).path


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


@contextlib.contextmanager
def browser_session(headless: bool = True) -> Iterator[Browser]:
    """Launch Chromium once and share it between platforms, crawls and flows."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            browser.close()


def new_context(browser: Browser, platform: str) -> BrowserContext:
    return browser.new_context(**context_options(platform))


def snapshot_page(page: Page, platform: str, screenshot_path: Path | None, rel_to: Path | None) -> PageSnapshot:
    """Extract the inventory of the currently loaded page and optionally take a full-page screenshot."""
    page.evaluate("window.scrollTo(0, 0)")
    data = page.evaluate(EXTRACT_JS)
    viewport = data["viewport"]
    shot: str | None = None
    if screenshot_path is not None:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_path), full_page=True, type="jpeg", quality=72)
        shot = str(screenshot_path.relative_to(rel_to)) if rel_to else str(screenshot_path)
    return PageSnapshot(
        platform=platform,
        url=canonical_url(page.url),
        path=url_path(page.url),
        title=data["title"],
        h1=data["h1"],
        nav_labels=[{"label": n["label"], "href": canonical_url(n["href"])} for n in data["nav"]],
        components=[Component(**c) for c in data["components"]],
        chat=build_chat_widget(data["chats"], viewport),
        screenshot=shot,
        links=[canonical_url(u) for u in data["links"]],
        viewport=viewport,
    )


def _slug(path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/")).strip("_")
    return slug or "home"


def crawl(
    browser: Browser,
    start_url: str,
    platform: str,
    out_dir: Path,
    max_pages: int = 30,
) -> list[PageSnapshot]:
    """Crawl same-origin links breadth-first from ``start_url`` (navigation links are queued first)."""
    context = new_context(browser, platform)
    page = context.new_page()
    queue: deque[str] = deque([canonical_url(start_url)])
    seen: set[str] = set(queue)
    snapshots: list[PageSnapshot] = []
    try:
        while queue and len(snapshots) < max_pages:
            url = queue.popleft()
            try:
                response = page.goto(url, wait_until="load", timeout=20_000)
            except Exception as exc:  # network errors should not abort the whole crawl
                log.warning("Skipping %s: %s", url, exc)
                continue
            if response is not None and response.status >= 400:
                log.warning("Skipping %s: HTTP %s", url, response.status)
                continue
            page.wait_for_timeout(150)  # let small client-side scripts settle
            shot = out_dir / "screenshots" / f"{platform}_{_slug(url_path(url))}.jpg"
            snap = snapshot_page(page, platform, shot, out_dir)
            snapshots.append(snap)
            log.info("[%s] %s -> %s", platform, snap.path, snap.name)
            nav_first = [n["href"] for n in snap.nav_labels] + snap.links
            for link in nav_first:
                link = canonical_url(link)
                if (
                    link not in seen
                    and link.startswith("http")
                    and _same_origin(link, start_url)
                    and not _SKIP_EXT.search(urlparse(link).path)
                ):
                    seen.add(link)
                    queue.append(link)
    finally:
        context.close()
    return snapshots
