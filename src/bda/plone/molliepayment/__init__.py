from bda.plone.shop import message_factory as _

from zope import schema
from plone.supermodel import model
from zope.interface import Interface
from zope.interface import provider

from bda.plone.shop.interfaces import IShopSettingsProvider

#from zope.interface import Attribute


@provider(IShopSettingsProvider)
class IMolliePaymentSettings(model.Schema):
    
    model.fieldset( 'mollie',label=_(u'mollie', default=u'mollie'),
        fields=[
        'mollie_server_url',
        'mollie_sha_in_password',
        'mollie_sha_out_password',
        ],
    )
                   
    mollie_server_url = schema.ASCIILine(title=_(u'mollie_server_url', default=u'Server url'),
                 required=True
    )

    mollie_sha_in_password = schema.ASCIILine(title=_(u'mollie_sha_in_password', default=u'SHA in password'),
               required=True
    )
    
    mollie_sha_out_password = schema.ASCIILine(title=_(u'mollie_sha_out_password', default=u'SHA out password'),
               required=True
    )
    