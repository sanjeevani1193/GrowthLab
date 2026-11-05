"""Acquire the official purchase-history member and audit/aggregate on disk."""
import argparse
import json
import platform
import resource
import shutil
import struct
import time
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .acquire import ARCHIVE, RangeReader, sha256
from .experiment import quote, records, verify_inputs, verify_split, write_json


def acquire_history(root=Path('.')):
    docs = root/'docs/causal/phase6'
    docs.mkdir(parents=True, exist_ok=True)
    receipt = docs/'history_acquisition.json'
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if sha256(root/saved['path']) != saved['sha256']:
            raise ValueError('history hash mismatch')
        return saved
    path = root/'data/retailhero/raw/purchases.csv'
    if path.exists():
        raise FileExistsError('unmanifested purchase history; refusing overwrite')
    if shutil.disk_usage(root).free < 12*1024**3:
        raise RuntimeError('require 12 GiB free for raw, audit database, and spill margin')
    remote = RangeReader(ARCHIVE)
    previous = json.loads((root/'docs/causal/phase5/acquisition.json').read_text())
    if remote.etag != previous['archive_etag'] or remote.size != previous['archive_bytes']:
        raise ValueError('official archive differs from Phase 5')
    with zipfile.ZipFile(remote) as z:
        info = z.getinfo('data/purchases.csv')
    if info.compress_type != zipfile.ZIP_DEFLATED or info.flag_bits & 1:
        raise ValueError('unsupported archive compression/encryption')
    remote.seek(info.header_offset)
    header = remote.read(30)
    if header[:4] != b'PK\x03\x04':
        raise ValueError('invalid local ZIP header')
    name_len, extra_len = struct.unpack('<HH', header[26:30])
    start = info.header_offset+30+name_len+extra_len
    end = start+info.compress_size-1
    req = urllib.request.Request(ARCHIVE, headers={'Range':f'bytes={start}-{end}', 'If-Match':remote.etag})
    part = path.with_suffix('.csv.part')
    crc, size, compressed = 0, 0, 0
    decoder = zlib.decompressobj(-15)
    started = time.perf_counter()
    with urllib.request.urlopen(req,timeout=90) as response, part.open('xb') as out:
        if (response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{remote.size}'
                or response.headers.get('ETag') != remote.etag):
            raise ValueError('server ignored immutable member range')
        while block := response.read(1024*1024):
            compressed += len(block)
            while block:
                expanded = decoder.decompress(block, 4*1024*1024)
                block = decoder.unconsumed_tail
                out.write(expanded)
                size += len(expanded)
                crc = zlib.crc32(expanded, crc)
        tail = decoder.flush()
        out.write(tail); size += len(tail); crc = zlib.crc32(tail,crc)
    if not decoder.eof or decoder.unused_data or size != info.file_size or compressed != info.compress_size or crc != info.CRC:
        raise ValueError('history decompression/size/CRC verification failed')
    part.rename(path)
    result = {'retrieved_at_utc':datetime.now(timezone.utc).isoformat(), 'archive_url':ARCHIVE,
              'archive_etag':remote.etag,'archive_bytes':remote.size,'member':info.filename,
              'path':str(path.relative_to(root)), 'bytes':size,'compressed_member_bytes':compressed,
              'zip_crc32':f'{crc:08x}','sha256':sha256(path),
              'elapsed_seconds':time.perf_counter()-started,
              'source_timing_evidence':'Official competition describes purchases as prior to communication. No exact campaign cutoff or assignment protocol supplied.',
              'attribution':previous['attribution'],'license':previous['license']}
    write_json(receipt,result)
    return result


def connection(root):
    work=root/'data/retailhero/phase6';work.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(work/'history.duckdb'))
    con.execute("SET threads=1")
    con.execute("SET memory_limit='512MB'")
    con.execute(f"SET temp_directory={quote(work/'spill')}")
    con.execute("SET max_temp_directory_size='8GB'")
    return con


def load_history(con, path):
    # Explicit types prevent identifiers being converted to numbers; DECIMAL
    # retains source monetary precision. Parsing errors fail rather than skip.
    columns = {'client_id':'VARCHAR','transaction_id':'VARCHAR','transaction_datetime':'TIMESTAMP',
               'regular_points_received':'DECIMAL(18,4)','express_points_received':'DECIMAL(18,4)',
               'regular_points_spent':'DECIMAL(18,4)','express_points_spent':'DECIMAL(18,4)',
               'purchase_sum':'DECIMAL(18,4)','store_id':'VARCHAR','product_id':'VARCHAR',
               'product_quantity':'DECIMAL(18,4)','trn_sum_from_iss':'DECIMAL(18,4)',
               'trn_sum_from_red':'DECIMAL(18,4)'}
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='history'").fetchone()[0]:
        return
    schema='{'+','.join(f"'{k}':'{v}'" for k,v in columns.items())+'}'
    con.execute(f"CREATE TABLE history AS SELECT * FROM read_csv({quote(path)},header=true,columns={schema})")


