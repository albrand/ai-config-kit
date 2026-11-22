def report_rows(rows, start_day, end_day):
    return [row for row in rows if start_day <= row['day'] < end_day]
