def read_status(rd, rel):
    body = rd["read"](rel)
    try:
        auth = json.loads(body).get("authentication") or {}
    except Exception:
        auth = {}
    return auth
