## v4: dedicated API host + event-list fallback

This version uses `https://api.sofascore.com/api/v1`.

For each season it first tries the normal round endpoint. If that fails, or returns
an implausibly small season, it automatically falls back to:

`/unique-tournament/23/season/{season_id}/events/last/{page}`

and discovers matches page-by-page before downloading `/event/{event_id}/lineups`.

This makes the extractor resilient to SofaScore disabling one match-discovery route.

## v3 API-host fix

This version uses the dedicated SofaScore API host:

`https://api.sofascore.com/api/v1`

rather than routing API calls through `www.sofascore.com`.

If an older repository contains URLs beginning with:

`https://www.sofascore.com/api/v1`

replace them with:

`https://api.sofascore.com/api/v1`


# Serie A Sofascore starting-XI extractor (browser version)

This version uses Playwright/Chromium because direct HTTP requests to Sofascore can receive a 403 challenge.

## Run in GitHub
1. Upload these files preserving `.github/workflows/extract_lineups.yml`.
2. Open Actions -> Extract Serie A starting XIs -> Run workflow.
3. Output files are committed to `data/processed/`.

Five seasons are hardcoded to avoid calling the protected season-discovery endpoint:
2021-22 37475; 2022-23 42415; 2023-24 52760; 2024-25 63515; 2025-26 76457.

Raw JSON responses are cached under `data/raw/`, so reruns resume rather than downloading completed requests again.
