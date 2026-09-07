# Serie A Sofascore starting-XI extractor (browser version)

This version uses Playwright/Chromium because direct HTTP requests to Sofascore can receive a 403 challenge.

## Run in GitHub
1. Upload these files preserving `.github/workflows/extract_lineups.yml`.
2. Open Actions -> Extract Serie A starting XIs -> Run workflow.
3. Output files are committed to `data/processed/`.

Five seasons are hardcoded to avoid calling the protected season-discovery endpoint:
2021-22 37475; 2022-23 42415; 2023-24 52760; 2024-25 63515; 2025-26 76457.

Raw JSON responses are cached under `data/raw/`, so reruns resume rather than downloading completed requests again.
