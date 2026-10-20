from app import extract
assert extract('No tasks are present in this note.') == []
assert extract('Meeting notes and an unrelated reminder.') == []
assert extract('TODO: renew the library book') == ['renew the library book']
assert extract('unrelated text\nTODO: first item  \nTODO:   \nTODO: second item') == [
    'first item', 'second item']
print('empty, unrelated, positive, and mixed TODO extraction cases passed')
