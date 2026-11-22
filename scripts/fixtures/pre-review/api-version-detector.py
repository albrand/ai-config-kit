import re


def detect_api_version(path):
    return re.search(r"/v\d+/", path)
