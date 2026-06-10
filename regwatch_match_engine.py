"""
RegWatch — Layer 2: SQL Matching & Reconciliation Engine
Compares internal vs counterparty trades field-by-field,
flags breaks above tolerance thresholds, maps each break
to affected regulators, and writes to the exceptions table.
"""

import sqlite3
from datetime import datetime

DB_PATH = "regwatch.db"

TOLERANCES = {"price": 0.001, "quantity": 0, "commission": 0.50, "cash": 1.00}

REG_MAP = {
    "equity":  ["SEC", "FCA"],
    "fx":      ["CFTC", "FCA", "MAS"],
    "futures": ["CFTC", "NFA"],
    "digital": ["CFTC", "SEC"],
}
REG_OVERRIDE = {
    "settlement_fail": ["FCA"],
    "wallet_mismatch": ["CFTC"],
}

def get_regulators(asset_class, break_type):
    regs = list(REG_MAP.get(asset_class, ["SEC"]))
    if break_type in REG_OVERRIDE:
        regs += REG_OVERRIDE[break_type]
    return ",".join(sorted(set(regs))[:2])


def match_trades(conn):
    sql = """
    SELECT i.trade_id, i.asset_class, i.instrument, i.counterparty,
           i.price, c.price, i.quantity, c.quantity,
           i.commission, c.commission, i.cash_position, c.cash_position,
           i.settlement_status, c.settlement_status,
           i.wallet_address, c.wallet_address, i.notional
    FROM internal_trades i
    JOIN counterparty_trades c ON i.trade_id = c.trade_id
    """
    rows = conn.execute(sql).fetchall()
    cols = ["trade_id","asset_class","instrument","counterparty",
            "i_price","c_price","i_qty","c_qty","i_comm","c_comm",
            "i_cash","c_cash","i_settle","c_settle","i_wallet","c_wallet","notional"]
    breaks = []
    for row in rows:
        r = dict(zip(cols, row))
        breaks.extend(check(r))
    return breaks


def check(r):
    found = []
    tid, ac, inst, cp = r["trade_id"], r["asset_class"], r["instrument"], r["counterparty"]

    price_pct = abs((r["i_price"] or 0) - (r["c_price"] or 0)) / (r["i_price"] or 1)
    if price_pct > TOLERANCES["price"]:
        bamt = price_pct * (r["i_price"] or 0) * (r["i_qty"] or 1)
        bt = "rate_discrepancy" if ac == "fx" else "price_mismatch"
        found.append(build(tid, ac, inst, cp, bt, "price", r["i_price"], r["c_price"], bamt))

    qty_delta = abs((r["i_qty"] or 0) - (r["c_qty"] or 0))
    if qty_delta > TOLERANCES["quantity"]:
        found.append(build(tid, ac, inst, cp, "quantity_break", "quantity", r["i_qty"], r["c_qty"], qty_delta*(r["i_price"] or 1)))

    comm_delta = abs((r["i_comm"] or 0) - (r["c_comm"] or 0))
    if comm_delta > TOLERANCES["commission"]:
        found.append(build(tid, ac, inst, cp, "commission_error", "commission", r["i_comm"], r["c_comm"], comm_delta))

    cash_delta = abs((r["i_cash"] or 0) - (r["c_cash"] or 0))
    if cash_delta > TOLERANCES["cash"] and comm_delta <= TOLERANCES["commission"]:
        found.append(build(tid, ac, inst, cp, "nostro_break", "cash_position", r["i_cash"], r["c_cash"], cash_delta))

    if r["i_settle"] != r["c_settle"]:
        found.append(build(tid, ac, inst, cp, "settlement_fail", "settlement_status", r["i_settle"], r["c_settle"], r["notional"] or 0))

    if ac == "digital" and r["i_wallet"] and r["c_wallet"] and r["i_wallet"] != r["c_wallet"]:
        found.append(build(tid, ac, inst, cp, "wallet_mismatch", "wallet_address", r["i_wallet"], r["c_wallet"], r["notional"] or 0))

    return found


def build(trade_id, asset_class, instrument, counterparty, break_type, field, iv, cv, amt):
    a = abs(amt)
    sev = "critical" if a>500000 else "high" if a>100000 else "medium" if a>10000 else "low"
    regs = get_regulators(asset_class, break_type)
    return {"trade_id":trade_id,"asset_class":asset_class,"instrument":instrument,
            "counterparty":counterparty,"break_type":break_type,"field":field,
            "internal_value":str(iv),"counterparty_value":str(cv),
            "break_amount":round(a,2),"severity":sev,"regulators":regs,"status":"open",
            "created_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def write_exceptions(conn, breaks):
    conn.execute("DELETE FROM exceptions")
    sql = """INSERT INTO exceptions
        (trade_id,asset_class,instrument,break_type,severity,internal_value,
         counterparty_value,break_amount,regulators,ai_classification,ai_action,confidence,status,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)"""
    for b in breaks:
        conn.execute(sql,(b["trade_id"],b["asset_class"],b["instrument"],b["break_type"],
                          b["severity"],b["internal_value"],b["counterparty_value"],
                          b["break_amount"],b["regulators"],b["status"],b["created_at"]))
    conn.commit()


def run():
    conn = sqlite3.connect(DB_PATH)
    print("Running SQL matching engine...")
    breaks = match_trades(conn)
    write_exceptions(conn, breaks)

    total = conn.execute("SELECT COUNT(*) FROM internal_trades").fetchone()[0]
    unique_exc = len({b["trade_id"] for b in breaks})
    exp = sum(b["break_amount"] for b in breaks)
    mr  = round((total-unique_exc)/total*100,1) if total else 0

    reg_counts = {}
    for b in breaks:
        for r in b["regulators"].split(","):
            reg_counts[r] = reg_counts.get(r,0)+1

    print(f"\n{'='*55}")
    print(f"  REGWATCH — RECONCILIATION SUMMARY · {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*55}")
    print(f"  Total trades:       {total:>6}")
    print(f"  Matched (clean):    {total-unique_exc:>6}  ({mr}%)")
    print(f"  Exceptions:         {len(breaks):>6}")
    print(f"  Total exposure:     ${exp:>14,.2f}")
    sev_order = ["critical","high","medium","low"]
    sev_counts = {}
    for b in breaks: sev_counts[b["severity"]] = sev_counts.get(b["severity"],0)+1
    print(f"\n  By severity:")
    for s in sev_order:
        if sev_counts.get(s): print(f"    {s:<10} {sev_counts[s]:>3}")
    print(f"\n  By regulator affected:")
    for r,n in sorted(reg_counts.items(),key=lambda x:-x[1]):
        print(f"    {r:<8} {n:>3} exceptions")
    print(f"{'='*55}\n")
    conn.close()
    return breaks


if __name__ == "__main__":
    run()
