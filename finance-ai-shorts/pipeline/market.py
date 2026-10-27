"""Live market numbers for the ticker bar and the chart scene."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Quote:
    label: str
    symbol: str
    price: float
    change_pct: float
    series: list[float]          # recent prices for the chart (intraday, or 5 days)
    series_label: str            # "Today" / "5 days"


def get_quotes(tickers: dict[str, str]) -> list[Quote]:
    import warnings
    warnings.filterwarnings("ignore")              # hide noisy pandas/yfinance warnings
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed — skipping market data")
        return []

    quotes = []
    for label, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            daily = t.history(period="5d", interval="1d")
            if len(daily) < 2:
                continue
            prev_close = float(daily["Close"].iloc[-2])
            price = float(daily["Close"].iloc[-1])
            intraday = t.history(period="1d", interval="5m")
            if len(intraday) >= 12:
                series, series_label = [float(x) for x in intraday["Close"]], "Today"
            else:
                wk = t.history(period="5d", interval="30m")
                series, series_label = [float(x) for x in wk["Close"]], "5 days"
            quotes.append(Quote(label, sym, price, (price / prev_close - 1) * 100,
                                series, series_label))
            print(f"  ✓ {label}: {price:,.2f} ({quotes[-1].change_pct:+.2f}%)")
        except Exception as e:
            print(f"  ✗ {label}: {e.__class__.__name__}")
    return quotes


def as_prompt_text(quotes: list[Quote]) -> str:
    if not quotes:
        return "(market data unavailable — do not quote index levels)"
    return "\n".join(f"- {q.label}: {q.price:,.2f} ({q.change_pct:+.2f}% vs previous close)"
                     for q in quotes)
