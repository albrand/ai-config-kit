def normalize_query(query):
    return query.strip().lower()

RECORDS = ['Maple']

def search_endpoint(query):
    return [record for record in RECORDS if record == query]
