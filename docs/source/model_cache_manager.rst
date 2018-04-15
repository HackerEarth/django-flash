*****************
ModelCacheManager
*****************

Suppose there are many key_fields of model on which InstanceCache classes
can be defined. E.g. :code:`User` model's instance can be cached on :code:`id`
as well as on :code:`username`. So instead of defining two InstanceCache
classes like below:

.. code-block:: python

    class UserCacheOnId(InstanceCache):
        model = User
        key_fields = ('id',)

    # and

    class UserCacheOnUsername(InstanceCache):
        model = User
        key_fields = ('username',)


You can define model cache manager class derived from
:code:`flash.ModelCacheManager` for User model.

.. code-block:: python

    from flash import ModelCacheManager

    class UserCacheManager(ModelCacheManager):
        model = User
        get_key_fields_list = [
            ('id',),
            ('username',),
        ]

and you can use both caches on :code:`User.cache` . E.g.

.. code-block:: python

    user = User.cache.get(id=id)

    # and

    user = User.cache.get(username=username)


And in fact, :code:`User.cache` is an instance of :code:`UserCacheManager`
class.
In this case, two instnace cache clases gets created behind the scene using
:code:`get_key_fields_list` attribute on UserCacheManager.
And in last section, an automatic ModelCacheManager class was being created
when we were using :code:`User.cache` but hadn't defined any ModelCacheManager
for User.
