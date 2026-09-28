"""Reproduce the ambiguity numbers in the case study from the bundled NSE lists."""
import re

import pandas as pd

from mandate_gate import resolve
from mandate_gate.instruments import company_count

df = pd.read_csv("data/nse_instruments.csv").fillna("")
eq = df[df.kind == "EQUITY"]
names = eq["name"].str.strip().str.title().drop_duplicates()
first = names.map(lambda n: (re.findall(r"[a-z0-9&]+", n.lower()) or [""])[0])
shared = first.map(first.value_counts()) > 1

print(f"Companies on the list: {len(names):,}")
print(f"Share whose first word is shared with another listed company: {shared.mean():.1%} ({shared.sum()} companies)")
for word in ["tata", "reliance", "bajaj", "jindal", "mahindra", "adani", "birla"]:
    print(f"  '{word}' matches {company_count(resolve(word))} companies")
print(f"ETFs tracking the Nifty 50: {len(resolve('nifty', want_etf=True))}")
print(f"Gold ETFs: {len(resolve('gold'))}")
