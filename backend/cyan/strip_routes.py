from fastapi import APIRouter, Depends, HTTPException, Response
from core import db, require
from cyan.edition_store import plate, open_correction
from cyan.readings import Strip
from cyan.strip_store import list_pairs, insert, classify
router=APIRouter(prefix="/cyan/plates")

@router.get("/{code}/strips")
def list_strips(code:str,_actor=Depends(require())):
    with db() as connection:
        plate(connection,code)
        return list_pairs(connection,code)

@router.post("/{code}/strips",status_code=201)
def measure(code:str, strip:Strip, response:Response,
            _actor=Depends(require("operator"))):
    with db() as connection:
        plate(connection,code,True)
        exists=connection.execute(
            "SELECT 1 FROM strips WHERE plate=%s AND code=%s",(code,strip.code)
        ).fetchone()
        if exists:
            # 封版后只有挂着更正单，才允许用同一编号重新提交正确读数；
            # 保留复核状态，改完由新的重算指纹决定原检验是否失效。
            if open_correction(connection,code) is None:
                raise HTTPException(409,"试条编号已存在，读数更正请先在工作台发起更正")
            data=strip.model_dump()
            strip_code=data.pop("code")
            assignments=", ".join(f"{key}=%s" for key in data)
            row=connection.execute(
                f"UPDATE strips SET {assignments} WHERE plate=%s AND code=%s RETURNING *",
                (*data.values(),code,strip_code)).fetchone()
            response.status_code=200
            return row
        return insert(connection,code,strip)

@router.post("/{code}/strips/{strip}/qualify")
def qualify(code:str,strip:str,include:bool,_actor=Depends(require("reviewer"))):
    with db() as connection:
        plate(connection,code,True)
        return classify(connection,code,strip,include)
