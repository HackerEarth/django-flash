***************
Getting Started
***************

For each type of cache query, you need to define a class. You should define
them in :code:`caches.py` file inside your app. Also you need to put your app
name inside :code:`FLASH_APPS` settings to get your cache classes registered
on startup.

There are mainly two types of cache classes :code:`InstanceCache`,
:code:`QuerysetCache`. There is one more class :code:`BatchCacheQuery`
for making batch cache queries using which you can get values corressponding to
multiple keys from memcache in single network call. You can also define
:code:`ModelCacheManager` for models which are somewhat similar to
Django's Managers.
