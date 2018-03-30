*************
InstanceCache
*************

To cache single instance of a model on some (one or more) fields of same model,
you have to define a class derived from :code:`flash.InstanceCache` class in
caches.py file inside your app.

Suppose you want to cache :code:`User` model's instance on :code:`username`
field. Then you have to create class:

.. code-block:: python

    from flash import InstanceCache
    from django.contrib.auth.models import User

    class UserCacheOnUsername(InstanceCache):
        model = User
        key_fields = ('username',)


Here, we have created a class :code:`UserCacheOnUsername` derived from
:code:`InstanceCache` with attributes :code:`model` and :code:`key_fields`.
It's mandatory for each type of cache class to define these attributes.
:code:`model` tells whose fields will be given to get the instance.
:code:`key_fields` tells what parameters will be given to get result from memcached.

These parameters must be the fields of same model. If value is not found in
memcached then these are used to retrieve the result from database.

In case of InstanceCache, the model is the same whose instance will get cached.


Use case
########

Here's the code to use our newly created cache class:

.. code-block:: python

    username = 'bill1992'
    user = UserCacheOnUsername.get(username)
    # or
    user = UserCacheOnUsername.get(username=username)


With newer version of flash, preferably use .resolve() instead of .get()

.. code-block:: python

    user = UserCacheOnUsername(username).resolve()


To get result using any type of cache class, you've to use it's :code:`get`
method. In above code, :code:`UserCacheOnUsername.get` tries to get user from
memcached, if not found then fetches it from
database and sets it to memcached.

If user is not found then it will raise :code:`User.DoesNotExist` exception,
which is similar in behaviour if we'd written:

.. code-block:: python

    # Db query
    user = User.objects.get(username=username)


Using cache manager
###################

You can also use :code:`cache` manager on :code:`User` to obtain the instance
which looks very similar to Django's get query syntax:

.. code-block:: python

    user = User.cache.get(username=username)

You will soon get to know about it when we come to :code:`ModelCacheManager`
section.

There are methods :code:`get_or_none` and :code:`get_or_404` on cache
manager which you can also use:

.. code-block:: python

    # It returns User's instance if found otherwise returns None
    user = User.cache.get_or_none(username=username)

    # It raises Http404 exception if instance not found
    user = User.cache.get_or_404(username=username)


Override get_instance
#####################

The current behaviour of InstanceCache derived classes is to use
:code:`<model>.objects.get` on given parameters as fallback method if
value not found in memcached.
You can override this behaviour by defining :code:`get_instance`
method in the class.

E.g. there's Avatar model defined like:

.. code-block:: python

    class Avatar(models.Model):
        user = models.ForeignKey(User)
        file_path = models.FileField()
        primary = models.BooleanField()

And you want to cache primary avatar instnace on user.
Then you do it by

.. code-block:: python

    class PrimaryAvatarCacheOnUser(InstanceCache):
        model = Avatar
        key_fields = ('user',)

        def get_instance(self, user):
            avatars = Avatar.objects.filter(user=user, primary=True)
            if avatars:
                return avatars[0]
            return None

    # Use above cache class
    avatar = PrimaryAvatarCacheOnUser.get(user=user)

In this case, this cache class will never raise :code:`Avatar.DoesNotExist`
exception since it is setting :code:`None` in memcached against the key
when primary avatar not found.


More about key_fields
#####################

Till now we defined cache classes having key_fields with one field only.
So here is an example where more than one fields are used to create key
for cache:

.. code-block:: python

    class ParticipationCacheOnUserEvent(InstanceCache):
        model = Participation
        # Since only one Participation instance exists for
        # a user and an event
        key_fields = ('user', 'event')


And here are the different ways to use this cache class

.. code-block:: python

    # If parameters given as args, taken in same order of key_fields
    participation = ParticipationCacheOnUserEvent.get(user, event)

    # Parameters can be given in hibrid form too (args & kwargs)
    participation = ParticipationCacheOnUserEvent.get(user, event=event)

    # Parameters can be given in any order if given as kwargs
    participation = ParticipationCacheOnUserEvent.get(event=event, user=user)

    # Parameters must be given as kwargs when using cache manager
    participation = Participation.cache.get(user=user, event=event)


Even if you have id of any related field, you can pass them instead of
instance. So this will work


.. code-block:: python

    participation = Participation.cache.get(user=user, event_id=event_id)

**Some notes:**

* Names of cache classes should be unique because cache keys are made using that
  name.

* Don't use related fields's attname as key_fields though those are which
  gets used in db table. E.g. in above example,
  you should not use :code:`user_id` or :code:`event_id` in key_fields.

* When defining custom :code:`get_instance` method, neither the order nor
  the name of key_fields should be altered.

* In case of :code:`InstanceCache` and :code:`QuerysetCache`, you can
  put GenericForeignKey field's name in key_fields.