def audit_history(con):
    schema=records(con,'DESCRIBE history')
    fields=[r['column_name'] for r in schema]
    missing={c:con.execute(f'SELECT count(*) FROM history WHERE "{c}" IS NULL').fetchone()[0] for c in fields}
    stats=records(con,"""SELECT count(*) AS rows, count(DISTINCT client_id) AS users,
      cast(min(transaction_datetime) AS VARCHAR) AS first_timestamp,
      cast(max(transaction_datetime) AS VARCHAR) AS last_timestamp,
      cast(min(purchase_sum) AS DOUBLE) AS min_purchase_sum,
      cast(max(purchase_sum) AS DOUBLE) AS max_purchase_sum,
      count(*) FILTER (WHERE purchase_sum<0) AS negative_price_rows,
      count(*) FILTER (WHERE purchase_sum=0) AS zero_price_rows,
      count(*) FILTER (WHERE product_quantity<=0) AS nonpositive_quantity_rows,
      count(*) FILTER (WHERE NOT regexp_full_match(client_id,'[0-9a-f]{10}')) AS malformed_client_ids
      FROM history""")[0]
    # Materialize one record per customer/transaction. Validate repeated totals
    # before summing them; never sum a basket total once per item row.
    con.execute("""CREATE OR REPLACE TABLE transactions AS SELECT client_id,transaction_id,
        min(transaction_datetime) AS ts, max(transaction_datetime) AS last_ts,
        count(DISTINCT transaction_datetime) AS n_timestamps,
        count(DISTINCT store_id) AS n_stores,
        min(purchase_sum) AS amount, max(purchase_sum) AS largest_amount,
        count(DISTINCT purchase_sum) AS n_amounts,
        count(*) AS item_rows, count(purchase_sum) AS amount_rows
        FROM history GROUP BY client_id,transaction_id""")
    txn=records(con,"""SELECT count(*) AS transactions,
        count(*) FILTER (WHERE n_timestamps!=1) AS inconsistent_timestamps,
        count(*) FILTER (WHERE n_stores!=1) AS inconsistent_stores,
        count(*) FILTER (WHERE n_amounts!=1 OR amount_rows!=item_rows) AS inconsistent_amounts,
        count(*) FILTER (WHERE amount<0) AS negative_amount_transactions,
        count(*) FILTER (WHERE amount=0) AS zero_amount_transactions,
        max(item_rows) AS max_items_per_transaction FROM transactions""")[0]
    # Duplicates of the explicitly typed rows; raw text remains immutable.
    group=','.join('"'+f+'"' for f in fields)
    duplicate_excess=con.execute(f'SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) AS n FROM history GROUP BY {group} HAVING count(*)>1)').fetchone()[0]
    dates=records(con,"SELECT cast(cast(transaction_datetime AS DATE) AS VARCHAR) AS day,count(*) AS rows FROM history GROUP BY 1 ORDER BY 1")
    stats.update({'schema':schema,'missing':missing,'transaction_quality':txn,
                  'typed_duplicate_row_excess':duplicate_excess,'events_by_day':dates})
    if any(missing[k] for k in ['client_id','transaction_id','transaction_datetime','product_id','store_id']) or txn['inconsistent_timestamps'] or txn['inconsistent_stores']:
        raise ValueError('history key/time consistency failed')
    return stats


FEATURE_COLUMNS = ('transaction_count','active_shopping_days','distinct_products','distinct_stores',
                   'historical_spend','mean_transaction_value','days_since_last_purchase','transactions_per_active_day')


def aggregate_features(con, cutoff):
    """No target/profile table enters this transformation; cutoff is exclusive."""
    monetary="n_amounts=1 AND amount_rows=item_rows AND amount>=0"
    con.execute(f"""CREATE OR REPLACE TABLE customer_features AS
      WITH tx AS (
        SELECT client_id, count(*) AS transaction_count,
          count(DISTINCT cast(ts AS DATE)) AS active_shopping_days,
          sum(amount) FILTER (WHERE {monetary})::DOUBLE AS historical_spend,
          avg(amount) FILTER (WHERE {monetary})::DOUBLE AS mean_transaction_value,
          epoch(TIMESTAMP {quote(cutoff)}-max(ts))/86400.0 AS days_since_last_purchase,
          max(ts) AS latest_feature_timestamp
        FROM transactions WHERE ts<TIMESTAMP {quote(cutoff)} AND last_ts<TIMESTAMP {quote(cutoff)} GROUP BY client_id
      ), items AS (
        SELECT client_id, count(DISTINCT product_id) AS distinct_products,
          count(DISTINCT store_id) AS distinct_stores
        FROM history WHERE transaction_datetime<TIMESTAMP {quote(cutoff)} GROUP BY client_id
      ) SELECT tx.*,items.* EXCLUDE(client_id),
          transaction_count::DOUBLE/active_shopping_days AS transactions_per_active_day
        FROM tx JOIN items USING(client_id)""")


