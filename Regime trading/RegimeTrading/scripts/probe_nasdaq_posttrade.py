from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from RegimeTrading.core.paths import DATA_DIR


POST_TRADE_PAGE = "https://tradereports.nasdaq.com/shares/trade-reports/post-trade"
FILE_PREFIX = "NordicEquity-posttrade-"
PROBE_DIR = DATA_DIR / "nasdaq_raw" / "probe"
PAGE_TIMEOUT_SECONDS = 75
DOWNLOAD_TIMEOUT_SECONDS = 120
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Nasdaq Nordic delayed post-trade CSV delivery."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless. Visible Chrome is the safer default.",
    )
    parser.add_argument(
        "--profile-latest",
        action="store_true",
        help=(
            "Profile the newest already-downloaded Nasdaq CSV without "
            "opening a browser or downloading another file."
        ),
    )
    parser.add_argument(
        "--profile-file",
        type=Path,
        help="Profile a specific already-downloaded Nasdaq CSV file.",
    )
    return parser.parse_args()


def safe_filename_from_url(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    if not name or "." not in name:
        name = f"{fallback}.csv"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def request_page(url: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.geturl()


def extract_report_candidates(page_html: str, base_url: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    anchor_pattern = re.compile(
        r"<a\b[^>]*?href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    tag_pattern = re.compile(r"<[^>]+>")
    identifier_pattern = re.compile(
        rf"{re.escape(FILE_PREFIX)}\d{{4}}-\d{{2}}-\d{{2}}T\d{{4}}",
        flags=re.IGNORECASE,
    )

    for match in anchor_pattern.finditer(page_html):
        href = html.unescape(match.group("href")).strip()
        body_text = html.unescape(tag_pattern.sub(" ", match.group("body")))
        combined = f"{body_text} {href}"
        identifier_match = identifier_pattern.search(combined)
        if not identifier_match:
            continue
        identifier = identifier_match.group(0)
        absolute_url = urljoin(base_url, href)
        key = (identifier, absolute_url)
        if key not in seen:
            candidates.append(key)
            seen.add(key)

    return sorted(candidates, key=lambda item: item[0], reverse=True)


def download_url(
    url: str,
    destination_dir: Path,
    identifier: str,
    cookie_header: str = "",
    referer: str = POST_TRADE_PAGE,
) -> Path:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Referer": referer,
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
        disposition = response.headers.get("Content-Disposition", "")

    if b"<html" in content[:1000].lower() and "csv" not in content_type.lower():
        raise RuntimeError(
            "The discovered URL returned HTML instead of a CSV download."
        )

    disposition_match = re.search(
        r"filename\*?=(?:UTF-8''|[\"])?([^;\"]+)",
        disposition,
        flags=re.IGNORECASE,
    )
    if disposition_match:
        filename = Path(disposition_match.group(1).strip()).name
    else:
        filename = safe_filename_from_url(final_url, identifier)

    destination = destination_dir / filename
    destination.write_bytes(content)
    return destination


def try_direct_http_probe(destination_dir: Path) -> tuple[Path | None, str]:
    print("\nTrying direct HTTP discovery first...")
    try:
        page_html, final_url = request_page(POST_TRADE_PAGE)
    except Exception as exc:
        return None, f"Direct page request failed: {type(exc).__name__}: {exc!r}"

    (destination_dir / "nasdaq_probe_http_page.html").write_text(
        page_html,
        encoding="utf-8",
    )
    candidates = extract_report_candidates(page_html, final_url)
    if not candidates:
        return None, (
            "Direct page request succeeded, but no report links were present "
            "in the static HTML. Falling back to visible Chrome."
        )

    identifier, url = candidates[0]
    print(f"Direct discovery selected: {identifier}")
    try:
        path = download_url(url, destination_dir, identifier)
    except Exception as exc:
        return None, (
            f"A report URL was discovered, but direct download failed: "
            f"{type(exc).__name__}: {exc!r}. Falling back to Chrome."
        )
    return path, "Direct HTTP download succeeded."


def build_driver(download_dir: Path, headless: bool) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_dir.resolve()),
            },
        )
    except Exception:
        pass
    return driver


def try_accept_cookies(driver: webdriver.Chrome) -> None:
    labels = [
        "Accept all",
        "Accept All",
        "Allow all",
        "I accept",
        "Accept",
        "Godkänn alla",
        "Acceptera alla",
    ]
    for label in labels:
        xpath = (
            "//button[contains(translate(normalize-space(.), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ', "
            "'abcdefghijklmnopqrstuvwxyzåäö'), "
            f"'{label.lower()}')]"
        )
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            for button in buttons:
                if button.is_displayed() and button.is_enabled():
                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(1)
                    return
        except Exception:
            continue


def newest_download(download_dir: Path, existing: set[Path]) -> Path | None:
    ignored_names = {
        "nasdaq_probe_page.html",
        "nasdaq_probe_page.png",
        "nasdaq_probe_http_page.html",
    }
    candidates = [
        path
        for path in download_dir.iterdir()
        if path.is_file()
        and path not in existing
        and path.name not in ignored_names
        and not path.name.endswith((".crdownload", ".tmp", ".part"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def wait_for_download(download_dir: Path, existing: set[Path]) -> Path:
    deadline = time.time() + DOWNLOAD_TIMEOUT_SECONDS
    while time.time() < deadline:
        partials = list(download_dir.glob("*.crdownload"))
        downloaded = newest_download(download_dir, existing)
        if downloaded is not None and not partials and downloaded.stat().st_size > 0:
            return downloaded
        time.sleep(0.5)
    raise TimeoutError(
        f"No completed file appeared in {download_dir} within "
        f"{DOWNLOAD_TIMEOUT_SECONDS} seconds."
    )


def browser_cookie_header(driver: webdriver.Chrome) -> str:
    cookies = driver.get_cookies()
    return "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name")
    )


def javascript_report_snapshot(driver: webdriver.Chrome) -> list[dict]:
    script = r"""
        const prefix = arguments[0].toLowerCase();
        const selector = 'a,button,[role="button"],[onclick],td,span,div';
        const results = [];
        for (const element of document.querySelectorAll(selector)) {
            const text = (element.innerText || element.textContent || '').trim();
            const href = element.href || element.getAttribute('href') || '';
            const title = element.getAttribute('title') || '';
            const value = element.getAttribute('value') || '';
            const combined = `${text} ${href} ${title} ${value}`;
            if (!combined.toLowerCase().includes(prefix)) continue;
            results.push({
                text: text.slice(0, 500),
                href: href,
                title: title,
                value: value,
                tag: element.tagName || '',
                html: (element.outerHTML || '').slice(0, 1000)
            });
        }
        return results;
    """
    result = driver.execute_script(script, FILE_PREFIX)
    return result if isinstance(result, list) else []


def snapshot_identifier(item: dict) -> str:
    combined = " ".join(
        str(item.get(key, ""))
        for key in ["text", "href", "title", "value", "html"]
    )
    match = re.search(
        rf"{re.escape(FILE_PREFIX)}\d{{4}}-\d{{2}}-\d{{2}}T\d{{4}}",
        combined,
        flags=re.IGNORECASE,
    )
    return match.group(0) if match else ""


def collect_browser_report_candidates(
    driver: webdriver.Chrome,
    destination_dir: Path,
) -> list[tuple[str, str]]:
    # page_source is a single DOM snapshot and therefore cannot produce stale
    # Selenium element references. Try ordinary anchors first.
    candidates = extract_report_candidates(driver.page_source, driver.current_url)

    snapshots = javascript_report_snapshot(driver)
    (destination_dir / "nasdaq_probe_dom_candidates.json").write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    seen = set(candidates)
    for item in snapshots:
        identifier = snapshot_identifier(item)
        if not identifier:
            continue
        href = str(item.get("href", "") or "").strip()
        absolute_url = urljoin(driver.current_url, href) if href else ""
        candidate = (identifier, absolute_url)
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    return sorted(candidates, key=lambda item: item[0], reverse=True)


def latest_report_descriptor(
    driver: webdriver.Chrome,
    destination_dir: Path,
) -> tuple[str, str]:
    def snapshot_available(current) -> bool:
        try:
            return bool(collect_browser_report_candidates(current, destination_dir))
        except Exception:
            return False

    WebDriverWait(driver, PAGE_TIMEOUT_SECONDS).until(snapshot_available)
    candidates = collect_browser_report_candidates(driver, destination_dir)
    if not candidates:
        raise RuntimeError(
            "The Nasdaq page loaded, but no Nordic equity report candidates "
            "were found in the rendered DOM."
        )
    return candidates[0]


def click_report_by_identifier(
    driver: webdriver.Chrome,
    identifier: str,
) -> dict:
    # Locate and click within one JavaScript execution. Nasdaq refreshes the
    # report list frequently; returning WebElement objects to Python can make
    # them stale before the next Selenium command.
    script = r"""
        const identifier = arguments[0].toLowerCase();
        const selector = 'a,button,[role="button"],[onclick],td,span,div';
        const matches = Array.from(document.querySelectorAll(selector))
            .filter(element => {
                const text = (element.innerText || element.textContent || '').trim();
                const href = element.href || element.getAttribute('href') || '';
                const title = element.getAttribute('title') || '';
                return `${text} ${href} ${title}`.toLowerCase().includes(identifier);
            })
            .sort((left, right) => {
                const l = (left.innerText || left.textContent || '').length;
                const r = (right.innerText || right.textContent || '').length;
                return l - r;
            });

        if (!matches.length) {
            return {clicked: false, reason: 'identifier_not_found'};
        }

        const found = matches[0];
        const target = found.closest('a,button,[role="button"],[onclick]')
            || found.querySelector('a,button,[role="button"],[onclick]')
            || found;
        target.scrollIntoView({block: 'center'});
        target.click();
        return {
            clicked: true,
            tag: target.tagName || '',
            href: target.href || target.getAttribute('href') || '',
            text: (target.innerText || target.textContent || '').trim().slice(0, 300)
        };
    """
    result = driver.execute_script(script, identifier)
    return result if isinstance(result, dict) else {"clicked": bool(result)}


def browser_diagnostics(driver: webdriver.Chrome, destination_dir: Path) -> str:
    details: list[str] = []
    try:
        details.append(f"Page title: {driver.title!r}")
        details.append(f"Current URL: {driver.current_url}")
        body = driver.find_element(By.TAG_NAME, "body").text.strip()
        compact_body = re.sub(r"\s+", " ", body)
        details.append(f"Visible body preview: {compact_body[:500]!r}")
        details.append(f"Page source characters: {len(driver.page_source)}")
        try:
            snapshots = javascript_report_snapshot(driver)
            details.append(f"Rendered report candidate elements: {len(snapshots)}")
        except Exception as snapshot_exc:
            details.append(f"Could not snapshot report candidates: {snapshot_exc!r}")
        (destination_dir / "nasdaq_probe_page.html").write_text(
            driver.page_source,
            encoding="utf-8",
        )
        driver.save_screenshot(str(destination_dir / "nasdaq_probe_page.png"))
    except Exception as diagnostic_exc:
        details.append(
            f"Could not capture full browser diagnostics: {diagnostic_exc!r}"
        )
    return "\n".join(details)


def try_browser_probe(
    destination_dir: Path,
    existing: set[Path],
    headless: bool,
) -> Path:
    mode = "headless" if headless else "visible"
    print(f"\nTrying {mode} Chrome discovery...")
    if not headless:
        print(
            "A Chrome window will open briefly. Do not close it. If a cookie "
            "banner appears, the script will try to accept it automatically."
        )

    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver(destination_dir, headless=headless)
        driver.get(POST_TRADE_PAGE)
        WebDriverWait(driver, PAGE_TIMEOUT_SECONDS).until(
            lambda current: current.execute_script("return document.readyState")
            in {"interactive", "complete"}
        )
        try_accept_cookies(driver)
        identifier, href = latest_report_descriptor(driver, destination_dir)
        print(f"Browser discovery selected: {identifier}")

        if href and not href.lower().startswith(("javascript:", "blob:")):
            try:
                path = download_url(
                    url=href,
                    destination_dir=destination_dir,
                    identifier=identifier,
                    cookie_header=browser_cookie_header(driver),
                    referer=driver.current_url,
                )
                print("Downloaded the rendered report URL directly.")
                return path
            except Exception as direct_exc:
                print(
                    "Rendered report URL could not be downloaded directly; "
                    "falling back to an atomic browser click."
                )
                print(
                    f"Direct rendered-link error: "
                    f"{type(direct_exc).__name__}: {direct_exc!r}"
                )

        click_result = click_report_by_identifier(driver, identifier)
        if not click_result.get("clicked"):
            raise RuntimeError(
                "The latest report was discovered, but the browser could not "
                f"click it atomically: {click_result}"
            )
        print(f"Atomic click result: {click_result}")
        return wait_for_download(destination_dir, existing)
    except Exception as exc:
        diagnostic_text = ""
        if driver is not None:
            diagnostic_text = browser_diagnostics(driver, destination_dir)
        raise RuntimeError(
            "Browser probe failed.\n"
            f"Exception type: {type(exc).__name__}\n"
            f"Exception repr: {exc!r}\n"
            f"{diagnostic_text}"
        ) from exc
    finally:
        if driver is not None:
            driver.quit()


def read_csv_flexibly(path: Path) -> tuple[pd.DataFrame, str, str, int]:
    """Read Nasdaq CSV files, including Excel-style ``sep=;`` declarations.

    Nasdaq currently places a separator declaration on the first line. That
    line is metadata rather than the table header and must be skipped before
    pandas parses the file.
    """
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            lines = text.splitlines()

            delimiter = ""
            skiprows = 0
            first_content_index = next(
                (index for index, line in enumerate(lines) if line.strip()),
                None,
            )

            if first_content_index is not None:
                declaration = (
                    lines[first_content_index]
                    .lstrip("\ufeff")
                    .strip()
                )

                # Nasdaq currently writes the Excel-style declaration as
                # either sep=; or "sep=;". Strip one matching pair of
                # surrounding quotes before checking it.
                if (
                    len(declaration) >= 2
                    and declaration[0] == declaration[-1]
                    and declaration[0] in {"\"", "'"}
                ):
                    declaration = declaration[1:-1].strip()

                separator_match = re.fullmatch(
                    r"sep\s*=\s*(.)",
                    declaration,
                    flags=re.IGNORECASE,
                )
                if separator_match:
                    delimiter = separator_match.group(1)
                    skiprows = first_content_index + 1

            if not delimiter:
                sample = "\n".join(lines[skiprows:])[:20000]
                try:
                    delimiter = csv.Sniffer().sniff(
                        sample,
                        delimiters=[",", ";", "\t", "|"],
                    ).delimiter
                except csv.Error:
                    delimiter = ";" if sample.count(";") > sample.count(",") else ","

            dataframe = pd.read_csv(
                path,
                encoding=encoding,
                sep=delimiter,
                skiprows=skiprows,
                dtype=str,
                keep_default_na=False,
                engine="python",
            )
            return dataframe, encoding, delimiter, skiprows
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Could not parse downloaded file: {path}") from last_error

def print_file_profile(path: Path) -> None:
    dataframe, encoding, delimiter, skipped_rows = read_csv_flexibly(path)
    delimiter_name = "TAB" if delimiter == "\t" else delimiter

    print("\n=== DOWNLOADED FILE PROFILE ===")
    print(f"File       : {path}")
    print(f"Size bytes : {path.stat().st_size}")
    print(f"Encoding   : {encoding}")
    print(f"Delimiter  : {delimiter_name}")
    print(f"Skipped metadata rows: {skipped_rows}")
    print(f"Rows       : {len(dataframe)}")
    print(f"Columns    : {len(dataframe.columns)}")

    print("\nColumn names:")
    for index, column in enumerate(dataframe.columns, start=1):
        print(f"{index:02d}. {column}")

    if len(dataframe.columns) <= 1:
        print("\nWarning: the file still parsed as one column.")
        print("First eight raw lines:")
        raw_lines = path.read_text(encoding=encoding, errors="replace").splitlines()
        for raw_index, raw_line in enumerate(raw_lines[:8], start=1):
            print(f"{raw_index:02d}: {raw_line[:500]}")

    print("\nFirst three rows:")
    if dataframe.empty:
        print("The downloaded CSV has no data rows.")
    else:
        with pd.option_context(
            "display.max_columns",
            None,
            "display.width",
            240,
            "display.max_colwidth",
            60,
        ):
            print(dataframe.head(3).to_string(index=False))


def main() -> None:
    args = parse_args()
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== PROBE NASDAQ NORDIC POST-TRADE DATA V5 ===")
    print(f"Source page : {POST_TRADE_PAGE}")
    print(f"Download dir: {PROBE_DIR}")
    print("This probe does not modify any SQLite database or research output.")

    if args.profile_file is not None:
        profile_path = args.profile_file.expanduser().resolve()
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile file not found: {profile_path}")
        print("\nProfiling an existing file only. No browser will be opened.")
        print_file_profile(profile_path)
        return

    if args.profile_latest:
        existing_csvs = sorted(
            PROBE_DIR.glob(f"{FILE_PREFIX}*.csv"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not existing_csvs:
            raise FileNotFoundError(
                f"No existing Nasdaq CSV files found in {PROBE_DIR}"
            )
        print("\nProfiling the newest existing file only. No browser will be opened.")
        print_file_profile(existing_csvs[0])
        return

    existing = set(PROBE_DIR.iterdir())

    downloaded, direct_message = try_direct_http_probe(PROBE_DIR)
    print(direct_message)

    if downloaded is None:
        try:
            downloaded = try_browser_probe(
                destination_dir=PROBE_DIR,
                existing=existing,
                headless=args.headless,
            )
        except (RuntimeError, TimeoutException, TimeoutError, WebDriverException) as exc:
            print("\nNasdaq probe failed.")
            print(str(exc))
            print(
                "Diagnostic HTML and screenshot were saved in the probe "
                "directory when possible."
            )
            sys.exit(1)

    print_file_profile(downloaded)
    print("\nProbe complete. No database was changed.")
    print(
        "Share the console output from this command before enabling the full "
        "daily collector and five-minute aggregation."
    )


if __name__ == "__main__":
    main()
