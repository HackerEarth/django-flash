import six
import time
import copy

from distutils.version import StrictVersion
from abc import ABCMeta, abstractmethod, abstractproperty
from collections import defaultdict
from functools import partial

import django

try:
    from django.core.cache import get_cache
except ImportError:
    from django.core.cache import caches
    def get_cache(backend):
        return caches[backend]

from django.http import Http404
from django.db import models, transaction

try:
    from django.db.models import get_models
except ImportError:
    from django.apps import apps
    get_models = apps.get_models

try:
    from django.db.models.fields.related import ReverseSingleRelatedObjectDescriptor
except ImportError:
    from django.db.models.fields.related_descriptors import \
        ForwardManyToOneDescriptor as ReverseSingleRelatedObjectDescriptor

def importGenericForeignKey():
    try:
        from django.contrib.contenttypes.generic import GenericForeignKey
    except ImportError:
        from django.contrib.contenttypes.fields import GenericForeignKey
    return GenericForeignKey


from flash import settings as flash_settings
from flash.option import Some
from flash.utils import memcache_key_escape, flash_properties


cache = get_cache(flash_settings.CACHE_NAME)


def is_abstract_class(cls):
    """ Returns boolean telling whether given class is abstract or not.

        A class is abstract if it has not implemented any abstractmethod or
        abstractproperty of base classes.
    """
    return bool(getattr(cls, "__abstractmethods__", False))


def instancemethod(method):
    """ Decorator for creating descriptor class to call method with
    instance when called with class.
    """
    class MethodDisc(object):
        def __get__(self, ins, cls):
            if ins is None:
                # when method is called from class
                # get instance of that class and use that
                ins = cls()
            return partial(method, ins)
    return MethodDisc()


class DontCache(object):
    def __init__(self, val):
        self.inner_val = val


@six.python_2_unicode_compatible
class StaleData(object):
    def __init__(self, timestamp):
        self.timestamp = timestamp

    def __str__(self):
        return "StaleData(timestamp=%s)" % self.timestamp


def cache_get_many(keys):
    d = cache.get_many(keys)
    result_dict = {}
    stale_data_dict = {}

    for key, value in d.items():
        if isinstance(value, StaleData):
            stale_data_dict[key] = value
        else:
            result_dict[key] = value

    return result_dict, stale_data_dict


class InvalidationType(object):
    OFF = 0
    UNSET = 1
    RESET = 2
    DYNAMIC = 3

USING_KWARG = '__using'

class WrappedValue(object):
    def __init__(self, value, version, timestamp):
        self.value = value
        self.version = version
        self.timestamp = timestamp


