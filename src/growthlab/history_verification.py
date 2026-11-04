"""Independent, bounded Python recalculation from raw CSV customer histories.

This verifier does not call the feature SQL or read the cleaned event layer.
It stores only selected histories in memory and publishes no customer IDs.
"""

import csv
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta

from growthlab.acquire import save_json


def python_customer(raw_rows):
    """Hand-checkable reference implementation of the approved twelve features."""
    # Each tuple contains all nine original decoded CSV strings. Empty strings
    # represent SQL NULLs from this source and remain part of the duplicate key.
    unique=set(raw_rows)
    events=[(datetime.strptime(r[0],"%Y-%m-%d %H:%M:%S UTC"),r) for r in unique]
    first_seen=min(t for t,_ in events)
    prediction=first_seen+timedelta(days=7)
    end=first_seen+timedelta(days=37)
    observed=[(t,r) for t,r in events if first_seen<=t<prediction]
    kinds=Counter(r[1] for _,r in observed)
    viewed=[r for _,r in observed if r[1]=="view"]
    valid_prices=[float(r[6]) for r in viewed if r[6] and math.isfinite(float(r[6])) and float(r[6])>=0]
    nviews=kinds["view"]
    return {
        "first_seen":first_seen,"prediction_time":prediction,"outcome_end":end,
        "n_views_7d":nviews,"n_carts_7d":kinds["cart"],"n_removals_7d":kinds["remove_from_cart"],
        "n_purchases_7d":kinds["purchase"],"n_viewed_products_7d":len({int(r[2]) for r in viewed}),
        "active_24h_bins_7d":len({int((t-first_seen).total_seconds()//86400) for t,_ in observed}),
        "n_sessions_7d":len({r[8] for _,r in observed if r[8]}),
        "hours_since_last_event":(prediction-max(t for t,_ in observed)).total_seconds()/3600,
        "cart_view_ratio_7d":kinds["cart"]/nviews if nviews else 0.0,
        "purchase_view_ratio_7d":kinds["purchase"]/nviews if nviews else 0.0,
        "median_view_price_7d":statistics.median(valid_prices) if valid_prices else None,
        "view_price_unavailable_7d":int(not valid_prices),
        "purchased_next_30d":int(any(r[1]=="purchase" and prediction<=t<end for t,r in events)),
        "qa_total_events_7d":len(observed),
        "qa_negative_price_events_7d":sum(float(r[6])<0 for _,r in observed),
        "qa_zero_price_events_7d":sum(float(r[6])==0 for _,r in observed),
        "qa_missing_session_events_7d":sum(not r[8] for _,r in observed),
    }


def verify_histories(con,root,work):
    # Label strata are used solely to exercise label verification, not to design
    # features, tune a threshold, or estimate predictive performance.
    selected=set()
    for split in ("train","validation","test"):
        for label in (0,1):
            selected.update(r[0] for r in con.execute("""SELECT user_id FROM customer_features
                WHERE primary_split=? AND purchased_next_30d=? ORDER BY user_id LIMIT 2""",[split,label]).fetchall())
    for condition in ("qa_zero_price_events_7d>0","qa_negative_price_events_7d>0",
                      "qa_missing_session_events_7d>0","view_price_unavailable_7d=1",
                      "feature_gap","outcome_gap"):
        selected.update(r[0] for r in con.execute("SELECT user_id FROM customer_features WHERE "+condition+" ORDER BY user_id LIMIT 1").fetchall())
    histories={user:[] for user in selected}
    scanned=0
    for path in sorted((root/"data/raw").glob("*.csv")):
        with path.open(newline="") as stream:
            reader=csv.reader(stream)
            next(reader)
            for row in reader:
                scanned+=1
                user=int(row[7])
                if user in histories:
                    histories[user].append(tuple(row))
    checked=[]
    for user,history in sorted(histories.items()):
        reference=python_customer(history)
        fields=list(reference)
        actual=con.execute("SELECT "+",".join(fields)+" FROM customer_features WHERE user_id=?",[user]).fetchone()
        assert actual is not None
        for name,got in zip(fields,actual):
            expected=reference[name]
            if isinstance(expected,float):
                assert got is not None and math.isclose(got,expected,rel_tol=1e-10,abs_tol=1e-10),(user,name,got,expected)
            else:
                assert got==expected,(user,name,got,expected)
        checked.append({"user_id":user,"raw_history_events":len(history),"verified_values":reference})
    save_json(work/"history_checks.json",checked)
    return {"customers_checked":len(checked),"raw_events_scanned":scanned,
            "fields_checked_per_customer":len(checked[0]["verified_values"]),
            "mismatches":0,"method":"Independent Python exact-tuple deduplication and datetime/statistics aggregation from all five raw CSVs",
            "selection":"Two positive and two negative customers per primary split, plus deterministic price/session/gap edge cases; overlaps removed",
            "customer_details_path":"data/features/phase2/history_checks.json (local, ignored)"}
