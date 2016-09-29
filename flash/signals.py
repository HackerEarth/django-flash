from functools import wraps

from django.dispatch import Signal
from django.db.models.query import QuerySet


queryset_update = Signal()


# patch QuerySet's update method

update = QuerySet.update

@wraps(update)
def custom_update(self, **kwargs):
    queryset_update.send(self.model, queryset=self._clone(),
                         update_kwargs=kwargs)
    return update(self, **kwargs)

QuerySet.update = custom_update


def invalidate_flash_cache(self):
    queryset_update.send(self.model, queryset=self._clone(),
                         update_kwargs={}, force=True)

QuerySet.invalidate_flash_cache = invalidate_flash_cache
