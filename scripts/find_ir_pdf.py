#!/usr/bin/env python3
"""
find_ir_pdf.py — Find IR PDF URLs for any company

Searches multiple sources to discover annual report / quarterly PDF URLs:
  1. Wayback Machine CDX API (domain-based PDF discovery)
  2. SEC EDGAR (6-K / 20-F filing PDF attachments)
  3. Known IR domain patterns

Usage:
    python3 find_ir_pdf.py --company "Alibaba"                    # Search by company name
    python3 find_ir_pdf.py --domain ir.baidu.com                  # Search by IR domain
    python3 find_ir_pdf.py --domain ir.alibabagroup.com --year 2024
    python3 find_ir_pdf.py --company "Baidu" --output results.json

Output: list of found PDF URLs with dates and types, written to stdout (or JSON file).
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime
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

DEFAULT_TIMEOUT = 20
HEAD_TIMEOUT = 10

# ─── Known IR Domain Map ──────────────────────────────────────────────────────

COMPANY_IR_DOMAINS = {
    # company name aliases -> IR domain
    "jd": "ir.jd.com",
    "jd.com": "ir.jd.com",
    "alibaba": "ir.alibabagroup.com",
    "alibabagroup": "ir.alibabagroup.com",
    "baidu": "ir.baidu.com",
    "tencent": "ir.tencent.com",
    "pdd": "ir.pddgroup.com",
    "pddgroup": "ir.pddgroup.com",
    "netease": "ir.163.com",
    "163": "ir.163.com",
    "meituan": "ir.meituan.com",
    "xiaomi": "ir.xiaomi.com",
    "nio": "ir.nio.cn",
    "li auto": "ir.lixiang.com",
    "lixiang": "ir.lixiang.com",
    "bilibili": "ir.bilibili.com",
    "trip.com": "ir.trip.com",
    "ke holdings": "ir.ke.com",
    "ke.com": "ir.ke.com",
    "xiao": "ir.xiaomi.com",
    "xpeng": "ir.xpeng.com",
    "bytedance": "ir.bytedance.com",
}

# SEC CIK map for Chinese companies (commonly traded in US)
COMPANY_CIK_MAP = {
    "jd": "0001547592",
    "alibaba": "0001577552",
    "baidu": "0001329099",
    "tencent": "0001329091",  # 00700.HK ADR
    "pdd": "0001737406",
    "netease": "0001329091",
    "meituan": "0001737456",
    "xiaomi": "0001780184",
    "nio": "0001737646",
    "bilibili": "0001727548",
    "trip.com": "0001775312",
    "ke holdings": "0001820305",
}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def infer_ir_domain(company_or_domain: str) -> str | None:
    """Try to resolve a company name or partial domain to a full IR domain."""
    key = company_or_domain.lower().strip()

    # Direct match
    if key in COMPANY_IR_DOMAINS:
        return COMPANY_IR_DOMAINS[key]

    # Try adding ir. prefix
    if not key.startswith("ir."):
        candidate = f"ir.{key}"
        if candidate in [v for v in COMPANY_IR_DOMAINS.values()]:
            return candidate
        # Try common TLDs
        for tld in [".com", ".cn", ".io"]:
            candidate2 = f"ir.{key}{tld}"
            if candidate2 in [v for v in COMPANY_IR_DOMAINS.values()]:
                return candidate2

    # Return as-is if it looks like a domain
    if "." in key:
        return key

    return None


def infer_cik(company: str) -> str | None:
    """Try to find SEC CIK for a company name."""
    key = company.lower().strip()
    return COMPANY_CIK_MAP.get(key)


# ─── Source 1: Wayback Machine CDX ─────────────────────────────────────────────

def find_via_wayback(domain: str, year: int | None = None, limit: int = 100) -> list[dict]:
    """
    Search Wayback Machine CDX for PDF URLs under a domain.
    Returns list of {url, timestamp, source}.
    """
    log(f"Searching Wayback Machine for PDFs under: {domain}", "INFO")

    results = []

    # Try different URL patterns to maximize coverage
    patterns = [
        f"*{domain}*/static-files/*.pdf",
        f"*{domain}*/assets/pdf/*.pdf",
        f"*{domain}*/en-us/assets/pdf/*.pdf",
        f"*{domain}*/en-US/assets/pdf/*.pdf",
        f"*{domain}*/press/*.pdf",
        f"*{domain}*/annual-report/*.pdf",
        f"*{domain}*/annual-reports/*.pdf",
        f"*{domain}*/*.pdf",
    ]

    seen = set()

    for pattern in patterns:
        encoded = urllib.parse.quote(pattern, safe="")
        cdx_url = (
            f"https://web.archive.org/cdx/search/cdx"
            f"?url={encoded}"
            f"&output=json"
            f"&limit={limit}"
            f"&fl=original,statuscode,mimetype,timestamp"
            f"&filter=statuscode:200"
            f"&filter=mimetype:application/pdf"
            f"&collapse=original"
        )

        try:
            resp = requests.get(
                cdx_url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data and len(data) > 1:
                # header row
                rows = data[1:]
                for row in rows:
                    if len(row) >= 4:
                        url, status, mimetype, timestamp = row[0], row[1], row[2], row[3]
                        if url in seen:
                            continue
                        seen.add(url)

                        # Filter by year
                        if year:
                            ts_year = timestamp[:4]
                            if str(year) != ts_year:
                                continue

                        results.append({
                            "url": url,
                            "timestamp": timestamp,
                            "year": timestamp[:4] if timestamp else None,
                            "source": "wayback",
                            "domain": domain,
                        })
        except Exception as e:
            log(f"  CDX pattern '{pattern}' failed: {e}", "WARN")

    log(f"  Wayback Machine: found {len(results)} PDF(s)", "INFO")
    return results


# ─── Source 2: SEC EDGAR ───────────────────────────────────────────────────────

def find_via_edgar(cik: str, year: int | None = None, limit: int = 20) -> list[dict]:
    """
    Search SEC EDGAR for 20-F (annual) and 6-K (quarterly) filing PDF attachments.
    Returns list of {url, filing_type, filing_date, form, source}.
    """
    log(f"Searching SEC EDGAR for CIK: {cik}", "INFO")

    results = []

    try:
        # Get company facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        resp = requests.get(
            facts_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        facts = resp.json()

        # Get company name
        entity_name = facts.get("entityName", cik)

        # Find 20-F and 6-K filings
        forms_url = f"https://data.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=20-F&dateb=&owner=include&count={limit}"
        resp2 = requests.get(
            forms_url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )

        if resp2.status_code == 200:
            html = resp2.text
            # Parse filing rows - find PDF links
            # 20-F filings are annual reports
            pdf_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.pdf)"', html)
            dates = re.findall(r'(\d{4}-\d{2}-\d{2})', html)

            for i, pdf_link in enumerate(pdf_links[:limit]):
                if not pdf_link.endswith(".pdf"):
                    continue
                full_url = f"https://www.sec.gov{pdf_link}"
                filing_date = dates[i] if i < len(dates) else None
                filing_year = filing_date[:4] if filing_date else None

                if year and filing_year and str(year) != filing_year:
                    continue

                results.append({
                    "url": full_url,
                    "form": "20-F",
                    "filing_date": filing_date,
                    "year": filing_year,
                    "source": "sec_edgar",
                    "company": entity_name,
                })

        # Also get 6-K filings
        edgar_search = f"https://efts.sec.gov/LATEST/search-index?q=%22CIK{cik}%22&dateRange=custom&startdt={year or 2020}-01-01&enddt={year or 2025}-12-31&forms=6-K"
        # Try the EDGAR full-text search
        edgar_url = f"https://efts.sec.gov/LATEST/search-index?q=%22CIK{cik}%22&forms=6-K"

        resp3 = requests.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=6-K&dateb=&owner=include&count={limit}",
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )

        if resp3.status_code == 200:
            html = resp3.text
            pdf_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.pdf)"', html)
            dates = re.findall(r'(\d{4}-\d{2}-\d{2})', html)
            for i, pdf_link in enumerate(pdf_links[:limit]):
                if not pdf_link.endswith(".pdf"):
                    continue
                full_url = f"https://www.sec.gov{pdf_link}"
                filing_date = dates[i] if i < len(dates) else None
                filing_year = filing_date[:4] if filing_date else None

                if year and filing_year and str(year) != filing_year:
                    continue

                results.append({
                    "url": full_url,
                    "form": "6-K",
                    "filing_date": filing_date,
                    "year": filing_year,
                    "source": "sec_edgar",
                    "company": entity_name,
                })

    except Exception as e:
        log(f"  SEC EDGAR search failed: {e}", "WARN")

    log(f"  SEC EDGAR: found {len(results)} PDF(s)", "INFO")
    return results


# ─── Source 3: Direct IR Domain Probe ────────────────────────────────────────

def probe_ir_direct(domain: str, year: int | None = None) -> list[dict]:
    """
    Try common IR PDF URL patterns directly on the domain.
    Returns list of {url, year, source}.
    """
    log(f"Probing direct IR URLs on: {domain}", "INFO")

    results = []

    # Common annual report URL patterns
    url_patterns = [
        # Alibaba-style
        f"https://{domain}/en-US/assets/pdf/annual-report/{year or '2024'}-Annual-Report.pdf",
        f"https://{domain}/en-us/assets/pdf/annual-report/{year or '2024'}-Annual-Report.pdf",
        f"https://{domain}/assets/pdf/annual-report/{year or '2024'}-Annual-Report.pdf",
        # Generic
        f"https://{domain}/annual-report-{year or '2024'}.pdf",
        f"https://{domain}/annual-report-{year or '2023'}.pdf",
        f"https://{domain}/annual-reports/{year or '2024'}.pdf",
        f"https://{domain}/en/annual-report-{year or '2024'}.pdf",
        f"https://{domain}/ir/annual-report-{year or '2024'}.pdf",
    ]

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"https://{domain}/",
    }

    for url in url_patterns:
        try:
            resp = requests.head(url, headers=headers, timeout=HEAD_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "")
                if "pdf" in ct.lower() or url.endswith(".pdf"):
                    # Try get to verify it's a PDF
                    resp2 = requests.get(url, headers=headers, timeout=10)
                    if resp2.status_code == 200 and resp2.content[:5] == b"%PDF-":
                        results.append({
                            "url": url,
                            "year": year,
                            "source": "direct_probe",
                            "domain": domain,
                        })
        except Exception:
            pass

    log(f"  Direct probe: found {len(results)} accessible PDF(s)", "INFO")
    return results


# ─── Main Search ───────────────────────────────────────────────────────────────

def find_pdfs(
    company: str | None = None,
    domain: str | None = None,
    year: int | None = None,
    sources: list[str] | None = None,
) -> list[dict]:
    """
    Find IR PDF URLs from all requested sources.
    Returns deduplicated list of result dicts.
    """
    if sources is None:
        sources = ["wayback", "edgar", "direct"]

    # Resolve domain
    if not domain and company:
        domain = infer_ir_domain(company)

    all_results = []
    seen_urls = set()

    def dedup_add(results: list[dict]):
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)

    # Source 1: Wayback Machine
    if domain and "wayback" in sources:
        wb_results = find_via_wayback(domain, year=year)
        dedup_add(wb_results)

    # Source 2: SEC EDGAR
    if company or domain:
        cik = infer_cik(company) if company else None
        if not cik and domain:
            # Try to map domain to company name
            for name, d in COMPANY_IR_DOMAINS.items():
                if d == domain:
                    cik = COMPANY_CIK_MAP.get(name)
                    break
        if cik and "edgar" in sources:
            edgar_results = find_via_edgar(cik, year=year)
            dedup_add(edgar_results)

    # Source 3: Direct probe
    if domain and "direct" in sources:
        direct_results = probe_ir_direct(domain, year=year)
        dedup_add(direct_results)

    return all_results


def print_results(results: list[dict], format: str = "text"):
    """Print results in text or JSON format."""
    if format == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    if not results:
        print("No PDFs found.")
        return

    print(f"\nFound {len(results)} PDF URL(s):\n")
    print(f"{'#':<4} {'Year':<6} {'Form':<8} {'Source':<12}  URL")
    print("-" * 100)

    for i, r in enumerate(results, 1):
        year = r.get("year", "") or ""
        form = r.get("form", r.get("type", "PDF")) or "PDF"
        source = r.get("source", "")
        url = r.get("url", "")
        print(f"{i:<4} {year:<6} {form:<8} {source:<12}  {url}")

    print()


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="find_ir_pdf.py",
        description="Find IR PDF URLs (annual reports, quarterly results) for any company "
                    "by searching Wayback Machine, SEC EDGAR, and direct IR domain probes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Find PDFs for a company by name (uses known IR domain mapping)
  python3 find_ir_pdf.py --company Alibaba

  # Find PDFs for a specific IR domain
  python3 find_ir_pdf.py --domain ir.baidu.com

  # Find PDFs from a specific year
  python3 find_ir_pdf.py --company Baidu --year 2024

  # Output as JSON for automation
  python3 find_ir_pdf.py --domain ir.alibabagroup.com --year 2024 --format json

  # Only search Wayback Machine (fastest)
  python3 find_ir_pdf.py --domain ir.jd.com --sources wayback
        """,
    )

    parser.add_argument("--company", "-c", metavar="NAME",
                        help="Company name or ticker (e.g. Alibaba, JD, Baidu)")
    parser.add_argument("--domain", "-d", metavar="DOMAIN",
                        help="IR domain (e.g. ir.jd.com, ir.alibabagroup.com)")
    parser.add_argument("--year", "-y", type=int, metavar="YEAR",
                        help="Filter results to a specific year (e.g. 2024)")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Write results to a JSON file")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("--sources", "-s", metavar="SRC",
                        help="Comma-separated sources: wayback,edgar,direct (default: all)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max results per source (default: 100)")

    return parser.parse_args()


def main():
    args = parse_args()

    if not args.company and not args.domain:
        print("ERROR: Must provide --company or --domain", file=sys.stderr)
        sys.exit(1)

    # Resolve domain
    domain = args.domain
    if not domain and args.company:
        domain = infer_ir_domain(args.company)
        if domain:
            log(f"Resolved '{args.company}' to IR domain: {domain}")
        else:
            log(f"Could not resolve '{args.company}' to an IR domain. Will try SEC EDGAR directly.", "WARN")

    # Parse sources
    sources = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",")]
        valid = {"wayback", "edgar", "direct"}
        for s in sources:
            if s not in valid:
                log(f"Unknown source: {s}. Valid: {valid}", "ERROR")
                sys.exit(1)

    results = find_pdfs(
        company=args.company,
        domain=domain,
        year=args.year,
        sources=sources,
    )

    print_results(results, format=args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        log(f"Results written to: {args.output}")

    if not results:
        log("No PDFs found. Try --sources wayback or --year <year>", "WARN")


if __name__ == "__main__":
    main()
