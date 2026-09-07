# Serie A FotMob starting-XI extractor — v7

v7 fixes the two issues found in the diagnostic run:

1. It uses a server-visible historical match route:
   `https://www.fotmob.com/match/<matchId>`

   This is important because the older league-page URL stores the match ID after
   `#`, and URL fragments are not sent to the server.

2. It parses the confirmed historical lineup paths:
   - `content.lineup.homeTeam.starters`
   - `content.lineup.awayTeam.starters`

The v6 diagnostic showed 11 players in each list.

## Checkpointing

v7 writes the three output CSVs after every match, so cancelling a GitHub Actions
run no longer loses all progress.

Outputs:
- `data/processed/serie_a_matches.csv`
- `data/processed/serie_a_starting_xi.csv`
- `data/processed/serie_a_lineup_coverage.csv`

## Recommended first run

Run only `2021-22`.

In the Actions log, the first match should show:

`starters: home=11, away=11`

If that appears, allow the season to continue.

## Expected complete-season result

For 380 matches:
- about 380 coverage rows
- ideally 380 complete XIs
- ideally 8,360 starter rows
