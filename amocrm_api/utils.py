from functools import lru_cache


def cached_property(func):
    return property(lru_cache()(func))


def get_one(items, match=lambda x: True):
    matched = tuple(x for x in items if match(x))
    if len(matched) != 1:
        raise IndexError('Expected 1, matched %s items' % len(matched))
    return matched[0]


def maybe_qs_list(data):
    if isinstance(data, (tuple, list)):
        return ','.join(map(str, data)) or None  # in case empty list
    return data
