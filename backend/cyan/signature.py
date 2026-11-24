from fastapi import HTTPException
from psycopg.types.json import Jsonb

from cyan.cohort import sample, snapshot_rows
from cyan.correction import serialize_recipe
from cyan.edition_store import open_correction


def _lock_plate(connection, code):
    trial = connection.execute(
        "SELECT * FROM plates WHERE code=%s FOR UPDATE", (code,)
    ).fetchone()
    if not trial:
        raise HTTPException(404, "试印版不存在")
    return trial


def _adopted_snapshot(connection, code):
    rows, fingerprint = sample(connection, code)
    readings = snapshot_rows(rows)
    all_rows = connection.execute(
        "SELECT * FROM strips WHERE plate=%s ORDER BY code", (code,)
    ).fetchall()
    return fingerprint, readings, snapshot_rows(all_rows)


def sign(connection, code, assay, actor):
    """签发 / 重试 / 换签。返回 (响应体, HTTP 状态码)。

    - 首次签发：201，封版，写第 1 版存根；
    - 用当前 assay 重试：原样返回当前工签（201），不写存根、不重复出签；
    - 用新 assay 换签：必须有 open 更正单且新检验指纹一致、达标，
      同一事务内把 recipes 指针一次性切到新检验并写新版存根。
    """
    trial = _lock_plate(connection, code)
    recipe = connection.execute(
        "SELECT * FROM recipes WHERE plate=%s", (code,)
    ).fetchone()
    result = connection.execute(
        "SELECT * FROM assays WHERE plate=%s AND id=%s", (code, assay)
    ).fetchone()

    # 幂等重试：当前工签正是用这张检验签发的，原样返回同一工签，
    # 不写新存根、不重复出签。状态仍沿用签发入口的 201。
    if recipe is not None and recipe["assay"] == assay:
        body = serialize_recipe(connection, recipe)
        return body, 201

    if not result:
        raise HTTPException(409, "试条有变，须重算后签发")

    fingerprint, readings, all_readings = _adopted_snapshot(connection, code)
    if result["sample_key"] != fingerprint:
        raise HTTPException(409, "试条有变，须重算后签发")
    if not result["eligible"]:
        raise HTTPException(409, "密度或掉色未达到定版限值")

    if recipe is None:
        if trial["state"] != "open":
            raise HTTPException(409, "定版后试印批锁定")
        receipt = connection.execute(
            "INSERT INTO recipes(plate,assay,wash_sec,signer) VALUES(%s,%s,%s,%s) RETURNING *",
            (code, assay, trial["long_sec"], actor),
        ).fetchone()
        connection.execute(
            """INSERT INTO recipe_issues
                   (plate,revision,assay,wash_sec,signer,sample_key,readings,all_readings,state)
               VALUES(%s,1,%s,%s,%s,%s,%s,%s,'current')""",
            (code, assay, trial["long_sec"], actor, fingerprint,
             Jsonb(readings), Jsonb(all_readings)),
        )
        connection.execute("UPDATE plates SET state='sealed' WHERE code=%s", (code,))
        receipt = connection.execute(
            "SELECT * FROM recipes WHERE plate=%s", (code,)
        ).fetchone()
        return serialize_recipe(connection, receipt), 201

    # 已有工签且 assay 不同 => 换签，必须存在进行中的更正单。
    correction = open_correction(connection, code)
    if correction is None:
        raise HTTPException(409, "工签已签发；请先在工作台发起更正，重算达标后再换签")

    already = connection.execute(
        "SELECT id,state FROM recipe_issues WHERE plate=%s AND assay=%s",
        (code, assay),
    ).fetchone()
    if already is not None:
        # 这张检验已经出过签（通常是旧版），不能借更正再次出签。
        raise HTTPException(409, "该检验已用于签发，不能重复出签；请用最新重算结果换签")

    revision = int(correction["revision"])
    connection.execute(
        "UPDATE recipe_issues SET state='replaced' WHERE plate=%s AND state='current'",
        (code,),
    )
    new_issue = connection.execute(
        """INSERT INTO recipe_issues
               (plate,revision,assay,wash_sec,signer,sample_key,readings,all_readings,
                state,correction_id)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'current',%s) RETURNING id""",
        (code, revision, assay, trial["long_sec"], actor, fingerprint,
         Jsonb(readings), Jsonb(all_readings), correction["id"]),
    ).fetchone()
    receipt = connection.execute(
        """UPDATE recipes SET assay=%s,wash_sec=%s,signer=%s,signed_at=now()
           WHERE plate=%s RETURNING *""",
        (assay, trial["long_sec"], actor, code),
    ).fetchone()
    connection.execute(
        """UPDATE corrections
           SET state='applied',to_assay=%s,to_issue=%s,applied_at=now()
           WHERE id=%s""",
        (assay, new_issue["id"], correction["id"]),
    )
    # plate 始终保持 sealed；切换一次性完成。
    return serialize_recipe(connection, receipt), 201
