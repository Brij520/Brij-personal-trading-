"""The tradable/researchable universe.

Real NSE tickers with real sector classifications. In ``demo`` data mode the
*numbers* attached to these tickers are synthetic; the tickers themselves are
real identifiers used for routing and display only.

Index membership is intentionally approximate and is stored as data (not code)
so it can be corrected without touching the analytics layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NIFTY50 = "NIFTY 50"
BANKNIFTY = "NIFTY BANK"
FINNIFTY = "NIFTY FIN SERVICE"
MIDCAP = "NIFTY MIDCAP 100"
SMALLCAP = "NIFTY SMALLCAP 100"
SENSEX = "SENSEX"
SENSEX = "SENSEX"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    sector: str
    industry: str
    exchange: str = "NSE"
    indices: tuple[str, ...] = ()
    fno: bool = False
    lot_size: int = 0
    isin: str | None = None

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.symbol}"


def _i(symbol: str, name: str, sector: str, industry: str, idx=(), fno=False, lot=0):
    return Instrument(
        symbol=symbol,
        name=name,
        sector=sector,
        industry=industry,
        indices=tuple(idx),
        fno=fno,
        lot_size=lot,
    )


INSTRUMENTS: tuple[Instrument, ...] = (
    # ------------------------------------------------------------ NIFTY 50
    _i("RELIANCE", "Reliance Industries", "Oil & Gas", "Refineries", (NIFTY50,), True, 250),
    _i("TCS", "Tata Consultancy Services", "Information Technology", "IT Services", (NIFTY50,), True, 175),
    _i("HDFCBANK", "HDFC Bank", "Financial Services", "Private Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 550),
    _i("ICICIBANK", "ICICI Bank", "Financial Services", "Private Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 700),
    _i("INFY", "Infosys", "Information Technology", "IT Services", (NIFTY50,), True, 400),
    _i("BHARTIARTL", "Bharti Airtel", "Telecom", "Telecom Services", (NIFTY50,), True, 475),
    _i("ITC", "ITC", "FMCG", "Cigarettes & FMCG", (NIFTY50,), True, 1600),
    _i("SBIN", "State Bank of India", "Financial Services", "PSU Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 750),
    _i("LT", "Larsen & Toubro", "Capital Goods", "Construction & Engineering", (NIFTY50,), True, 150),
    _i("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services", "Private Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 400),
    _i("AXISBANK", "Axis Bank", "Financial Services", "Private Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 625),
    _i("HINDUNILVR", "Hindustan Unilever", "FMCG", "Home & Personal Care", (NIFTY50,), True, 300),
    _i("BAJFINANCE", "Bajaj Finance", "Financial Services", "NBFC", (NIFTY50, FINNIFTY), True, 125),
    _i("MARUTI", "Maruti Suzuki India", "Automobile", "Passenger Vehicles", (NIFTY50,), True, 50),
    _i("M&M", "Mahindra & Mahindra", "Automobile", "Utility Vehicles", (NIFTY50,), True, 350),
    _i("SUNPHARMA", "Sun Pharmaceutical", "Pharmaceuticals", "Pharmaceuticals", (NIFTY50,), True, 350),
    _i("TITAN", "Titan Company", "Consumer Durables", "Jewellery & Watches", (NIFTY50,), True, 175),
    _i("ULTRACEMCO", "UltraTech Cement", "Cement", "Cement", (NIFTY50,), True, 50),
    _i("NTPC", "NTPC", "Power", "Power Generation", (NIFTY50,), True, 1500),
    _i("POWERGRID", "Power Grid Corporation", "Power", "Power Transmission", (NIFTY50,), True, 1900),
    _i("TATAMOTORS", "Tata Motors", "Automobile", "Commercial Vehicles", (NIFTY50,), True, 550),
    _i("TATASTEEL", "Tata Steel", "Metals & Mining", "Iron & Steel", (NIFTY50,), True, 5500),
    _i("JSWSTEEL", "JSW Steel", "Metals & Mining", "Iron & Steel", (NIFTY50,), True, 675),
    _i("HINDALCO", "Hindalco Industries", "Metals & Mining", "Aluminium", (NIFTY50,), True, 1075),
    _i("ADANIENT", "Adani Enterprises", "Conglomerate", "Trading & Infrastructure", (NIFTY50,), True, 300),
    _i("ADANIPORTS", "Adani Ports & SEZ", "Infrastructure", "Ports", (NIFTY50,), True, 475),
    _i("ASIANPAINT", "Asian Paints", "Paints", "Decorative Paints", (NIFTY50,), True, 200),
    _i("BAJAJFINSV", "Bajaj Finserv", "Financial Services", "Holding & Insurance", (NIFTY50, FINNIFTY), True, 500),
    _i("BAJAJ-AUTO", "Bajaj Auto", "Automobile", "Two Wheelers", (NIFTY50,), True, 75),
    _i("BEL", "Bharat Electronics", "Capital Goods", "Defence Electronics", (NIFTY50,), True, 2850),
    _i("BPCL", "Bharat Petroleum", "Oil & Gas", "Refineries", (NIFTY50,), True, 1800),
    _i("BRITANNIA", "Britannia Industries", "FMCG", "Packaged Foods", (NIFTY50,), True, 200),
    _i("CIPLA", "Cipla", "Pharmaceuticals", "Pharmaceuticals", (NIFTY50,), True, 650),
    _i("COALINDIA", "Coal India", "Metals & Mining", "Coal", (NIFTY50,), True, 2100),
    _i("DIVISLAB", "Divi's Laboratories", "Pharmaceuticals", "API & CRAMS", (NIFTY50,), True, 200),
    _i("DRREDDY", "Dr. Reddy's Laboratories", "Pharmaceuticals", "Pharmaceuticals", (NIFTY50,), True, 625),
    _i("EICHERMOT", "Eicher Motors", "Automobile", "Two Wheelers", (NIFTY50,), True, 175),
    _i("GRASIM", "Grasim Industries", "Cement", "Diversified Cement", (NIFTY50,), True, 475),
    _i("HCLTECH", "HCL Technologies", "Information Technology", "IT Services", (NIFTY50,), True, 350),
    _i("HDFCLIFE", "HDFC Life Insurance", "Financial Services", "Life Insurance", (NIFTY50, FINNIFTY), True, 1100),
    _i("HEROMOTOCO", "Hero MotoCorp", "Automobile", "Two Wheelers", (NIFTY50,), True, 150),
    _i("INDUSINDBK", "IndusInd Bank", "Financial Services", "Private Bank", (NIFTY50, BANKNIFTY, FINNIFTY), True, 500),
    _i("NESTLEIND", "Nestle India", "FMCG", "Packaged Foods", (NIFTY50,), True, 250),
    _i("ONGC", "Oil & Natural Gas Corp", "Oil & Gas", "Exploration", (NIFTY50,), True, 3850),
    _i("SBILIFE", "SBI Life Insurance", "Financial Services", "Life Insurance", (NIFTY50, FINNIFTY), True, 750),
    _i("SHRIRAMFIN", "Shriram Finance", "Financial Services", "NBFC", (NIFTY50, FINNIFTY), True, 900),
    _i("TATACONSUM", "Tata Consumer Products", "FMCG", "Packaged Foods", (NIFTY50,), True, 550),
    _i("TECHM", "Tech Mahindra", "Information Technology", "IT Services", (NIFTY50,), True, 600),
    _i("TRENT", "Trent", "Retail", "Apparel Retail", (NIFTY50,), True, 275),
    _i("WIPRO", "Wipro", "Information Technology", "IT Services", (NIFTY50,), True, 3000),
    # ------------------------------------------------------- mid / small cap
    _i("POLYCAB", "Polycab India", "Capital Goods", "Wires & Cables", (MIDCAP,), True, 175),
    _i("DIXON", "Dixon Technologies", "Consumer Durables", "Electronics Manufacturing", (MIDCAP,), True, 100),
    _i("PERSISTENT", "Persistent Systems", "Information Technology", "IT Services", (MIDCAP,), True, 175),
    _i("COFORGE", "Coforge", "Information Technology", "IT Services", (MIDCAP,), True, 150),
    _i("ASTRAL", "Astral", "Chemicals", "Pipes & Adhesives", (MIDCAP,), True, 425),
    _i("PIIND", "PI Industries", "Chemicals", "Agrochemicals", (MIDCAP,), True, 250),
    _i("CUMMINSIND", "Cummins India", "Capital Goods", "Industrial Engines", (MIDCAP,), True, 300),
    _i("HAVELLS", "Havells India", "Consumer Durables", "Electrical Equipment", (MIDCAP,), True, 500),
    _i("AUBANK", "AU Small Finance Bank", "Financial Services", "Small Finance Bank", (MIDCAP, FINNIFTY), True, 1000),
    _i("IDFCFIRSTB", "IDFC First Bank", "Financial Services", "Private Bank", (MIDCAP, BANKNIFTY), True, 7500),
    _i("FEDERALBNK", "Federal Bank", "Financial Services", "Private Bank", (MIDCAP, BANKNIFTY), True, 5000),
    _i("BANDHANBNK", "Bandhan Bank", "Financial Services", "Private Bank", (MIDCAP, BANKNIFTY), True, 3600),
    _i("YESBANK", "Yes Bank", "Financial Services", "Private Bank", (SMALLCAP,), True, 15000),
    _i("IDEA", "Vodafone Idea", "Telecom", "Telecom Services", (SMALLCAP,), True, 60000),
    _i("PAYTM", "One97 Communications", "Fintech", "Digital Payments", (MIDCAP,), True, 625),
    _i("IRCTC", "Indian Railway Catering & Tourism", "Infrastructure", "Travel Services", (MIDCAP,), True, 875),
    _i("IRFC", "Indian Railway Finance Corp", "Infrastructure", "Infrastructure Finance", (MIDCAP,), True, 6750),
    _i("RVNL", "Rail Vikas Nigam", "Infrastructure", "Rail EPC", (MIDCAP,), True, 2500),
    _i("HAL", "Hindustan Aeronautics", "Capital Goods", "Defence Aerospace", (MIDCAP,), True, 150),
    _i("BHEL", "Bharat Heavy Electricals", "Capital Goods", "Heavy Electricals", (MIDCAP,), True, 4000),
    _i("SAIL", "Steel Authority of India", "Metals & Mining", "Iron & Steel", (MIDCAP,), True, 13000),
    _i("NMDC", "NMDC", "Metals & Mining", "Mining", (MIDCAP,), True, 3000),
    _i("TATAPOWER", "Tata Power", "Power", "Power Generation", (MIDCAP,), True, 2500),
    _i("ADANIGREEN", "Adani Green Energy", "Power", "Renewable Energy", (MIDCAP,), True, 500),
    _i("AVENUE", "Avenue Supermarts (DMart)", "Retail", "Retail", (MIDCAP,), True, 350),
    _i("PAGEIND", "Page Industries", "Retail", "Apparel", (MIDCAP,), True, 25),
    _i("MUTHOOTFIN", "Muthoot Finance", "Financial Services", "Gold Loan NBFC", (MIDCAP, FINNIFTY), True, 400),
    _i("CDSL", "Central Depository Services", "Financial Services", "Capital Markets", (MIDCAP,), True, 475),
    _i("BSE", "BSE", "Financial Services", "Capital Markets", (MIDCAP,), True, 375),
    _i("ANGELONE", "Angel One", "Financial Services", "Broking", (MIDCAP,), True, 275),
    _i("SUZLON", "Suzlon Energy", "Power", "Renewable Energy", (SMALLCAP,), True, 8000),
)

BY_SYMBOL: dict[str, Instrument] = {i.symbol: i for i in INSTRUMENTS}

#: Index definitions. ``descriptive`` indices are computed from their
#: constituents; the rest are treated as synthetic market proxies in demo mode.
INDEX_MEMBERSHIP: dict[str, tuple[str, ...]] = {
    NIFTY50: tuple(i.symbol for i in INSTRUMENTS if NIFTY50 in i.indices),
    BANKNIFTY: tuple(i.symbol for i in INSTRUMENTS if BANKNIFTY in i.indices),
    FINNIFTY: tuple(i.symbol for i in INSTRUMENTS if FINNIFTY in i.indices)
    + ("HDFCLIFE", "SBILIFE", "BAJFINANCE", "MUTHOOTFIN"),
    MIDCAP: tuple(i.symbol for i in INSTRUMENTS if MIDCAP in i.indices),
    SMALLCAP: tuple(i.symbol for i in INSTRUMENTS if SMALLCAP in i.indices),
    # The 30 largest NIFTY 50 names stand in for the BSE 30. A synthetic
    # composite, labelled as such wherever it is shown.
    SENSEX: tuple(i.symbol for i in INSTRUMENTS if NIFTY50 in i.indices)[:30],
}

SECTORS: tuple[str, ...] = tuple(sorted({i.sector for i in INSTRUMENTS}))


def get_instrument(symbol: str) -> Instrument | None:
    return BY_SYMBOL.get(symbol.upper().strip())


def search_instruments(query: str, limit: int = 20) -> list[Instrument]:
    q = query.strip().lower()
    if not q:
        return list(INSTRUMENTS)[:limit]
    scored: list[tuple[int, Instrument]] = []
    for inst in INSTRUMENTS:
        sym = inst.symbol.lower()
        name = inst.name.lower()
        if sym == q:
            scored.append((0, inst))
        elif sym.startswith(q):
            scored.append((1, inst))
        elif q in name:
            scored.append((2, inst))
        elif q in inst.sector.lower():
            scored.append((3, inst))
    scored.sort(key=lambda pair: (pair[0], pair[1].symbol))
    return [inst for _, inst in scored[:limit]]


def fno_symbols() -> list[str]:
    return [i.symbol for i in INSTRUMENTS if i.fno]
