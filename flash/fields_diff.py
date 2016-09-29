from django.conf import settings
from django.dispatch import receiver
from django.db.models.signals import post_init, pre_save, post_save
from django.db import models


class AttrDict(dict):
    def __getattr__(self, attr):
        if attr in self:
            return self[attr]
        raise AttributeError(attr)

    def __repr__(self):
        return u'AttrDict' + super(AttrDict, self).__repr__()


class ModelStateDiff(object):
    """ To contain the state of values of all fields in instance.
        And contain the diff of fields if save() is called.
    """
    def __init__(self):
        self.state = {}
        self.diff = AttrDict()

    def __setstate__(self, state):
        """ Override this method to set custom pickle.loads on it.
        """
        if 'diff' in state:
            diff = state['diff']
            if not isinstance(diff, AttrDict):
                diff = AttrDict(diff)
                state['diff'] = diff
                for attr, val in diff.iteritems():
                    if not isinstance(val, Diff):
                        diff[attr] = Diff(**val)
        self.state = state['state']
        self.diff = state['diff']


class Diff(dict):
    class Empty(object):
        def __nonzero__(self):
            return False

        def __bool__(self):
            return False

        def __repr__(self):
            return 'Diff.empty'

    empty = Empty()

    def __init__(self, post, pre=empty):
        super(Diff, self).__init__(self)
        self['post'] = post
        if pre is not Diff.empty:
            self['pre'] = pre

    @property
    def pre(self):
        return self.get('pre', Diff.empty)

    @property
    def post(self):
        return self['post']

    def is_pre_empty(self):
        return not 'pre' in self

    def __repr__(self):
        return u'Diff' + super(Diff, self).__repr__()


def get_simple_fields(instance):
    return filter(lambda field: not isinstance(field, models.FileField),
                    instance._meta.local_fields)


def save_state(instance):
    for field in get_simple_fields(instance):
        instance._statediff.state[field.attname] = getattr(instance,
                field.attname)


@receiver(post_init)
def post_init_statediff(sender, instance, **kwargs):
    try:
        instance._statediff = ModelStateDiff()
        save_state(instance)
    except:
        if settings.DEBUG:
            raise


@receiver(pre_save)
def pre_save_statediff(sender, instance, **kwargs):
    try:
        if not hasattr(instance, '_statediff'):
            instance._statediff = ModelStateDiff()
            save_state(instance)
        instance._statediff.diff = AttrDict()
        for field in get_simple_fields(instance):
            if hasattr(instance, field.attname):
                post_value = getattr(instance, field.attname)
                if not instance._state.adding:
                    if instance._statediff.state.has_key(field.attname):
                        pre_value = instance._statediff.state.get(field.attname)
                        if not post_value == pre_value:
                            instance._statediff.diff[field.attname] = Diff(
                                    post_value, pre_value)
                else:
                    instance._statediff.diff[field.attname] = Diff(post_value)
    except:
        if settings.DEBUG:
            raise


@receiver(post_save)
def post_save_statediff(sender, instance, created, **kwargs):
    try:
        save_state(instance)
    except:
        if settings.DEBUG:
            raise


def get_state_diff(self):
    if hasattr(self, '_statediff'):
        return self._statediff.diff
    return AttrDict()


def create_state_diff(self):
    if hasattr(self, '_statediff'):
        pre_save_statediff(self.__class__, self)


models.Model.get_state_diff = get_state_diff
models.Model.create_state_diff = create_state_diff
