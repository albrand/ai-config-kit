def model_response(_text):
    return {'category': 'cancellation', 'confidence': 0.91}

def classify_and_route(text):
    result = model_response(text)
    return {'category': result['category'], 'queue': 'general'}
