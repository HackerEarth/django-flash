from flash.base import ModelCacheManager, QuerysetCache, InvalidationType
from flash.models import CacheDynamicVersion
from flash.constants import CACHE_TIME_M


class CacheDynamicVersionCacheManager(ModelCacheManager):
    model = CacheDynamicVersion
    get_key_fields_list = [
        ('cache_type', 'cache_name'),
    ]


class CacheDynamicVersionListCache(QuerysetCache):
    model = CacheDynamicVersion
    key_fields = ()
    invalidation = InvalidationType.DYNAMIC
    allowtime = CACHE_TIME_M
