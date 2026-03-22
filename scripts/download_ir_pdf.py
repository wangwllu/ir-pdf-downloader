#!/usr/bin/env python3
"""
IR PDF Downloader — Production Script

Downloads annual reports and quarterly results PDFs from Cloudflare-protected
Investor Relations (IR) websites.

Usage:
    python3 download_ir_pdf.py <url> [url ...]          # Single or multiple URLs
    python3 download_ir_pdf.py --list urls.txt          # Batch from file
    python3 download_ir_pdf.py --search-wb ir.jd.com     # Search Wayback Machine for PDF URLs
    python3 download_ir_pdf.py --verbose <url>           # Debug mode
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' module not found. Install with: pip3 install requests", file=sys.stderr)
    sys.exit(1)

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
MIN_PDF_SIZE = 10_000  # bytes — anything smaller is likely an error page
PDF_MAGIC = b"%PDF-"

# ─── Logging ──────────────────────────────────────────────────────────────────

class Logger:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _print(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")

    def info(self, msg: str):
        self._print("INFO", msg)

    def warn(self, msg: str):
        self._print("WARN", msg)

    def error(self, msg: str):
        self._print("ERROR", msg)

    def debug(self, msg: str):
        if self.verbose:
            self._print("DEBUG", msg)

    def success(self, msg: str):
        self._print("OK", msg)


# ─── PDF Verification ──────────────────────────────────────────────────────────

def is_valid_pdf(data: bytes) -> bool:
    """Check PDF magic bytes at start of file."""
    return data[:5] == PDF_MAGIC


def verify_pdf(path: Path, min_size: int = MIN_PDF_SIZE) -> tuple[bool, str]:
    """
    Verify a downloaded file is a valid PDF.
    Returns (is_valid, reason).
    """
    if not path.exists():
        return False, f"File does not exist: {path}"

    size = path.stat().st_size
    if size < min_size:
        return False, f"File too small ({size:,} bytes), expected >={min_size:,} bytes"

    with open(path, "rb") as f:
        header = f.read(5)

    if header != PDF_MAGIC:
        return False, f"Invalid PDF magic bytes: {header!r} (expected {PDF_MAGIC!r})"

    return True, f"Valid PDF ({size:,} bytes)"


# ─── Filename Extraction ───────────────────────────────────────────────────────

def extract_filename_from_url(url: str) -> str:
    """Extract a meaningful filename from URL path."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    # Try to get the last path segment
    name = os.path.basename(path.rstrip("/"))
    if name.lower().endswith(".pdf"):
        return name

    # If UUID-style path, generate name from domain
    if len(name) > 30:  # UUID-like
        domain = parsed.netloc or "unknown"
        return f"{domain.replace('.', '_')}_report.pdf"

    return name + ".pdf" if name else "download.pdf"


def infer_referer(url: str) -> str:
    """Infer a valid Referer header from the URL."""
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc
    scheme = parsed.scheme or "https"
    # Use the IR root as referer
    return f"{scheme}://{netloc}/"


def infer_output_dir(url: str, output_dir: str | None) -> Path:
    """Determine output directory, optionally creating subdirs by domain."""
    if output_dir:
        base = Path(output_dir)
    else:
        # Default: ./downloads/
        base = Path("downloads")
    base.mkdir(parents=True, exist_ok=True)
    return base


# ─── Core Downloader ───────────────────────────────────────────────────────────

