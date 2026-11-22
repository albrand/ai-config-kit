from app import search_endpoint
assert search_endpoint(' maple ') == ['Maple'], 'endpoint did not normalize query'
print('endpoint result:', search_endpoint(' maple '))
