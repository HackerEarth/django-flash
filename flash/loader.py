from aiodataloader import DataLoader

from .base import BatchCacheQuery


class FlashCacheLoader(DataLoader):
    def get_cache_key(self, cache_query):
        return cache_query.key

    async def batch_load_fn(self, cache_queries):
        batch_query = BatchCacheQuery()
        for i, cache_query in enumerate(cache_queries):
            batch_query.push({i: cache_query})
        result_dict = batch_query.get()
        return [result_dict[i] for i in range(len(cache_queries))]
