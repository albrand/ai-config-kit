from app import extract
assert extract('No tasks are present in this note.') == []
print(extract('No tasks are present in this note.'))
