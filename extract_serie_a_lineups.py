#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from pathlib import Path

import requests

BASE = "https://www.fotmob.com"
LEAGUE_ID = 55

SEASON_QUERY = {
    "2021-22": "2021-2022",
    "2022-23": "2022-2023",
    "2023-24": "2023-2024",
    "2024-25": "2024-2025",
    "2025-26": "2025-2026",
}

PROCESSED = Path("data/processed")
RAW = Path("data/raw/fotmob")
PROCESSED.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

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

MATCH_FIELDS = [
    "Season","MatchID","DateUTC","Round","Home","Away",
    "HomeTeamID","AwayTeamID","CanonicalURL"
]

PLAYER_FIELDS = [
    "Season","MatchID","DateUTC","Round","Home","Away",
    "Side","Team","Formation","StarterNo",
    "PlayerID","Player","FirstName","LastName",
    "PositionID","UsualPlayingPositionID","ShirtNumber",
    "Age","CountryName","CountryCode","IsCaptain",
    "MarketValue","Rating","CanonicalURL"
]

COVERAGE_FIELDS = [
    "Season","MatchID","DateUTC","Round","Home","Away",
    "HomeStarters","AwayStarters","CompleteXI","CanonicalURL","Error"
]

def first(d, *names, default=None):
    if not isinstance(d, dict):
        return default
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

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

def league_url(season):
    return f"{BASE}/leagues/{LEAGUE_ID}/overview/serie?season={SEASON_QUERY[season]}"

def match_url(match_id):
    # Important: server-visible historical ID, NOT a #fragment.
    return f"{BASE}/match/{match_id}"

def get_html(session, url, cache=None, retries=5, force=False):
    if cache and cache.exists() and not force:
        return cache.read_text(encoding="utf-8", errors="replace"), None

    last = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=60, allow_redirects=True)
            print(f"    GET {r.status_code} {url} -> {r.url}", flush=True)
            if r.status_code == 200 and "__NEXT_DATA__" in r.text:
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(r.text, encoding="utf-8")
                return r.text, r.url
            last = RuntimeError(
                f"status={r.status_code}, final={r.url}, "
                f"next_data={'__NEXT_DATA__' in r.text}"
            )
        except Exception as e:
            last = e

        if attempt < retries:
            time.sleep(min(20, 2 ** (attempt - 1)) + random.uniform(.4, 1.2))

    raise RuntimeError(f"Failed after {retries} attempts: {url}; last={last}")

def next_data(html):
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        flags=re.S
    )
    if not m:
        raise RuntimeError("__NEXT_DATA__ not found")
    return json.loads(m.group(1))

def pageprops(wrapper):
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

def discover_matches(session, season, force=False):
    html, _ = get_html(
        session,
        league_url(season),
        RAW/"league"/f"{season}.html",
        force=force,
    )
    props = pageprops(next_data(html))
    raw_matches = find_allmatches(props)
    if not raw_matches:
        raise RuntimeError(f"No matches discovered for {season}")

    rows = []
    for m in raw_matches:
        status = m.get("status") or {}
        home = m.get("home") or m.get("homeTeam") or {}
        away = m.get("away") or m.get("awayTeam") or {}
        mid = first(m, "id", "matchId", default="")
        if not mid:
            continue
        rows.append({
            "Season": season,
            "MatchID": mid,
            "DateUTC": first(
                status, "utcTime",
                default=first(m, "matchTimeUTCDate", "date", default="")
            ),
            "Round": first(m, "round", "roundName", "roundId", default=""),
            "Home": nested_name(home) or first(m, "homeName", default=""),
            "Away": nested_name(away) or first(m, "awayName", default=""),
            "HomeTeamID": first(home, "id", "teamId", default=""),
            "AwayTeamID": first(away, "id", "teamId", default=""),
            "CanonicalURL": "",
        })

    uniq = {str(x["MatchID"]): x for x in rows}
    rows = sorted(uniq.values(), key=lambda x: str(x["DateUTC"]))
    print(f"  Discovered {len(rows)} matches", flush=True)
    return rows

def extract_player(p, match, side, team_name, formation, seq, canonical_url):
    country = p.get("country") or {}
    return {
        "Season": match["Season"],
        "MatchID": match["MatchID"],
        "DateUTC": match["DateUTC"],
        "Round": match["Round"],
        "Home": match["Home"],
        "Away": match["Away"],
        "Side": side,
        "Team": team_name,
        "Formation": formation,
        "StarterNo": seq,
        "PlayerID": first(p, "id", "playerId", default=""),
        "Player": first(p, "name", "playerName", "fullName", default=""),
        "FirstName": first(p, "firstName", default=""),
        "LastName": first(p, "lastName", default=""),
        "PositionID": first(p, "positionId", "position", default=""),
        "UsualPlayingPositionID": first(p, "usualPlayingPositionId", default=""),
        "ShirtNumber": first(p, "shirtNumber", "shirt", default=""),
        "Age": first(p, "age", default=""),
        "CountryName": first(country, "name", default=""),
        "CountryCode": first(country, "code", "countryCode", default=""),
        "IsCaptain": first(p, "isCaptain", "captain", default=False),
        "MarketValue": first(p, "marketValue", default=""),
        "Rating": first(p, "rating", default=""),
        "CanonicalURL": canonical_url,
    }

