from app import report_rows
rows = [{'day': '2026-04-10', 'id': 10}, {'day': '2026-04-11', 'id': 11}, {'day': '2026-04-12', 'id': 12}]
assert report_rows(rows, '2026-04-10', '2026-04-10') == rows[:1], 'same-day inclusive range must include 2026-04-10'
assert report_rows(rows, '2026-04-10', '2026-04-11') == rows[:2], 'two-day inclusive range must include both dates and exclude 2026-04-12'
assert report_rows(rows, '2026-04-13', '2026-04-14') == [], 'range outside available records must be empty'
