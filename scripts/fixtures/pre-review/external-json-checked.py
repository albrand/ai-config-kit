def read_status(rd, rel):
    body = rd["read"](rel)
    response = json.loads(body)
    if not isinstance(response, dict):
        raise ValueError("response must be an object")
    return response.get("authentication")