def download_pdf(
    url: str,
    output_path: Path | None = None,
    referer: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
    verbose: bool = False,
    log: Logger | None = None,
) -> Path | None:
    """
    Download a single PDF from an IR website.

    Returns the Path on success, None on failure.
    """
    if log is None:
        log = Logger(verbose=verbose)

    log.debug(f"Downloading: {url}")

    # Build headers
    resolved_referer = referer or infer_referer(url)
    headers = {
        **DEFAULT_HEADERS,
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": resolved_referer,
    }

    log.debug(f"Referer: {resolved_referer}")

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            log.debug(f"Attempt {attempt}/{retries}")
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)

            if resp.status_code == 403:
                last_error = f"HTTP 403 Forbidden — IR site blocked the request. Check Referer header (current: {resolved_referer})."
                log.warn(f"Attempt {attempt}: {last_error}")
            elif resp.status_code == 404:
                last_error = f"HTTP 404 Not Found — PDF URL does not exist: {url}"
                log.error(last_error)
                return None
            elif resp.status_code != 200:
                last_error = f"HTTP {resp.status_code} — unexpected response"
                log.warn(f"Attempt {attempt}: {last_error}")
            else:
                # Success — read content
                data = b"".join(resp.iter_content(chunk_size=65536))

                content_type = resp.headers.get("Content-Type", "")
                log.debug(f"Content-Type: {content_type}, Size: {len(data):,} bytes")

                # Check size
                if len(data) < MIN_PDF_SIZE:
                    last_error = f"Downloaded file too small ({len(data):,} bytes) — likely an error/challenge page"
                    log.warn(f"Attempt {attempt}: {last_error}")
                else:
                    # Determine output path
                    if output_path is None:
                        fname = extract_filename_from_url(url)
                        out_dir = infer_output_dir(url, None)
                        output_path = out_dir / fname

                    output_path.parent.mkdir(parents=True, exist_ok=True)

                    with open(output_path, "wb") as f:
                        f.write(data)

                    # Verify PDF integrity
                    valid, reason = verify_pdf(output_path)
                    if not valid:
                        output_path.unlink(missing_ok=True)
                        last_error = f"PDF verification failed: {reason}"
                        log.warn(f"Attempt {attempt}: {last_error}")
                    else:
                        log.success(f"Downloaded {len(data):,} bytes → {output_path}")
                        return output_path

        except requests.exceptions.Timeout:
            last_error = f"Request timed out after {timeout}s"
            log.warn(f"Attempt {attempt}: {last_error}")
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
            log.warn(f"Attempt {attempt}: {last_error}")
        except requests.exceptions.RequestException as e:
            last_error = f"Request failed: {e}"
            log.warn(f"Attempt {attempt}: {last_error}")

        if attempt < retries:
            log.debug(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    log.error(f"All {retries} attempts failed. Last error: {last_error}")
    return None


# ─── Wayback Machine Search ─────────────────────────────────────────────────────

def search_wayback(domain: str, verbose: bool = False, log: Logger | None = None) -> list[str]:
    """
    Search Wayback Machine CDX API for PDF URLs on a given domain.
    Returns list of PDF URLs found.
    """
    if log is None:
        log = Logger(verbose=verbose)

    log.info(f"Searching Wayback Machine for PDFs on: {domain}")

    # Encode domain for CDX query
    # Match URLs like ir.jd.com/static-files/*.pdf
    wildcard = f"*{domain}*/static-files/*.pdf"
    encoded = urllib.parse.quote(wildcard)

    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={encoded}"
        f"&output=json"
        f"&limit=50"
        f"&fl=original,statuscode,mimetype"
        f"&filter=statuscode:200"
        f"&filter=mimetype:application/pdf"
    )

    log.debug(f"CDX URL: {cdx_url}")

    try:
        resp = requests.get(
            cdx_url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        log.error(f"Wayback Machine CDX request failed: {e}")
        return []

    try:
        data = resp.json()
    except json.JSONDecodeError:
        log.error("Failed to parse Wayback Machine CDX response (not JSON)")
        return []

    if not data or len(data) < 2:
        log.warn(f"No PDF snapshots found for {domain}")
        return []

    # First row is header: ["original", "statuscode", "mimetype"]
    header = data[0]
    rows = data[1:]
    log.info(f"Found {len(rows)} PDF snapshot(s) in Wayback Machine")

    urls = []
    for row in rows:
        if len(row) >= 1:
            url = row[0]
            urls.append(url)
            log.debug(f"  Found: {url}")

    return urls


# ─── Batch Download ─────────────────────────────────────────────────────────────

def batch_download(
    urls: list[str],
    output_dir: str | None = None,
    referer: str | None = None,
    verbose: bool = False,
    delay: float = 1.0,
) -> dict[str, Path | None]:
    """
    Download multiple PDFs in sequence.

    Returns a dict mapping url -> Path (or None if failed).
    """
    log = Logger(verbose=verbose)
    results = {}

    for i, url in enumerate(urls, 1):
        log.info(f"[{i}/{len(urls)}] {url}")
        out_dir = infer_output_dir(url, output_dir)
        path = download_pdf(
            url,
            output_path=None,
            referer=referer,
            verbose=verbose,
            log=log,
        )
        results[url] = path
        if delay > 0 and i < len(urls):
            log.debug(f"Waiting {delay}s before next download...")
            time.sleep(delay)

    succeeded = sum(1 for v in results.values() if v is not None)
    log.info(f"Batch complete: {succeeded}/{len(urls)} succeeded")
    return results


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="download_ir_pdf.py",
        description="Download IR PDFs (annual reports, quarterly results) from Cloudflare-protected websites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download a single PDF
  python3 download_ir_pdf.py "https://ir.jd.com/static-files/..."

  # Download with verbose output
  python3 download_ir_pdf.py --verbose "https://ir.jd.com/static-files/..."

  # Batch from a text file (one URL per line)
  python3 download_ir_pdf.py --list urls.txt

  # Search Wayback Machine for PDFs on ir.jd.com
  python3 download_ir_pdf.py --search-wb ir.jd.com

  # Batch from Wayback Machine search
  python3 download_ir_pdf.py --search-wb ir.jd.com --download-found
        """,
    )

    parser.add_argument("urls", nargs="*", help="One or more PDF URLs to download")
    parser.add_argument("--list", "-l", metavar="FILE",
                        help="Path to a text file with URLs (one per line)")
    parser.add_argument("--search-wb", "-w", metavar="DOMAIN",
                        help="Search Wayback Machine for PDF URLs on this domain (e.g. ir.jd.com)")
    parser.add_argument("--download-found", "-d", action="store_true",
                        help="Download all PDFs found by --search-wb")
    parser.add_argument("--output", "-o", metavar="DIR",
                        help="Output directory (default: ./downloads/)")
    parser.add_argument("--referer", "-r", metavar="URL",
                        help="Custom Referer header (default: inferred from PDF URL)")
    parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=MAX_RETRIES,
                        help=f"Number of retry attempts (default: {MAX_RETRIES})")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between downloads in batch mode (default: 1.0s)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose debug output")

    return parser.parse_args()


def read_url_list(path: str) -> list[str]:
    """Read URLs from a file, one per line, skipping blanks and comments."""
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    args = parse_args()
    log = Logger(verbose=args.verbose)

    # ── Wayback Machine search mode ──────────────────────────────────────────
    if args.search_wb:
        domain = args.search_wb
        if not re.match(r"^[a-zA-Z0-9.\-]+$", domain):
            log.error(f"Invalid domain format: {domain}")
            sys.exit(1)

        pdf_urls = search_wayback(domain, verbose=args.verbose, log=log)

        if not pdf_urls:
            log.warn("No PDFs found.")
            sys.exit(0)

        print("\n--- Found PDF URLs ---")
        for url in pdf_urls:
            print(url)

        if args.download_found:
            print(f"\n--- Downloading {len(pdf_urls)} PDF(s) ---\n")
            # Infer referer for batch
            wb_referer = f"https://{domain}/"
            batch_download(
                pdf_urls,
                output_dir=args.output,
                referer=wb_referer,
                verbose=args.verbose,
                delay=args.delay,
            )
        else:
            print(f"\n(Use --download-found to download all {len(pdf_urls)} PDFs)")

        return

    # ── Collect URLs ──────────────────────────────────────────────────────────
    urls = []
    if args.urls:
        urls = list(args.urls)
    elif args.list:
        path = Path(args.list)
        if not path.exists():
            log.error(f"URL list file not found: {path}")
            sys.exit(1)
        urls = read_url_list(str(path))
        log.info(f"Loaded {len(urls)} URL(s) from {path}")
    else:
        log.error("No URLs provided. Use positional args, --list FILE, or --search-wb DOMAIN.")
        parser.print_help()
        sys.exit(1)

    if not urls:
        log.error("No URLs to download.")
        sys.exit(1)

    # ── Download ──────────────────────────────────────────────────────────────
    if len(urls) == 1:
        log.info(f"Downloading: {urls[0]}")
        result = download_pdf(
            urls[0],
            output_path=None,
            referer=args.referer,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose,
            log=log,
        )
        if result is None:
            sys.exit(1)
    else:
        results = batch_download(
            urls,
            output_dir=args.output,
            referer=args.referer,
            verbose=args.verbose,
            delay=args.delay,
        )
        failed = [url for url, path in results.items() if path is None]
        if failed:
            log.warn(f"{len(failed)} download(s) failed:")
            for url in failed:
                log.warn(f"  FAILED: {url}")
            sys.exit(1)


if __name__ == "__main__":
    main()