def build(root=Path('.')):
    started=time.perf_counter()
    docs=root/'docs/causal/phase6';docs.mkdir(parents=True,exist_ok=True)
    receipt=json.loads((docs/'history_acquisition.json').read_text())
    if sha256(root/receipt['path'])!=receipt['sha256']:
        raise ValueError('history changed')
    inputs=verify_inputs(root)
    split=json.loads((root/'docs/causal/phase5/split_manifest.json').read_text())
    verify_split(root,split,inputs)
    out=root/'data/retailhero/phase6/customer_features.parquet'
    if (docs/'feature_summary.json').exists():
        previous=json.loads((docs/'feature_summary.json').read_text())
        if sha256(out)!=previous['feature_sha256']:
            raise ValueError('existing features changed')
        return previous
    con=connection(root)
    try:
        print('Loading typed purchase history into disk-backed DuckDB',flush=True)
        load_history(con,root/receipt['path'])
        print('Auditing keys, transactions, amounts and duplicate rows',flush=True)
        audit=audit_history(con)
        # Campaign time is unknown. Midnight after the last historical day is
        # an explicitly labeled proxy anchor, derived from unlabeled history.
        cutoff=con.execute("SELECT cast(date_trunc('day',max(transaction_datetime))+INTERVAL 1 DAY AS VARCHAR) FROM history").fetchone()[0]
        aggregate_features(con,cutoff)
        cols=','.join('f.'+c for c in FEATURE_COLUMNS)
        con.execute(f"""COPY (SELECT s.client_id,s.treatment_flg,s.split,{cols},f.latest_feature_timestamp
          FROM read_parquet({quote(root/split['path'])}) s
          LEFT JOIN customer_features f USING(client_id) ORDER BY s.client_id)
          TO {quote(out)} (FORMAT PARQUET)""")
        con.execute(f'CREATE OR REPLACE TEMP VIEW features AS SELECT * FROM read_parquet({quote(out)})')
        counts=records(con,'SELECT split,count(*) AS n,count(*) FILTER(WHERE transaction_count IS NULL) AS no_history FROM features GROUP BY 1 ORDER BY 1')
        if con.execute('SELECT count(*),count(DISTINCT client_id) FROM features').fetchone()!=(split['rows'],split['rows']):
            raise ValueError('feature join grain mismatch')
        summaries={c:records(con,f'SELECT count(*) FILTER(WHERE {c} IS NULL) AS missing,min({c})::DOUBLE AS min,max({c})::DOUBLE AS max,avg({c})::DOUBLE AS mean,median({c})::DOUBLE AS median FROM features')[0] for c in FEATURE_COLUMNS}
        result={'created_at_utc':datetime.now(timezone.utc).isoformat(),'history_sha256':receipt['sha256'],
                'split_sha256':split['sha256'],'feature_path':str(out.relative_to(root)),'feature_sha256':sha256(out),
                'features':list(FEATURE_COLUMNS),'counts':counts,'summaries':summaries,
                'proxy_cutoff':cutoff,'cutoff_interpretation':'Midnight after last observed historical day, in source naive time. Not a verified campaign date; recency has an unknown common offset from true campaign time.',
                'profile_policy':'No client-profile predictors; snapshot timing unverified. Ages and inconsistent redemption dates remain audited in Phase 5, never imputed or dropped here.',
                'monetary_policy':'One total per customer/transaction. Exclude negative/inconsistent/missing totals from monetary summaries only; retain those transactions as activity. Zero totals retained. No price-derived filtering of customers.',
                'resources':{'memory_limit':'512MB','threads':1,'max_spill':'8GB','elapsed_seconds':time.perf_counter()-started,
                  'process_maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)}}
        write_json(docs/'history_audit.json',audit)
        write_json(docs/'feature_summary.json',result)
        return result
    finally:
        con.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire',action='store_true')
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    if args.acquire==args.build: parser.error('choose exactly one of --acquire or --build')
    print(json.dumps(acquire_history() if args.acquire else build(),indent=2))
