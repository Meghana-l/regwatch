"""
RegWatch — Layer 1: Synthetic Trade Data Generator
Generates realistic internal + counterparty trade records across
equities, FX, futures, and digital assets with intentional breaks.
Writes to regwatch.db (SQLite).
"""

import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = "regwatch.db"

EQUITIES     = [("AAPL",189.50),("MSFT",415.20),("NVDA",875.30),("GS",438.10),("JPM",198.40),("BAC",38.90),("AMZN",185.20),("META",512.30)]
FX_PAIRS     = [("EUR/USD",1.0812),("GBP/USD",1.2740),("USD/JPY",156.80),("AUD/USD",0.6530),("USD/CHF",0.9015)]
FUTURES      = [("ES",5280.00),("NQ",18450.00),("CL",82.40),("GC",2340.00),("ZN",110.50)]
DIGITAL      = [("BTC/USD",67500.00),("ETH/USD",3420.00),("SOL/USD",145.00)]
COUNTERPARTIES = ["GS Prime","JPM Clearing","Citi Sec","Morgan Sec","Barclays","UBS Sec"]

# Regulatory mapping per asset class and break type
REG_MAP = {
    "equity":  ["SEC","FCA"],
    "fx":      ["CFTC","FCA","MAS"],
    "futures": ["CFTC","NFA"],
    "digital": ["CFTC","SEC"],
}
REG_OVERRIDE = {
    "settlement_fail": ["FCA"],   # FCA CSDR reportable
    "wallet_mismatch": ["CFTC"],  # CFTC digital asset reporting
}

