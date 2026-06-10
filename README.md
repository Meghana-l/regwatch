# RegWatch — Regulatory Reporting Control Dashboard

**Live demo → [meghana-l.github.io/regwatch](https://meghana-l.github.io/regwatch)**

A regulatory reporting control dashboard that mirrors what a global reporting team deals with daily — filing deadline tracking across 7 regulators, position reconciliation, exception triage, regulatory impact mapping, and a full audit trail.

---

## What it does

RegWatch runs a full control pipeline on every page load:

1. **Filing deadline tracker** — real calendar logic for SEC, CFTC, FCA, NFA, MAS, SFC, and KFB filings. Each deadline is color-coded by urgency with day counts and submission status
2. **Fetches live market prices** via Polygon.io (equities, FX, crypto)
3. **Generates synthetic trade positions** using those live prices across equities, FX, futures, and digital assets
4. **Runs a field-level reconciliation engine** — compares internal bookings against counterparty confirmations on price, quantity, commission, cash position, settlement status, and wallet addresses
5. **Maps exceptions to regulatory obligations** — each break is tagged with the regulators it affects (e.g. a settlement fail flags FCA CSDR; a quantity break on futures flags CFTC Large Trader Report)
6. **Classifies each exception** with root cause analysis and a recommended control action
7. **Maintains a live audit trail** — every escalation and resolution is logged with timestamp and action taken

Data is fully randomized on every run — no two loads show the same positions or exceptions.

---

## Architecture

```
Polygon.io REST API        real closing prices (equities, FX, crypto)
        ↓
Trade Generator            synthetic positions built on live prices
        ↓
Matching Engine            field-level comparison with tolerance thresholds
        ↓
Regulatory Impact Mapper   each exception tagged to affected regulators
        ↓
Exception Classifier       rule-based ops logic (browser) / Claude API (local)
        ↓
Control Dashboard          live, runs entirely in browser — no server needed
```

---

## Regulators covered

| Regulator | Filing | Frequency |
|---|---|---|
| SEC | Form 13F | Quarterly |
| SEC | Form PF | Quarterly |
| CFTC | Large Trader Report | Daily |
| CFTC | Form CPO-PQR | Quarterly |
| FCA | MiFID II Transaction Report | Daily |
| NFA | FOCUS Report | Monthly |
| MAS | MAS 610 | Monthly |
| SFC | Fund Manager Return | Quarterly |

---

## Break types detected

| Break type | Detection logic | Regulatory impact |
|---|---|---|
| Price mismatch | > 0.1% delta between internal and CP price | SEC, FCA |
| Rate discrepancy | FX settlement rate differs | CFTC, FCA, MAS |
| Quantity break | Unit count mismatch (zero tolerance) | CFTC, NFA |
| Commission error | Invoiced commission > $0.50 over internal calc | NFA FOCUS |
| Nostro break | Cash position delta > $1.00 | Internal controls |
| Settlement fail | Counterparty status = FAIL vs internal PENDING | FCA CSDR |
| Wallet mismatch | Digital asset wallet address differs | CFTC, SEC |

---

## Running the full AI pipeline locally

The live site uses rule-based classification. For full Claude AI classification:

```bash
pip install anthropic

python3 generate_trades.py      # generates 200 synthetic trades into SQLite
python3 match_engine.py         # SQL matching, flags breaks with regulatory mapping

export ANTHROPIC_API_KEY=your_key_here
python3 ai_classifier.py        # Claude classifies each exception with root cause,
                                # recommended action, confidence score, escalation flag
```

---

## Setting up live prices

1. Sign up free at [polygon.io](https://polygon.io)
2. Copy your API key
3. Open `index.html`, find:
   ```js
   const POLYGON_KEY = 'YOUR_POLYGON_API_KEY';
   ```
4. Replace with your key and save

Without a key the dashboard falls back to realistic static prices and still runs the full pipeline.

---

## File structure

```
regwatch/
├── index.html            ← Live dashboard (GitHub Pages)
├── generate_trades.py    ← Layer 1: synthetic trade generator
├── match_engine.py       ← Layer 2: SQL matching + regulatory mapping
├── ai_classifier.py      ← Layer 3: Claude API exception classifier
├── regwatch.db           ← SQLite DB (generated locally)
└── README.md
```

---

## Built by

**Meghana Lakshminarayana Swamy**
MS Business Analytics · University of New Haven · GPA 3.81 · May 2026
ECBA Certified · [meghana-l.github.io](https://meghana-l.github.io) · meghana.drlnswamy@gmail.com
