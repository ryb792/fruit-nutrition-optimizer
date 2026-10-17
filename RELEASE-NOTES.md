# v1.1.0 — Public release candidate

- Built from V1.0 nutrient ranking and price evidence analysis.
- Added Pareto analysis, price thresholds, multi-day MILP procurement with packages, budget limits, shelf-life windows, and optional fixed shopping costs.
- Verified locally: 79 tests passed on the source snapshot (2026-10-16).
- Important boundaries: no verified live local retail feed, no standalone CLI image recognition, no production FDC API connectivity test; edible yields and shelf lives are planning assumptions.

# v1.2.0 — Keyless web evidence import

- Ordinary users can let a web-capable Agent retrieve primary public nutrition sources without an API key, then validate and import the evidence with `import-web`.
- Preserve original nutrient labels, values, units, source locators, access dates and SHA256 evidence; normalize edible mass and units while keeping missing values unknown.
- Validate merged catalogs before atomic writes; preserve inputs and existing output on invalid imports. Reports retain the actual dataset identity.
- Keep the developer `import-fdc` API and `FDC_API_KEY` environment variable. API network errors do not echo credential-bearing URLs.
- Verified locally on 2026-10-17: **135 tests passed** and Skill validation passed. A real keyless USDA Foundation download, mango evidence import, profile/compare and optimization calculations succeeded.
- The Agent host supplies search/browser tools; the CLI does not search arbitrary websites. Live developer API calls with a real key and standalone photo recognition remain unverified.

# v1.3.0 — Ask for missing prices, then look up recent references

- For text or photo requests without a usable price, ask for the missing price/unit/location and wait for the reply. When the user does not know or already asks for a lookup, the Agent searches recent local market references without asking for the same price again.
- Add `reference_retail` for sourced fallback retail quotes, distinct from actual user quotes and simulated prices. Keep dates, locations, URLs and the reference qualification in profiles, rankings, Pareto/threshold analyses and purchase/budget reports.
- Prefer the last seven days; do not refresh old quotes with retrieval dates or silently substitute wholesale prices, other locations or simulated prices.
- Preserve the optional developer USDA FDC API and the keyless nutrition import workflow.
- Validation on 2026-10-17: **156 tests passed**, Skill validation and diff checks passed. The 21 added cases use synthetic fixtures to test quote evidence, freshness, units, arithmetic and report labels; they are not real current market prices.

