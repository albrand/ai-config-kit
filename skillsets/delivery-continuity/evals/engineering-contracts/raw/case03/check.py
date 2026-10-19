from app import build_application
routes = build_application()
assert '/' in routes and routes['/']() == 'home'
assert '/health' in routes, 'health route is not registered'
assert routes['/health']() == {'status': 'ok'}
print('registered routes:', sorted(routes))
