import base64
import hashlib
from collections import defaultdict


def memcache_key_escape(key):
    if isinstance(key, unicode):
        key = key.encode('utf-8')
    if not key.isalnum():
        chars = []
        for c in key:
            if ord(c) > 32 and ord(c) < 127:
                chars.append(c)
            else:
                c64 = base64.b64encode(c)
                chars.append('~')
                chars.append(c64)
        key = ''.join(chars)
    if len(key) > 250:
        m = hashlib.md5()
        m.update(key)
        key = m.hexdigest()
    return key


flash_properties = defaultdict(list)


class FlashCacheAttributeDiscriptor(object):
    def __init__(self, prop, func, local_cache_on):
        self.cached_prop = '_%s_cache' % prop
        self.func = func
        self.local_cache_on = local_cache_on

    def __get__(self, instance, *args):
        if instance is None:
            return self
        if self.local_cache_on:
            if hasattr(instance, self.cached_prop):
                return getattr(instance, self.cached_prop)
        result = self.func(instance)
        if self.local_cache_on:
            setattr(instance, self.cached_prop, result)
        return result

    def __set__(self, instance, value):
        setattr(instance, self.cached_prop, value)


def flash_cache_property(model, prop, local_cache_on=True):
    def decorator(func):
        setattr(model, prop, FlashCacheAttributeDiscriptor(
            prop, func, local_cache_on))
        return func
    return decorator
