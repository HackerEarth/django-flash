from django.contrib.contenttypes.models import (
        ContentType, ContentTypeManager)

from flash.base import InstanceCache
from flash.constants import CACHE_TIME_MONTH


class ContentTypeCacheManager(ContentTypeManager):
    def _get_from_cache(self, opts):
        """ Tries to return ContentType instance from local cache
        If not found tries to get it from memcache
        """
        key_error = Exception()

        # Try to get it from local cache
        try:
            return super(ContentTypeCacheManager, self)._get_from_cache(opts)
        except KeyError as e:
            key_error = e

        # Try to get it from memcache
        app_label = opts.app_label
        if hasattr(opts, 'model_name'):
            model_name = opts.model_name
        else:
            model_name = opts.object_name.lower()

        try:
            ct = ContentTypeCacheOnAppModel.get(app_label, model_name)
        except ContentType.DoesNotExist:
            raise key_error

        # Add it to local cache
        self._add_to_cache(self.db, ct)

        return ct

#ContentType.add_to_class('objects_cache', ContentTypeCacheManager())
ContentType.objects_cache = ContentTypeCacheManager()
ContentType.objects_cache.model = ContentType


class ContentTypeCacheOnAppModel(InstanceCache):
    model = ContentType
    key_fields = ('app_label', 'model')
    timeout = CACHE_TIME_MONTH
