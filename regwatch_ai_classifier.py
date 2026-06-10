"""
RegWatch — Layer 3: AI Exception Classifier
For each unclassified exception, calls Claude API to return:
  - Root cause analysis
  - Recommended control action
  - Regulatory filing impact
  - Confidence score
  - Escalation flag
Requires: ANTHROPIC_API_KEY environment variable
"""

import sqlite3
import json
import time
import anthropic

DB_PATH = "regwatch.db"
MODEL   = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a senior regulatory reporting analyst at a global hedge fund.
You receive trade exception details from a reconciliation system and must classify each one
with specific focus on regulatory reporting impact (SEC, CFTC, FCA, NFA, MAS, SFC, KFB).

Respond ONLY with a valid JSON object — no preamble, no markdown, no extra text.

Required fields:
{
  "root_cause": "one sentence — the likely technical or operational reason for this break",
  "recommended_action": "one sentence — what the ops/compliance team should do right now",
  "regulatory_impact": "one sentence — which filing(s) are affected and how",
  "escalate": true/false,
  "confidence": integer 60-99,
  "tags": ["TAG1", "TAG2"]
}

Guidelines:
- Be specific to the asset class, break type, and listed regulators
- Always mention the specific regulatory filing affected (e.g. CFTC Large Trader, FCA MiFID II, SEC 13F)
- confidence above 90 = clear-cut case
- confidence 75-89 = probable cause, verify
- confidence 60-74 = uncertain, needs investigation
- escalate=true for critical severity, settlement fails, or wallet mismatches
"""

def build_prompt(exc):
    return f"""Trade exception:

Trade ID:         {exc['trade_id']}
Asset class:      {exc['asset_class']}
Instrument:       {exc['instrument']}
Break type:       {exc['break_type']}
Severity:         {exc['severity']}
Internal value:   {exc['internal_value']}
Counterparty val: {exc['counterparty_value']}
Break amount:     ${exc['break_amount']:,.2f}
Regulators:       {exc['regulators']}

Classify this exception and return the JSON response."""


def classify(client, exc):
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role":"user","content":build_prompt(exc)}]
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        result = json.loads(raw)
        for k in ["root_cause","recommended_action","regulatory_impact","escalate","confidence","tags"]:
            if k not in result: raise ValueError(f"Missing: {k}")
        return result
    except Exception as e:
        return {"root_cause":"Classification failed — manual review required",
                "recommended_action":"Escalate to senior regulatory reporting analyst",
                "regulatory_impact":"Filing impact unknown — escalate immediately",
                "escalate":True,"confidence":60,"tags":["MANUAL","REVIEW"],"_error":str(e)}


def run(limit=None):
    conn   = sqlite3.connect(DB_PATH)
    client = anthropic.Anthropic()

    sql = "SELECT id,trade_id,asset_class,instrument,break_type,severity,internal_value,counterparty_value,break_amount,regulators FROM exceptions WHERE ai_classification IS NULL"
    if limit: sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    cols = ["id","trade_id","asset_class","instrument","break_type","severity","internal_value","counterparty_value","break_amount","regulators"]
    exceptions = [dict(zip(cols,r)) for r in rows]

    if not exceptions:
        print("No unclassified exceptions found.")
        conn.close(); return []

    print(f"Classifying {len(exceptions)} exceptions with Claude ({MODEL})...\n")
    results = []

    for i, exc in enumerate(exceptions, 1):
        print(f"  [{i:>2}/{len(exceptions)}] {exc['trade_id']} | {exc['break_type']:<22} | ${exc['break_amount']:>12,.2f} | {exc['severity']:<8} | regs: {exc['regulators']}", end=" ... ", flush=True)
        result = classify(client, exc)
        ai_class  = result["root_cause"]
        ai_action = f"[{','.join(result.get('tags',[]))}] {result['recommended_action']} | REG: {result['regulatory_impact']}"
        conf      = result["confidence"]
        conn.execute("UPDATE exceptions SET ai_classification=?,ai_action=?,confidence=? WHERE id=?",
                     (ai_class, ai_action, conf, exc["id"]))
        conn.commit()
        print(f"conf={conf}%")
        results.append({**exc, **result})
        if i < len(exceptions): time.sleep(0.3)

    conn.close()
    print(f"\n✓ Done — {len(results)} exceptions classified")
    return results


def print_report():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT trade_id,asset_class,instrument,break_type,severity,break_amount,
               regulators,confidence,ai_classification,ai_action,status
        FROM exceptions
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, break_amount DESC
    """).fetchall()
    conn.close()
    icon = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}
    print(f"\n{'='*80}")
    print(f"  REGWATCH — AI-CLASSIFIED EXCEPTION REPORT")
    print(f"{'='*80}")
    for r in rows:
        tid,ac,inst,bt,sev,amt,regs,conf,cls,action,status = r
        print(f"\n  {icon.get(sev,'○')} {tid} | {inst:<10} | {bt:<22} | ${amt:>12,.2f} | {sev.upper()}")
        print(f"     Regulators:  {regs}")
        print(f"     Root cause:  {cls}")
        print(f"     Action:      {action}")
        print(f"     Confidence:  {conf}% | Status: {status}")
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    run()
    print_report()
