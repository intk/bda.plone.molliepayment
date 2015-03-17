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


logger = logging.getLogger('bda.plone.payment')
_ = MessageFactory('bda.plone.payment')

#
# Mollie Data
#

API_URL = "https://www.qantanipayments.com/api/"
MERCHANT_ID = "2699"
MERCHANT_KEY = "JiJ3vrR"
MERCHANT_SECRET = "pjrO8FfLSmxckVOv6IPsl7i1H"

#
# Util functions
#
def shopmaster_mail(context):
    props = getToolByName(context, 'portal_properties')
    return props.site_properties.email_from_address

def get_banks():
    easy_ideal = EasyIdeal(MERCHANT_ID, MERCHANT_KEY, MERCHANT_SECRET)
    return easy_ideal.request_banks()

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

        easy_ideal = EasyIdeal(MERCHANT_ID, MERCHANT_KEY, MERCHANT_SECRET)

        data = IPaymentData(self.context).data(order_uid)
        amount = data["amount"]
        ordernumber = data["ordernumber"]
        
        real_amount = D(int(amount)/100.0)

        try:
            transaction_response = easy_ideal.request_transaction(real_amount, bank_id, str(ordernumber), '%s/@@mollie_payment_success?order_id=%s'%(base_url, ordernumber))
            redirect_url = transaction_response.bank_url
            transaction_id = transaction_response.transaction_id
            transaction_code = transaction_response.transaction_code
            checksum = transaction_response.checksum
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
        
        if 'status' in data.keys():
            status = data["status"]
            payment = Payments(self.context).get('easyideal_payment')
            ordernumber = data["order_id"]
            order_uid = IPaymentData(self.context).uid_for(ordernumber)

            if status == '1':
                payment.succeed(self.context, order_uid)
                order = OrderData(self.context, uid=order_uid)
                order.salaried = ifaces.SALARIED_YES
                return True
            else:
                payment.failed(self.context, order_uid)
                return False
        else:
            return False

    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)
 
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

class easyidealError(Exception):
    """Raised if Easy-iDeal Payment return an error.
    """


    

        
