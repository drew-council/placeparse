"""Bounded, public-website email discovery with per-address source evidence."""

import ipaddress
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Comment

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTACT_RE = re.compile(
    r"contact|about|reserv|faq|allerg|dietary|inquir|location|team|private.din|event",
    re.I,
)
OBFUSCATED_RE = re.compile(
    r"([\w.+-]+)\s*(?:\[at\]|\(at\))\s*([a-z0-9-]+(?:\s*(?:\[dot\]|\(dot\)|\.)\s*[a-z0-9-]+)+)",
    re.I,
)
USER_AGENT = "placeparse/0.1 (public restaurant contact discovery)"


def valid_email(email: str) -> bool:
    address = email.lower().strip()
    if not EMAIL_RE.fullmatch(address):
        return False
    local, domain = address.rsplit("@", 1)
    return not (
        local.startswith(("noreply", "no-reply", "donotreply"))
        or local in {"freewebsitecopyright", "placejoys.com", "localoria.com"}
        or domain
        in {
            "example.com",
            "example.org",
            "example.net",
            "test.com",
            "invalid.com",
            "mystore.com",
            "mysite.com",
            "totalav.com",
        }
        or any(
            domain == suffix or domain.endswith("." + suffix)
            for suffix in ("sentry.io", "wixpress.com", "sentry.wixpress.com")
        )
        or domain.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".js", ".css")
        )
        or ".." in domain
        or "." not in domain
    )


def email_role(email: str) -> str:
    domain = email.rsplit("@", 1)[-1].lower()
    if any(
        domain == vendor or domain.endswith("." + vendor)
        for vendor in (
            "wix.com",
            "wixpress.com",
            "squarespace.com",
            "bentobox.com",
            "getbento.com",
            "popmenu.com",
            "wearepopmenu.com",
            "toasttab.com",
            "resy.com",
            "opentable.com",
            "grubhub.com",
            "doordash.com",
            "menufy.com",
            "squareup.com",
            "slicelife.com",
            "one7g.com",
            "forumdas.com.tr",
            "placejoys.com",
            "localoria.com",
            "totalav.com",
        )
    ):
        return "platform/vendor"
    local = email.split("@", 1)[0].lower()
    for role, words in (
        ("allergy/dietary", ("allerg", "dietary")),
        ("reservations", ("reserv", "booking")),
        ("press/marketing", ("press", "media", "pr", "marketing")),
        ("careers", ("career", "job", "hiring", "resume")),
        ("events/catering", ("event", "cater", "party", "parties", "private")),
        ("privacy/legal", ("privacy", "legal", "abuse", "copyright")),
        ("ticketing/membership", ("ticket", "member", "sponsor")),
        ("lost property", ("lostproperty", "lostandfound", "ismystuff")),
        ("billing/accounts", ("billing", "accounts")),
    ):
        if any(local == word or (len(word) > 2 and word in local) for word in words):
            return role
    return "general/unspecified"


