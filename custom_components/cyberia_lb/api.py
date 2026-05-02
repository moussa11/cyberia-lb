"""Cyberia Lebanon Account Management Center client.

Cyberia's self-care site is an ASP.NET/SharePoint portal. Login requires a
normal form post with SharePoint hidden fields such as __VIEWSTATE and
__EVENTVALIDATION. After authentication, account data is rendered as HTML.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://myaccount.cyberia.net.lb"
LOGIN_URL = f"{BASE_URL}/_layouts/15/Cyberia/ManageUsers/Login.aspx"
MY_ACCOUNTS_URL = f"{BASE_URL}/_layouts/15/Cyberia/ManageServices/MyAccounts.aspx"
PROFILE_URL = f"{BASE_URL}/_layouts/15/Cyberia/ManageUsers/Profile.aspx"

USERNAME_FIELD = "ctl00$PlaceHolderMain$signInControl$UserName"
PASSWORD_FIELD = "ctl00$PlaceHolderMain$signInControl$password"
SIGN_IN_TARGET = "ctl00$PlaceHolderMain$signInControl$SignInButton"
MANAGE_RESIDENTIAL_RE = re.compile(
    r"__doPostBack\('([^']*ResidentialServicesGridView[^']*ManageResidentialButton)'",
    re.I,
)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": BASE_URL,
    "Referer": LOGIN_URL,
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


class CyberiaAuthError(Exception):
    """Credentials rejected by the Cyberia portal."""


class CyberiaApiError(Exception):
    """Transport, parsing, or non-auth portal error."""


class _AspNetFormParser(HTMLParser):
    """Collect form action and input values from the ASP.NET form."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, str] = {}
        self.action: str | None = None
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag.lower() == "form" and attr.get("id") == "aspnetForm":
            self._in_form = True
            self.action = attr.get("action") or None
            return
        if self._in_form and tag.lower() == "input":
            name = attr.get("name")
            if name:
                self.inputs[name] = attr.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self._in_form = False


