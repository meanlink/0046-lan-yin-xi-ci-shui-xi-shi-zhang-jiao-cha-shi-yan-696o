from fastapi import APIRouter, Depends

from core import db, require
from cyan.edition_store import plate as load_plate, open_correction

router=APIRouter(prefix="/cyan")

def _plate_view(connection,row):
    item=dict(row)
    corr=open_correction(connection,row["code"])
    item["correcting"]=corr is not None
    item["active_correction"]=dict(corr) if corr is not None else None
    item["correction_id"]=corr["id"] if corr is not None else None
    # state 仍为 open/sealed；另给语义化 status，更正中为 correcting。
    item["status"]="correcting" if corr is not None else row["state"]
    return item

@router.get("/plates")
def plates(_actor=Depends(require())):
    with db() as connection:
        rows=connection.execute("SELECT * FROM plates ORDER BY code").fetchall()
        return [_plate_view(connection,row) for row in rows]

@router.get("/plates/{code}")
def plate_detail(code:str,_actor=Depends(require())):
    with db() as connection:
        row=load_plate(connection,code)
        return _plate_view(connection,row)
