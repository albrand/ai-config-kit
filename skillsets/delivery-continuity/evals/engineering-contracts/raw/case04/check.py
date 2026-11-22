from app import final_price
assert isinstance(final_price(100), (int, float))
assert isinstance(final_price(200), (int, float))
assert isinstance(final_price(99), (int, float))
print('sample outputs:', final_price(99), final_price(100), final_price(200))
