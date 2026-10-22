from service import item_title
from cli import render_item
assert item_title() == 'Field Guide'
assert render_item() == 'Item: Field Guide'
print(render_item())
