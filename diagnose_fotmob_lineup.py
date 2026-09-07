#!/usr/bin/env python3
"""
v6 diagnostic extractor for FotMob Serie A lineups.

Purpose:
- Fetch ONLY the first Serie A match of a selected season.
- Save the raw HTML and full __NEXT_DATA__ JSON.
- Print every JSON path whose key/value suggests lineup/player/starter/bench data.
- Produce a compact candidate-path report.
- Stop immediately after one match.

This is intentionally diagnostic. Do not use it for the full 5-season extraction.
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://www.fotmob.com"
LEAGUE_ID = 55

SEASON_QUERY = {
    "2021-22":"2021-2022",
    "2022-23":"2022-2023",
    "2023-24":"2023-2024",
    "2024-25":"2024-2025",
    "2025-26":"2025-2026",
}

OUT = Path("data/diagnostics")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

KEYWORDS = (
    "lineup","line-up","starter","starting","bench","substitute",
    "player","formation","squad"
)

def get_html(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=60)
    print(f"GET {r.status_code} {url}", flush=True)
    r.raise_for_status()
    if "__NEXT_DATA__" not in r.text:
        raise RuntimeError("__NEXT_DATA__ not found in HTML")
    return r.text

def next_data(html: str) -> dict:
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        flags=re.S
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ script tag not found")
    return json.loads(m.group(1))

def pageprops(wrapper: dict) -> dict:
    return wrapper.get("props", {}).get("pageProps", {})

def find_allmatches(obj):
    found = []
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "allMatches" and isinstance(v, list):
                    found.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return max(found, key=len) if found else []

def nested_name(x):
    if isinstance(x, str):
        return x
    if not isinstance(x, dict):
        return ""
    n = x.get("name")
    if isinstance(n, str):
        return n
    if isinstance(n, dict):
        return n.get("fullName") or n.get("name") or ""
    return x.get("fullName") or x.get("shortName") or ""

def first(d: dict, *names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

def first_match_from_league(props: dict):
    matches = find_allmatches(props)
    if not matches:
        raise RuntimeError("No matches found in league page")
    # Sort by known UTC timestamp so the first historical match is deterministic.
    def key(m):
        status = m.get("status") or {}
        return (
            first(status, "utcTime",
                  default=first(m, "matchTimeUTCDate", "date", default="9999"))
            or "9999"
        )
    matches = sorted(matches, key=key)
    m = matches[0]

    home = m.get("home") or m.get("homeTeam") or {}
    away = m.get("away") or m.get("awayTeam") or {}
    slug = first(m, "pageUrl", "pageURL", "url", default="")
    match_id = first(m, "id", "matchId", default="")

    if not slug:
        raise RuntimeError(f"First match has no page URL: {m}")

    url = slug if str(slug).startswith("http") else urljoin(BASE, str(slug))
    return {
        "match_id": match_id,
        "home": nested_name(home) or first(m, "homeName", default=""),
        "away": nested_name(away) or first(m, "awayName", default=""),
        "url": url,
        "raw_match": m,
    }

def json_type_summary(v):
    if isinstance(v, dict):
        return f"dict[{len(v)}]"
    if isinstance(v, list):
        return f"list[{len(v)}]"
    return type(v).__name__

def looks_interesting(key, value):
    k = str(key).lower()
    if any(w in k for w in KEYWORDS):
        return True
    if isinstance(value, str):
        s = value.lower()
        if any(w in s for w in ("lineup","starter","bench","formation")):
            return True
    return False

def path_join(parent, child):
    if isinstance(child, int):
        return f"{parent}[{child}]"
    if not parent:
        return str(child)
    return f"{parent}.{child}"

def scan_paths(obj):
    hits = []

    def walk(x, path=""):
        if isinstance(x, dict):
            for k, v in x.items():
                p = path_join(path, k)
                if looks_interesting(k, v):
                    preview = ""
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        preview = repr(v)[:300]
                    else:
                        preview = json_type_summary(v)
                    hits.append((p, str(k), preview))
                walk(v, p)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, path_join(path, i))

    walk(obj)
    return hits

def collect_candidate_containers(obj):
    """
    Find dict/list containers likely to hold lineups by structural clues:
    - lists with player-like dicts
    - dicts with formation/team/player keys
    """
    candidates = []

    def playerish(d):
        if not isinstance(d, dict):
            return False
        keys = {str(k).lower() for k in d.keys()}
        score = 0
        if {"id","playerid"} & keys: score += 1
        if {"name","playername","fullname"} & keys: score += 1
        if {"position","positionid","shirtnumber","shirt"} & keys: score += 1
        if {"isstarter","starter","issubstitute","substitute"} & keys: score += 2
        return score >= 2

    def walk(x, path=""):
        if isinstance(x, dict):
            keys = {str(k).lower() for k in x.keys()}
            if (
                any("lineup" in k for k in keys)
                or any("formation" in k for k in keys)
                or ("players" in keys and any(k in keys for k in ("teamid","team","teamname")))
            ):
                candidates.append((path, json_type_summary(x), sorted(list(keys))[:40]))
            for k, v in x.items():
                walk(v, path_join(path, k))

        elif isinstance(x, list):
            if x:
                dicts = [v for v in x if isinstance(v, dict)]
                if len(dicts) >= min(3, len(x)):
                    pcount = sum(playerish(v) for v in dicts[:30])
                    if pcount >= 3:
                        candidates.append(
                            (path, f"list[{len(x)}]", f"playerish={pcount}/{len(dicts[:30])}")
                        )
            for i, v in enumerate(x[:100]):
                walk(v, path_join(path, i))

    walk(obj)
    return candidates

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", choices=list(SEASON_QUERY), default="2021-22")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    league_url = f"{BASE}/leagues/{LEAGUE_ID}/overview/serie?season={SEASON_QUERY[args.season]}"
    league_html = get_html(session, league_url)
    league_wrapper = next_data(league_html)
    league_props = pageprops(league_wrapper)

    first_match = first_match_from_league(league_props)
    print(
        f"FIRST MATCH: {first_match['home']} vs {first_match['away']} "
        f"(id={first_match['match_id']})",
        flush=True
    )
    print(f"MATCH URL: {first_match['url']}", flush=True)

    match_html = get_html(session, first_match["url"])
    wrapper = next_data(match_html)
    props = pageprops(wrapper)

    # Save complete diagnostics.
    (OUT/"league_page.html").write_text(league_html, encoding="utf-8")
    (OUT/"match_page.html").write_text(match_html, encoding="utf-8")
    (OUT/"next_data_full.json").write_text(
        json.dumps(wrapper, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (OUT/"pageprops.json").write_text(
        json.dumps(props, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (OUT/"selected_match.json").write_text(
        json.dumps(first_match, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    hits = scan_paths(props)
    candidates = collect_candidate_containers(props)

    with (OUT/"keyword_paths.txt").open("w", encoding="utf-8") as f:
        for path, key, preview in hits:
            f.write(f"{path}\tkey={key}\t{preview}\n")

    with (OUT/"candidate_containers.txt").open("w", encoding="utf-8") as f:
        for row in candidates:
            f.write("\t".join(map(str, row)) + "\n")

    print("\n=== KEYWORD PATHS ===", flush=True)
    if hits:
        for path, key, preview in hits[:250]:
            print(f"{path} | {preview}", flush=True)
    else:
        print("NO KEYWORD PATHS FOUND", flush=True)

    print("\n=== STRUCTURAL CANDIDATES ===", flush=True)
    if candidates:
        for row in candidates[:250]:
            print(" | ".join(map(str, row)), flush=True)
    else:
        print("NO STRUCTURAL CANDIDATES FOUND", flush=True)

    print("\nDiagnostics written to data/diagnostics/", flush=True)
    print("Upload the diagnostic artifact and inspect pageprops.json / candidate_containers.txt", flush=True)

if __name__ == "__main__":
    main()