BREAK_PROB = {
    "price_mismatch":   0.08,
    "quantity_break":   0.06,
    "commission_error": 0.05,
    "nostro_break":     0.04,
    "settlement_fail":  0.03,
    "wallet_mismatch":  0.07,
    "rate_discrepancy": 0.07,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_trades (
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    price REAL, quantity REAL, notional REAL, commission REAL,
    cash_position REAL, settlement_status TEXT, settlement_date TEXT,
    counterparty TEXT, wallet_address TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS counterparty_trades (
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    price REAL, quantity REAL, notional REAL, commission REAL,
    cash_position REAL, settlement_status TEXT, settlement_date TEXT,
    counterparty TEXT, wallet_address TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT, asset_class TEXT, instrument TEXT,
    break_type TEXT, severity TEXT,
    internal_value TEXT, counterparty_value TEXT,
    break_amount REAL, regulators TEXT,
    ai_classification TEXT, ai_action TEXT, confidence INTEGER,
    status TEXT DEFAULT 'open', created_at TEXT
);
"""

def get_regulators(asset_class, break_type):
    regs = list(REG_MAP.get(asset_class, ["SEC"]))
    if break_type in REG_OVERRIDE:
        regs += REG_OVERRIDE[break_type]
    return ",".join(sorted(set(regs))[:2])

def generate(n_trades=200, seed=None):
    random.seed(seed or datetime.now().timestamp())
    base_date = datetime(2026, 5, 22, 9, 0, 0)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM internal_trades")
    conn.execute("DELETE FROM counterparty_trades")
    conn.execute("DELETE FROM exceptions")
    conn.commit()

    asset_pool = ["equity"]*5 + ["fx"]*3 + ["futures"]*2 + ["digital"]*2
    seen = set()
    internal_rows, cp_rows, exc_rows = [], [], []

    for _ in range(n_trades):
        tid = f"TRD-{random.randint(1000,9999)}"
        while tid in seen: tid = f"TRD-{random.randint(1000,9999)}"
        seen.add(tid)

        asset = random.choice(asset_pool)
        ts = (base_date + timedelta(seconds=random.randint(0,28800))).strftime("%Y-%m-%d %H:%M:%S")
        sdate = (base_date + timedelta(days=2 if asset!='digital' else 1)).strftime("%Y-%m-%d")
        wallet = None

        if asset == "equity":
            inst, bp = random.choice(EQUITIES)
            price = round(bp * random.uniform(0.995,1.005), 2)
            qty   = random.randint(50,8000)
            comm  = round(price*qty*random.uniform(0.0003,0.001), 2)
        elif asset == "fx":
            inst, bp = random.choice(FX_PAIRS)
            price = round(bp * random.uniform(0.9995,1.0005), 5)
            qty   = random.randint(50000,8000000)
            comm  = round(price*qty*0.00002, 2)
        elif asset == "futures":
            inst, bp = random.choice(FUTURES)
            price = round(bp * random.uniform(0.998,1.002), 2)
            qty   = random.randint(1,300)
            comm  = round(qty * random.uniform(1.5,5.0), 2)
        else:
            inst, bp = random.choice(DIGITAL)
            price = round(bp * random.uniform(0.997,1.003), 2)
            qty   = round(random.uniform(0.005,15.0), 4)
            comm  = round(price*qty*random.uniform(0.001,0.003), 2)
            wallet = "0x" + "".join(random.choices("0123456789ABCDEF",k=10))

        notional = round(price*qty, 2)
        cp_name  = random.choice(COUNTERPARTIES)

        internal = [tid, asset, inst, price, qty, notional, comm, notional, "PENDING", sdate, cp_name, wallet, ts]
        cp       = list(internal)
        break_type = None

        eligible = [(k,v) for k,v in BREAK_PROB.items()
                    if not (k=="wallet_mismatch" and asset!="digital")
                    and not (k=="rate_discrepancy" and asset!="fx")]

        for bt, prob in eligible:
            if random.random() < prob:
                if bt == "price_mismatch":
                    d = random.uniform(0.005,0.03) * random.choice([-1,1])
                    cp[3] = round(price*(1+d), 5)
                elif bt == "quantity_break":
                    cp[4] = round(qty - random.randint(1,max(1,int(qty*0.08))), 4)
                elif bt == "commission_error":
                    cp[6] = round(comm * random.uniform(1.2,2.0), 2)
                elif bt == "nostro_break":
                    cp[7] = round(notional * random.uniform(0.80,0.97), 2)
                elif bt == "settlement_fail":
                    cp[8] = "FAIL"
                elif bt == "wallet_mismatch" and wallet:
                    cp[11] = wallet[:-3] + "".join(random.choices("0123456789ABCDEF",k=3))
                elif bt == "rate_discrepancy":
                    cp[3] = round(price * random.uniform(0.980,0.999), 5)
                break_type = bt
                break

        internal_rows.append(tuple(internal))
        cp_rows.append(tuple(cp))

        if break_type:
            if break_type in ("price_mismatch","rate_discrepancy"):
                bamt = abs(internal[3]-cp[3]) * qty
                iv, cv = str(internal[3]), str(cp[3])
            elif break_type == "quantity_break":
                bamt = abs(internal[4]-cp[4]) * price
                iv, cv = str(internal[4]), str(cp[4])
            elif break_type == "commission_error":
                bamt = abs(internal[6]-cp[6])
                iv, cv = str(internal[6]), str(cp[6])
            elif break_type == "nostro_break":
                bamt = abs(internal[7]-cp[7])
                iv, cv = str(internal[7]), str(cp[7])
            elif break_type == "settlement_fail":
                bamt = notional
                iv, cv = "PENDING", "FAIL"
            else:
                bamt = notional
                iv, cv = str(internal[11]), str(cp[11])

            sev = "critical" if bamt>500000 else "high" if bamt>100000 else "medium" if bamt>10000 else "low"
            regs = get_regulators(asset, break_type)
            exc_rows.append((tid,asset,inst,break_type,sev,iv,cv,round(bamt,2),regs,None,None,None,"open",datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    cols = "(trade_id,asset_class,instrument,price,quantity,notional,commission,cash_position,settlement_status,settlement_date,counterparty,wallet_address,timestamp)"
    conn.executemany(f"INSERT INTO internal_trades {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", internal_rows)
    conn.executemany(f"INSERT INTO counterparty_trades {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", cp_rows)
    ecols = "(trade_id,asset_class,instrument,break_type,severity,internal_value,counterparty_value,break_amount,regulators,ai_classification,ai_action,confidence,status,created_at)"
    conn.executemany(f"INSERT INTO exceptions {ecols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", exc_rows)
    conn.commit()

    total = len(internal_rows)
    exc   = len(exc_rows)
    print(f"✓ Generated {total} trades → {exc} exceptions ({round((total-exc)/total*100,1)}% match rate)")
    print(f"  {sum(1 for r in exc_rows if r[4]=='critical')} critical · {sum(1 for r in exc_rows if r[4]=='high')} high · {sum(1 for r in exc_rows if r[4]=='medium')} medium · {sum(1 for r in exc_rows if r[4]=='low')} low")
    conn.close()

if __name__ == "__main__":
    generate(200)
