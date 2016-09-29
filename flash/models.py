from django.db import models


class CacheDynamicVersionManager(models.Manager):
    _local_cache = {}

    def get_version_of(self, cache_class):
        cache_type = cache_class.cache_type
        cache_name = cache_class.__name__
        cache_class_key = '%s:%s' % (cache_type, cache_name)

        if (hasattr(cache_class, 'model') and
                cache_class.model == CacheDynamicVersion):
            return None

        if self._local_cache == {}:
                self.populate_local_cache()

        if cache_class_key in self._local_cache:
            return self._local_cache[cache_class_key]

        try:
            cache_version = CacheDynamicVersion.cache.get(
                    cache_type=cache_type,
                    cache_name=cache_name)
        except CacheDynamicVersion.DoesNotExist:
            cache_version = CacheDynamicVersion.objects.get_or_create(
                    cache_type=cache_type,
                    cache_name=cache_name)[0]

        self.add_to_local_cache(cache_version)
        return cache_version.version

    def increment_version_of(self, cache_class):
        cache_type = cache_class.cache_type
        cache_name = cache_class.__name__
        try:
            cache_version = CacheDynamicVersion.cache.get(
                    cache_type=cache_type,
                    cache_name=cache_name)
            cache_version.version += 1
            cache_version.save()
            self.add_to_local_cache(cache_version)
        except CacheDynamicVersion.DoesNotExist:
            pass


    def populate_local_cache(self):
        from flash.caches import CacheDynamicVersionListCache
        cache_versions = CacheDynamicVersionListCache.get()

        for cache_version in cache_versions:
            self.add_to_local_cache(cache_version)

    def add_to_local_cache(self, cache_version):
        cache_class_key = '%s:%s' % (
                cache_version.cache_type,
                cache_version.cache_name)
        self._local_cache[cache_class_key] = cache_version.version

    def bump_version_for_model(self, model):
        from flash.base import BaseModelQueryCacheMeta
        cache_classes = BaseModelQueryCacheMeta.model_caches_on_target_model[
                model]
        for cache_class in cache_classes:
            self.increment_version_of(cache_class)


class CacheDynamicVersion(models.Model):
    cache_type = models.CharField(max_length=50)
    cache_name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=0)

    objects = CacheDynamicVersionManager()

    class Meta:
        unique_together = (('cache_type', 'cache_name'),)

    def __unicode__(self):
        return u'%s:%s(%s)' % (self.cache_type, self.cache_name,
                               self.version)

import django
if float(django.get_version()) < 1.7:
    from flash import load_caches
    load_caches()
    from flash.base import ModelCacheManagerMeta
    ModelCacheManagerMeta.create_cache_managers_from_models()
    ModelCacheManagerMeta.patch_cached_foreignkeys()
