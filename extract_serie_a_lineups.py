#!/usr/bin/env python3
"""
Extract historical Serie A starting XIs from FotMob HTML pages.

Why HTML instead of the JSON API?
FotMob's protected matchDetails API can return 403 to automated clients.
The normal league/match web pages still contain the required data in the
Next.js __NEXT_DATA__ JSON embedded in the HTML.

Outputs:
  data/processed/serie_a_matches.csv
  data/processed/serie_a_starting_xi.csv
  data/processed/serie_a_lineup_coverage.csv
  data/processed/missing_lineups.csv
"""

from __future__ import annotations
import argparse, csv, json, random, re, time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

BASE = "https://www.fotmob.com"
LEAGUE_ID = 55
SEASONS = ["2021-22","2022-23","2023-24","2024-25","2025-26"]
SEASON_QUERY = {
    "2021-22":"2021-2022",
    "2022-23":"2022-2023",
    "2023-24":"2023-2024",
    "2024-25":"2024-2025",
    "2025-26":"2025-2026",
}
OUT = Path("data/processed")
RAW = Path("data/raw/fotmob")
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

def season_url(season: str) -> str:
    return f"{BASE}/leagues/{LEAGUE_ID}/overview/serie?season={SEASON_QUERY[season]}"

def clean_slug(slug: str) -> str:
    if not slug:
        return ""
    if slug.startswith("http"):
        return slug
    return urljoin(BASE, slug)

def request_html(session: requests.Session, url: str, cache: Path,
                 retries: int = 6, force: bool = False) -> str:
    if cache.exists() and not force:
        return cache.read_text(encoding="utf-8", errors="replace")

    cache.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, retries+1):
        try:
            r = session.get(url, timeout=45)
            print(f"    GET {r.status_code} {url}")
            if r.status_code == 200 and "__NEXT_DATA__" in r.text:
                cache.write_text(r.text, encoding="utf-8")
                return r.text
            last = RuntimeError(
                f"status={r.status_code}, len={len(r.text)}, "
                f"next_data={'__NEXT_DATA__' in r.text}"
            )
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(min(30, (2**(attempt-1))) + random.uniform(.5, 1.5))
    raise RuntimeError(f"Failed after {retries} attempts: {url}; last={last}")

def next_data(html: str) -> dict:
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, flags=re.S
    )
    if not m:
        raise ValueError("__NEXT_DATA__ script not found")
    wrapper = json.loads(m.group(1))
    return wrapper.get("props", {}).get("pageProps", {})

def find_allmatches(obj: Any):
    """Find the largest plausible allMatches list anywhere in pageProps."""
    found = []
    def walk(x):
        if isinstance(x, dict):
            for k,v in x.items():
                if k == "allMatches" and isinstance(v, list):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    if not found:
        return []
    return max(found, key=len)

