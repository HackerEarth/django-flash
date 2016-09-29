from django.conf import settings

from flash.constants import CACHE_TIME_WEEK, CACHE_TIME_30S

FLASH_APPS = getattr(settings, 'FLASH_APPS', settings.INSTALLED_APPS)
CACHE_NAME = getattr(settings, 'FLASH_CACHE', 'default')
DEFAULT_TIMEOUT = getattr(settings, 'FLASH_DEFAULT_TIMEOUT', CACHE_TIME_WEEK)
DONT_USE_CACHE = getattr(settings, 'FLASH_DONT_USE_CACHE', False)
WRITE_LOCK_TIMEOUT = getattr(settings, 'FLASH_WRITE_LOCK_TIMEOUT',
                            CACHE_TIME_30S)
