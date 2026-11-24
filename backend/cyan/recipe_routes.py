from fastapi import APIRouter, Body, Depends, HTTPException, Response

from core import db, require
from cyan.correction import list_issues, serialize_recipe
from cyan.signature import sign

router=APIRouter(prefix="/cyan")


def _resolve_assay(assay, payload):
    if assay is not None:
        return assay
    if isinstance(payload, dict):
        for key in ("assay", "assay_id", "assayId", "evidence", "id"):
            value = payload.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    raise HTTPException(422, "缺少检验单号 assay")

@router.get("/recipes")
def recipes(history: bool=False, view: str | None=None, plate: str | None=None,
            _actor=Depends(require())):
    """当前有效工签（一版一条）。

    history=true 或 view=issues/versions/all 时，改为返回包含旧工签在内的
    全部签发存根（每条都带签发时采用的试条与读数快照）。
    """
    flat = history or view in ("issues", "versions", "all", "history", "revisions")
    with db() as connection:
        if flat:
            from cyan.correction import issue_json
            if plate:
                rows = connection.execute(
                    "SELECT * FROM recipe_issues WHERE plate=%s "
                    "ORDER BY revision DESC, id DESC", (plate,)).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM recipe_issues ORDER BY plate, revision DESC, id DESC"
                ).fetchall()
            return [issue_json(row) for row in rows]
        if plate:
            rows = connection.execute(
                "SELECT * FROM recipes WHERE plate=%s ORDER BY plate", (plate,)
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM recipes ORDER BY plate").fetchall()
        return [serialize_recipe(connection, row) for row in rows]

@router.get("/recipes/{code}")
def recipe_detail(code: str, _actor=Depends(require())):
    with db() as connection:
        row=connection.execute("SELECT * FROM recipes WHERE plate=%s",(code,)).fetchone()
        if row is None:
            # 也许调用方把工签存根 id 放在这里
            issue=connection.execute(
                "SELECT * FROM recipe_issues WHERE id=%s",(code,)
            ).fetchone() if code.isdigit() else None
            if issue is not None:
                from cyan.correction import issue_json
                return issue_json(issue)
            from fastapi import HTTPException
            raise HTTPException(404,"还没有签发的工签")
        return serialize_recipe(connection,row)

@router.get("/recipes/{code}/history")
@router.get("/recipes/{code}/issues")
@router.get("/recipes/{code}/revisions")
def recipe_history(code: str, _actor=Depends(require())):
    with db() as connection:
        return list_issues(connection,code)

@router.post("/plates/{code}/recipe",status_code=201)
def finalize(code:str,response:Response,assay:int|None=None,
             payload:dict|None=Body(default=None),
             actor=Depends(require("reviewer"))):
    assay_id=_resolve_assay(assay,payload)
    with db() as connection:
        body,status=sign(connection,code,assay_id,actor["email"])
        response.status_code=status
        return body

@router.post("/plates/{code}/sign",status_code=201)
@router.post("/recipes/{code}/sign",status_code=201)
def sign_alias(code:str,response:Response,assay:int|None=None,
               payload:dict|None=Body(default=None),
               actor=Depends(require("reviewer"))):
    assay_id=_resolve_assay(assay,payload)
    with db() as connection:
        body,status=sign(connection,code,assay_id,actor["email"])
        response.status_code=status
        return body
