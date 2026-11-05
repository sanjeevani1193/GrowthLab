"""Independent raw-CSV history checks; never open experimental outcome fields."""
import csv
import json
import math
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from .acquire import sha256
from .experiment import quote, write_json
from .history import FEATURE_COLUMNS


def verify(root=Path('.'),sample_n=12):
    started=time.perf_counter();docs=root/'docs/causal/phase6'
    features=json.loads((docs/'feature_summary.json').read_text())
    receipt=json.loads((docs/'history_acquisition.json').read_text())
    if sha256(root/receipt['path'])!=receipt['sha256'] or sha256(root/features['feature_path'])!=features['feature_sha256']:
        raise ValueError('raw history/features changed')
    con=duckdb.connect(str(root/'data/retailhero/phase6/history.duckdb'),read_only=True)
    con.execute("SET memory_limit='512MB'");con.execute('SET threads=1')
    con.execute(f"SET temp_directory={quote(root/'data/retailhero/phase6/verification_spill')}")
    con.execute("SET max_temp_directory_size='2GB'")
    try:
        extra={}
        for name,predicate in [('quantity_negative','product_quantity<0'),('quantity_zero','product_quantity=0')]:
            extra[name]=con.execute(f'SELECT count(*) FROM history WHERE {predicate}').fetchone()[0]
        profiles=root/'data/retailhero/raw/clients.csv'
        extra['history_clients_missing_profile']=con.execute(f"SELECT count(*) FROM (SELECT DISTINCT client_id FROM history) h ANTI JOIN read_csv({quote(profiles)},all_varchar=true) c USING(client_id)").fetchone()[0]
        extra['profile_clients_missing_history']=con.execute(f"SELECT count(*) FROM read_csv({quote(profiles)},all_varchar=true) c ANTI JOIN (SELECT DISTINCT client_id FROM history) h USING(client_id)").fetchone()[0]
        extra['global_transaction_ids_reused_across_customers']=con.execute('SELECT count(*) FROM (SELECT transaction_id FROM transactions GROUP BY 1 HAVING count(*)>1)').fetchone()[0]
        extra['latest_feature_at_or_after_proxy_cutoff']=con.execute(f"SELECT count(*) FROM customer_features WHERE latest_feature_timestamp>=TIMESTAMP {quote(features['proxy_cutoff'])}").fetchone()[0]
        # Independently inspect raw basket text: monetary casting must not
        # silently round any value used in the spending features.
        raw_amount=con.execute(f"""SELECT
            count(*) FILTER(WHERE try_cast(purchase_sum AS DECIMAL(30,10)) IS NULL),
            count(*) FILTER(WHERE try_cast(purchase_sum AS DECIMAL(30,10)) != try_cast(purchase_sum AS DECIMAL(18,4)))
            FROM read_csv({quote(root/receipt['path'])},all_varchar=true)""").fetchone()
        extra['raw_basket_numeric_parse_failures']=raw_amount[0]
        extra['raw_basket_values_changed_by_decimal_18_4']=raw_amount[1]
        if any(raw_amount): raise ValueError('raw basket precision/parse check failed')
        columns=','.join(FEATURE_COLUMNS)
        rows=con.execute(f"SELECT client_id,{columns} FROM read_parquet({quote(root/features['feature_path'])}) WHERE split='train' ORDER BY sha256(client_id) LIMIT ?",[sample_n]).fetchall()
    finally:
        con.close()
    selected={r[0] for r in rows};events={i:[] for i in selected}
    cutoff=datetime.fromisoformat(features['proxy_cutoff'])
    scanned=0
    with (root/receipt['path']).open(newline='') as f:
        names=next(csv.reader([f.readline()]))
        for line in f:
            scanned+=1
            client=line.partition(',')[0]
            if client not in selected: continue
            r=dict(zip(names,next(csv.reader([line]))))
            ts=datetime.fromisoformat(r['transaction_datetime'])
            if ts<cutoff:
                events[client].append((r['transaction_id'],ts,Decimal(r['purchase_sum']),r['product_id'],r['store_id']))
    checked=0
    for row in rows:
        ev=events[row[0]];transactions={}
        for tx,ts,amount,product,store in ev:
            if tx in transactions and transactions[tx]!=(ts,amount): raise ValueError('sample inconsistent transaction')
            transactions[tx]=(ts,amount)
        valid=[amount for ts,amount in transactions.values() if amount>=0]
        days={ts.date() for ts,amount in transactions.values()}
        expected=[len(transactions),len(days),len({e[3] for e in ev}),len({e[4] for e in ev}),
                  float(sum(valid)),float(sum(valid)/len(valid)),
                  (cutoff-max(ts for ts,amount in transactions.values())).total_seconds()/86400,
                  len(transactions)/len(days)]
        if not all(math.isclose(float(a),float(b),rel_tol=1e-12,abs_tol=1e-8) for a,b in zip(row[1:],expected)):
            raise ValueError('independent history feature mismatch')
        checked+=len(expected)
    write_json(docs/'additional_history_checks.json',extra)
    result={'method':'Independent Python raw CSV scan; deterministic training-only customer sample selected by SHA256(client_id), no outcomes accessed.',
            'sample_customers':len(rows),'features_per_customer':len(FEATURE_COLUMNS),'comparisons':checked,
            'mismatches':0,'raw_rows_scanned':scanned,'elapsed_seconds':time.perf_counter()-started,
            'history_sha256':receipt['sha256'],'feature_sha256':features['feature_sha256']}
    write_json(docs/'history_verification.json',result)
    return result


if __name__=='__main__': print(json.dumps(verify(),indent=2))
