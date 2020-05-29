SECRET_KEY = 's3cr3t'
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'flash',
    'tests',
]
DATABASES = {
    'default': {
        'NAME': 'default',
        'ENGINE': 'django.db.backends.sqlite3',
    },
}