class _TableParser(HTMLParser):
    """Extract simple text rows from every HTML table."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            text = _clean_text(" ".join(self._cell_parts))
            self._row.append(text)
            self._cell_parts = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


@dataclass
class _CandidateValue:
    label: str
    value: str


def _clean_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _page_text(html: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    for pattern in (
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
    ):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            pass
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", raw)
    if not match:
        return None
    month, day, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _to_mb(raw: str | None) -> float | None:
    if not raw:
        return None
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(kb|mb|gb|tb)?", raw, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = (match.group(2) or "mb").lower()
    if unit == "kb":
        return value / 1000
    if unit == "gb":
        return value * 1000
    if unit == "tb":
        return value * 1000 * 1000
    return value


def _parse_usage_pair(raw: str | None) -> tuple[float | None, float | None]:
    if not raw:
        return None, None
    parts = re.split(r"\s*(?:/|of|from)\s*", raw, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None, None
    return _to_mb(parts[0]), _to_mb(parts[1])


def _extract_tables(html: str) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def _candidate_values(tables: list[list[list[str]]]) -> list[_CandidateValue]:
    values: list[_CandidateValue] = []
    for table in tables:
        headers: list[str] | None = None
        for row in table:
            cells = [_clean_text(cell) for cell in row if _clean_text(cell)]
            if len(cells) < 2:
                continue
            lower = [cell.lower() for cell in cells]
            if any("account" in cell or "subscription" in cell for cell in lower):
                headers = cells
            if len(cells) == 2:
                values.append(_CandidateValue(cells[0], cells[1]))
            elif headers and len(headers) == len(cells):
                for header, cell in zip(headers, cells, strict=False):
                    if header != cell:
                        values.append(_CandidateValue(header, cell))
            else:
                for idx in range(0, len(cells) - 1, 2):
                    values.append(_CandidateValue(cells[idx], cells[idx + 1]))
    return values


def _find_value(candidates: list[_CandidateValue], *needles: str) -> str | None:
    for candidate in candidates:
        label = candidate.label.lower()
        if any(needle in label for needle in needles):
            return candidate.value
    return None


def _find_manage_target(html: str) -> str | None:
    match = MANAGE_RESIDENTIAL_RE.search(html)
    return match.group(1) if match else None


def _parse_account_data(html: str, account_list_html: str | None = None) -> dict[str, Any]:
    text = _page_text(html)
    tables = _extract_tables(html)
    candidates = _candidate_values(tables)

    usage_text = _find_value(candidates, "traffic", "consumption", "usage", "quota")
    used_mb = _to_mb(_find_value(candidates, "traffic usage", "used", "consumed"))
    total_mb = _to_mb(_find_value(candidates, "total", "quota", "package"))
    pair_used, pair_total = _parse_usage_pair(usage_text)
    used_mb = used_mb if used_mb is not None else pair_used
    total_mb = total_mb if total_mb is not None else pair_total

    remaining_candidate = _find_candidate(
        candidates, "remaining extra traffic", "remaining traffic", "remaining", "left"
    )
    remaining_mb = _to_mb(remaining_candidate.value if remaining_candidate else None)
    if remaining_mb is None and used_mb is not None and total_mb is not None:
        remaining_mb = max(total_mb - used_mb, 0)
    if (
        total_mb is None
        and used_mb is not None
        and remaining_mb is not None
        and remaining_candidate is not None
        and "extra" not in remaining_candidate.label.lower()
    ):
        total_mb = used_mb + remaining_mb

    validity_raw = _find_value(candidates, "expiry", "expiration", "validity", "valid until")
    validity_date = _parse_date(validity_raw)

    accounts = _summarize_tables(_extract_tables(account_list_html)) if account_list_html else []
    details = _details_from_candidates(candidates)
    return {
        "account_count": len(accounts) or None,
        "accounts": accounts,
        "details": details,
        "plan_name": _find_value(candidates, "type", "plan", "service", "package"),
        "status": _find_value(candidates, "status", "state"),
        "data_used_mb": used_mb,
        "data_total_mb": total_mb,
        "data_remaining_mb": remaining_mb,
        "balance_raw": _find_value(candidates, "balance"),
        "validity": (
            datetime.combine(validity_date, datetime.min.time()).astimezone()
            if validity_date
            else None
        ),
        "validity_raw": validity_raw,
        "days_until_expiry": (validity_date - date.today()).days if validity_date else None,
        "raw_text": text[:1000],
    }


def _details_from_candidates(candidates: list[_CandidateValue]) -> dict[str, str]:
    details: dict[str, str] = {}
    for candidate in candidates:
        label = _clean_text(candidate.label).lower()
        key = re.sub(r"[^a-z0-9]+", "_", label).strip("_")
        if key and candidate.value and key not in details:
            details[key] = candidate.value
    return details


def _find_candidate(
    candidates: list[_CandidateValue], *needles: str
) -> _CandidateValue | None:
    for candidate in candidates:
        label = candidate.label.lower()
        if any(needle in label for needle in needles):
            return candidate
    return None


def _summarize_tables(tables: list[list[list[str]]]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for table in tables:
        if len(table) < 2:
            continue
        headers = table[0]
        if len(headers) < 2:
            continue
        for row in table[1:]:
            if len(row) != len(headers):
                continue
            item = {
                _clean_text(header).lower().replace(" ", "_"): _clean_text(value)
                for header, value in zip(headers, row, strict=False)
                if _clean_text(header) and _clean_text(value)
            }
            if item:
                summaries.append(item)
    return summaries[:10]


class CyberiaClient:
    """Async client for Cyberia's web Account Management Center."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username.strip()
        self._password = password
        self._logged_in = False

    @property
    def username(self) -> str:
        return self._username

    async def _get(self, url: str) -> str:
        try:
            async with self._session.get(
                url,
                headers={k: v for k, v in HEADERS.items() if k != "Content-Type"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status >= 500:
                    raise CyberiaApiError(f"HTTP {resp.status} from Cyberia")
                if resp.status >= 400:
                    raise CyberiaApiError(f"HTTP {resp.status}: {text[:200]}")
                return text
        except aiohttp.ClientError as err:
            raise CyberiaApiError(str(err)) from err
        except asyncio.TimeoutError as err:
            raise CyberiaApiError(f"Timeout fetching {url}") from err

    async def _login(self) -> None:
        login_html = await self._get(LOGIN_URL)
        parser = _AspNetFormParser()
        parser.feed(login_html)
        if not parser.inputs:
            raise CyberiaApiError("Could not find Cyberia login form")

        fields = dict(parser.inputs)
        fields[USERNAME_FIELD] = self._username
        fields[PASSWORD_FIELD] = self._password
        fields["__EVENTTARGET"] = SIGN_IN_TARGET
        fields["__EVENTARGUMENT"] = ""

        post_url = urljoin(LOGIN_URL, parser.action or "Login.aspx")
        try:
            async with self._session.post(
                post_url,
                data=fields,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                text = await resp.text()
                if resp.status >= 500:
                    raise CyberiaApiError(f"HTTP {resp.status} from Cyberia")
                if resp.status >= 400:
                    raise CyberiaApiError(f"HTTP {resp.status}: {text[:200]}")
        except aiohttp.ClientError as err:
            raise CyberiaApiError(str(err)) from err
        except asyncio.TimeoutError as err:
            raise CyberiaApiError("Timeout signing in to Cyberia") from err

        lowered = _page_text(text).lower()
        if "your account is not registered yet" in lowered:
            raise CyberiaAuthError("Account is not registered in Cyberia AMC")
        if USERNAME_FIELD in text or PASSWORD_FIELD in text:
            raise CyberiaAuthError("Cyberia login was not accepted")

        self._logged_in = True

    async def _authed_get(self, url: str) -> str:
        if not self._logged_in:
            await self._login()
        text = await self._get(url)
        if USERNAME_FIELD in text or PASSWORD_FIELD in text:
            self._logged_in = False
            await self._login()
            text = await self._get(url)
        return text

    async def _postback(self, url: str, html: str, event_target: str) -> str:
        parser = _AspNetFormParser()
        parser.feed(html)
        if not parser.inputs:
            raise CyberiaApiError("Could not find Cyberia postback form")
        fields = dict(parser.inputs)
        fields["__EVENTTARGET"] = event_target
        fields["__EVENTARGUMENT"] = ""
        try:
            async with self._session.post(
                url,
                data=fields,
                headers={**HEADERS, "Referer": url},
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as resp:
                text = await resp.text()
                if resp.status >= 500:
                    raise CyberiaApiError(f"HTTP {resp.status} from Cyberia")
                if resp.status >= 400:
                    raise CyberiaApiError(f"HTTP {resp.status}: {text[:200]}")
                return text
        except aiohttp.ClientError as err:
            raise CyberiaApiError(str(err)) from err
        except asyncio.TimeoutError as err:
            raise CyberiaApiError(f"Timeout posting {event_target}") from err

    async def async_validate(self) -> dict[str, Any]:
        """Verify credentials."""
        await self._login()
        page = await self._authed_get(PROFILE_URL)
        if USERNAME_FIELD in page or PASSWORD_FIELD in page:
            raise CyberiaAuthError("Cyberia login was not accepted")
        return {"username": self._username}

    async def async_get_account_data(self) -> dict[str, Any]:
        """Fetch and normalize Cyberia account data."""
        accounts_html = await self._authed_get(MY_ACCOUNTS_URL)
        manage_target = _find_manage_target(accounts_html)
        html = (
            await self._postback(MY_ACCOUNTS_URL, accounts_html, manage_target)
            if manage_target
            else accounts_html
        )
        data = _parse_account_data(html, accounts_html)
        data["username"] = self._username
        _LOGGER.debug("Cyberia parsed account data keys: %s", sorted(data))
        return data