def first(d: dict, *names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

def nested_name(x):
    if isinstance(x, str): return x
    if not isinstance(x, dict): return None
    n = x.get("name")
    if isinstance(n, str): return n
    if isinstance(n, dict):
        return n.get("fullName") or n.get("name")
    return x.get("fullName") or x.get("shortName")

def match_row(m: dict, season: str) -> dict:
    home = m.get("home") or m.get("homeTeam") or {}
    away = m.get("away") or m.get("awayTeam") or {}
    status = m.get("status") or {}
    return {
        "Season": season,
        "MatchID": first(m, "id", "matchId"),
        "DateUTC": first(status, "utcTime", default=first(m, "matchTimeUTCDate","date")),
        "Round": first(m, "round", "roundName", "roundId", default=""),
        "Home": nested_name(home) or first(m,"homeName", default=""),
        "Away": nested_name(away) or first(m,"awayName", default=""),
        "HomeTeamID": first(home,"id","teamId", default=""),
        "AwayTeamID": first(away,"id","teamId", default=""),
        "PageURL": clean_slug(first(m,"pageUrl","pageURL","url", default="")),
    }

def get_lineup_obj(pageprops: dict):
    content = pageprops.get("content") or {}
    if isinstance(content, dict) and "lineup" in content:
        return content.get("lineup") or {}
    # fallback recursive lookup
    stack=[pageprops]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            if "lineup" in x and isinstance(x["lineup"],dict):
                return x["lineup"]
            stack.extend(x.values())
        elif isinstance(x,list):
            stack.extend(x)
    return {}

def player_name(p: dict):
    for key in ("name","playerName","fullName"):
        v=p.get(key)
        if isinstance(v,str): return v
        if isinstance(v,dict):
            z=v.get("fullName") or v.get("name")
            if z: return z
    pl=p.get("player")
    if isinstance(pl,dict):
        return player_name(pl)
    return ""

def player_id(p: dict):
    for key in ("id","playerId"):
        if p.get(key) is not None:
            return p.get(key)
    pl=p.get("player")
    if isinstance(pl,dict):
        return pl.get("id") or pl.get("playerId")
    return ""

def player_position(p: dict):
    for key in ("position","positionId","positionLabel","role"):
        v=p.get(key)
        if isinstance(v,str): return v
        if isinstance(v,dict):
            return v.get("label") or v.get("name") or v.get("shortName") or ""
        if v is not None: return str(v)
    pl=p.get("player")
    if isinstance(pl,dict):
        return player_position(pl)
    return ""

def is_bench_player(p: dict) -> bool:
    # Explicit flags where available.
    if p.get("isStarter") is True or p.get("starter") is True:
        return False
    if p.get("isStarter") is False or p.get("starter") is False:
        return True
    if p.get("isSubstitute") is True or p.get("substitute") is True:
        return True
    return False

def flatten_players(x):
    """Yield player-like dicts from nested lineup arrays without duplicating them."""
    out=[]
    seen=set()
    def walk(v):
        if isinstance(v,dict):
            pid=player_id(v); nm=player_name(v)
            playerish = bool(pid or nm) and any(
                k in v for k in ("position","positionId","shirt","shirtNumber",
                                 "playerId","isStarter","starter","isSubstitute")
            )
            if playerish:
                key=(str(pid),nm)
                if key not in seen:
                    seen.add(key); out.append(v)
            else:
                for z in v.values(): walk(z)
        elif isinstance(v,list):
            for z in v: walk(z)
    walk(x)
    return out

def parse_starting_xi(pageprops: dict, match: dict):
    lineup=get_lineup_obj(pageprops)
    rows=[]
    if not lineup:
        return rows

    home_id=str(match["HomeTeamID"])
    away_id=str(match["AwayTeamID"])

    # Modern shape: lineup.lineups = [{teamId, teamName, players:[...]} ...]
    teams = lineup.get("lineups")
    if isinstance(teams,list):
        for t in teams:
            tid=str(first(t,"teamId","id", default=""))
            side = "Home" if tid==home_id else ("Away" if tid==away_id else "")
            tname=first(t,"teamName","name", default="")
            players=t.get("players") or t.get("lineup") or []
            # In this structure players are typically the XI. Filter explicit bench flags anyway.
            plist=[p for p in flatten_players(players) if not is_bench_player(p)]
            # Prefer first 11 if nested data added duplicates/extras.
            if len(plist)>11:
                starter_flagged=[p for p in plist if p.get("isStarter") is True or p.get("starter") is True]
                if len(starter_flagged)==11: plist=starter_flagged
                else: plist=plist[:11]
            for seq,p in enumerate(plist,1):
                rows.append(make_player_row(match,side,tname,seq,p))
        if rows:
            return rows

    # Older shape commonly has a paired starting lineup array plus paired bench arrays.
    # Search named keys that imply STARTERS, explicitly excluding bench/substitute keys.
    candidate_arrays=[]
    def collect_named(d):
        if isinstance(d,dict):
            for k,v in d.items():
                kl=k.lower()
                if isinstance(v,list) and ("lineup" in kl or "starter" in kl):
                    if "bench" not in kl and "sub" not in kl:
                        candidate_arrays.append((k,v))
                elif isinstance(v,(dict,list)):
                    collect_named(v)
        elif isinstance(d,list):
            for v in d: collect_named(v)
    collect_named(lineup)

    for _,arr in candidate_arrays:
        # Often [homeXI, awayXI]
        if len(arr)==2 and all(isinstance(z,list) for z in arr):
            for side,tname,players in [
                ("Home",match["Home"],arr[0]),("Away",match["Away"],arr[1])
            ]:
                plist=[p for p in flatten_players(players) if not is_bench_player(p)][:11]
                for seq,p in enumerate(plist,1):
                    rows.append(make_player_row(match,side,tname,seq,p))
            if rows:
                return rows

    return rows

def make_player_row(match, side, team_name, seq, p):
    return {
        "Season":match["Season"],"MatchID":match["MatchID"],
        "DateUTC":match["DateUTC"],"Round":match["Round"],
        "Home":match["Home"],"Away":match["Away"],
        "Side":side,"Team":team_name,"StarterNo":seq,
        "PlayerID":player_id(p),"Player":player_name(p),
        "Position":player_position(p),
        "ShirtNumber":first(p,"shirtNumber","shirt", default=""),
        "PageURL":match["PageURL"],
    }

def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--season", choices=["all"]+SEASONS, default="all")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--delay-min", type=float, default=0.8)
    ap.add_argument("--delay-max", type=float, default=1.5)
    args=ap.parse_args()
    seasons=SEASONS if args.season=="all" else [args.season]

    session=requests.Session()
    session.headers.update(HEADERS)

    all_matches=[]
    all_players=[]
    missing=[]

    for season in seasons:
        print(f"\n=== {season} ===")
        html=request_html(session, season_url(season),
                          RAW/"league"/f"{season}.html", force=args.force)
        props=next_data(html)
        raw_matches=find_allmatches(props)
        matches=[]
        for m in raw_matches:
            row=match_row(m,season)
            if row["MatchID"] and row["Home"] and row["Away"]:
                matches.append(row)

        # Deduplicate by MatchID.
        uniq={str(m["MatchID"]):m for m in matches}
        matches=list(uniq.values())
        matches.sort(key=lambda z: str(z["DateUTC"]))
        print(f"  Discovered {len(matches)} matches")
        if len(matches)<350:
            print("  WARNING: fewer than 350 matches discovered; check league page cache.")

        for i,m in enumerate(matches,1):
            print(f"  [{i:03d}/{len(matches):03d}] {m['Home']} vs {m['Away']}")
            if not m["PageURL"]:
                missing.append({**m,"Reason":"No PageURL in league page"})
                continue
            try:
                html=request_html(
                    session,m["PageURL"],
                    RAW/"matches"/season/f"{m['MatchID']}.html",
                    force=args.force
                )
                props=next_data(html)
                players=parse_starting_xi(props,m)
                hc=sum(1 for p in players if p["Side"]=="Home")
                ac=sum(1 for p in players if p["Side"]=="Away")
                print(f"       starters: home={hc}, away={ac}")
                if hc!=11 or ac!=11:
                    missing.append({**m,"Reason":f"Parsed starters home={hc}, away={ac}"})
                all_players.extend(players)
            except Exception as e:
                print(f"       ERROR: {e}")
                missing.append({**m,"Reason":str(e)})
            time.sleep(random.uniform(args.delay_min,args.delay_max))

        all_matches.extend(matches)

    match_fields=["Season","MatchID","DateUTC","Round","Home","Away",
                  "HomeTeamID","AwayTeamID","PageURL"]
    player_fields=["Season","MatchID","DateUTC","Round","Home","Away","Side",
                   "Team","StarterNo","PlayerID","Player","Position",
                   "ShirtNumber","PageURL"]
    write_csv(OUT/"serie_a_matches.csv",all_matches,match_fields)
    write_csv(OUT/"serie_a_starting_xi.csv",all_players,player_fields)

    coverage=[]
    for m in all_matches:
        ps=[p for p in all_players if str(p["MatchID"])==str(m["MatchID"])]
        hc=sum(p["Side"]=="Home" for p in ps); ac=sum(p["Side"]=="Away" for p in ps)
        coverage.append({
            "Season":m["Season"],"MatchID":m["MatchID"],"DateUTC":m["DateUTC"],
            "Home":m["Home"],"Away":m["Away"],
            "HomeStarters":hc,"AwayStarters":ac,"CompleteXI":hc==11 and ac==11
        })
    write_csv(OUT/"serie_a_lineup_coverage.csv",coverage,
              ["Season","MatchID","DateUTC","Home","Away",
               "HomeStarters","AwayStarters","CompleteXI"])
    write_csv(OUT/"missing_lineups.csv",missing,match_fields+["Reason"])

    complete=sum(r["CompleteXI"] for r in coverage)
    print("\nDONE")
    print(f"Matches: {len(all_matches)}")
    print(f"Starting-player rows: {len(all_players)}")
    print(f"Complete 11+11 lineups: {complete}/{len(coverage)}")
    if len(all_matches) and complete < 0.90*len(all_matches):
        raise SystemExit(
            "Coverage below 90%. Outputs were still written/uploaded for diagnosis."
        )

if __name__=="__main__":
    main()
