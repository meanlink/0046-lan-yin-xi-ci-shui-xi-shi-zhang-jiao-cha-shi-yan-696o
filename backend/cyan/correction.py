"""工签更正 / 换签领域服务。

不变量：
* 更正单开启后，封版试印批允许改读数、重算；换签前 recipes 指针不动，原工签继续有效；
* 每次出签在 recipe_issues 留一条不可变存根，含签发时采用的试条与读数；
* 同一 assay 重复签发幂等，不产生第二条存根 / 工签。
"""
from fastapi import HTTPException

from cyan.cohort import snapshot_rows
from cyan.edition_store import open_correction

READING_FIELDS = (
    "short_temp", "long_temp", "short_density", "long_density", "long_fade",
)
READING_RANGES = {
    "short_temp": (4, 70), "long_temp": (4, 70),
    "short_density": (0, 2), "long_density": (0, 2),
    "long_fade": (0, 1),
}
_STRIP_KEYS = ("strip", "strip_code", "target", "code")


def _row_dict(row):
    return dict(row) if row is not None else None


def issue_json(row, all_readings=None):
    data = _row_dict(row)
    if data is None:
        return None
    readings = data.get("readings") or []
    data["readings"] = readings
    data["strips"] = readings
    data["adopted_readings"] = readings
    data["signed_at"] = data.get("issued_at")
    all_rows = all_readings if all_readings is not None else data.get("all_readings")
    snapshot = {
        "plate": data.get("plate"),
        "revision": data.get("revision"),
        "assay": data.get("assay"),
        "sample_key": data.get("sample_key"),
        "wash_sec": data.get("wash_sec"),
        "signer": data.get("signer"),
        "issued_at": data.get("issued_at"),
        "signed_at": data.get("issued_at"),
        "readings": readings,
        "strips": readings,
        "adopted": readings,
        "all_readings": all_rows or [],
        "all_strips": all_rows or [],
    }
    data["snapshot"] = snapshot
    data["readings_snapshot"] = readings
    data["evidence"] = readings
    data["sample"] = snapshot
    return data


def list_issues(connection, code):
    rows = connection.execute(
        "SELECT * FROM recipe_issues WHERE plate=%s ORDER BY revision DESC, id DESC",
        (code,),
    ).fetchall()
    return [issue_json(row) for row in rows]


def current_issue(connection, code):
    row = connection.execute(
        "SELECT * FROM recipe_issues WHERE plate=%s AND state='current' "
        "ORDER BY revision DESC, id DESC LIMIT 1",
        (code,),
    ).fetchone()
    return issue_json(row)


def serialize_recipe(connection, row, *, history=True):
    if row is None:
        return None
    data = _row_dict(row)
    issue = current_issue(connection, data["plate"])
    if issue:
        data.setdefault("id", issue["id"])
        data["issue_id"] = issue["id"]
        data["revision"] = issue["revision"]
        data["sample_key"] = issue["sample_key"]
        data["readings"] = issue["readings"]
        data["strips"] = issue["strips"]
        data["snapshot"] = issue["snapshot"]
        data["issue_state"] = issue["state"]
    else:
        data["readings"] = []
        data["strips"] = []
    corr = open_correction(connection, data["plate"])
    data["active_correction"] = _row_dict(corr)
    data["correcting"] = corr is not None
    if history:
        issues = list_issues(connection, data["plate"])
        data["issues"] = issues
        data["history"] = issues
        data["revisions"] = issues
        replaced = [item for item in issues if item["state"] == "replaced"]
        data["previous"] = replaced[0] if replaced else None
        data["old_issue"] = replaced[0] if replaced else None
        data["previous_recipe"] = replaced[0] if replaced else None
        data["old_recipe"] = replaced[0] if replaced else None
    return data


def _max_revision(connection, code):
    row = connection.execute(
        "SELECT COALESCE(MAX(revision), 1) AS rev FROM recipe_issues WHERE plate=%s",
        (code,),
    ).fetchone()
    return int(row["rev"])