class Cache(six.with_metaclass(ABCMeta, object)):
    """ The very base class for all cache classes.

        Methods decorated with abstractmethod or abstractproperty
        have to be implemented by derived classes.

        It's necessary to put ABCMeta or its derived class to put
        as metaclass to achieve above constraints.
    """
    # Derived class may provide serializer (E.g. for compression)
    serializer = None

    # default version
    version = 0

    # default timeout
    timeout = flash_settings.DEFAULT_TIMEOUT

    # default invalidation
    invalidation = InvalidationType.UNSET

    # default allowtime
    allowtime = None

    cache_type = 'SimpleCache'

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    @property
    def key(self):
        return self.get_key(*self.args, **self.kwargs)

    @abstractmethod
    def get_key(self, *args, **kwargs):
        """ Returns the key for given params (args and kwargs).
        """
        pass

    @instancemethod
    def get_dynamic_version(self):
        from flash.models import CacheDynamicVersion
        return CacheDynamicVersion.objects.get_version_of(type(self))

    @staticmethod
    def get_stale_key(key):
        return key + '__stale'

    def to_cache_value(self, value):
        if self.serializer:
            value = self.serializer.dumps(value)
        return value

    def from_cache_value(self, value):
        if self.serializer:
            value = self.serializer.loads(value)
        return value

    @staticmethod
    def get_write_lock_key(key):
        return key + '__write_lock'

    def try_acquire_write_lock(self, key):
        write_lock_key = self.get_write_lock_key(key)
        return cache.add(write_lock_key, True,
                         timeout=flash_settings.WRITE_LOCK_TIMEOUT)

    def release_write_lock(self, key):
        write_lock_key = self.get_write_lock_key(key)
        return cache.delete(write_lock_key)

    def get_option_value_from_cache_coroutine(self, key, extra_keys=None,
            key_value_dict=None):
        """ key: str,
            extra_keys: list
            key_value_dict: dict,

            Yields value assosiated with key in cache, wrapped as Option value.

            If extra_keys is passed then all values are fetched assosiated with
            keys in extra_keys and put to key_value_dict.
        """
        keys = []
        keys.append(key)
        if extra_keys is not None:
            keys.extend(extra_keys)

        # result_dict is dict of key value pair
        result_dict = yield keys

        if not result_dict:
            yield None
            return

        if extra_keys and (key_value_dict is not None):
            keys_found = set(result_dict.keys()) & set(extra_keys)
            for key_found in keys_found:
                key_value_dict[key_found] = result_dict[key_found]

        if key not in result_dict:
            yield None
            return

        value = result_dict[key]
        if isinstance(value, WrappedValue):
            value.value = self.from_cache_value(value.value)
        else:
            value = self.from_cache_value(value)
        yield Some(value)

    @abstractmethod
    def get_value_for_params(self, *args, **kwargs):
        """ The fallback method to return value for given params.
            Mostly implemented to get value from database.
        """
        pass

    def get_extra_keys(self, *args, **kwargs):
        pass

    def get_extra_key_value_dict(self, value, *args, **kwargs):
        pass

    def pre_set_process_value(self, value, *args, **kwargs):
        return value

    def post_process_value(self, value, *args, **kwargs):
        return value

    def _set(self, key, value, key_value_dict=None, stale_data_dict=None,
            force_update=False):
        """ Sets the given key value in cache.

        If key_value_dict is passed sets all key-values
        in this dict to cache too.
        """
        if stale_data_dict is None:
            stale_data_dict = {}

        value = self.to_cache_value(value)
        value = WrappedValue(value, self.get_dynamic_version(), time.time())

        if key_value_dict is None:
            key_value_dict = {}
        key_value_dict[key] = value

        for key_, value_ in key_value_dict.items():
            if key_ in stale_data_dict:
                current_value_dict = cache.get_many([key_])
                if key_ in current_value_dict:
                    current_value = current_value_dict[key_]
                    stale_value = stale_data_dict[key_]
                    if (isinstance(current_value, StaleData) and
                            current_value.timestamp == stale_value.timestamp):
                        cache.set(key_, value_, timeout=self.timeout)
                    continue
            if force_update:
                cache.set(key_, value_, timeout=self.timeout)
            else:
                cache.add(key_, value_, timeout=self.timeout)

    def get_coroutine(self, *args, **kwargs):
        """ Yields the value for given params (args and kwargs).

        First tries to get it from cache. If not found, gets it from
        fallback method and sets the value to cache.
        """
        key = self.get_key(*args, **kwargs)

        is_invalidation_dynamic = (
                self.invalidation == InvalidationType.DYNAMIC)
        extra_keys = self.get_extra_keys(*args, **kwargs) or []
        if is_invalidation_dynamic:
            stale_key = self.get_stale_key(key)
            extra_keys.append(stale_key)
        key_value_dict = {}

        coroutine = self.get_option_value_from_cache_coroutine(key, extra_keys,
                key_value_dict)
        keys = coroutine.send(None)
        result_dict, stale_data_dict = yield keys
        option_value = coroutine.send(result_dict)

        return_cache_value = False
        lock_acquired = False
        force_update = False
        if option_value is not None:
            # cache found in cache
            w_value = option_value.unwrap()
            current_dynamic_version = self.get_dynamic_version()
            if isinstance(w_value, WrappedValue):
                try_acquire_lock = False
                value = w_value.value
                if self.allowtime and (
                        (time.time() - w_value.timestamp) < self.allowtime):
                    return_cache_value = True
                elif (current_dynamic_version is not None and
                        current_dynamic_version != w_value.version):
                    if self.invalidation in [
                            InvalidationType.OFF,
                            InvalidationType.DYNAMIC]:
                        try_acquire_lock = True
                    else:
                        force_update = True
                elif is_invalidation_dynamic:
                    is_stale = stale_key in stale_data_dict
                    if not is_stale:
                        return_cache_value = True
                    else:
                        try_acquire_lock = True
                elif self.allowtime and (
                        self.invalidation == InvalidationType.OFF):
                    try_acquire_lock = True
                elif self.allowtime is None:
                    return_cache_value = True
                else:
                    force_update = True
                if try_acquire_lock:
                    lock_acquired = self.try_acquire_write_lock(key)
                    if not lock_acquired:
                        return_cache_value = True
                    else:
                        force_update = True
            else:
                value = w_value
                return_cache_value = True

        if not return_cache_value:
            # get value using fallback method (e.g. db)
            value = self.get_value_for_params(*args, **kwargs)
            if not isinstance(value, DontCache):
                key_value_dict = self.get_extra_key_value_dict(
                        value, *args, **kwargs)

                set_value_in_cache = True
                if (option_value is None and key in stale_data_dict and
                        (time.time() - stale_data_dict[key].timestamp) < 0.3):
                    # cache was just invalidated
                    # db may return stale data
                    # hence
                    set_value_in_cache = False

                if StrictVersion(django.get_version()) < StrictVersion('1.7'):
                    transaction.commit_unless_managed()

                value = self.pre_set_process_value(value, *args, **kwargs)

                # set the key value in cache
                if set_value_in_cache:
                    self._set(key, value, key_value_dict, stale_data_dict,
                          force_update=force_update)

                if is_invalidation_dynamic:
                    cache.delete(stale_key)

                if lock_acquired:
                    self.release_write_lock(key)

        if isinstance(value, DontCache):
            value = value.inner_val

        value = self.post_process_value(
                value, key_value_dict, *args, **kwargs)
        yield value

    def resolve_coroutine(self):
        return self.get_coroutine(*self.args, **self.kwargs)

    def get(self, *args, **kwargs):
        """ Returns the yielded vale from get_coroutine method
        """
        coroutine = self.get_coroutine(*args, **kwargs)
        keys = coroutine.send(None)
        if flash_settings.DONT_USE_CACHE:
            result_dict, stale_data_dict = {}, {}
        else:
            result_dict, stale_data_dict = cache_get_many(keys)
        value = coroutine.send((result_dict, stale_data_dict))
        return value

    def resolve(self):
        return self.get(*self.args, **self.kwargs)

    def reset(self, *args, **kwargs):
        """ Resets the value in cache using fallback method for given params
        """
        if flash_settings.DONT_USE_CACHE:
            return
        key = self.get_key(*args, **kwargs)
        value = self.get_value_for_params(*args, **kwargs)
        key_value_dict = self.get_extra_key_value_dict(value, *args, **kwargs)
        value = self.pre_set_process_value(value, *args, **kwargs)
        self._set(key, value, key_value_dict)

    def set(self, params, value, pre_set_process=True):
        """ Sets the given value in cache for given params
        """
        if flash_settings.DONT_USE_CACHE:
            return
        key = self.get_key(**params)
        if pre_set_process:
            value = self.pre_set_process_value(value, **params)
        self._set(key, value, force_update=True)

    def resolve_async(self):
        from .loader import FlashCacheLoader
        from thread_context.dataloader_context import DataLoadersFactory

        loader = DataLoadersFactory.get_loader_for(FlashCacheLoader)
        return loader.load(self)


