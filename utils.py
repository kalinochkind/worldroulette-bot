import json


def parse_map(text):
    data = text.replace('jQuery.fn.vectorMap(', '[').replace(');', ']').replace("'", '"')
    return json.loads(data)[2]['paths']
