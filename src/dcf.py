"""
dcf.py

Values PepsiCo by discounting build_model.py's projected unlevered free
cash flows at wacc.py's WACC, then bridges Enterprise Value to an implied
per-share equity value - the actual "so what" of this whole project.

REUSES rather than duplicates: imports the exact same projection engine
and WACC build-up already tested in build_model.py and wacc.py, so the
DCF is guaranteed to stay internally consistent with everything upstream
(if you change an assumption in build_model.py, this picks it up
automatically next run - no numbers to keep in sync by hand).

TERMINAL VALUE: uses the Gordon Growth (perpetuity) method - the standard
approach when a company is expected to keep growing indefinitely, rather
than the exit-multiple method (which needs a comparable company multiple
we haven't built here). Terminal growth is capped conservatively, since
no company can outgrow the overall economy forever - a common DCF error
is setting this too high and getting an absurd valuation.
"""

import pandas as pd
from build_model import load_historicals, build_projection
from wacc import compute_wacc, SHARE_PRICE, SHARES_OUTSTANDING

TERMINAL_GROWTH = 0.025  # long-run growth cap, roughly nominal GDP growth


def compute_unlevered_fcf(hist: pd.DataFrame, projected: pd.DataFrame, tax_rate: float) -> pd.Series:
    """UFCF = EBIT x (1 - tax rate) + D&A - CapEx - change in net working capital.
    Uses the WACC's tax rate (not each year's levered tax_expense), since
    unlevered FCF asks 'what would this business generate with no debt at
    all' - so it removes the tax shield from interest, not just re-uses
    the projection's already-levered tax figure."""
    base = hist.iloc[-1]
    prior_recv, prior_inv, prior_pay = base["receivables"], base["inventory"], base["payables"]

    ufcf = {}
    for fy, row in projected.iterrows():
        delta_nwc = ((row["receivables"] - prior_recv)
                     + (row["inventory"] - prior_inv)
                     - (row["payables"] - prior_pay))
        ufcf[fy] = (row["operating_income"] * (1 - tax_rate)
                    + row["da"] - row["capex"] - delta_nwc)
        prior_recv, prior_inv, prior_pay = row["receivables"], row["inventory"], row["payables"]

    return pd.Series(ufcf, name="ufcf")


def run_dcf():
    hist = load_historicals()
    projected = build_projection(hist)
    wacc_result = compute_wacc(verbose=False)
    wacc = wacc_result["wacc"]
    tax_rate = wacc_result["tax_rate"]

    ufcf = compute_unlevered_fcf(hist, projected, tax_rate)

    years = list(range(1, len(ufcf) + 1))
    discount_factors = [1 / (1 + wacc) ** t for t in years]
    pv_ufcf = ufcf.values * discount_factors
    pv_ufcf_sum = pv_ufcf.sum()

    terminal_value = ufcf.iloc[-1] * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    pv_terminal_value = terminal_value * discount_factors[-1]

    enterprise_value = pv_ufcf_sum + pv_terminal_value

    base = hist.iloc[-1]
    net_debt = base.get("long_term_debt", 0) + base.get("short_term_debt", 0) - base["cash"]
    equity_value = enterprise_value - net_debt
    implied_share_price = equity_value / SHARES_OUTSTANDING

    print("Unlevered free cash flow by year:")
    for fy, val in ufcf.items():
        print(f"  FY{fy}: ${val/1e9:.2f}B")
    print()
    print(f"WACC used:                    {wacc:.2%}")
    print(f"Terminal growth rate:          {TERMINAL_GROWTH:.2%}")
    print(f"PV of forecast period FCF:     ${pv_ufcf_sum/1e9:.1f}B")
    print(f"Terminal value (undiscounted): ${terminal_value/1e9:.1f}B")
    print(f"PV of terminal value:          ${pv_terminal_value/1e9:.1f}B")
    print(f"  (terminal value is {pv_terminal_value/enterprise_value:.1%} of total EV - "
          f"typical DCFs run 60-80% here, worth a second look if far outside that)")
    print()
    print(f"Enterprise value:              ${enterprise_value/1e9:.1f}B")
    print(f"Less: net debt (base year):    ${net_debt/1e9:.1f}B")
    print(f"Equity value:                  ${equity_value/1e9:.1f}B")
    print()
    print(f"Shares outstanding:            {SHARES_OUTSTANDING/1e9:.2f}B")
    print(f"Implied share price:           ${implied_share_price:.2f}")
    print(f"Current market price:          ${SHARE_PRICE:.2f}")
    upside = implied_share_price / SHARE_PRICE - 1
    verdict = "undervalued" if upside > 0 else "overvalued"
    print(f"Implied upside/downside:       {upside:+.1%} ({verdict} per this model)")


if __name__ == "__main__":
    run_dcf()
