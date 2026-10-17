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