class BatchCacheQuery(object):
    """ Class to make multiple cache queries into one
    """
    def __init__(self, *args, **queries):
        if args:
            self.queries = args[0]
        else:
            self.queries = queries

    def push(self, *args, **kwargs):
        if args:
            self.queries.update(args[0])
        else:
            self.queries.update(kwargs)

    def get(self, only_cache=False, none_on_exception=False,
            return_exceptions=False):
        all_cache_keys = set()
        coroutines_dict = {}
        value_dict = {}

        for key, cache_query in self.queries.items():
            coroutine = cache_query.resolve_coroutine()
            cache_keys = coroutine.send(None)
            all_cache_keys.update(cache_keys)
            coroutines_dict[key] = (coroutine, cache_keys)

        all_cache_keys = list(all_cache_keys)
        all_cache_result, all_stale_data_dict = cache_get_many(all_cache_keys)

        for key in coroutines_dict:
            coroutine, cache_keys = coroutines_dict[key]
            result_dict = {}
            stale_data_dict = {}

            to_continue = False
            for cache_key in cache_keys:
                if cache_key in all_cache_result:
                    result_dict[cache_key] = all_cache_result[cache_key]
                elif only_cache:
                    to_continue = True
                    break
                elif cache_key in all_stale_data_dict:
                    stale_data_dict[cache_key] = all_stale_data_dict[cache_key]
            if to_continue:
                continue

            try:
                value = coroutine.send((result_dict, stale_data_dict))
                value_dict[key] = value
            except Exception as e:
                if return_exceptions:
                    value_dict[key] = e
                elif none_on_exception:
                    value_dict[key] = None
                else:
                    raise
        return value_dict


class BaseModelQueryCacheMeta(ABCMeta):
    """ Meta class for BaseModelQueryCache class.

    Deriving it from ABCMeta because BaseModelQueryCache is
    derived from Cache class wich has metaclass ABCMeta
    """
    model_caches = defaultdict(list)
    model_caches_on_target_model = defaultdict(list)

    def __init__(self, *args, **kwargs):
        """ self is the class with BaseModelQueryCacheMeta as its
        metaclass
        """
        super(BaseModelQueryCacheMeta, self).__init__(*args, **kwargs)

        if is_abstract_class(self):
            return

        # register self in model_caches dict corressponding to all the models
        # against which cache should get invalidated.
        for model in self.get_invalidation_models():
            self.model_caches[model].append(self)

        target_models = self.get_cache_model()
        if target_models:
            if not isinstance(target_models, (list, tuple)):
                # If it's a single model
                target_models = [target_models]
            for target_model in target_models:
                self.model_caches_on_target_model[target_model].append(self)


class BaseModelQueryCache(six.with_metaclass(BaseModelQueryCacheMeta, Cache)):
    """ Base class for all cache classes which cache some query's result
        on assosiated model.
    """
    generic_fields_support = True

    def __init__(self, *args, **kwargs):
        if USING_KWARG in kwargs:
            self.using = kwargs.pop(USING_KWARG)
        else:
            self.using = self.get_using()
        super(BaseModelQueryCache, self).__init__(*args, **kwargs)

    @abstractproperty
    def model(self):
        pass

    def get_cache_model(self):
        return None

    @abstractproperty
    def key_fields(self):
        pass

    def get_using(self):
        return self.model.objects.get_queryset().db

    @instancemethod
    def get(self, *args, **kwargs):
        if USING_KWARG in kwargs:
            self.using = kwargs.pop(USING_KWARG)
        return super(BaseModelQueryCache, self).get(*args, **kwargs)

    @instancemethod
    def set(self, *args, **kwargs):
        return super(BaseModelQueryCache, self).set(*args, **kwargs)

    @abstractmethod
    def get_invalidation_models(self):
        pass

    @abstractmethod
    def get_keys_to_be_invalidated(self, instance, signal, using):
        pass

    def get_field_dict(self, *args, **kwargs):
        """ Returns the given params as dict of field_name as key
        and given param value as value
        """
        field_dict = {}
        args_len = len(args)
        if args:
            # put all values in args in same order as of field_name in
            # key_fields starting.
            for i in range(args_len):
                field_name = self.key_fields[i]
                field_dict[field_name] = args[i]
        if kwargs:
            # iterate over all rest key_fields and take values from kwargs
            for field_name in self.key_fields[args_len:]:
                if field_name in kwargs:
                    field_dict[field_name] = kwargs[field_name]
                else:
                    # check if field is passed in kwargs as attname of field
                    # If field is a related field (E.g. ForeignKey) then its
                    # attname is actually postfixed with `_id`.
                    # E.g. user field has attname user_id
                    field = self.model._meta.get_field(field_name)
                    if field.attname in kwargs:
                        field_dict[field.attname] = kwargs[field.attname]
                    else:
                        raise KeyFieldNotPassed(field_name)
        return field_dict

    @instancemethod
    def get_key(self, *args, **kwargs):
        cls_name = self.__class__.__name__
        using = kwargs.pop(USING_KWARG, self.using)
        key = '%s__%s__%s' % (self.cache_type, using, cls_name)
        field_dict = self.get_field_dict(*args, **kwargs)

        for field_name in self.key_fields:
            if self.generic_fields_support:
                if hasattr(self.model, field_name):
                    field_obj = getattr(self.model, field_name)
                    GenericForeignKey = importGenericForeignKey()
                    if isinstance(field_obj, GenericForeignKey):
                        value = field_dict[field_name]
                        if isinstance(value, tuple):
                            ctype_id, object_id = value
                        else:
                            from django.contrib.contenttypes.models import ContentType
                            ctype_id = ContentType.objects_cache.get_for_model(
                                    value).id
                            object_id = getattr(value, value._meta.pk.attname)
                        key += '__%s-%s' % (ctype_id, object_id)
                        continue

            field = self.model._meta.get_field(field_name)

            if field_name in field_dict:
                value = field_dict[field_name]
            else:
                value = field_dict[field.attname]
            if isinstance(value, models.Model):
                # get the pk value on instance
                if field.rel:
                    rel_model = field.rel.to
                else:
                    # In very rare cases, field.rel is found to be None
                    # that I do not know why.
                    # fallback method to get rel_model
                    rel_model = value.__class__
                value = getattr(value, rel_model._meta.pk.attname)
            """
            if isinstance(value, unicode):
                value = value.encode('utf-8')
            """
            key += '__%s' % str(value)
        key += '__v%s' % self.version
        key = memcache_key_escape(key)
        return key


