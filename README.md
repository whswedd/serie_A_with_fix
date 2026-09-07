# Serie A historical starting-XI extractor — FotMob HTML version

This version deliberately does **not** call SofaScore or FotMob's protected
`/api/matchDetails` endpoint.

It uses normal FotMob web pages and extracts the server-rendered Next.js
`__NEXT_DATA__` JSON embedded in the HTML.

## Source
Serie A is FotMob league ID **55**.

Seasons:
- 2021-22
- 2022-23
- 2023-24
- 2024-25
- 2025-26

## GitHub Actions
1. Upload this repository.
2. Open **Actions**.
3. Choose **Extract Serie A starting XIs (FotMob HTML)**.
4. Click **Run workflow**.
5. Run one season first (`2021-22` recommended).
6. Download the `serie-a-lineups-2021-22` artifact.

Running a single season first is intentional: it verifies the current FotMob
HTML structure with only ~381 page requests before scaling to all five seasons.

## Outputs
- `serie_a_matches.csv`
- `serie_a_starting_xi.csv`
- `serie_a_lineup_coverage.csv`
- `missing_lineups.csv`

The workflow uploads CSVs even when coverage validation fails, so we can inspect
what changed instead of losing the run.

## Expected coverage
A perfect 380-match season has:
- 380 matches
- 8,360 starter rows (380 × 22)
- 380 complete 11+11 lineups

Some historical matches may genuinely have incomplete FotMob lineup data.

## Why this version is different
During 2026, automated clients began seeing 403/challenge failures on protected
football-data JSON endpoints. A current FotMob client (`0xjuanma/golazo`) works
around this by fetching the normal match page and reading `__NEXT_DATA__`.
This project applies the same approach to historical Serie A extraction.
