from fastapi import HTTPException

def open_correction(connection,code):
    return connection.execute(
        "SELECT * FROM corrections WHERE plate=%s AND state='open' ORDER BY id DESC LIMIT 1",
        (code,)).fetchone()

def plate(connection, code, lock=False):
    row=connection.execute("SELECT * FROM plates WHERE code=%s"+(" FOR UPDATE" if lock else ""),(code,)).fetchone()
    if not row:
        raise HTTPException(404,"试印版不存在")
    if lock and row["state"]!="open":
        # 封版后默认锁定；只有在该版存在“进行中的更正单”时，
        # 才允许改读数 / 重算 / 换签（原工签在换签前仍有效）。
        correction=open_correction(connection,code)
        if row["state"]!="sealed" or correction is None:
            raise HTTPException(409,"定版后试印批锁定")
        row=dict(row)
        row["active_correction"]=correction
    return row
