def offline_response(text):
    items = []
    for line in text.splitlines():
        if line.startswith('TODO:'):
            payload = line.split(':', 1)[1].strip()
            if payload:
                items.append(payload)
    return {'items': items}

def extract(text):
    response = offline_response(text)
    return response['items']
