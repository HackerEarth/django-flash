from inspect import isfunction

from django.db.models.base import ModelBase
from importlib import import_module
from django.utils.module_loading import module_has_submodule

from flash.base import ModelCacheManagerMeta
from flash import settings as flash_settings
import flash.signal_receivers

# Import things here to export
from flash.base import (
        ModelCacheManager, InstanceCache, RelatedInstanceCache,
        QuerysetCache, QuerysetExistsCache, RelatedQuerysetCache,
        DontCache, BatchCacheQuery, InvalidationType)


def load_caches():
    import_module('.caches', 'flash')

    FLASH_APPS = flash_settings.FLASH_APPS
    if isfunction(FLASH_APPS):
        FLASH_APPS = FLASH_APPS()

    for app_name in FLASH_APPS:
        app_module = import_module(app_name)
        try:
            module = import_module('.caches', app_name)
        except ImportError:
            if module_has_submodule(app_module, 'caches'):
                print ('Import error in %s/caches.py:' % app_name)
                raise
    import flash.contenttypes_caches

#load_caches()

def get_cache_manager(self):
    return ModelCacheManagerMeta.get_model_cache_manager(self)

ModelBase.cache = property(get_cache_manager)

# Register signals for fields_diff
import flash.fields_diff

default_app_config = 'flash.apps.FlashConfig'