class InstanceCacheMeta(BaseModelQueryCacheMeta):
    """ Meta class for InstanceCache class
    """
    instance_cache_classes = defaultdict(list)

    def __new__(cls, *args, **kwargs):
        ncls = super(InstanceCacheMeta, cls).__new__(cls, *args, **kwargs)
        if is_abstract_class(ncls):
            return ncls
        model = ncls.model
        # store the new class's single instance with its model
        # in instance_cache_classes dict
        cls.instance_cache_classes[model].append(ncls)
        if (six.get_unbound_function(ncls.get_instance) ==
                six.get_unbound_function(InstanceCache.get_instance)):
            # if the get_instance method is not overriden then mark the class
            # as simple
            ncls.is_simple = True
        else:
            ncls.is_simple = False
        # ask the class the class to create assosiated related instance classes
        # if any
        ncls.register_related_caches()
        return ncls


class KeyFieldNotPassed(Exception):
    def __init__(self, field_name):
        msg = 'key field `%s` not given' % field_name
        super(KeyFieldNotPassed, self).__init__(msg)


class SameModelInvalidationCache(object):
    """ Mixin class to be used with InstanceCache, QuerysetCache classes.
    """

    def _get_invalidation_models(self):
        return [self.model]

    def _get_keys_to_be_invalidated(self, instance, signal, using):
        keys = []
        for params in self.get_invalidation_params_list_(instance, signal):
            keys.append(self.get_key(*params, **{USING_KWARG: using}))
        return keys

    def get_invalidation_params_list_(self, instance, signal):
        """ It's called when an instance gets saved and caches
        have to be invalidated.

        Returns the list of params on which keys to be invalidated.
        """
        params_list = []
        instances = []

        if isinstance(instance, tuple):
            # case when instances of many_to_many through model are added
            # or removed.
            instance, _, model, pk_set = instance
            if len(self.key_fields) == 1:
                if (self.key_fields[0] ==
                        instance.__class__._meta.object_name.lower()):
                    params = (instance.pk,)
                    params_list = [params]
                elif (self.key_fields[0] ==
                        model._meta.object_name.lower()):
                    for pk in pk_set:
                        params_list.append((pk,))
                return params_list

            filter_dict = {
                instance.__class__._meta.object_name.lower():
                    instance.pk,
                '%s__in' % model._meta.object_name.lower():
                    pk_set,
            }
            instances = list(self.model.objects.filter(**filter_dict))
        else:
            instances = [instance]

        for instance in instances:
            params = []
            params_pre = []
            instance_state_diff = instance.get_state_diff()
            for field_name in self.key_fields:
                try:
                    field = self.model._meta.get_field(field_name)
                    params.append(getattr(instance, field.attname))
                    if (field.attname in instance_state_diff and
                        'pre' in instance_state_diff[field.attname]):
                        params_pre.append(instance_state_diff[
                            field.attname]['pre'])
                    else:
                        params_pre.append(getattr(instance, field.attname))
                except:
                    if hasattr(self.model, field_name):
                        field_obj = getattr(self.model, field_name)
                        GenericForeignKey = importGenericForeignKey()
                        if isinstance(field_obj, GenericForeignKey):
                            ctype_field_name = field_obj.ct_field
                            ctype_field_attname = self.model._meta.get_field(
                                    ctype_field_name).attname
                            object_id_attname = field_obj.fk_field
                            params.append((getattr(instance, ctype_field_attname),
                                          (getattr(instance, object_id_attname))))
                            if (object_id_attname in instance_state_diff and
                                'pre' in instance_state_diff[object_id_attname]):
                                params_pre.append((
                                    getattr(instance, ctype_field_attname),
                                    instance_state_diff[object_id_attname]['pre']))
                            else:
                                params_pre.append((
                                    getattr(instance, ctype_field_attname),
                                    getattr(instance, object_id_attname)))
                            continue
                    raise
            params_list.append(params)
            if params_pre != params:
                params_list.append(params_pre)
        return params_list


