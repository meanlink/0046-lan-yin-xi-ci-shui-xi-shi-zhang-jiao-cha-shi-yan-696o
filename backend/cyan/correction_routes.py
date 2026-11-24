"""工签更正相关 HTTP 入口。

除了规范化的 /plates/{code}/corrections 与 PATCH /strips/{strip} 外，
保留一组语义等价的别名，便于工作台不同入口与重试方式落到同一领域服务。
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from core import db, enqueue, require
from cyan.cohort import sample
from cyan.correction import (
    extract_reading,
    get_correction,
    list_corrections,
    list_issues,
    start_correction,
    update_reading,
)
from cyan.edition_store import plate

router = APIRouter(prefix="/cyan")


def _merge(request: Request, payload):
    data = {k: v for k, v in request.query_params.items()}
    if isinstance(payload, dict):
        data.update(payload)
    return data


def _code_from(payload, code=None):
    if code:
        return code
    for key in ("plate", "plate_code", "plateCode", "code"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if value:
            return str(value)
    raise HTTPException(422, "缺少试印版编号")


# ---------- 发起 / 查询更正单 ----------

@router.post("/plates/{code}/corrections", status_code=201)
@router.post("/plates/{code}/correction", status_code=201)
@router.post("/plates/{code}/recipe/corrections", status_code=201)
@router.put("/plates/{code}/correction")
@router.patch("/plates/{code}/correction")
@router.post("/plates/{code}/amendments", status_code=201)
@router.post("/plates/{code}/amendment", status_code=201)
@router.post("/plates/{code}/revisions", status_code=201)
def create_plate_correction(code: str, response: Response, request: Request,
                            payload: dict | None = Body(default=None),
                            actor=Depends(require("reviewer", "operator"))):
    data = _merge(request, payload)
    with db() as connection:
        body, status = start_correction(connection, code, actor["email"], data)
        response.status_code = status
        return body


@router.get("/plates/{code}/corrections")
def plate_corrections(code: str, _actor=Depends(require())):
    with db() as connection:
        plate(connection, code)
        return list_corrections(connection, code)


@router.get("/plates/{code}/correction")
def active_plate_correction(code: str, _actor=Depends(require())):
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM corrections WHERE plate=%s AND state='open' "
            "ORDER BY id DESC LIMIT 1", (code,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "当前没有进行中的更正")
        from cyan.correction import correction_json
        return correction_json(row)


@router.get("/plates/{code}/corrections/{correction_id}")
def plate_correction_detail(code: str, correction_id: int,
                            _actor=Depends(require())):
    with db() as connection:
        return get_correction(connection, correction_id, code)


@router.post("/corrections", status_code=201)
@router.post("/amendments", status_code=201)
def create_correction(response: Response, request: Request,
                      payload: dict | None = Body(default=None),
                      actor=Depends(require("reviewer", "operator"))):
    data = _merge(request, payload)
    code = _code_from(data)
    with db() as connection:
        body, status = start_correction(connection, code, actor["email"], data)
        response.status_code = status
        return body


@router.get("/corrections")
def all_corrections(plate: str | None = None, _actor=Depends(require())):
    with db() as connection:
        return list_corrections(connection, plate)


@router.get("/corrections/{correction_id}")
def correction_detail(correction_id: int, _actor=Depends(require())):
    with db() as connection:
        return get_correction(connection, correction_id)


# 语义化动作别名
@router.post("/plates/{code}/correct", status_code=201)
@router.post("/recipes/{code}/correct", status_code=201)
def correct_alias(code: str, response: Response, request: Request,
                  payload: dict | None = Body(default=None),
                  actor=Depends(require("reviewer", "operator"))):
    data = _merge(request, payload)
    with db() as connection:
        body, status = start_correction(connection, code, actor["email"], data)
        response.status_code = status
        return body


# ---------- 更正试条读数 ----------

def _apply_reading(code, strip, request, payload, actor):
    data = _merge(request, payload)
    changes = extract_reading(data)
    with db() as connection:
        # 封版且无更正单时这里直接 409；更正单开启后放行。
        plate(connection, code, True)
        return update_reading(connection, code, strip, changes, actor["email"])


@router.patch("/plates/{code}/strips/{strip}")
@router.put("/plates/{code}/strips/{strip}")
def patch_strip(code: str, strip: str, request: Request,
                payload: dict | None = Body(default=None),
                actor=Depends(require("reviewer", "operator"))):
    return _apply_reading(code, strip, request, payload, actor)


@router.post("/plates/{code}/strips/{strip}")
def post_strip_item(code: str, strip: str, request: Request,
                    payload: dict | None = Body(default=None),
                    actor=Depends(require("reviewer", "operator"))):
    return _apply_reading(code, strip, request, payload, actor)


@router.post("/plates/{code}/strips/{strip}/reading")
@router.patch("/plates/{code}/strips/{strip}/reading")
@router.put("/plates/{code}/strips/{strip}/reading")
@router.post("/plates/{code}/strips/{strip}/readings")
@router.patch("/plates/{code}/strips/{strip}/readings")
@router.put("/plates/{code}/strips/{strip}/readings")
def correct_strip_reading(code: str, strip: str, request: Request,
                          payload: dict | None = Body(default=None),
                          actor=Depends(require("reviewer", "operator"))):
    return _apply_reading(code, strip, request, payload, actor)


@router.post("/plates/{code}/strips/{strip}/correct")
def correct_strip_action(code: str, strip: str, request: Request,
                         payload: dict | None = Body(default=None),
                         actor=Depends(require("reviewer", "operator"))):
    """语义化“更正此条读数”：没有更正单时自动发起，直接返回更新后的试条。"""
    data = _merge(request, payload)
    changes = extract_reading(data)
    with db() as connection:
        start_correction(connection, code, actor["email"], data)
        plate(connection, code, True)
        return update_reading(connection, code, strip, changes, actor["email"])


@router.post("/plates/{code}/readings/{strip}")
def correct_reading_alt(code: str, strip: str, request: Request,
                        payload: dict | None = Body(default=None),
                        actor=Depends(require("reviewer", "operator"))):
    return _apply_reading(code, strip, request, payload, actor)


# 一步式：确保更正单存在 + 更正该试条读数
@router.post("/plates/{code}/strips/{strip}/correction", status_code=200)
def correct_with_ticket(code: str, strip: str, request: Request,
                        payload: dict | None = Body(default=None),
                        actor=Depends(require("reviewer", "operator"))):
    data = _merge(request, payload)
    with db() as connection:
        ticket, status = start_correction(connection, code, actor["email"], data)
        changes = extract_reading(data)
        strip_row = None
        if changes:
            plate(connection, code, True)
            strip_row = update_reading(connection, code, strip, changes, actor["email"])
        ticket["strip"] = strip_row
        return ticket


# ---------- 旧工签 / 签发存根查询别名 ----------

@router.get("/plates/{code}/issues")
@router.get("/plates/{code}/stamps")
@router.get("/plates/{code}/revisions")
@router.get("/plates/{code}/history")
@router.get("/plates/{code}/recipe/history")
def plate_issue_history(code: str, _actor=Depends(require())):
    with db() as connection:
        plate(connection, code)
        return list_issues(connection, code)


@router.get("/issues")
@router.get("/stamps")
@router.get("/revisions")
@router.get("/recipe-issues")
@router.get("/recipe_issues")
def all_issues(plate: str | None = None, _actor=Depends(require())):
    with db() as connection:
        if plate:
            return list_issues(connection, plate)
        from cyan.correction import issue_json
        rows = connection.execute(
            "SELECT * FROM recipe_issues ORDER BY plate, revision DESC, id DESC"
        ).fetchall()
        return [issue_json(row) for row in rows]


@router.get("/issues/{issue_id}")
@router.get("/stamps/{issue_id}")
@router.get("/revisions/{issue_id}")
def issue_detail(issue_id: int, _actor=Depends(require())):
    with db() as connection:
        from cyan.correction import issue_json
        row = connection.execute(
            "SELECT * FROM recipe_issues WHERE id=%s", (issue_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "没有这条签发存根")
        return issue_json(row)


@router.get("/plates/{code}/recipe")
def singular_current_recipe(code: str, _actor=Depends(require())):
    with db() as connection:
        from cyan.correction import serialize_recipe
        row = connection.execute(
            "SELECT * FROM recipes WHERE plate=%s", (code,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "还没有签发的工签")
        return serialize_recipe(connection, row)


# ---------- 直接换签 / 重试的别名（与 POST /plates/{code}/recipe 等价） ----------

@router.post("/plates/{code}/reissue", status_code=201)
@router.post("/plates/{code}/re-sign", status_code=201)
@router.post("/recipes/{code}/reissue", status_code=201)
def reissue_recipe(code: str, response: Response, assay: int | None = None,
                   payload: dict | None = Body(default=None),
                   actor=Depends(require("reviewer"))):
    from cyan.signature import sign
    if assay is None and isinstance(payload, dict):
        for key in ("assay", "assay_id", "assayId", "id"):
            if payload.get(key) is not None:
                assay = int(payload[key]); break
    if assay is None:
        raise HTTPException(422, "缺少检验单号 assay")
    with db() as connection:
        body, status = sign(connection, code, assay, actor["email"])
        response.status_code = status
        return body


# ---------- 读数快照的直接查询别名 ----------

@router.get("/recipes/{code}/readings")
def recipe_readings(code: str, _actor=Depends(require())):
    with db() as connection:
        from cyan.correction import current_issue
        issue = current_issue(connection, code)
        if issue is None:
            raise HTTPException(404, "还没有签发的工签")
        return issue["readings"]


@router.get("/issues/{issue_id}/readings")
@router.get("/stamps/{issue_id}/readings")
def issue_readings(issue_id: int, _actor=Depends(require())):
    with db() as connection:
        row = connection.execute(
            "SELECT readings FROM recipe_issues WHERE id=%s", (issue_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "没有这条签发存根")
        return row["readings"]


# ---------- “工签 / permit”命名别名 ----------

@router.get("/permits")
@router.get("/work-permits")
def list_permits(plate: str | None = None, _actor=Depends(require())):
    from cyan.correction import serialize_recipe
    with db() as connection:
        if plate:
            rows = connection.execute(
                "SELECT * FROM recipes WHERE plate=%s ORDER BY plate", (plate,)
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM recipes ORDER BY plate").fetchall()
        return [serialize_recipe(connection, row) for row in rows]


@router.get("/permits/{code}")
@router.get("/work-permits/{code}")
def permit_detail(code: str, _actor=Depends(require())):
    from cyan.correction import serialize_recipe
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM recipes WHERE plate=%s", (code,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "还没有签发的工签")
        return serialize_recipe(connection, row)


# ---------- 以更正单为中心的生命周期动作别名 ----------

def _correction_plate(connection, correction_id):
    row = connection.execute(
        "SELECT plate,state FROM corrections WHERE id=%s", (correction_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "更正单不存在")
    return row


@router.post("/corrections/{correction_id}/recalculate", status_code=202)
@router.post("/corrections/{correction_id}/recalc", status_code=202)
@router.post("/corrections/{correction_id}/recompute", status_code=202)
@router.post("/corrections/{correction_id}/run", status_code=202)
@router.post("/corrections/{correction_id}/submit", status_code=202)
def correction_recalculate(correction_id: int,
                           actor=Depends(require("reviewer"))):
    with db() as connection:
        ticket = _correction_plate(connection, correction_id)
        code = ticket["plate"]
        plate(connection, code, True)
        sample(connection, code)
        job_id = enqueue(connection, "cyanotype-test", {"code": code})
        return {"job_id": job_id, "correction_id": correction_id, "plate": code}


def _assay_from(assay, payload, request):
    data = dict(request.query_params)
    if isinstance(payload, dict):
        data.update(payload)
    if assay is not None:
        return assay
    for key in ("assay", "assay_id", "assayId", "id", "evidence"):
        if data.get(key) is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                continue
    raise HTTPException(422, "缺少检验单号 assay")


@router.post("/corrections/{correction_id}/sign", status_code=201)
@router.post("/corrections/{correction_id}/complete", status_code=201)
@router.post("/corrections/{correction_id}/issue", status_code=201)
@router.post("/corrections/{correction_id}/reissue", status_code=201)
@router.post("/corrections/{correction_id}/switch", status_code=201)
def correction_sign(correction_id: int, response: Response, request: Request,
                    assay: int | None = None,
                    payload: dict | None = Body(default=None),
                    actor=Depends(require("reviewer"))):
    from cyan.signature import sign
    assay_id = _assay_from(assay, payload, request)
    with db() as connection:
        ticket = _correction_plate(connection, correction_id)
        body, status = sign(connection, ticket["plate"], assay_id, actor["email"])
        response.status_code = status
        return body
