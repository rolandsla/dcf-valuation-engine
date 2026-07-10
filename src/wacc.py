"""
wacc.py

Computes PepsiCo's Weighted Average Cost of Capital (WACC) - the discount
rate the DCF will use to convert projected free cash flows into a present
value.

MARKET INPUTS (hardcoded below, sourced and dated - these are NOT pulled
from data_pull.py because they're market data, not company filings, and
need periodic refreshing as markets move):
- Risk-free rate: 10-year US Treasury yield, ~4.55% (as of July 2026)
- Beta: 0.36 - PepsiCo's 5yr beta (source: stockanalysis.com/CNBC, July 2026)
- Equity risk premium: 4.23% - Damodaran's implied ERP for the US (Jan 2026,
  his most recent published estimate)
- Share price: $137.42 (July 9 2026 close, post-Q2-earnings reaction)
- Shares outstanding: ~1.37bn (source: stockanalysis.com, mid-2026)
- Credit rating: A+ (S&P Global, affirmed October 2025, outlook stable)

WHY TWO DIFFERENT "COST OF DEBT" NUMBERS EXIST IN THIS PROJECT:
- build_model.py's ~2% interest_rate driver is the *book* rate: actual
  interest expense divided by actual debt balance, i.e. the coupon on
  PepsiCo's existing (mostly older, lower-rate) debt. That's the right
  number for projecting the income statement, since it's what PepsiCo
  actually pays on the debt it actually has.
- WACC needs the cost of *new* debt today - what a lender would charge
  PepsiCo if it borrowed right now, given current rates and its credit
  rating. In today's higher-rate environment that's a meaningfully
  different (higher) number. This script derives it from PepsiCo's
  credit rating instead of the book rate, which is standard practice.
"""

import pandas as pd

# ==================== MARKET INPUTS (update periodically) ====================
RISK_FREE_RATE = 0.0455              # 10yr US Treasury yield, July 2026
BETA = 0.36                          # PepsiCo 5yr beta
EQUITY_RISK_PREMIUM = 0.0423         # Damodaran implied ERP, Jan 2026
SHARE_PRICE = 137.42                 # PEP close, July 9 2026
SHARES_OUTSTANDING = 1_370_000_000   # ~1.37bn shares
CREDIT_SPREAD = 0.0085               # rating-implied spread for A+ credit over risk-free

HIST_PATH = "../data/financials_annual.csv"
LOOKBACK_YEARS = 3


def compute_cost_of_equity() -> float:
    """CAPM: Re = Rf + Beta x ERP"""
    return RISK_FREE_RATE + BETA * EQUITY_RISK_PREMIUM


def compute_cost_of_debt(hist: pd.DataFrame):
    """Pre-tax cost of new debt (rating-based) and after-tax cost using
    the company's own effective tax rate."""
    pretax_cost_of_debt = RISK_FREE_RATE + CREDIT_SPREAD
    recent = hist.tail(LOOKBACK_YEARS)
    tax_rate = (recent["tax_expense"] / recent["pretax_income"]).mean()
    after_tax_cost_of_debt = pretax_cost_of_debt * (1 - tax_rate)
    return pretax_cost_of_debt, after_tax_cost_of_debt, tax_rate


def compute_weights(hist: pd.DataFrame):
    """Market value of equity vs. book value of debt (standard practice -
    market value of debt is rarely directly observable, book value is a
    widely accepted proxy)."""
    last = hist.iloc[-1]
    market_cap = SHARE_PRICE * SHARES_OUTSTANDING
    total_debt = last.get("long_term_debt", 0) + last.get("short_term_debt", 0)
    total_capital = market_cap + total_debt
    return market_cap, total_debt, market_cap / total_capital, total_debt / total_capital


def compute_wacc(verbose: bool = True) -> dict:
    hist = pd.read_csv(HIST_PATH, index_col="fy").sort_index()

    cost_of_equity = compute_cost_of_equity()
    pretax_cod, aftertax_cod, tax_rate = compute_cost_of_debt(hist)
    market_cap, total_debt, w_equity, w_debt = compute_weights(hist)
    wacc = w_equity * cost_of_equity + w_debt * aftertax_cod

    if not verbose:
        return {
            "cost_of_equity": cost_of_equity, "pretax_cost_of_debt": pretax_cod,
            "aftertax_cost_of_debt": aftertax_cod, "tax_rate": tax_rate,
            "market_cap": market_cap, "total_debt": total_debt,
            "weight_equity": w_equity, "weight_debt": w_debt, "wacc": wacc,
        }

    print("WACC build-up")
    print(f"  Risk-free rate:            {RISK_FREE_RATE:.2%}")
    print(f"  Beta:                      {BETA:.2f}")
    print(f"  Equity risk premium:       {EQUITY_RISK_PREMIUM:.2%}")
    print(f"  Cost of equity (CAPM):     {cost_of_equity:.2%}")
    print()
    print(f"  Credit rating spread:      {CREDIT_SPREAD:.2%}")
    print(f"  Pre-tax cost of debt:      {pretax_cod:.2%}")
    print(f"  Effective tax rate:        {tax_rate:.2%}")
    print(f"  After-tax cost of debt:    {aftertax_cod:.2%}")
    print()
    print(f"  Market cap (E):            ${market_cap/1e9:.1f}B")
    print(f"  Total debt (D):            ${total_debt/1e9:.1f}B")
    print(f"  Weight of equity:          {w_equity:.1%}")
    print(f"  Weight of debt:            {w_debt:.1%}")
    print()
    print(f"  WACC:                      {wacc:.2%}")

    return {
        "cost_of_equity": cost_of_equity, "pretax_cost_of_debt": pretax_cod,
        "aftertax_cost_of_debt": aftertax_cod, "tax_rate": tax_rate,
        "market_cap": market_cap, "total_debt": total_debt,
        "weight_equity": w_equity, "weight_debt": w_debt, "wacc": wacc,
    }


if __name__ == "__main__":
    compute_wacc()