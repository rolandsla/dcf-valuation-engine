# DCF Valuation Engine

An automated three-statement financial model and DCF valuation engine, built in Python, using PepsiCo (NASDAQ: PEP) as a live test case. Pulls real financial data directly from the SEC's EDGAR API, projects a full 3-statement model, builds a WACC from current market data, and discounts the resulting cash flows to an implied share price.

**Bottom line output:** the model implies PepsiCo is worth **$175.91/share** against an actual market price of **$137.42** (+28.0%) — landing inside the real range of Wall Street analyst price targets ($144–$183) as of July 2026.

## What this actually does

Most "DCF templates" online are static spreadsheets with hardcoded numbers. This project pulls real numbers from source and rebuilds the entire valuation from scratch every time it's run:

```
SEC EDGAR API  →  data_pull.py   →  raw XBRL financials, cleaned into a annual time series
                        ↓
                  build_model.py →  5-year projected 3-statement model
                        ↓                    (income statement, balance sheet, cash flow —
                        ↓                     self-balancing, with a debt/revolver schedule
                        ↓                     and a real dividend payout policy)
                        ↓
                  wacc.py        →  cost of capital, built from CAPM + credit-rating-based
                        ↓             cost of debt + actual market cap
                        ↓
                  dcf.py         →  discounts the model's unlevered free cash flow at WACC,
                                     adds a Gordon Growth terminal value, bridges to an
                                     implied per-share equity value
```

Each script imports from the previous one rather than duplicating logic — change an assumption in `build_model.py` and the DCF picks it up automatically on the next run.

## Repo structure

```
dcf-valuation-engine/
├── data/
│   ├── financials_annual.csv     # cleaned annual financials, 2006-2025
│   └── raw_companyfacts.json     # full raw XBRL pull (gitignored - regenerate via data_pull.py)
├── src/
│   ├── data_pull.py               # SEC EDGAR API -> cleaned annual financials
│   ├── build_model.py             # 5-year 3-statement projection engine
│   ├── wacc.py                    # WACC build-up
│   └── dcf.py                     # DCF valuation
├── output/
│   └── model_output.csv           # historical + projected financials, combined
└── notebooks/                     # exploratory work
```

## Running it

Requires Python 3.11+ and `pandas`, `requests`. Scripts are meant to be run from inside `src/`, in this order:

```bash
cd src
python data_pull.py    # pulls fresh data from SEC EDGAR (takes a few seconds)
python build_model.py  # builds the 5-year projection
python wacc.py          # computes the discount rate
python dcf.py            # runs the valuation
```

Each script is also independently runnable and prints its own output — useful for checking any single step without re-running the whole pipeline.

## Key modeling decisions

A few choices are worth stating explicitly rather than leaving implicit:

- **Interest expense circularity is solved iteratively**, not with Excel's "enable iterative calculation" toggle. `build_model.py` recomputes interest expense, net income, and the resulting revolver draw/paydown in a loop until they converge to within $1 — fully inspectable, not a hidden spreadsheet setting.
- **The dividend payout ratio (80.6%) is derived from real historical data** (dividends ÷ net income, averaged over 3 years), not assumed. Equity grows by retained earnings only.
- **Cost of debt for WACC uses PepsiCo's actual credit rating (S&P A+)**, not the book interest rate on existing debt. Those are two genuinely different numbers for two different jobs — the book rate is what the income statement projection uses (what PepsiCo actually pays on debt it actually has), while WACC needs the cost of *new* debt today. Conflating the two is a common modeling mistake.
- **"Other" balance sheet items** (goodwill, accrued liabilities, deferred tax — anything not itemized by the SEC tags this project pulls) are held flat in dollar terms rather than modeled line-by-line. This is what keeps the balance sheet balancing exactly every year (`balance_check` column, always ~0).
- **Terminal value is ~86% of enterprise value** in the current output — above the typical 60-80% range for a DCF. This is flagged directly in `dcf.py`'s output rather than hidden, because it means the valuation is more sensitive to the terminal growth assumption than to the 5 years of explicit forecasting. Quantifying that sensitivity properly (rather than just noting it) is the next planned addition — see below.

## A real debugging story

Building this surfaced a genuinely interesting data quality issue worth documenting: PepsiCo's XBRL filings had migrated to newer tag names for both `receivables` (`AccountsNotesAndLoansReceivableNetCurrent`, tied to a 2016 accounting standard change) and `capex` (`PaymentsToAcquireProductiveAssets` instead of the more common `PaymentsToAcquirePropertyPlantAndEquipment`) at some point in its filing history. The original tag list silently returned `NaN` for both rather than erroring, which cascaded into a circularity solver that could never converge. Separately, `total_equity` was initially pulled from a tag that excluded non-controlling interest while `total_assets`/`total_liabilities` were fully consolidated — breaking the balance sheet by exactly the NCI amount (~$130-141M across 2021-2025) every year. Both were root-caused by inspecting the raw XBRL tag list directly rather than guessing, and fixed with priority-ordered tag fallback lists.

## Status / what's built vs. planned

**Built:** SEC data pipeline, 3-statement model with debt schedule and dividend policy, WACC, DCF with terminal value.

**Planned:** Monte Carlo sensitivity analysis (to properly quantify how much the +28% conclusion moves with WACC/terminal growth uncertainty), formatted Excel export, a 2-3 page equity note, and a Streamlit dashboard.

## Data sources

- Financial statements: [SEC EDGAR XBRL Frames API](https://www.sec.gov/edgar/sec-api-documentation)
- Market data (risk-free rate, beta, equity risk premium, share price, credit rating): sourced and dated inline in `wacc.py`

## Author

Built by Roland Lapa as a portfolio project ahead of an MSc in Accounting and Data Analytics at LSE.
