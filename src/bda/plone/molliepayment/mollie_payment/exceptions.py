from status_codes import get_status_description


class easyidealException(Exception):
    pass


class InvalidSignatureException(easyidealException):
    pass


class InvalidParamsException(easyidealException):
    pass


class UnknownStatusException(easyidealException):
    def __init__(self, status):
        assert isinstance(status, int)

        self.status = status

    def __unicode__(self):

        try:
            description = get_status_description(self.status)
            return u'easyideal returned unknown status: %s (%d)' % \
                (description, self.status)
        except:
            return u'easyideal returned unknown status: %d' % self.status

    def __str__(self):
        return repr(self.parameter)
