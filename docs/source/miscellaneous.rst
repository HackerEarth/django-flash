*************
Miscellaneous
*************

This section talks about many things.


CacheMeta
#########

If you are too lazy to create ModelCacheManager class for a model in
<some_app>/caches.py, then you can just create CacheMeta class inside your model
and define attributes like get_key_fields_list, filter_key_fields_list etc.

E.g.


.. code-block:: python

    class Event(models.Model):
        slug = models.CharField(...)
        title = models.CharField(...)
        # other fields

        class CacheMeta:
            get_key_fields_list = [
                ('id',),
                ('slug',),
            ]

    # Then you can use cache queries
    event = Event.cache.get(id=event_id)
    # or
    event = Event.cache.get(slug=event_slug)


If both ModelCacheManager and CacheMeta are defined for a model then
attributes defined in both classes gets merged.


Cached ForeignKey
#################

Consider this model Participation which foreignkeys to model Event.

.. code-block:: python

    class Participation(models.Model):
        event = models.ForeignKey(Event)
        user = models.ForeignKey(User)
        # other fields

And you've got an instance of Participation say :code:`participation`, then
accessing event on it by :code:`participation.event` will make a db query.
But we know that we can get event using cache call simply if we have id of it.
To make foreignkeys to use memcache call instead of db query, put in all names
of such fields in :code:`cached_foreignkeys` in CacheMeta or ModelCacheManager.

E.g. change above code to

.. code-block:: python

    class Participation(models.Model):
        event = models.ForeignKey(Event)
        user = models.ForeignKey(User)
        # other fields

        class CacheMeta:
            cached_foreignkeys = ['event', 'user']

    # Now accessing event on participation will make cache call instead of
    # db query
    event = participation.event

**Note**: cached_foreignkeys will work only if related model has cache class
registered (by InstanceCache or get_key_fields_list) on it's primary key and
:code:`get_instance` method is not overridden.


Timeout
#######

:code:`timeout` attribute can be put on all types of cache classes and
ModelCacheManager. Timeout is number of seconds after which memcached will
make the value expired. By default it is a week.

E.g.

.. code-block:: python

    from flash.constants import CACHE_TIME_DAY

    class UserCacheOnUsername(InstanceCache):
        model = User
        key_fields = ('username',)

        timeout = CACHE_TIME_DAY


Static version
##############

All cache classes have static versions associated with them, which are
concatenated while creating keys. Version should be an integeral value and by default it's Zero (0). So increment the version every time you change the logic of getting value using fallback method.

E.g.

.. code-block:: python

    class ParticipatedEventIdListCacheOnUser(QuerysetCache):
        model = Participation
        key_fields = ('user',)

        version = 2

        def get_result(self, user):
            event_ids = Participation.objects.filter(
                            user=user).values_list('event', flat=True)
            return event_ids

**Note**: Do not just bump this static version if some migrations are made on
some model.


Dynamic version
###############

All values which are saved in memcached against keys are wrapped in a special
class along with a timestamp at that time and a dynamic version of their cache
class. So when some new fields are added/modified/deleted in a model, you just
need to bump the dynamic version of all cache classes associated with that
model.

E.g. You made some changes in fields of Event model, then after the migrations
are done and code changes have been deployed, do this in shell.

.. code-block:: python

    from flash.models import CacheDynamicVersion
    CacheDynamicVersion.objects.bump_version_for_model(Event)


Invalidation
############

Flash handles invalidation automatically by default.

Each cache class has an invalidation type associated with it.
It can be set by giving one of the follwoing values to attribute
:code:`invalidation` inside cache class.

* InvalidationType.OFF
    No automatic invalidation will happen.

* InvalidationType.UNSET
    It's the default. Whenever some instance.save(), instance.delete(),
    queryset.update() or queryset.delete() happens, corresponding keys
    to instances which get changed are deleted from memcached.

    Next time cache query happens, key won't be found in memcached then
    it will get set in memcached after getting the value from db.

* InvalidationType.DYNAMIC
    Values get invalidated dynamically. When a value is fetched it's checked
    whether it is stale or not by checking associated key.


Allowtime
#########

If a db query is expensive and write is heavy on some model so that cache is
getting invalidated very frequently, then you may get okay with serving stale data
for some time (let's say for few seconds to minutes).

You may come up with the solution of making invalidation OFF and putting the timeout
little. But this costs you even when there is no change in your model and
db query happens everytime after the timeout.

So instead of doing this you can put :code:`allowtime` attribute and make
invalidation DYNAMIC. It will allow the value to be stale for given time but
also only invalidate it if it's needed.


Manual Invalidation
###################

Sometimes it may happen (due to misconfiguration maybe) that some cache query's
value gets inconsistent against some instances of a model and you want to
invalidate them, then use :code:`invalidate_flash_cache()` method on the
queryset.

.. code-block:: python

    # Make a queryset conatining all those instances
    qs = YourModel.objects.filter(...)
    # and then do this
    qs.invalidate_flash_cache()