class InstanceCache(six.with_metaclass(InstanceCacheMeta,
        BaseModelQueryCache, SameModelInvalidationCache)):
    """ This class is used when an instance of a model is cached on
    some fields of same model.

    Derived class can define following (*s are mandatory):

    1) model: ModelClass                            (* attribute)
    2) key_fields: list of field_names              (* attribute)
    3) select_related: list of related instances    (attribute)
    4) get_instance : custom method to get instance (method)
    """
    cache_type = 'InstanceCache'

    @abstractproperty
    def key_fields(self):
        pass

    @classmethod
    def register_related_caches(cls):
        cls.related_caches = {}
        if not hasattr(cls, 'select_related'):
            return
        for relation in cls.select_related:
            class_name = '%s__%s' % (cls.__name__, relation)
            # Create new RelatedInstanceCache class dynamically
            related_cache_class = type(class_name, (RelatedInstanceCache,), {
                'model': cls.model,
                'key_fields': cls.key_fields,
                'relation': relation,
                'version': cls.version,
                'timeout': cls.timeout,
            })
            # And store it's instance in related_caches
            cls.related_caches[relation] = related_cache_class

    @instancemethod
    def get_cache_model(self):
        return self.model

    @instancemethod
    def get_invalidation_models(self):
        return self._get_invalidation_models()

    def get_keys_to_be_invalidated(self, instance, signal, using):
        return self._get_keys_to_be_invalidated(instance, signal, using)

    def get_extra_keys(self, *args, **kwargs):
        """ Returns the keys from assosiated related cache classes
        for given params.
        """
        if not hasattr(self, 'select_related'):
            return
        keys = []
        for relation in self.select_related:
            related_cache = self.related_caches[relation]
            key = related_cache.get_key(*args, **kwargs)
            keys.append(key)
        return keys

    def get_instance(self, **filter_dict):
        """ Returns the instance of model.
        Can be overriden in derived classes.
        """
        try:
            return self.model.objects.using(self.using).get(**filter_dict)
        except self.model.DoesNotExist:
            if self.is_simple:
                # Returning the None so that it gets cached.
                return DontCache(None)
            raise
        except:
            raise

    def remove_fk_instances(self, instance):
        """ Removes all related instances through fields on instance
        before the instance gets saved in cache
        """
        if instance is None:
            return

        for prop in flash_properties[instance.__class__]:
            attr = '_%s_cache' % prop
            if hasattr(instance, attr):
                delattr(instance, attr)

        for field in instance._meta.fields:
            if field.rel:
                attr = '_%s_cache' % field.name
                if hasattr(instance, attr):
                    delattr(instance, attr)

    def get_value_for_params(self, *args, **kwargs):
        params = self.get_field_dict(*args, **kwargs)
        instance = self.get_instance(**params)
        return instance

    def pre_set_process_value(self, instance, *args, **kwargs):
        instance_clone = copy.copy(instance)
        self.remove_fk_instances(instance_clone)
        return instance_clone

    def get_extra_key_value_dict(self, instance, *args, **kwargs):
        """ Returns the key value dict from relations given in select_related
        for given instance. Used when instance is saved in cache.
        """
        if instance is None:
            return
        if self.related_caches:
            key_value_dict = {}
            for relation in self.related_caches:
                related_value = instance
                for field_name in relation.split('__'):
                    related_value = getattr(related_value, field_name)
                related_cache = self.related_caches[relation]
                related_key = related_cache.get_key(*args, **kwargs)
                key_value_dict[related_key] = related_value
            return key_value_dict

    def post_process_value(self, instance, key_value_dict, *args, **kwargs):
        """ Patches all related instances got from cache in key_value_dict
        to instance.
        """
        if instance is None:
            if self.is_simple:
                cache_model = self.get_cache_model()
                raise cache_model.DoesNotExist(
                        "%s matching query does not exist." %
                        cache_model._meta.object_name)
            return instance
        if not hasattr(self, 'select_related'):
            return instance
        if key_value_dict is None:
            return instance
        keys = []
        relation_keys = {}
        for relation in self.select_related:
            related_cache = self.related_caches[relation]
            key = related_cache.get_key(*args, **kwargs)
            keys.append(key)
            relation_keys[relation] = key

        for relation in self.select_related:
            key = relation_keys[relation]
            if not key in key_value_dict:
                continue
            value = key_value_dict[key]
            last_field_name = None
            related_value = instance
            for field_name in (relation.split('__') + [None]):
                if field_name is None:
                    setattr(related_value, last_field_name, value)
                else:
                    if last_field_name:
                        if not hasattr(related_value, last_field_name):
                            break
                        related_value = getattr(related_value, last_field_name)
                last_field_name = field_name
        return instance


class RelatedInstanceCacheMeta(InstanceCacheMeta):
    """ Meta class for RelatedInstanceCache
    """
    def __new__(cls, *args, **kwargs):
        ncls = super(RelatedInstanceCacheMeta, cls).__new__(cls, *args, **kwargs)
        if is_abstract_class(ncls):
            return ncls
        # store all models encountered in reaching last field of relation
        # in rel_models of new class.
        model = ncls.model
        rel_models = {}
        rel_models_inv = {}
        rel_model = model
        relation_splits = ncls.relation.split('__')
        relation_str = ''
        for field_name in relation_splits:
            rel_model = rel_model._meta.get_field(field_name).rel.to
            if relation_str:
                relation_str += '__%s' % field_name
            else:
                relation_str += field_name
            rel_models[rel_model] = relation_str
            rel_models_inv[relation_str] = rel_model
        ncls.rel_models = rel_models
        ncls.rel_models_inv = rel_models_inv
        return ncls


class RelatedModelInvalidationCache(object):
    """ Mixin class used in RelatedInstanceCache, RelatedQuerysetCache
    """
    def _get_invalidation_models(self):
        return [self.model] + self.rel_models.keys()

    def _get_keys_to_be_invalidated(self, instance, signal, using):
        keys = []
        for params in self.get_invalidation_params_list(instance, signal):
            keys.append(self.get_key(*params, **{USING_KWARG: using}))
        return keys

    def get_invalidation_params_list(self, instance, signal):
        """ It's called when an instance gets saved and caches
        have to be invalidated.

        Returns the list of params on which keys to be invalidated.
        """
        key_params_list = []

        key_fields_attname = []
        for field_name in self.key_fields:
            field = self.model._meta.get_field(field_name)
            key_fields_attname.append(field.attname)

        if isinstance(instance, self.model):
            # get all values in instance assosiated with
            # key_fields and put in params list.
            field_values = []
            field_values_pre = []
            instance_state_diff = instance.get_state_diff()
            for field_attname in key_fields_attname:
                value = getattr(instance, field_attname)
                field_values.append(value)
                if field_attname in instance_state_diff and (
                        'pre' in instance_state_diff[field_attname]):
                    field_values_pre.append(instance_state_diff[field_attname]['pre'])
                else:
                    field_values_pre.append(value)
            key_params_list.append(tuple(field_values))
            if field_values_pre != field_values:
                key_params_list.append(tuple(field_values_pre))

        for rel_model in self.rel_models:
            if isinstance(instance, rel_model):
                filter_dict = {
                    self.rel_models[rel_model]: instance,
                }
                # get list of all values using database
                attname_values_list = self.model.objects.filter(
                        **filter_dict).values(*key_fields_attname)
                for value in attname_values_list:
                    key_params_list.append(tuple(
                        [value[attname] for attname in key_fields_attname]))
        if isinstance(instance, tuple):
            # case when instances of many_to_many through model are added
            # or removed.
            instance, _, model, pk_set = instance
            if len(self.key_fields) == 1:
                if (self.key_fields[0] ==
                        instance.__class__._meta.object_name.lower()):
                    key_params_list.append((instance.id,))
                elif (self.key_fields[0] ==
                        model._meta.object_name.lower()):
                    for pk in pk_set:
                        key_params_list.append((pk,))
            else:
                filter_dict = {
                    instance.__class__._meta.object_name.lower():
                        instance.pk,
                    '%s__in' % model._meta.object_name.lower():
                        pk_set,
                }
                # get list of all values using database
                attname_values_list = self.model.objects.filter(
                        **filter_dict).values(*key_fields_attname)
                for value in attname_values_list:
                    key_params_list.append(tuple(
                        [value[attname] for attname in key_fields_attname]))
        return key_params_list



