import time

from django.test import TestCase

from flash.base import cache, BatchCacheQuery

from .models import ModelA, ModelB, ModelC, ModelD
from .caches import BCacheOnNum, AListCacheOnD


class CacheTestCase(TestCase):
    def tearDown(self):
        ModelA.objects.raw("DELETE FROM tests_modela")
        ModelB.objects.raw("DELETE FROM tests_modelb")
        ModelC.objects.raw("DELETE FROM tests_modelc")
        ModelD.objects.raw("DELETE FROM tests_modeld")
        cache.clear()


class InstanceCacheTest(CacheTestCase):
    def test_basic1(self):
        a = ModelA.objects.create(num=1, text='hello')

        self.assertEqual(a, ModelA.cache.get(num=1))

        key = ModelA.cache.get_key(num=1)
        self.assertTrue(bool(cache.get(key)))

        a.text = 'bye'
        a.save()

        self.assertEqual(a, ModelA.cache.get(num=1))

        a.num = 2
        a.save()

        def check_cache(n):
            def get_from_cache():
                return ModelA.cache.get(num=n)
            return get_from_cache

        self.assertEqual(a, ModelA.cache.get(num=2))
        self.assertRaises(ModelA.DoesNotExist, check_cache(1))

        a.delete()

        self.assertRaises(ModelA.DoesNotExist, check_cache(2))


    def test_basic2(self):
        a = ModelA.objects.create(num=1, text='hello')
        b = ModelB.objects.create(num=1, text='hello', a=a)

        self.assertEqual(b, ModelB.cache.get(a=a))

        b.text = 'bye'
        b.save()

        self.assertEqual(b, ModelB.cache.get(a_id=a.id))

        b.delete()

        def get_from_cache():
            return ModelB.cache.get(a=a)

        self.assertRaises(ModelB.DoesNotExist, get_from_cache)


class QuerysetCacheTest(CacheTestCase):
    def test_basic(self):
        a1 = ModelA.objects.create(num=10, text='hello1')
        b1 = ModelB.objects.create(num=1, text='good1', a=a1)
        a2 = ModelA.objects.create(num=11, text='hello2')
        b2 = ModelB.objects.create(num=1, text='good2', a=a2)

        bs = list(ModelB.objects.filter(num=1))
        self.assertEqual(bs, ModelB.cache.filter(num=1))

        b1.text = 'bye1'
        b1.save()

        bs = list(ModelB.objects.filter(num=1))
        self.assertEqual(bs, ModelB.cache.filter(num=1))

        b1.delete()

        bs = list(ModelB.objects.filter(num=1))
        self.assertEqual(bs, ModelB.cache.filter(num=1))


class RelatedInstanceCacheTest(CacheTestCase):
    def test_basic1(self):
        a = ModelA.objects.create(num=1, text='abc')
        b = ModelB.objects.create(num=2, text='def', a=a)
        c = ModelC.objects.create(a=a, b=b, num=3)

        self.assertEqual(b, ModelC.cache.get_B_for_A(a))

        b.text = 'xyz'
        b.save()

        self.assertEqual(b, ModelC.cache.get_B_for_A(a))

    def test_basic2(self):
        a = ModelA.objects.create(num=1, text='abc')
        b = ModelB.objects.create(num=2, text='def', a=a)

        b_cache = BCacheOnNum.get(num=2)
        self.assertTrue(hasattr(b_cache, '_a_cache'))
        self.assertEqual(a, b_cache.a)

        a.text = 'xyz'
        a.save()

        b_cache = BCacheOnNum.get(num=2)
        self.assertEqual(a, b_cache.a)


class RelatedQuerysetCacheTest(CacheTestCase):
    def test_basic1(self):
        a = ModelA.objects.create(num=1, text='abc')
        b1 = ModelB.objects.create(num=2, text='def', a=a)
        c1 = ModelC.objects.create(a=a, b=b1, num=3)
        b2 = ModelB.objects.create(num=3, text='lmn', a=a)
        c2 = ModelC.objects.create(a=a, b=b2, num=4)

        self.assertEqual([b1, b2], ModelC.cache.get_B_list_for_A(a))

        b1.text = 'xyz'
        b1.save()

        self.assertEqual([b1, b2], ModelC.cache.get_B_list_for_A(a))

    def test_basic2(self):
        a1 = ModelA.objects.create(num=10, text='hello1')
        a2 = ModelA.objects.create(num=11, text='hello2')
        d = ModelD.objects.create(num=1)

        d.a_list.add(a1, a2)

        self.assertEqual([a1, a2], AListCacheOnD.get(d))

        a1.text = 'xyz'
        a1.save()

        self.assertEqual([a1, a2], AListCacheOnD.get(d))


class BatchCacheQueryTest(CacheTestCase):
    def test_basic1(self):
        a = ModelA.objects.create(num=1, text='abc')
        b = ModelB.objects.create(num=2, text='def', a=a)

        time.sleep(1)

        result = BatchCacheQuery({
            1: ModelA.cache.get_query(num=1),
            2: BCacheOnNum(num=2),
        }).get()

        self.assertEqual(result, {1:a, 2:b})

        b.delete()

        result = BatchCacheQuery({
            1: ModelA.cache.get_query(num=1),
            2: BCacheOnNum(num=2),
        }).get(only_cache=True)

        self.assertEqual(list(result), [1])

        result = BatchCacheQuery({
            1: ModelA.cache.get_query(num=1),
            2: BCacheOnNum(num=2),
        }).get(none_on_exception=True)

        self.assertEqual(result, {1:a, 2:None})
