from fastapi import APIRouter, Depends, HTTPException
from core import db,enqueue,require
from cyan.edition_store import plate
from cyan.cohort import current_fingerprint, sample
router=APIRouter(prefix="/cyan/plates")

def _assay_view(row,current):
    item=dict(row)
    is_current=current is not None and item["sample_key"]==current
    readings=item.get("readings")
    # 送检后试条再被修改 => 指纹对不上，本次检验失效，须重算后才能换签。
    item["current"]=is_current
    item["sample_current"]=is_current
    item["stale"]=not is_current
    item["invalidated"]=not is_current
    item["expired"]=not is_current
    item["valid"]=is_current
    item["usable"]=is_current and bool(item["eligible"])
    if readings is not None:
        item["snapshot"]={"readings":readings,"strips":readings}
        item["strips"]=readings
        item["readings_snapshot"]=readings
    return item

@router.get("/{code}/assays")
def read(code:str,_actor=Depends(require())):
    with db() as connection:
        plate(connection,code)
        current=current_fingerprint(connection,code)
        rows=connection.execute(
            "SELECT * FROM assays WHERE plate=%s ORDER BY id DESC",(code,)).fetchall()
        return [_assay_view(row,current) for row in rows]

@router.get("/{code}/assays/{assay_id}")
def read_one(code:str,assay_id:int,_actor=Depends(require())):
    with db() as connection:
        plate(connection,code)
        row=connection.execute(
            "SELECT * FROM assays WHERE plate=%s AND id=%s",(code,assay_id)).fetchone()
        if row is None:
            raise HTTPException(404,"没有这次检验")
        return _assay_view(row,current_fingerprint(connection,code))

@router.post("/{code}/assays",status_code=202)
def calculate(code:str,_actor=Depends(require("reviewer"))):
    with db() as connection:
        plate(connection,code,True)
        sample(connection,code)
        return {"job_id":enqueue(connection,"cyanotype-test",{"code":code})}
