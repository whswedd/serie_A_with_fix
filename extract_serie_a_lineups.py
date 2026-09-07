#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, re, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

BASE = 'https://www.sofascore.com/api/v1'
TOURNAMENT_ID = 23
SEASON_IDS = {
    '2021-22': 37475,
    '2022-23': 42415,
    '2023-24': 52760,
    '2024-25': 63515,
    '2025-26': 76457,
}
ROUNDS = range(1, 39)
ROOT = Path(__file__).resolve().parent
RAW = ROOT/'data'/'raw'
OUT = ROOT/'data'/'processed'
POSITION_MAP = {'G':'GK','GK':'GK','D':'DEF','DF':'DEF','DEF':'DEF','M':'MID','MF':'MID','MID':'MID','F':'FWD','FW':'FWD','FWD':'FWD'}

def iso_utc(ts: Any) -> str:
    try: return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception: return ''

def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def browser_json(page, url: str, cache: Path, force=False, retries=5):
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding='utf-8'))
    cache.parent.mkdir(parents=True, exist_ok=True)
    last=None
    for attempt in range(retries):
        try:
            result = page.evaluate("""async (url) => {
              const r = await fetch(url, {credentials:'include', headers:{'accept':'application/json,text/plain,*/*'}});
              const text = await r.text();
              return {status:r.status, text};
            }""", url)
            status=result['status']
            if status != 200:
                raise RuntimeError(f'HTTP {status}: {result["text"][:300]}')
            data=json.loads(result['text'])
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            time.sleep(0.35)
            return data
        except Exception as e:
            last=e; print(f'Attempt {attempt+1}/{retries} failed for {url}: {e}')
            time.sleep(min(15, 2**attempt))
    raise RuntimeError(f'Failed after {retries} attempts: {url}') from last

def event_url(season_id, rnd):
    return f'{BASE}/unique-tournament/{TOURNAMENT_ID}/season/{season_id}/events/round/{rnd}'

def lineup_url(event_id): return f'{BASE}/event/{event_id}/lineups'

def extract_match(ev, season, rnd):
    h=ev.get('homeTeam') or {}; a=ev.get('awayTeam') or {}
    hs=ev.get('homeScore') or {}; as_=ev.get('awayScore') or {}
    return {'season':season,'round':rnd,'event_id':ev.get('id'),'kickoff_utc':iso_utc(ev.get('startTimestamp')),
            'home_team':h.get('name',''),'home_team_id':h.get('id',''),'away_team':a.get('name',''),'away_team_id':a.get('id',''),
            'status':(ev.get('status') or {}).get('type',''),'home_goals':hs.get('current',''),'away_goals':as_.get('current','')}

def get_position(entry):
    p=entry.get('player') or {}
    raw=entry.get('position') or p.get('position') or (entry.get('statistics') or {}).get('position') or ''
    return POSITION_MAP.get(str(raw).upper(), str(raw).upper())

def parse_side(obj, side, m):
    players=(obj or {}).get('players') or []
    starters=[]
    for i,e in enumerate(players):
        p=e.get('player') or e
        is_sub=e.get('substitute', e.get('isSubstitute', False))
        if is_sub: continue
        starters.append({'season':m['season'],'round':m['round'],'event_id':m['event_id'],'kickoff_utc':m['kickoff_utc'],
                         'home_team':m['home_team'],'away_team':m['away_team'],'side':side,
                         'player_id':p.get('id',''),'player_name':p.get('name',''),'position':get_position(e),
                         'shirt_number':e.get('shirtNumber', p.get('jerseyNumber','')),'starter_order':len(starters)+1})
    # Fallback for responses without explicit substitute flag: first 11 are starters.
    return starters[:11]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--force', action='store_true'); ap.add_argument('--seasons', nargs='*', default=list(SEASON_IDS))
    args=ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36')
        page=context.new_page()
        print('Opening Sofascore in Chromium to establish browser session...')
        page.goto('https://www.sofascore.com/', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)
        matches=[]
        for season in args.seasons:
            sid=SEASON_IDS[season]; print(f'\n{season}: season id {sid}')
            for rnd in ROUNDS:
                data=browser_json(page,event_url(sid,rnd),RAW/'events'/season/f'round_{rnd:02d}.json',args.force)
                events=data.get('events',[]); print(f'  round {rnd:02d}: {len(events)} events')
                matches += [extract_match(e,season,rnd) for e in events if e.get('id')]
        # de-dupe
        matches=list({int(m['event_id']):m for m in matches}.values())
        matches.sort(key=lambda x:(x['season'],x['round'],x['kickoff_utc']))
        xi=[]; coverage=[]
        for k,m in enumerate(matches,1):
            eid=int(m['event_id']); print(f'Lineups {k}/{len(matches)}: {m["home_team"]} v {m["away_team"]} ({eid})')
            try:
                data=browser_json(page,lineup_url(eid),RAW/'lineups'/m['season']/f'{eid}.json',args.force)
                h=parse_side(data.get('home'), 'home', m); a=parse_side(data.get('away'),'away',m)
            except Exception as e:
                print(f'  WARNING lineup failed: {e}'); h=[]; a=[]
            xi += h+a
            coverage.append({'season':m['season'],'round':m['round'],'event_id':eid,'home_team':m['home_team'],'away_team':m['away_team'],
                             'home_starters':len(h),'away_starters':len(a),'complete_22':int(len(h)==11 and len(a)==11)})
        browser.close()
    write_csv(OUT/'serie_a_matches.csv',matches,list(matches[0].keys()))
    fields=['season','round','event_id','kickoff_utc','home_team','away_team','side','player_id','player_name','position','shirt_number','starter_order']
    write_csv(OUT/'serie_a_starting_xi.csv',xi,fields)
    write_csv(OUT/'serie_a_lineup_coverage.csv',coverage,list(coverage[0].keys()))
    complete=sum(r['complete_22'] for r in coverage)
    print(f'\nDone: {len(matches)} matches, {len(xi)} starter rows, {complete}/{len(coverage)} complete 22-player lineups')

if __name__=='__main__': main()
