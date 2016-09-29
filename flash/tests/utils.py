from django.conf import settings
from django.core.management import call_command
from django.db.models import loading
from django import test


class TestCase(test.TestCase):
    apps = ('flash.tests',)
    tables_created = False

    def _pre_setup(self):
        cls = TestCase
        if not cls.tables_created:
            # Add the models to the db.
            cls._original_installed_apps = list(settings.INSTALLED_APPS)
            for app in cls.apps:
                if isinstance(settings.INSTALLED_APPS, tuple):
                    settings.INSTALLED_APPS = list(settings.INSTALLED_APPS)
                settings.INSTALLED_APPS.append(app)
            loading.cache.loaded = False
            call_command('syncdb', interactive=False, verbosity=0)
            TestCase.tables_created = True

        # Call the original method that does the fixtures etc.
        super(TestCase, self)._pre_setup()

    def _post_teardown(self):
        # Call the original method.
        super(TestCase, self)._post_teardown()
        cls = TestCase
        # Restore the settings.
        settings.INSTALLED_APPS = cls._original_installed_apps
        loading.cache.loaded = False
