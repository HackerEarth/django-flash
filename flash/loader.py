from aiodataloader import DataLoader

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404

from .base import BatchCacheQuery


class FlashCacheLoader(DataLoader):
    def get_cache_key(self, cache_query):
        return cache_query.key

    async def batch_load_fn(self, cache_queries):
        batch_query = BatchCacheQuery()
        for i, cache_query in enumerate(cache_queries):
            batch_query.push({i: cache_query})
        result_dict = batch_query.get(return_exceptions=True)
        return [result_dict[i] for i in range(len(cache_queries))]


async def object_or_none(future):
    try:
        return await future
    except ObjectDoesNotExist:
        return None

async def object_or_404(future):
    try:
        return await future
    except ObjectDoesNotExist as e:
        raise Http404(str(e))
