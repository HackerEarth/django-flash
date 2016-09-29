# For Django >= 1.7
from django.apps import AppConfig

class FlashConfig(AppConfig):
    name = 'flash'
    verbose_name = "Flash"

    def ready(self):
        from flash import load_caches
        load_caches()
        from flash.base import ModelCacheManagerMeta
        ModelCacheManagerMeta.create_cache_managers_from_models()
        ModelCacheManagerMeta.patch_cached_foreignkeys()
