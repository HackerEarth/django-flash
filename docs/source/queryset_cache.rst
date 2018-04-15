*************
QuerysetCache
*************

InstanceCache is useful for caching single instance of a model.
If you want to cache some queryset's result of
model or some descendent query of that model's queryset.
E.g. existance check or count query. You should use QuerysetCache.


.. code-block:: python

    from flash import QuerysetCache

    class ParticipationListCacheOnUser(QuerysetCache):
        model = Participation
        key_fields = ('user',)

    # Using cache class
    participation_list = ParticipationListCacheOnUser(user=user).resolve()


The above class will cache list of all participants for a single user.
You may cache some descendent query result too. E.g. If you want to cache
the list of event ids a user have participated in then you can define it
by overriding default :code:`get_result` method.


.. code-block:: python

    class ParticipatedEventIdListCacheOnUser(QuerysetCache):
        model = Participation
        key_fields = ('user',)

        def get_result(self, user):
            event_ids = self.get_queryset().filter(user=user).values_list(
                            'event', flat=True)
            return event_ids

    event_ids = ParticipatedEventIdListCacheOnUser(user).resolve()


Or if you want to cache the count of the participation of single user


.. code-block:: python

    class ParticipationCountCacheOnUser(QuerysetCache):
        model = Participation
        key_fields = ('user',)

        def get_result(self, user):
            return self.get_queryset().filter(user=user).count()

    participation_count = ParticipationCountCacheOnUser(user).resolve()


You can also use ModelCacheManger to define default QuerysetCache.
E.g. :code:`ParticipationListCacheOnUser`'s behaviour can be achieved by


.. code-block:: python

    class ParticipationCacheManager(ModelCacheManger):
        model = Participation
        get_key_fields_list = [
            ('user', 'event')
        ]
        filter_key_fields_list = [
            ('user',),
        ]

    participation_list = Participation.cache.filter(user=user)


You can also define some supporting methods on ParticipationCacheManager class
for other cache classes defined above


.. code-block:: python

    class ParticipationCacheManager(ModelCacheManger):
        model = Participation
        get_key_fields_list = [
            ('user', 'event')
        ]
        filter_key_fields_list = [
            ('user',),
        ]

        def get_count_for_user(self, user):
            return ParticipationCountCacheOnUser(user).resolve()

        def get_event_id_list_for_user(self, user):
            return ParticipatedEventIdListCacheOnUser(user).resolve()

    # Use the methods
    participation_count = Participation.cache.get_count_for_user(user)
    event_ids = Participation.cache.get_event_id_list_for_user(user)


**Some notes:**

* When overriding :code:`get_result` method, remember that return value should not be
  some lazy queryset object. Use :code:`list()` builitn function to retrieve
  the list first before returning the queryset result in that case.

