import urllib
import urllib2
import urlparse
import logging
from lxml import etree
from zExceptions import Redirect
from zope.i18nmessageid import MessageFactory
from Products.Five import BrowserView
from Products.CMFCore.utils import getToolByName
from bda.plone.payment.interfaces import IPaymentData

from bda.plone.shop.interfaces import IShopSettings
from zope.component import getUtility
from plone.registry.interfaces import IRegistry
from zope.i18n.interfaces import IUserPreferredLanguages
from status_codes import get_status_category, SUCCESS_STATUS
from bda.plone.orders import interfaces as ifaces
from bda.plone.orders.common import OrderData
from bda.plone.orders.common import get_order

from bda.plone.payment import (
    Payment,
    Payments,
)

from ZTUtils import make_query
from bda.plone.orders.common import get_order
from security import easyidealSignature
from easyideal import EasyIdeal
from easyideal import ReturnValidator
from decimal import Decimal as D

import Mollie

logger = logging.getLogger('bda.plone.payment')
_ = MessageFactory('bda.plone.payment')

#
# Mollie Data
#

TEST_API_KEY = "test_aUZkTbRsiUcDnjSX4D7AqvxTp5TKJP"
LIVE_API_KEY = "live_BndGVkfjTnHuijrMPeKjnpGgV4rL7n"

#
# Util functions
#
def shopmaster_mail(context):
    props = getToolByName(context, 'portal_properties')
    return props.site_properties.email_from_address

def get_banks():
    mollie = Mollie.API.Client()
    mollie.setApiKey(LIVE_API_KEY)
    issuers = mollie.issuers.all()
    list_ideal_issuers = []

    for issuer in issuers:
        if issuer['method'] == Mollie.API.Object.Method.IDEAL:
            list_ideal_issuers.append(issuer)

    return list_ideal_issuers

class MolliePayment(Payment):
    pid = 'mollie_payment'
    label = _('mollie_payment', 'Mollie Payment')

    def init_url(self, uid, bank_id):
        return '%s/@@mollie_payment?uid=%s&bank_id=%s' % (self.context.absolute_url(), uid, bank_id)

# 
# Mollie implementation
#
class MolliePay(BrowserView):
    def __call__(self):
        base_url = self.context.absolute_url()
        order_uid = self.request['uid']
        bank_id = self.request['bank_id']

        data = IPaymentData(self.context).data(order_uid)
        amount = data["amount"]
        ordernumber = data["ordernumber"]
        
        real_amount = float(int(amount)/100.0)

        try:
            mollie = Mollie.API.Client()
            mollie.setApiKey(LIVE_API_KEY)
            order_redirect_url = '%s/@@mollie_payment_success?order_id=%s' %(base_url, ordernumber)

            payment = mollie.payments.create({
                'amount':real_amount, 
                'description':'My first API payment', 
                'redirectUrl':order_redirect_url, 
                'webhookUrl': '%s/@@mollie_webhook' %(base_url),
                'metadata':{'order_nr':ordernumber}, 
                'method': 'ideal', 
                'issuer': bank_id
            })

            redirect_url = payment.getPaymentUrl()
        except Exception, e:
            logger.error(u"Could not initialize payment: '%s'" % str(e))
            redirect_url = '%s/@@mollie_payment_failed?uid=%s' \
                % (base_url, order_uid)
        raise Redirect(redirect_url)

#
# Payment success
#
class MolliePaySuccess(BrowserView):
    def verify(self):
        data = self.request.form

        mollie = Mollie.API.Client()
        mollie.setApiKey(LIVE_API_KEY)

        #payment_id = data['id']
        #mollie_payment = mollie.payments.get(payment_id)
        order_nr = data['order_id']

        payment = Payments(self.context).get('mollie_payment')
        order_uid = IPaymentData(self.context).uid_for(order_nr)

        payment.succeed(self.context, order_uid)
        order = OrderData(self.context, uid=order_uid)
        
        if order.salaried == ifaces.SALARIED_YES:
            return True
        else:
            return False

    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)
 

class MollieWebhook(BrowserView):
    def __call__(self):
        data = self.request.form
        
        if 'id' not in data:
            return False

        mollie = Mollie.API.Client()
        mollie.setApiKey(LIVE_API_KEY)

        payment_id = data['id']
        mollie_payment = mollie.payments.get(payment_id)
        order_nr = mollie_payment['metadata']['order_nr']

        payment = Payments(self.context).get('mollie_payment')
        order_uid = IPaymentData(self.context).uid_for(order_nr)
        order = OrderData(self.context, uid=order_uid)

        if mollie_payment.isPaid():
            if order.salaried != ifaces.SALARIED_YES:
                payment.succeed(self.context, order_uid)
                order.salaried = ifaces.SALARIED_YES
        elif mollie_payment.isPending():
            return False
        elif mollie_payment.isOpen():
            return False
        else:
            payment.failed(self.context, order_uid)
            return False

        return True


#
# Payment finalized
#

class MolliePayFinalized(BrowserView):
    def verify(self):
        return True
    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)
        
#
# Payment failed
#
class MolliePayFailed(BrowserView):
    def finalize(self):
        return True
    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)

class MollieError(Exception):
    """Raised if Mollie Payment return an error.
    """


    

        