def start_correction(connection, code, actor, payload=None):
    """开启更正单；若已有进行中的更正单则幂等返回。可顺带提交一条读数更正。"""
    payload = payload or {}
    existing = open_correction(connection, code)
    created = False
    if existing is None:
        recipe = connection.execute(
            "SELECT * FROM recipes WHERE plate=%s", (code,)
        ).fetchone()
        if recipe is None:
            raise HTTPException(409, "该版尚未签发工签，无需更正；请先完成检验并签发")
        plate_row = connection.execute(
            "SELECT state FROM plates WHERE code=%s FOR UPDATE", (code,)
        ).fetchone()
        if plate_row is None:
            raise HTTPException(404, "试印版不存在")
        if plate_row["state"] != "sealed":
            raise HTTPException(409, "只有已签发封版的工签才能发起更正")
        from_issue = current_issue(connection, code)
        revision = _max_revision(connection, code) + 1
        reason = payload.get("reason") or payload.get("note") or payload.get("cause")
        row = connection.execute(
            """INSERT INTO corrections
                   (plate, revision, reason, initiator, from_issue, from_assay)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (code, revision, reason, actor,
             from_issue["id"] if from_issue else None,
             recipe["assay"]),
        ).fetchone()
        created = True
    else:
        row = existing

    result = correction_json(row)
    result["created"] = created

    # 允许在发起更正的同一请求里直接给出某条试条的正确读数
    strip_code = None
    for key in _STRIP_KEYS:
        value = payload.get(key)
        if value and str(value) != code:
            strip_code = str(value)
            break
    changes = extract_reading(payload)
    if strip_code and changes:
        strip = update_reading(connection, code, strip_code, changes)
        result["strip"] = strip
    nested = payload.get("correction") if isinstance(payload.get("correction"), dict) else None
    if strip_code is None and nested:
        for key in _STRIP_KEYS:
            value = nested.get(key)
            if value and str(value) != code:
                strip_code = str(value)
                break
        changes = extract_reading(nested)
        if strip_code and changes:
            result["strip"] = update_reading(connection, code, strip_code, changes)

    # 也允许在发起更正时一次性提交多条试条读数：
    # {"readings":[{"code":"S03","long_density":0.88}, ...]}
    applied = []
    for list_key in ("readings", "items", "strips", "corrections"):
        batch = payload.get(list_key)
        if isinstance(batch, list):
            for item in batch:
                if not isinstance(item, dict):
                    continue
                item_code = None
                for key in _STRIP_KEYS:
                    if item.get(key):
                        item_code = str(item[key])
                        break
                item_changes = extract_reading(item)
                if item_code and item_changes:
                    applied.append(update_reading(connection, code, item_code, item_changes))
    if applied:
        result["updated_strips"] = applied
        if "strip" not in result and len(applied) == 1:
            result["strip"] = applied[0]
    return result, (201 if created else 200)


def correction_json(row):
    data = _row_dict(row)
    if data is None:
        return None
    data["status"] = data["state"]
    data["open"] = data["state"] == "open"
    data["active"] = data["state"] == "open"
    data["plate_code"] = data.get("plate")
    return data


def list_corrections(connection, code=None):
    if code:
        rows = connection.execute(
            "SELECT * FROM corrections WHERE plate=%s ORDER BY id DESC", (code,)
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM corrections ORDER BY id DESC"
        ).fetchall()
    return [correction_json(row) for row in rows]


def get_correction(connection, correction_id, code=None):
    if code:
        row = connection.execute(
            "SELECT * FROM corrections WHERE id=%s AND plate=%s",
            (correction_id, code),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM corrections WHERE id=%s", (correction_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "更正单不存在")
    data = correction_json(row)
    if data.get("from_issue"):
        data["from_issue_detail"] = issue_json(connection.execute(
            "SELECT * FROM recipe_issues WHERE id=%s", (data["from_issue"],)
        ).fetchone())
    if data.get("to_issue"):
        data["to_issue_detail"] = issue_json(connection.execute(
            "SELECT * FROM recipe_issues WHERE id=%s", (data["to_issue"],)
        ).fetchone())
    return data


def extract_reading(payload):
    """从扁平 / 嵌套请求体里取出读数键，兼容常见命名。"""
    if not isinstance(payload, dict):
        return {}
    sources = [payload]
    for nested_key in ("reading", "values", "data", "changes", "fields", "correction"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            sources.append(nested)
    out = {}
    aliases = {
        "shorttemp": "short_temp", "longtemp": "long_temp",
        "shortdensity": "short_density", "longdensity": "long_density",
        "longfade": "long_fade",
    }
    for source in sources:
        for key, value in source.items():
            norm = aliases.get(str(key).lower().replace("-", "_"), str(key))
            if norm in READING_FIELDS and value is not None and norm not in out:
                out[norm] = value
    return out


def update_reading(connection, code, strip_code, changes, actor=None):
    if not changes:
        raise HTTPException(422, "没有需要更正的读数")
    row = connection.execute(
        "SELECT * FROM strips WHERE plate=%s AND code=%s FOR UPDATE",
        (code, strip_code),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "试条不存在")
    for field, value in changes.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{field} 必须是数字")
        low, high = READING_RANGES[field]
        if not (low <= number <= high):
            raise HTTPException(422, f"{field} 超出允许范围 {low}~{high}")
        changes[field] = number
    assignments = ", ".join(f"{field}=%s" for field in changes)
    params = [*changes.values(), code, strip_code]
    updated = connection.execute(
        f"UPDATE strips SET {assignments} WHERE plate=%s AND code=%s RETURNING *",
        params,
    ).fetchone()
    return _row_dict(updated)