class RelatedInstanceCache(six.with_metaclass(RelatedInstanceCacheMeta,
                           InstanceCache, RelatedModelInvalidationCache)):
    """ This class is used when an instance through a related field is cached on
        some fields of a model.

        Derived class can define following (*s are mandatory):

        1) model: ModelClass                            (* attribute)
        2) key_fields: list of field_names              (* attribute)
        3) relation: related field_name                 (* attribute)
        4) get_instance : custom method to get instance (method)
    """
    generic_fields_support = False

    cache_type = 'RelatedInstanceCache'

    @abstractproperty
    def relation(self):
        pass

    @instancemethod
    def get_cache_model(self):
        return self.rel_models_inv[self.relation]

    @instancemethod
    def get_invalidation_models(self):
        return RelatedModelInvalidationCache._get_invalidation_models(self)

    def get_keys_to_be_invalidated(self, instance, signal, using):
        return RelatedModelInvalidationCache._get_keys_to_be_invalidated(
                self, instance, signal, using)

    def get_instance(self, **filter_dict):
        dep_instance = self.model.objects.using(self.using).select_related(
                self.relation).get(**filter_dict)
        instance = dep_instance
        for rel_attr in self.relation.split('__'):
            instance = getattr(instance, rel_attr)
        return instance


class QuerysetCacheMeta(BaseModelQueryCacheMeta):
    """ Meta class of QuerysetCache class
    """
    queryset_cache_classes = defaultdict(list)

    def __new__(cls, *args, **kwargs):
        ncls = super(QuerysetCacheMeta, cls).__new__(cls, *args, **kwargs)
        if is_abstract_class(ncls):
            return ncls
        model = ncls.model
        cls.queryset_cache_classes[model].append(ncls)
        if (six.get_unbound_function(ncls.get_result) ==
                six.get_unbound_function(QuerysetCache.get_result)):
            ncls.is_simple = True
        else:
            ncls.is_simple = False
        return ncls


class QuerysetCache(six.with_metaclass(QuerysetCacheMeta,
                    BaseModelQueryCache, SameModelInvalidationCache)):
    """ This class is used when result of filter queryset or its
        descendent queryset of a model is cached on some fields of same model.

        Derived class can define following (*s are mandatory):

        1) model: ModelClass                            (* attribute)
        2) key_fields: list of field_names              (* attribute)
        4) get_result : custom method to get result     (method)
    """
    cache_type = 'QuerysetCache'

    caching_model_instances = True

    @abstractproperty
    def key_fields(self):
        pass

    @instancemethod
    def get_cache_model(self):
        if self.caching_model_instances:
            return self.model
        return None

    @instancemethod
    def get_invalidation_models(self):
        return self._get_invalidation_models()

    def get_keys_to_be_invalidated(self, instance, signal, using):
        return self._get_keys_to_be_invalidated(instance, signal, using)

    def get_result(self, **params):
        """ By default returns the filter queryset's result
        """
        return list(self.model.objects.using(self.using).filter(**params))

    def get_value_for_params(self, *args, **kwargs):
        params = self.get_field_dict(*args, **kwargs)
        result = self.get_result(**params)
        return result


class RelatedQuerysetCacheMeta(QuerysetCacheMeta):
    """ Meta class of RelatedQuerysetCache class
    """
    def __new__(cls, *args, **kwargs):
        ncls = super(RelatedQuerysetCacheMeta, cls).__new__(cls, *args, **kwargs)
        if is_abstract_class(ncls):
            return ncls
        # store all models encountered in reaching last field of relation
        # in rel_models of new class.
        model = ncls.model
        rel_models = {}
        rel_models_inv = {}
        rel_model = model
        relation_splits = ncls.relation.split('__')
        relation_str = ''
        for field_name in relation_splits:
            rel_model = rel_model._meta.get_field(field_name).rel.to
            if relation_str:
                relation_str += '__%s' % field_name
            else:
                relation_str += field_name
            rel_models[rel_model] = relation_str
            rel_models_inv[relation_str] = rel_model
        ncls.rel_models = rel_models
        ncls.rel_models_inv = rel_models_inv
        return ncls


class RelatedQuerysetCache(six.with_metaclass(RelatedQuerysetCacheMeta,
                           QuerysetCache, RelatedModelInvalidationCache)):
    """ This class is used when result of filter queryset or its descendent
        queryet through a related field is cached on some fields of a model.

        Derived class can define following (*s are mandatory):

        1) model: ModelClass                            (* attribute)
        2) key_fields: list of field_names              (* attribute)
        3) relation: related field_name                 (* attribute)
        4) get_result : custom method to get result     (method)
    """
    generic_fields_support = False

    cache_type = 'RelatedQuerysetCache'

    @instancemethod
    def get_cache_model(self):
        return self.rel_models_inv[self.relation]

    @abstractproperty
    def relation(self):
        pass

    @instancemethod
    def get_invalidation_models(self):
        return RelatedModelInvalidationCache._get_invalidation_models(self)

    def get_keys_to_be_invalidated(self, instance, signal, using):
        return RelatedModelInvalidationCache._get_keys_to_be_invalidated(
                self, instance, signal, using)

    def get_result(self, **params):
        qset = self.model.objects.using(self.using).filter(**params).select_related(
            self.relation)
        return list([getattr(i, self.relation) for i in qset])


class QuerysetExistsCache(QuerysetCache):
    """ QuerysetCache derived class to cache existance of instances
    """
    caching_model_instances = False

    @abstractproperty
    def key_fields(self):
        pass

    def get_result(self, **params):
        return self.model.objects.filter(**params).exists()

    def post_process_value(self, value, *args, **kwargs):
        """ It's defined cause cache retuned values are integers (0 or 1)
            It converts them to boolean
        """
        if value is None:
            return value
        return bool(value)


