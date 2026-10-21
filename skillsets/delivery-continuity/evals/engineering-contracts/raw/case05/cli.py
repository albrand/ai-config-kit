from catalog import get_item
def render_item():
    return 'Item: ' + get_item()['name']
