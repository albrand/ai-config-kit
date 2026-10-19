def offline_response(_text):
    return {'items': []}

def extract(text):
    response = offline_response(text)
    return response['items']
