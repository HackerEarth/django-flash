***************
Usage with Python3 Asyncio + DataLoader
***************

Facebook created DataLoader library for batching and caching purposes to be
used with any kind of service. Read more on
https://github.com/facebook/dataloader

The above package is written for JavaScript. There is a port of DataLoader for
Python too (https://github.com/syrusakbary/aiodataloader)
which avails the new async/await syntax provided by Python3.5 for
asyncio.

Flash has got support for making cache query using async/await syntax, recently.

await syntax
############

E.g. following code registers some cache classes

.. code-block:: python

    class User(Model):
        ...
        class CacheMeta:
            key_fields_list = [
                ('id',),
            ]
            filter_key_fields_list = [
                ('first_name',),
            ]

    class EventCacheOnSlug(InstanceCache):
        model = Event
        key_fields = ('slug',)


Here is the syntax to use above classes with asyncio.

.. code-block:: python3

    user = await User.cache.get_async(id=user_id)
    users = await User.cache.filter_async(first_name=first_name)
    event = await EventCacheOnSlug(event_slug).resolve_async()


If we hadn't used asyncio, the code would have looked like

.. code-block:: python

    user = User.cache.get(id=user_id)
    users = User.cache.filter(first_name=first_name)
    event = EventCacheOnSlug(event_slug).resolve()

Like :code:`Model.cache.get_or_none()` and :code:`Model.cache.get_or_404()`,
you can use :code:`Model.cache.get_async_or_none()` and
:code:`Model.cache.get_async_or_404()` with asyncio.


The results get locally cached too for same query with await syntax.

.. code-block:: python3

    user_id = 42
    user1 = await User.cache.get_async(id=user_id)
    user2 = await User.cache.get_async(id=user_id)

The result will get locally cached for first query. And while resolving
second query it will be used from local cache instead of making network call.


Batching multiple queries
#########################

In earlier section, we had seen how to batch queries using :code:`BatchCacheQuery`.
With asyncio and dataloaders you need to use :code:`asyncio.gather` function.
Let's say you have a list of user_ids and you want corresponding User
instances then you can get them at once by

.. code-block:: python3

    from asyncio import gather

    users = await gather(*[
        User.cache.get_async(id=user_id) for user_id in user_ids
    ])


Multiple independent cache queries can also be gathered/batched together. E.g.

.. code-block:: python3

    user, event = await gather(
        User.cache.get_async(id=user_id),
        EventCacheOnSlug(slug=event_slug).resolve_async()
    )

The above code results in one network call for both queries.


While using :code:`gather`, it will raise exception if any one of the cache
query raises an exception (E.g. User.DoesNotExist). If you manually want to
handle exceptions for individual queries, then pass :code:`return_exceptions=True`
while calling gather(). In this case, the result objects can be exception
objects too. (
Read more on https://docs.python.org/3/library/asyncio-task.html#asyncio.gather
) E.g.

.. code-block:: python3

    user_result, event_result = await gather(
        User.cache.get_async(id=user_id),
        EventCacheOnSlug(slug=event_slug).resolve_async(),
        return_exceptions=True,
    )

    if isinstance(user_result, Exception):
        # handle

    if isinstance(event_result, Exception):
        # hanlde


Event loop
##########

The async/await syntax works with coroutine functions only. And coroutines can be used
inside other coroutines only. So it is advised to write your Django view as a
coroutine function and apply :code:`run_in_async_loop` decorator, that would be
the starting point.

E.g. If your view was like

.. code-block:: python3

    def my_view(request, event_slug, ...):
        ...
        data = get_data(event_slug)
        ...

    def get_data(event_slug):
        event = EventCacheOnSlug(event_slug).resolve()
        return {
            'event': serialize_event(event),
        }



Change it too


.. code-block:: python3

    from core.utils.asyncio import run_in_async_loop

    @run_in_async_loop
    async def my_view(request, event_slug, ...):
        ...
        data = await get_data(event_slug)
        ...

    async def get_data(event_slug):
        event = await EventCacheOnSlug(event_slug).resolve_async()
        return {
            'event': serialize_event(event),
        }


If you are running workers with while loop, you can put this decorator on
loop function (or callback method) and call that function inside loop.

The decorator is defined like:

.. code-block:: python3

    import asyncio
    from functools import wraps

    from thread_context.dataloader_context import DataLoadersFactory


    def run_in_async_loop(coroutine_func):
        @wraps(coroutine_func)
        def wrappped_func(*args, **kwargs):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.get_event_loop()
            DataLoadersFactory.reset()
            try:
                return loop.run_until_complete(
                    coroutine_func(*args, **kwargs))
            finally:
                loop.close()
        return wrappped_func


You might have noticed that we haven't used DataLoders explicilty. This is because
we are using it implicitly using :code:`DataLoadersFactory`.
:code:`DataLoadersFactory.get_loader_for(DataLoaderSubclass)` is used
to get the same instance of defined DataLoaderSubclass for current thread.
And it is necessary to call :code:`DataLoadersFactory.reset()` otherwise locally cached
results for any DataLoader subclass won't ever get removed.


Dependencies
############

Flash has peer dependencies on packages **aiodataloader** and **he-thread-context**.
So host project should install these python packages to use Flash's asyncio functionality.