def parse_lineup(props, match, final_url):
    content = props.get("content") or {}
    lineup = content.get("lineup") or {}

    home = lineup.get("homeTeam") or {}
    away = lineup.get("awayTeam") or {}

    home_starters = home.get("starters") or []
    away_starters = away.get("starters") or []

    rows = []
    for seq, p in enumerate(home_starters, 1):
        rows.append(extract_player(
            p, match, "Home",
            first(home, "name", default=match["Home"]),
            first(home, "formation", default=""),
            seq, final_url
        ))

    for seq, p in enumerate(away_starters, 1):
        rows.append(extract_player(
            p, match, "Away",
            first(away, "name", default=match["Away"]),
            first(away, "formation", default=""),
            seq, final_url
        ))

    return rows, len(home_starters), len(away_starters)

def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)

def checkpoint(matches, players, coverage):
    write_csv(PROCESSED/"serie_a_matches.csv", matches, MATCH_FIELDS)
    write_csv(PROCESSED/"serie_a_starting_xi.csv", players, PLAYER_FIELDS)
    write_csv(PROCESSED/"serie_a_lineup_coverage.csv", coverage, COVERAGE_FIELDS)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--season",
        choices=list(SEASON_QUERY) + ["all"],
        default="2021-22"
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()

    seasons = list(SEASON_QUERY) if args.season == "all" else [args.season]

    session = requests.Session()
    session.headers.update(HEADERS)

    existing_matches = read_csv(PROCESSED/"serie_a_matches.csv")
    existing_players = read_csv(PROCESSED/"serie_a_starting_xi.csv")
    existing_coverage = read_csv(PROCESSED/"serie_a_lineup_coverage.csv")

    # Resume only complete 11+11 matches.
    completed = {
        str(r["MatchID"])
        for r in existing_coverage
        if str(r.get("CompleteXI","")).lower() == "true"
    }

    all_matches = existing_matches[:]
    all_players = existing_players[:]
    all_coverage = existing_coverage[:]

    known_match_ids = {str(r["MatchID"]) for r in all_matches}

    for season in seasons:
        print(f"\n=== {season} ===", flush=True)
        season_matches = discover_matches(session, season, force=args.force)

        for m in season_matches:
            mid = str(m["MatchID"])

            if mid not in known_match_ids:
                all_matches.append(m)
                known_match_ids.add(mid)
                checkpoint(all_matches, all_players, all_coverage)

            if mid in completed and not args.force:
                print(f"  SKIP complete {m['Home']} vs {m['Away']} ({mid})", flush=True)
                continue

            print(f"  {m['Home']} vs {m['Away']} ({mid})", flush=True)

            error = ""
            final_url = ""
            try:
                cache = RAW/"matches"/season/f"{mid}.html"
                html, final_url = get_html(
                    session, match_url(mid), cache, force=args.force
                )
                props = pageprops(next_data(html))

                rows, hc, ac = parse_lineup(props, m, final_url or match_url(mid))
                print(f"       starters: home={hc}, away={ac}", flush=True)

                # Remove any prior partial rows for this match before replacing them.
                all_players = [r for r in all_players if str(r["MatchID"]) != mid]
                all_coverage = [r for r in all_coverage if str(r["MatchID"]) != mid]

                all_players.extend(rows)

                complete = (hc == 11 and ac == 11)
                all_coverage.append({
                    "Season": m["Season"],
                    "MatchID": m["MatchID"],
                    "DateUTC": m["DateUTC"],
                    "Round": m["Round"],
                    "Home": m["Home"],
                    "Away": m["Away"],
                    "HomeStarters": hc,
                    "AwayStarters": ac,
                    "CompleteXI": complete,
                    "CanonicalURL": final_url,
                    "Error": "",
                })

                if complete:
                    completed.add(mid)

            except Exception as e:
                error = str(e)
                print(f"       ERROR: {error}", flush=True)

                all_coverage = [r for r in all_coverage if str(r["MatchID"]) != mid]
                all_coverage.append({
                    "Season": m["Season"],
                    "MatchID": m["MatchID"],
                    "DateUTC": m["DateUTC"],
                    "Round": m["Round"],
                    "Home": m["Home"],
                    "Away": m["Away"],
                    "HomeStarters": 0,
                    "AwayStarters": 0,
                    "CompleteXI": False,
                    "CanonicalURL": final_url,
                    "Error": error,
                })

            # Critical v7 behavior: persist after every match.
            checkpoint(all_matches, all_players, all_coverage)
            time.sleep(args.delay)

    complete_count = sum(
        str(r.get("CompleteXI","")).lower() == "true"
        for r in all_coverage
        if r.get("Season") in seasons
    )
    season_cov = [r for r in all_coverage if r.get("Season") in seasons]

    print("\nDONE", flush=True)
    print(f"Coverage rows: {len(season_cov)}", flush=True)
    print(f"Complete 11+11: {complete_count}/{len(season_cov)}", flush=True)

if __name__ == "__main__":
    main()
