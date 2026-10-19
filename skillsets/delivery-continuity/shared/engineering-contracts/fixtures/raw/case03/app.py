def existing_route():
    return 'home'

def create_health_route():
    return lambda: {'status': 'ok'}

def build_application():
    return {'/': existing_route}