def extract_emails(html: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if isinstance(href, str) and href.lower().startswith("mailto:"):
            found.update(EMAIL_RE.findall(unquote(href[7:].split("?", 1)[0])))
    for element in soup.select("[data-cfemail]"):
        encoded = element.get("data-cfemail")
        if isinstance(encoded, str):
            try:
                raw = bytes.fromhex(encoded)
                found.add(bytes(value ^ raw[0] for value in raw[1:]).decode())
            except (ValueError, IndexError, UnicodeDecodeError):
                pass
    for element in soup.select("script, style, svg, noscript"):
        element.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    text = soup.get_text(" ", strip=True)
    found.update(EMAIL_RE.findall(text))
    for user, domain in OBFUSCATED_RE.findall(text):
        decoded_domain = re.sub(
            r"\s*(?:\[dot\]|\(dot\)|\.)\s*", ".", domain, flags=re.I
        )
        found.add(f"{user}@{decoded_domain}")
    return {
        email.lower().strip(".")
        for email in found
        if valid_email(email) and email_role(email) != "platform/vendor"
    }


def public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return False
        if parsed.port not in {None, 80, 443}:
            return False
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
        return bool(addresses) and all(
            ipaddress.ip_address(addr[4][0]).is_global for addr in addresses
        )
    except (ValueError, OSError):
        return False


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def related_hosts(base: str, target: str) -> bool:
    first, second = host(base), host(target)
    return bool(first and second) and (first == second or second.endswith("." + first))


def contact_links(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ranked: dict[str, int] = {}
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = urldefrag(urljoin(base, href))[0]
        if urlsplit(url).scheme not in {"http", "https"} or host(url) != host(base):
            continue
        label = anchor.get_text(" ", strip=True) + " " + unquote(urlsplit(url).path)
        if CONTACT_RE.search(label) and not urlsplit(url).path.lower().endswith(
            (".pdf", ".jpg", ".png")
        ):
            ranked[url] = (
                0 if re.search(r"contact|allerg|dietary|inquir", label, re.I) else 1
            )
    return sorted(ranked, key=lambda url: (ranked[url], len(url)))


@dataclass
class Page:
    url: str
    status: str
    emails: list[str] = field(default_factory=list)


@dataclass
class Discovery:
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    outcome: str = "not_found_on_checked_pages"
    sources: dict[str, list[str]] = field(default_factory=dict)
    pages: list[Page] = field(default_factory=list)
    contact_forms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_page(session: requests.Session, url: str, deadline: float) -> tuple[str, str]:
    """Validate every redirect, cap bytes/time, and never send browser auth or API keys."""
    for _ in range(6):
        if time.monotonic() >= deadline:
            raise TimeoutError("site_budget")
        if not public_url(url):
            raise ValueError("unsafe_or_unresolvable_url")
        with session.get(
            url, timeout=(4, 8), allow_redirects=False, stream=True
        ) as response:
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("invalid_redirect")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            if not any(
                kind in response.headers.get("Content-Type", "").lower()
                for kind in ("html", "text/plain")
            ):
                raise ValueError("unsupported_content_type")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(16384):
                size += len(chunk)
                if size > 2_000_000 or time.monotonic() >= deadline:
                    raise TimeoutError("page_budget")
                chunks.append(chunk)
            return url, b"".join(chunks).decode(
                response.encoding or "utf-8", errors="replace"
            )
    raise ValueError("too_many_redirects")


def discover_emails(
    website: str, max_pages: int = 6, budget_seconds: float = 40
) -> Discovery:
    result = Discovery()
    if not website:
        result.outcome = "no_website"
        return result
    deadline = time.monotonic() + budget_seconds
    with requests.Session() as session:
        session.trust_env = False
        session.headers["User-Agent"] = USER_AGENT
        queue = [website]
        visited: set[str] = set()
        robots: dict[str, RobotFileParser | None] = {}
        while queue and len(result.pages) < max_pages and time.monotonic() < deadline:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
            if origin not in robots:
                robot = RobotFileParser()
                try:
                    _, text = fetch_page(session, origin + "/robots.txt", deadline)
                    robot.parse(text.splitlines())
                    robots[origin] = robot
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code in {
                        401,
                        403,
                    }:
                        robot.parse(["User-agent: *", "Disallow: /"])
                        robots[origin] = robot
                    else:
                        robots[origin] = None
                except (requests.RequestException, ValueError, TimeoutError):
                    robots[origin] = None
            rules = robots[origin]
            if rules and not rules.can_fetch(USER_AGENT, url):
                result.pages.append(Page(url, "robots_disallowed"))
                continue
            try:
                final_url, html = fetch_page(session, url, deadline)
            except (requests.RequestException, ValueError, TimeoutError) as exc:
                label = type(exc).__name__
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    label = f"HTTP_{exc.response.status_code}"
                result.pages.append(Page(url, label))
                continue
            if not related_hosts(website, final_url):
                result.pages.append(
                    Page(final_url, "external_redirect_requires_review")
                )
                continue
            if final_url in visited and final_url != url:
                continue
            visited.add(final_url)
            emails = sorted(extract_emails(html))
            result.pages.append(Page(final_url, "ok", emails))
            for email in emails:
                result.sources.setdefault(email, []).append(final_url)
            soup = BeautifulSoup(html, "html.parser")
            if any(
                form.select('input[type="email"], textarea')
                for form in soup.select("form")
            ):
                result.contact_forms.append(final_url)
            for link in contact_links(html, final_url):
                if link not in visited and link not in queue:
                    queue.append(link)
            time.sleep(0.25)
        if result.sources:
            result.outcome = "found"
        elif not result.pages or any(page.status != "ok" for page in result.pages):
            result.outcome = "incomplete_lookup"
        elif result.contact_forms:
            result.outcome = "contact_form_only"
        if queue and not result.sources:
            result.outcome = "incomplete_lookup"
    return result
