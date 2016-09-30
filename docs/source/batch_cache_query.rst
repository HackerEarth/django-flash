***************
BatchCacheQuery
***************

If you want to take advantage of cache.get_many to get mutiple values of
different cache queries in single network call, then BatchCacheQuery is the
right option.


E.g. following code registers some cache classes


.. code-block:: python

    class UserCacheManager(ModelCacheManager):
        model = User
        key_fields_list = [
            ('id',),
            ('username',),
        ]

    class EventCacheOnSlug(InstanceCache):
        model = Event
        key_fields = ('slug',)


And you have a user's id (user_id) and an event's slug (event_slug)
then you can get both instances in single memcached query.


.. code-block:: python

    from flash import BatchCacheQuery

    batch_query = BatchCacheQuery({
        'user': User.cache.get_query(id=user_id),
        'event': EventCacheOnSlug(event_slug),
    })
    result = batch_query.get()

    user = result['user']
    event = result['event']


In above code, :code:`User.cache.get_query(id=user_id)` and :code:`EventCacheOnSlug(event_slug)`
are lazy cache queries which contains passed parameters to be used while
creating key. :code:`User.cache.get_query(id=user_id)` is lazy
counterpart of :code:`User.cache.get(id=user_id)` and
:code:`EventCacheOnSlug(event_slug)` is lazy counterpart of
:code:`EventCacheOnSlug.get(event_slug)`.

:code:`batch_query.get()` returns a dict with same keys given to
BatchCacheQuery() and values as corresponding queries' result evaluated.

In above query, if any one of both cache query raises DoesNotExist exception
then :code:`batch_query.get()` will also raise the exception. One of the
methods to escape from this situation is to pass :code:`none_on_exception=True`
to :code:`batch_query.get()`, then it will put value as :code:`None` in case of
exception.

If you want that :code:`batch_query.get()` should not go for fallback db
methods if value is not found in cache then you may pass :code:`only_cache=True`
to it.


Another example, if you have a list of user_ids and you want corresponding User
instances then you can get them by

.. code-block:: python

    user_ids = [...]
    batch_query = BatchCacheQuery()

    for user_id in user_ids:
        batch_query.push({
            user_id: User.cache.get_query(id=user_id),
        })

    result = batch_query.get()
    # result is the dict (user_id as key and instance as value)
