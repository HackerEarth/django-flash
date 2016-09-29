from itertools import chain

from flash.base import Cache
from flash import BatchCacheQuery


class Lazy(object):
    def __init__(self, obj):
        self.obj = obj

    def __repr__(self):
        return u"Lazy(%r)" % self.obj

class NonLazy(object):
    def __init__(self, obj):
        self.obj = obj

    def __repr__(self):
        return u"NonLazy(%r)" % self.obj

class LazyCall(object):
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = list(args)
        self.kwargs = kwargs

    def __repr__(self):
        return u"LazyCall(%r, arg=%r, kwargs=%r)" % (
                self.func, self.args, self.kwargs)

class UniqueKey(object):
    def __repr__(self):
        return u"Key(%r)" % id(self)

class ListItemRef(object):
    def __init__(self, l, index):
        self.l = l
        self.index = index

    def get(self):
        return self.l[self.index]

    def set(self, value):
        self.l[self.index] = value

    def __repr__(self):
        return u"ListItemRef<index=%r>" % self.index

class DictValueRef(object):
    def __init__(self, d, key):
        self.d = d
        self.key = key

    def get(self):
        return self.d[self.key]

    def set(self, value):
        self.d[self.key] = value

    def delete(self):
        del self.d[self.key]

    def __repr__(self):
        return u"DictValueRef<key=%r>" % self.key

class LazyObjectRef(object):
    def __init__(self, lazy_obj):
        self.lazy_obj = lazy_obj

    def get(self):
        return self.lazy_obj.obj

    def set(self, value):
        self.lazy_obj.obj = value

    def __repr__(self):
        return u"LazyRef<%r>" % self.lazy_obj


def iter_refs(obj, lazy_only=False):
    if isinstance(obj, list):
        for i in xrange(len(obj)):
            val = obj[i]
            if not lazy_only or isinstance(val, (Lazy, LazyCall)):
                yield ListItemRef(obj, i)
    elif isinstance(obj, dict):
        for key in obj:
            val = obj[key]
            if not lazy_only or isinstance(val, (Lazy, LazyCall)):
                yield DictValueRef(obj, key)
    elif isinstance(obj, Lazy):
        yield LazyObjectRef(obj)
    elif isinstance(obj, LazyCall):
        for ref in chain(
                iter_refs(obj.args, lazy_only=True),
                iter_refs(obj.kwargs, lazy_only=True)):
            yield ref


def get_refs(obj):
    cache_refs = []
    lazy_refs = []
    nonlazy_refs = []
    apply_refs = {}

    for ref in iter_refs(obj):
        value = ref.get()
        if isinstance(value, Cache):
            cache_refs.append(ref)
        elif isinstance(value, Lazy):
            lazy_refs.append(ref)
        elif isinstance(value, NonLazy):
            nonlazy_refs.append(ref)
        if isinstance(value, (list, dict, Lazy, LazyCall)):
            cache_refs1, lazy_refs1, nonlazy_refs1, apply_refs1 = get_refs(value)
            if isinstance(value, LazyCall):
                apply_refs[ref] = {
                    'apply_refs': apply_refs1,
                    'lazy_refs': lazy_refs1,
                    'nonlazy_refs': nonlazy_refs1,
                }
            else:
                lazy_refs = lazy_refs1 + lazy_refs
                nonlazy_refs = nonlazy_refs1 + nonlazy_refs
                apply_refs.update(apply_refs1)
            cache_refs.extend(cache_refs1)

    return cache_refs, lazy_refs, nonlazy_refs, apply_refs


def get_leaf_metarefs(apply_refs, parent_metaref=None):
    metarefs = []
    for ref in apply_refs:
        val = apply_refs[ref]
        metaref = DictValueRef(apply_refs, ref)
        if val['apply_refs'] == {}:
            metarefs.append((metaref, parent_metaref))
        else:
            metarefs.extend(get_leaf_metarefs(val['apply_refs'], metaref))
    return metarefs


def remove_lazy_non_lazy_tags(refs):
    for ref in refs:
        val = ref.get()
        if isinstance(val, (Lazy, NonLazy)):
            ref.set(val.obj)


def eval_cache_refs(cache_refs):
    batch_query = BatchCacheQuery()
    for cache_ref in cache_refs:
        key = UniqueKey()
        batch_query.push({
            key: cache_ref.get()
        })
        cache_ref.set(key)

    batch_result = batch_query.get()
    for cache_ref in cache_refs:
        key = cache_ref.get()
        cache_ref.set(batch_result[key])


def eval_object(obj):
    root_obj = {
        'root': obj
    }
    cache_refs, lazy_refs, nonlazy_refs, apply_refs = get_refs(root_obj)

    if cache_refs:
        eval_cache_refs(cache_refs)

    while apply_refs:
        leaf_metarefs = get_leaf_metarefs(apply_refs)
        cache_refs = []
        for (metaref, parent_metaref) in leaf_metarefs:
            ref = metaref.key
            ref_data = metaref.get()
            apply_obj = ref.get()
            remove_lazy_non_lazy_tags(
                ref_data['lazy_refs']+ref_data['nonlazy_refs'])
            return_value = apply_obj.func(*apply_obj.args, **apply_obj.kwargs)

            return_value_is_lazy = False
            if isinstance(return_value, (Lazy, LazyCall)):
                return_value_is_lazy = True

            while isinstance(return_value, (Lazy, NonLazy)):
                return_value = return_value.obj

            ref.set(return_value)

            delete_metaref = True
            if isinstance(return_value, Cache):
                cache_refs.append(ref)
            elif return_value_is_lazy:
                return_value_obj = {'root': return_value}
                c_refs, l_refs, nl_refs, a_refs = get_refs(return_value_obj)
                cache_refs += c_refs
                extend_lazy_refs = True
                if a_refs:
                    first_ref = a_refs.keys()[0]
                    if isinstance(return_value, LazyCall):
                        ref_data = a_refs[first_ref]
                        metaref.set(ref_data)
                        delete_metaref = False
                    else:
                        ref_data = {
                            'apply_refs': a_refs,
                            'lazy_refs': l_refs,
                            'nonlazy_refs': nl_refs,
                        }
                        if parent_metaref:
                            parent_metaref.set(ref_data)
                        else:
                            apply_refs.update(a_refs)
                        extend_lazy_refs = False
                if extend_lazy_refs:
                    lazy_refs = l_refs + lazy_refs
                    nonlazy_refs = nl_refs + nl_refs
            if delete_metaref:
                metaref.delete()
        if cache_refs:
            eval_cache_refs(cache_refs)

    remove_lazy_non_lazy_tags(lazy_refs+nonlazy_refs)
    return root_obj['root']
