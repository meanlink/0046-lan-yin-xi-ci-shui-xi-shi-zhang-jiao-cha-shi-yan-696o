from decimal import Decimal
from hashlib import sha256
from fastapi import HTTPException
from cyan.strip_store import list_pairs

def sample(connection,code):
    rows=list_pairs(connection,code)
    if any(row["state"]=="pending" for row in rows):
        raise HTTPException(409,"仍有未复核试条")
    selected=[r for r in rows if r["state"]=="paired"]
    if not 6<=len(selected)<=16:
        raise HTTPException(409,"需要 6 至 16 个有效配对")
    return selected,sha256(repr(selected).encode()).hexdigest()

def jsonable(value):
    """把 psycopg 行里的 Decimal 等转成可写入 jsonb / JSON 响应的普通值。"""
    if isinstance(value,Decimal):
        return float(value)
    return value

def snapshot_rows(rows):
    return [{key:jsonable(value) for key,value in dict(row).items()} for row in rows]

def sample_snapshot(connection,code):
    rows,fingerprint=sample(connection,code)
    return rows,fingerprint,snapshot_rows(rows)

def current_fingerprint(connection,code):
    """样本当前指纹；当样本不满足计算条件时返回 None（既有检验随之失效）。"""
    try:
        _,fingerprint=sample(connection,code)
    except HTTPException:
        return None
    return fingerprint
