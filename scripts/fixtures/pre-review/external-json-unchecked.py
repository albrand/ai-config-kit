def read_status(rd, rel):
    body = rd["read"](rel)
    return json.loads(body).get("authentication")
