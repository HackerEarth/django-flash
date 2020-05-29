from flash import (
        ModelCacheManager, InstanceCache, RelatedInstanceCache,
        RelatedQuerysetCache)

from .models import ModelA, ModelB, ModelC, ModelD


class ModelACacheManager(ModelCacheManager):
    model = ModelA
    get_key_fields_list = [
        ('num',),
    ]


class ModelBCacheManager(ModelCacheManager):
    model = ModelB
    get_key_fields_list = [
        ('a',)
    ]
    filter_key_fields_list = [
        ('num',),
    ]


class ModelCCacheManager(ModelCacheManager):
    model = ModelC

    def get_B_for_A(self, a):
        return BCacheOnCA.get(a)

    def get_B_list_for_A(self, a):
        return BListCacheOnCA.get(a)


class BCacheOnCA(RelatedInstanceCache):
    model = ModelC
    key_fields = ('a',)
    relation = 'b'


class BCacheOnNum(InstanceCache):
    model = ModelB
    key_fields = ('num',)
    select_related = ['a']


class BListCacheOnCA(RelatedQuerysetCache):
    model = ModelC
    key_fields = ('a',)
    relation = 'b'


class AListCacheOnD(RelatedQuerysetCache):
    model = ModelD.a_list.through
    key_fields = ('modeld',)
    relation = 'modela'
