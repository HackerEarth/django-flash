class Option(object):
    """ A wrapper for objects to emulate values of Option type
        So that None and Some(None) are different
    """

    def __init__(self):
        pass

    @classmethod
    def Some(cls, obj):
        instance = cls()
        instance.obj = obj
        return instance

    def __unicode__(self):
        if not hasattr(self, 'obj'):
            return str(None)
        else:
            return u'Some(%s)' % self.obj

    def unwrap(self):
        """ Returns the wrapped value
        """
        if hasattr(self, 'obj'):
            return self.obj
        else:
            raise Exception('Wrapped value not found')

Some = Option.Some
