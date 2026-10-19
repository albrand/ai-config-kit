from app import classify_and_route
result = classify_and_route('Please cancel my appointment')
assert result == {'category': 'cancellation', 'queue': 'scheduling'}, result
print(result)
