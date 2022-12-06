from bda.plone.shop import message_factory as _

from zope import schema
from plone.supermodel import model
from zope.interface import Interface
from zope.interface import provider

from bda.plone.shop.interfaces import IShopSettingsProvider

#from zope.interface import Attribute


@provider(IShopSettingsProvider)
class IMolliePaymentSettings(model.Schema):
    
    model.fieldset('Mollie',label=_(u'Mollie', default=u'Mollie'),
        fields=[
        'test_api',
        'live_api',
        ],
    )
                   
    test_api = schema.ASCIILine(title=_(u'test_api', default=u'Test API key'),
                 required=True
    )

    live_api = schema.ASCIILine(title=_(u'live_api', default=u'Live API key'),
               required=True
    )
    