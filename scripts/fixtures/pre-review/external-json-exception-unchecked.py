def read_status(rd, rel):
    body = rd["read"](rel)
    auth = json.loads(body).get("authentication") or {}
    return auth
