"""
build_model.py

Builds a 5-year projected 3-statement model (Income Statement, Balance
Sheet, Cash Flow Statement) using PepsiCo's historical financials
(data/financials_annual.csv, produced by data_pull.py) as the starting point.

WORKFLOW:
1. Loads historical financials
2. Derives forecast assumptions from recent historical averages (drivers)
3. Projects the IS, BS and CFS forward year by year
4. Solves the interest expense <-> revolver circularity iteratively
5. Saves the combined historical + projected table to output/model_output.csv

KEY SIMPLIFICATIONS (worth knowing so you can defend/improve them later):
- Dividends are projected as a flat historical average payout ratio
  (dividends / net income, averaged over the last 3 years). Real payout
  ratios move year to year with management decisions - this assumes they
  hold steady, which is reasonable for a stable dividend payer like
  PepsiCo but wouldn't hold for a company changing its capital policy.
- No share buybacks modeled - PepsiCo also returns cash via buybacks,
  which would further reduce the cash buildup below what this shows.
- Long-term debt is held flat (no scheduled amortization) -> only the
  revolver (short_term_debt) flexes up or down to balance the model.
- "Other assets" / "other liabilities" (anything not itemized by
  data_pull.py - e.g. goodwill, intangibles, accrued liabilities,
  deferred tax) are held constant in dollar terms at their base-year
  level rather than modeled line-by-line. This is part of what keeps the
  balance sheet balancing exactly (see balance_check column in the
  output - it should be ~0 for every projected year).
"""

import pandas as pd
import os

# ==================== CONFIG ====================
HIST_PATH = "../data/financials_annual.csv"
OUTPUT_PATH = "../output/model_output.csv"
PROJECTION_YEARS = 5
LOOKBACK_YEARS = 3            # years of history used to derive assumptions
MIN_CASH = 0                  # minimum operating cash before revolver draws
DEFAULT_INTEREST_RATE = 0.04  # fallback only if debt columns are missing
DEFAULT_PAYOUT_RATIO = 0.75   # fallback only if dividends column is missing
CONVERGENCE_TOLERANCE = 1.0   # USD - circularity solve stops within $1
MAX_ITERATIONS = 50


# ==================== STEP 1: LOAD HISTORICALS ====================
def load_historicals(path=HIST_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, index_col="fy")
    return df.sort_index()


# ==================== STEP 2: DERIVE ASSUMPTIONS ====================
def compute_drivers(hist: pd.DataFrame, lookback: int = LOOKBACK_YEARS) -> dict:
    """Derive forecast assumptions from the most recent `lookback` years.
    This dict is the single place to tweak assumptions later for
    sensitivity analysis / Monte Carlo."""
    recent = hist.tail(lookback)
    last = hist.iloc[-1]
    d = {}

    d["revenue_growth"] = hist["revenue"].pct_change().tail(lookback).mean()
    d["cogs_pct_revenue"] = (recent["cogs"] / recent["revenue"]).mean()
    d["sga_pct_revenue"] = (recent["sga"] / recent["revenue"]).mean()
    d["tax_rate"] = (recent["tax_expense"] / recent["pretax_income"]).mean()
    d["capex_pct_revenue"] = (recent["capex"].abs() / recent["revenue"]).mean()
    d["da_pct_revenue"] = (recent["da"] / recent["revenue"]).mean()
    d["dso"] = (recent["receivables"] / recent["revenue"] * 365).mean()
    d["dio"] = (recent["inventory"] / recent["cogs"] * 365).mean()
    d["dpo"] = (recent["payables"] / recent["cogs"] * 365).mean()

    has_debt_data = "long_term_debt" in hist.columns and "short_term_debt" in hist.columns
    if has_debt_data:
        total_debt = recent["long_term_debt"].fillna(0) + recent["short_term_debt"].fillna(0)
        d["interest_rate"] = (recent["interest_expense"] / total_debt).mean()
    else:
        print("WARNING: no long_term_debt/short_term_debt columns found - "
              f"using a flat {DEFAULT_INTEREST_RATE:.1%} interest rate assumption. "
              "Add debt tags to data_pull.py's TAG_MAP for a real debt schedule.")
        d["interest_rate"] = None

    has_dividend_data = "dividends" in hist.columns
    if has_dividend_data:
        d["payout_ratio"] = (recent["dividends"] / recent["net_income"]).mean()
    else:
        print("WARNING: no dividends column found - using a flat "
              f"{DEFAULT_PAYOUT_RATIO:.0%} payout ratio assumption. Add a dividends "
              "tag to data_pull.py's TAG_MAP for a real historical payout ratio.")
        d["payout_ratio"] = DEFAULT_PAYOUT_RATIO

    # "Other" balance sheet items held flat in dollar terms (see docstring)
    d["other_assets_base"] = (last["total_assets"] - last["cash"] - last["receivables"]
                               - last["inventory"] - last["ppe_net"])
    d["other_liab_base"] = (last["total_liabilities"] - last["payables"]
                             - last.get("long_term_debt", 0) - last.get("short_term_debt", 0))
    return d


