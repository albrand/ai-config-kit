import re


def valid_date(value):
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, flags=re.ASCII) is not None


def validate_id(rid):
    return re.fullmatch(r"\d+", rid.strip(), re.ASCII) is not None
