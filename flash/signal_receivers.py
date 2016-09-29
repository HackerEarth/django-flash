import time
from copy import deepcopy

from django.db.models.signals import pre_save, post_save, pre_delete, m2m_changed
from django.dispatch import receiver
from django.conf import settings

from flash.base import (cache, StaleData, BaseModelQueryCacheMeta,
                        InvalidationType)
from flash.signals import queryset_update
from flash.constants import CACHE_TIME_S


def get_cache_keys_to_be_invalidated(model, instance, signal):
    cache_classes = BaseModelQueryCacheMeta.model_caches[model]

    unset_cache_keys = []
    dynamic_cache_keys = []

    for cache_class in cache_classes:
        if cache_class.invalidation == InvalidationType.OFF:
            continue
        try:
            cache_keys = list(cache_class.get_keys_to_be_invalidated(
                instance, signal))
            if cache_class.invalidation == InvalidationType.UNSET:
                unset_cache_keys.extend(cache_keys)
            elif cache_class.invalidation == InvalidationType.DYNAMIC:
                cache_keys = [cache_class.get_stale_key(key) for key in cache_keys]
                dynamic_cache_keys.extend(cache_keys)
        except Exception as e:
            if settings.DEBUG:
                raise
    return unset_cache_keys, dynamic_cache_keys


def invalidate_caches(unset_cache_keys, dynamic_cache_keys):
    if settings.DEBUG and unset_cache_keys:
        print 'Flash: Invalidating cache keys (unsetting)', unset_cache_keys
    if settings.DEBUG and dynamic_cache_keys:
        print 'Flash: Invalidating cache keys (dynamic unsetting)', dynamic_cache_keys
    stale_data = StaleData(time.time())
    if unset_cache_keys:
        key_value_map = {key: stale_data for key in unset_cache_keys}
        cache.set_many(key_value_map, timeout=CACHE_TIME_S)
    if dynamic_cache_keys:
        key_value_map = {key: stale_data for key in dynamic_cache_keys}
        cache.set_many(key_value_map, timeout=0)

@receiver(post_save)
def instance_post_save_receiver(sender, instance, **kwargs):
    try:
        model = sender
        cache_keys_tuple = get_cache_keys_to_be_invalidated(
                model, instance, 'post_save')
        invalidate_caches(*cache_keys_tuple)
    except:
        if settings.DEBUG:
            raise


@receiver(m2m_changed)
def instance_m2m_changed_receiver(sender, instance, action, reverse, model,
        pk_set, **kwargs):
    try:
        if action not in ['post_add', 'pre_remove']:
            return
        obj = (instance, reverse, model, pk_set)
        cache_keys_tuple = get_cache_keys_to_be_invalidated(
                sender, obj, 'm2m_changed')
        invalidate_caches(*cache_keys_tuple)
    except:
        if settings.DEBUG:
            raise


@receiver(pre_delete)
def instance_pre_delete_receiver(sender, instance, **kwargs):
    try:
        model = sender
        cache_keys_tuple = get_cache_keys_to_be_invalidated(
                model, instance, 'pre_delete')
        invalidate_caches(*cache_keys_tuple)
    except:
        if settings.DEBUG:
            raise


@receiver(queryset_update)
def queryset_update_receiver(sender, queryset, update_kwargs, **kwargs):
    try:
        model = sender
        if BaseModelQueryCacheMeta.model_caches[model] == []:
            return
        if not update_kwargs and kwargs.get('force', False) is False:
            return
        unset_cache_keys = []
        dynamic_cache_keys = []
        for instance in queryset:
            try:
                instance = deepcopy(instance)
                update_statediff(instance, update_kwargs)
                unset_keys, dynamic_keys = get_cache_keys_to_be_invalidated(
                        model, instance, 'instance_update')
                unset_cache_keys.extend(unset_keys)
                dynamic_cache_keys.extend(dynamic_keys)
            except:
                if settings.DEBUG:
                    raise
        invalidate_caches(unset_cache_keys, dynamic_cache_keys)
    except:
        if settings.DEBUG:
            raise


def update_statediff(instance, update_kwargs):
    for key, value in update_kwargs.items():
        setattr(instance, key, value)
    instance.create_state_diff()