class CacheManager(six.with_metaclass(ABCMeta, object)):
    """ Base class for model or non model based cache managers
    """


class CachedReverseSingleRelatedObjectDescriptor(
        ReverseSingleRelatedObjectDescriptor):
    def __init__(self, field_with_rel, cache_class):
        super(CachedReverseSingleRelatedObjectDescriptor, self).__init__(
                field_with_rel)
        self.cache_class = cache_class

    def __get__(self, instance, instance_type=None):
        if instance is None:
            return self
        try:
            return getattr(instance, self.cache_name)
        except AttributeError:
            val = getattr(instance, self.field.attname)
            if val is None:
                # If NULL is an allowed value, return it.
                if self.field.null:
                    return None
                raise self.field.rel.to.DoesNotExist
            rel_obj = self.cache_class.get(val)
            setattr(instance, self.cache_name, rel_obj)
            return rel_obj

def patch_related_object_descriptor(model, key, cache_class):
    orig_key = '_%s_using_db' % key
    setattr(model, orig_key, getattr(model, key))
    setattr(model, key, CachedReverseSingleRelatedObjectDescriptor(
        model._meta.get_field(key), cache_class))


class ModelCacheManagerMeta(ABCMeta):
    """ Meta class for ModelCacheManager
    """
    model_cache_managers = {}
    model_cached_foreignkeys = defaultdict(list)

    def __new__(cls, *args, **kwargs):
        own_attrs = args[2]
        model = own_attrs['model']

        if model in cls.model_cache_managers:
            # Commenting assertion due to some module reloading bug
            # assert False, "More than one ModelCacheManager can't be defined for %s" % (
            #     model,)
            return cls.model_cache_managers[model]

        if hasattr(model, 'CacheMeta'):
            cachemeta_attrs = {}
            for key, value in model.CacheMeta.__dict__.items():
                if not key.startswith('_'):
                    cachemeta_attrs[key] = value

            mergable_keys = [
                'key_fields_list',
                'filter_key_fields_list',
                'cached_foreignkeys'
            ]

            for key, value in cachemeta_attrs.items():
                if key in mergable_keys:
                    if (isinstance(value, (tuple, list)) and
                            key in own_attrs and
                            [i for i in value if i in own_attrs[key]]):
                        assert False, "`%s` in CacheMeta and %s should not have common values" % (
                            key, args[0])
                    own_attrs[key] = cachemeta_attrs[key] + own_attrs.get(key, [])
                elif key in own_attrs:
                    assert False, "`%s` can't be defined in both CacheMeta and %s" % (
                            key, args[0])
                else:
                    own_attrs[key] = cachemeta_attrs[key]

        ncls = super(ModelCacheManagerMeta, cls).__new__(cls, *args, **kwargs)
        if is_abstract_class(ncls):
            return ncls
        model = ncls.model
        ncls_instance = ncls()

        # register instance of new ModelCacheManager class
        cls.model_cache_managers[model] = ncls_instance

        # register all simple_instance_cache_classes
        # and simple_queryset_cache_classes so that `get` and `filter` methods
        # of model cache manager can decide which cache class to be used
        ncls.instance_cache_classes = []
        ncls.simple_instance_cache_classes = {}

        if hasattr(ncls_instance, 'key_fields_list'):
            # create instance_cache_classes for assosiated model
            ncls_instance.register_instance_classes()

        for instance_cache_class in InstanceCacheMeta.instance_cache_classes[
                model]:
            ncls.instance_cache_classes.append(instance_cache_class)
            if instance_cache_class.is_simple:
                key_fields_sorted = tuple(
                        sorted(instance_cache_class.key_fields))
                ncls.simple_instance_cache_classes[
                    key_fields_sorted] = instance_cache_class

        ncls.queryset_cache_classes = []
        ncls.simple_queryset_cache_classes = {}

        if hasattr(ncls_instance, 'filter_key_fields_list'):
            # create queryset_cache_classes for assosiated model
            ncls_instance.register_queryset_classes()

        for queryset_cache_class in QuerysetCacheMeta.queryset_cache_classes[
                model]:
            ncls.queryset_cache_classes.append(queryset_cache_class)
            if queryset_cache_class.is_simple:
                key_fields_sorted = tuple(
                        sorted(queryset_cache_class.key_fields))
                ncls.simple_queryset_cache_classes[
                    key_fields_sorted] = queryset_cache_class

        if hasattr(ncls_instance, 'cached_foreignkeys'):
            cls.model_cached_foreignkeys[model] = ncls_instance.cached_foreignkeys

        return ncls

    @classmethod
    def create_cache_managers_from_models(cls):
        for model in get_models():
            if (not model in cls.model_cache_managers and
                    hasattr(model, 'CacheMeta')):
                cache_manager_name = 'Auto%sCacheManager' % model.__name__
                type(cache_manager_name, (ModelCacheManager,), {
                    'model': model})


    @classmethod
    def patch_cached_foreignkeys(cls):
        for model, cached_foreignkeys in cls.model_cached_foreignkeys.items():
            for key in cached_foreignkeys:
                try:
                    rel_model = model._meta.get_field(key).rel.to
                    rel_model_pk_name = rel_model._meta.pk.name
                    cache_class = rel_model.cache.get_cache_class_for(
                        rel_model_pk_name)
                    patch_related_object_descriptor(
                        model, key, cache_class)
                except CacheNotRegistered:
                    assert False, ("Cached foreignkey can't be made on field "+
                                   "`%s` of %s. Because %s is not cached on "+
                                   "it's primary key") % (
                        key, model, model._meta.get_field(key).rel.to)


    @classmethod
    def get_model_cache_manager(cls, model):
        """ Returns the cache manager assosiated with given model
        """
        if model not in cls.model_cache_managers:
            # If some model cache manager class is not defined for given
            # model then create it dynamically
            class_name = 'Auto%sCacheManager' % model.__name__
            type(class_name, (ModelCacheManager,), {
                        'model': model})
        return cls.model_cache_managers[model]


