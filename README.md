# Serie A FotMob lineup diagnostic — v6

This version does not run a full season.

It fetches:
1. one Serie A league page;
2. the **first match only** for the selected season;
3. the full embedded Next.js `__NEXT_DATA__`;
4. every JSON path likely to contain lineup/player/starter/bench information.

## Run it

GitHub:

**Actions → Diagnose FotMob Serie A lineup structure (v6) → Run workflow**

Choose `2021-22`.

The run should complete quickly because it requests only two pages.

## Artifact

Download:

`fotmob-lineup-diagnostics-2021-22`

It contains:

- `league_page.html`
- `match_page.html`
- `next_data_full.json`
- `pageprops.json`
- `selected_match.json`
- `keyword_paths.txt`
- `candidate_containers.txt`

The important files are `candidate_containers.txt` and `pageprops.json`.

Once we know FotMob's exact lineup structure, the full extractor can be rebuilt to checkpoint CSVs continuously rather than writing only at the end.