# ==================== STEP 3: PROJECT ONE YEAR ====================
def project_year(prior: dict, drivers: dict) -> dict:
    """
    Projects one forecast year off the prior year's ending balance sheet.
    Interest expense depends on the average debt balance, which depends on
    the revolver draw, which depends on cash flow, which depends on net
    income, which depends on interest expense - a circular reference.
    Instead of Excel's iterative-calculation toggle, we solve it explicitly
    with a convergence loop.
    """
    revenue = prior["revenue"] * (1 + drivers["revenue_growth"])
    cogs = revenue * drivers["cogs_pct_revenue"]
    sga = revenue * drivers["sga_pct_revenue"]
    operating_income = revenue - cogs - sga

    capex = revenue * drivers["capex_pct_revenue"]
    da = revenue * drivers["da_pct_revenue"]
    ppe_net = prior["ppe_net"] + capex - da

    receivables = revenue / 365 * drivers["dso"]
    inventory = cogs / 365 * drivers["dio"]
    payables = cogs / 365 * drivers["dpo"]

    other_assets = drivers["other_assets_base"]
    other_liab = drivers["other_liab_base"]

    long_term_debt = prior["long_term_debt"]  # held flat - simplification
    interest_rate = drivers["interest_rate"] if drivers["interest_rate"] is not None else DEFAULT_INTEREST_RATE

    interest_expense = prior["interest_expense"]  # seed guess for the solve
    for _ in range(MAX_ITERATIONS):
        pretax_income = operating_income - interest_expense
        tax_expense = pretax_income * drivers["tax_rate"]
        net_income = pretax_income - tax_expense
        dividends = net_income * drivers["payout_ratio"]

        delta_nwc = ((receivables - prior["receivables"])
                     + (inventory - prior["inventory"])
                     - (payables - prior["payables"]))
        cfo = net_income + da - delta_nwc
        cfi = -capex
        cff_ex_revolver = -dividends
        cash_before_revolver = prior["cash"] + cfo + cfi + cff_ex_revolver

        if cash_before_revolver < MIN_CASH:
            revolver_draw = MIN_CASH - cash_before_revolver
            paydown = 0
        else:
            revolver_draw = 0
            paydown = min(cash_before_revolver - MIN_CASH, prior["short_term_debt"])

        short_term_debt = prior["short_term_debt"] + revolver_draw - paydown
        cash = cash_before_revolver + revolver_draw - paydown

        avg_debt = ((long_term_debt + short_term_debt)
                    + (prior["long_term_debt"] + prior["short_term_debt"])) / 2
        new_interest_expense = avg_debt * interest_rate

        if abs(new_interest_expense - interest_expense) < CONVERGENCE_TOLERANCE:
            interest_expense = new_interest_expense
            break
        interest_expense = new_interest_expense
    else:
        print(f"WARNING: interest expense did not converge within {MAX_ITERATIONS} iterations")

    # final recompute at the converged interest expense
    pretax_income = operating_income - interest_expense
    tax_expense = pretax_income * drivers["tax_rate"]
    net_income = pretax_income - tax_expense
    dividends = net_income * drivers["payout_ratio"]
    total_equity = prior["total_equity"] + net_income - dividends  # retained earnings only

    total_assets = cash + receivables + inventory + ppe_net + other_assets
    total_liabilities = payables + long_term_debt + short_term_debt + other_liab
    balance_check = total_assets - (total_liabilities + total_equity)

    return {
        "revenue": revenue, "cogs": cogs, "sga": sga, "operating_income": operating_income,
        "interest_expense": interest_expense, "pretax_income": pretax_income,
        "tax_expense": tax_expense, "net_income": net_income, "dividends": dividends,
        "cash": cash, "receivables": receivables, "inventory": inventory,
        "payables": payables, "ppe_net": ppe_net, "capex": capex, "da": da,
        "long_term_debt": long_term_debt, "short_term_debt": short_term_debt,
        "total_assets": total_assets, "total_liabilities": total_liabilities,
        "total_equity": total_equity, "balance_check": balance_check,
    }


# ==================== STEP 4: RUN FULL PROJECTION ====================
def build_projection(hist: pd.DataFrame, years: int = PROJECTION_YEARS) -> pd.DataFrame:
    drivers = compute_drivers(hist)
    print("Forecast drivers derived from history:")
    for k, v in drivers.items():
        print(f"  {k}: {v}")

    last_hist_year = hist.index.max()
    base = hist.loc[last_hist_year].to_dict()
    base.setdefault("long_term_debt", 0)
    base.setdefault("short_term_debt", 0)

    rows = {}
    prior = base
    for i in range(1, years + 1):
        fy = last_hist_year + i
        year_result = project_year(prior, drivers)
        rows[fy] = year_result
        prior = {**prior, **year_result}

    projected = pd.DataFrame.from_dict(rows, orient="index")
    projected.index.name = "fy"
    return projected


if __name__ == "__main__":
    hist = load_historicals()
    projected = build_projection(hist)

    print("\nProjected financials (USD):")
    print(projected[["revenue", "net_income", "cash", "total_assets", "balance_check"]])

    os.makedirs("../output", exist_ok=True)
    combined = pd.concat([hist, projected], axis=0, sort=False)
    combined.to_csv(OUTPUT_PATH)
    print(f"\nSaved combined historical + projected model to {OUTPUT_PATH}")