class CacheNotRegistered(Exception):
    def __init__(self, model, key_fields):
        msg = ('No cache registered for model `%s` on fields '+
               '`%s`') % (str(model), str(tuple(key_fields)))
        super(CacheNotRegistered, self).__init__(msg)


class ModelCacheManager(six.with_metaclass(ModelCacheManagerMeta,
                        CacheManager)):
    version = 0
    timeout = flash_settings.DEFAULT_TIMEOUT

    @abstractproperty
    def model(self):
        pass

    def register_instance_classes(self):
        """ Create InstanceCache classes dynamically
        for each pair in key_fields_list.
        """
        for key_fields in self.key_fields_list:
            class_name = '%sCacheOn' % self.model.__name__
            for field_name in key_fields:
                class_name += field_name.title()
            type(class_name, (InstanceCache,), {
                'model': self.model,
                'key_fields': key_fields,
                'version': self.version,
                'timeout': self.timeout,
            })

    def register_queryset_classes(self):
        """ Create QuerysetCache classes dynamically
        for each pair in filter_key_fields_list.
        """
        for key_fields in self.filter_key_fields_list:
            class_name = '%sCacheOn' % self.model.__name__
            for field_name in key_fields:
                class_name += field_name.title()
            type(class_name, (QuerysetCache,), {
                'model': self.model,
                'key_fields': key_fields,
                'version': self.version,
                'timeout': self.timeout,
            })

    def get_key_fields(self, args_or_kwargs):
        key_fields = []

        is_dict = False
        if isinstance(args_or_kwargs, dict):
            args_set = set(args_or_kwargs.keys())
            is_dict = True
            kwargs = args_or_kwargs
        else:
            args_set = set(args_or_kwargs)

        if 'pk' in args_set:
            args_set.remove('pk')
            if is_dict:
                value = kwargs.pop('pk')
            pk_field_name = self.model._meta.pk.name
            args_set.add(pk_field_name)
            if is_dict:
                kwargs[pk_field_name] = value

        for key in args_set:
            if key == USING_KWARG:
                continue
            try:
                field = self.model._meta.get_field(key)
                key_fields.append(field.name)
            except:
                if hasattr(self.model, key):
                    field = getattr(self.model, key)
                    GenericForeignKey = importGenericForeignKey()
                    if isinstance(field, GenericForeignKey):
                        key_fields.append(key)
                        continue
                if key.endswith('_id'):
                    key_fields.append(key[:-3])
                    continue
                raise
        return tuple(sorted(key_fields))

    def get(self, **kwargs):
        """ Find the instance_cache_class for given params
        and return it's get result.
        """
        key_fields = self.get_key_fields(kwargs)
        if key_fields in self.simple_instance_cache_classes:
            instance_cache_class = self.simple_instance_cache_classes[key_fields]
            return instance_cache_class.get(**kwargs)
        raise CacheNotRegistered(self.model, key_fields)

    def get_query(self, **kwargs):
        """ Find the instance_cache_class for given params
        and return it's object for given params.
        """
        key_fields = self.get_key_fields(kwargs)
        if key_fields in self.simple_instance_cache_classes:
            instance_cache_class = self.simple_instance_cache_classes[key_fields]
            return instance_cache_class(**kwargs)
        raise CacheNotRegistered(self.model, key_fields)

    def get_async(self, **kwargs):
        """ await counterpart of get method
        """
        return self.get_query(**kwargs).resolve_async()

    def get_async_or_none(self, **kwargs):
        from .loader import object_or_none
        return object_or_none(self.get_async(**kwargs))

    def get_async_or_404(self, **kwargs):
        from .loader import object_or_404
        return object_or_404(self.get_async(**kwargs))

    def get_cache_class_for(self, *args):
        """ Find the instance_cache_class for given params
        and return it's cache class.
        """
        key_fields = self.get_key_fields(args)
        if key_fields in self.simple_instance_cache_classes:
            instance_cache_class = self.simple_instance_cache_classes[key_fields]
            return instance_cache_class
        raise CacheNotRegistered(self.model, args)

    def get_key(self, **kwargs):
        """ Find the instance_cache_class for given params
        and return it's get_key result.
        """
        key_fields = self.get_key_fields(kwargs)
        if key_fields in self.simple_instance_cache_classes:
            instance_cache_class = self.simple_instance_cache_classes[key_fields]
            return instance_cache_class.get_key(**kwargs)
        raise CacheNotRegistered(self.model, key_fields)

    def filter(self, **kwargs):
        """ Find the queryset_cache_class for given params
        and return it's get result.
        """
        key_fields = self.get_key_fields(kwargs)
        if key_fields in self.simple_queryset_cache_classes:
            queryset_cache_class = self.simple_queryset_cache_classes[key_fields]
            return queryset_cache_class.get(**kwargs)
        raise CacheNotRegistered(self.model, key_fields)

    def filter_query(self, **kwargs):
        """ Find the queryset_cache_class for given params
        and return it's object for given params.
        """
        key_fields = self.get_key_fields(kwargs)
        if key_fields in self.simple_queryset_cache_classes:
            queryset_cache_class = self.simple_queryset_cache_classes[key_fields]
            return queryset_cache_class(**kwargs)
        raise CacheNotRegistered(self.model, key_fields)

    def filter_async(self, **kwargs):
        """ await counterpart of filter method.
        """
        return self.filter_query(**kwargs).resolve_async()

    def filter_cache_class_for(self, *args):
        """ Find the queryset_cache_class for given params
        and return it's cache class.
        """
        key_fields = self.get_key_fields(args)
        if key_fields in self.simple_queryset_cache_classes:
            queryset_cache_class = self.simple_queryset_cache_classes[key_fields]
            return queryset_cache_class
        raise CacheNotRegistered(self.model, args)

    def get_or_404(self, **kwargs):
        """ If the get result is not found raises 404.
        """
        try:
            return self.get(**kwargs)
        except self.model.DoesNotExist:
            raise Http404('No %s matches the given query.' %
                    self.model._meta.object_name)

    def get_or_none(self, **kwargs):
        """ If the get result is not found returns None.
        """
        try:
            return self.get(**kwargs)
        except self.model.DoesNotExist:
            return None
