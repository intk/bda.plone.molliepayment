#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
from bda.plone.orders.common import get_orders_soup
from bda.plone.shop.interfaces import IShopSettings
from zope.component import getUtility
from plone.registry.interfaces import IRegistry
from zope.i18n.interfaces import IUserPreferredLanguages
from status_codes import get_status_category, SUCCESS_STATUS
from bda.plone.orders import interfaces as ifaces
from bda.plone.orders.common import OrderData
from bda.plone.orders.common import get_order
import transaction
from bda.plone.orders.common import get_bookings_soup
from zope.component.hooks import getSite
from bda.plone.cart import get_object_by_uid
from plone import api

from zope.component import getMultiAdapter

from bda.plone.payment import (
    Payment,
    Payments,
)

from ZTUtils import make_query
from bda.plone.orders.common import get_order
from decimal import Decimal as D

import json
import Mollie

logger = logging.getLogger('bda.plone.payment')
_ = MessageFactory('bda.plone.payment')


from bda.plone.cart import is_ticket as is_context_ticket
from plone.app.uuid.utils import uuidToCatalogBrain


#
# Mollie Data
#

testing = True

# TODO: get keys from a settings interface
#TEST_API_KEY = "test_ktHwAH8wFVfvasS2J4deey6BHnAvap"

TEST_API_KEY = "test_tcSMfAcFVWvCKHaVS2RWj7k7Bk7sFe"
LIVE_API_KEY = "live_hTM4TennryeSMuhbRb23xPVhGsAwcU"

# Switch keys
API_KEY = LIVE_API_KEY
if testing:
    API_KEY = LIVE_API_KEY
#
# Util functions
#
def shopmaster_mail(context):
    try:
        props = getToolByName(context, 'portal_properties')
        return props.site_properties.email_from_address
    except:
        return "info@zeeuwsmuseum.nl"

def get_banks():
    mollie = Mollie.API.Client()
    mollie.setApiKey(API_KEY)

    issuers = mollie.issuers.all()
    list_ideal_issuers = []

    for issuer in issuers:
        if issuer['method'] == Mollie.API.Object.Method.IDEAL:
            list_ideal_issuers.append(issuer)

    return list_ideal_issuers

class MolliePayment(Payment):
    pid = 'mollie_payment'
    label = _('mollie_payment', 'Mollie Payment')

    def init_url(self, uid, bank_id='ideal_TESTNL99', payment_type='ideal'):
        return '%s/@@mollie_payment?uid=%s&bank_id=%s&payment=%s' % (self.context.absolute_url(), uid, bank_id, payment_type)

# 
# Mollie implementation
#
class MolliePay(BrowserView):

    def get_language(self):
        """
        @return: Two-letter string, the active language code
        """
        context = self.context.aq_inner
        portal_state = getMultiAdapter((context, self.request), name=u'plone_portal_state')
        current_language = portal_state.language()
        return current_language

    def __call__(self):
        context_url = self.context.absolute_url()
        
        # Detect tickets interface
        tickets = is_context_ticket(self.context)
        base_url = self.context.absolute_url()
        order_uid = self.request['uid']

        try:
            bank_id = self.request['bank_id']
            payment_type = self.request['payment']

            data = IPaymentData(self.context).data(order_uid)
            amount = data["amount"]
            ordernumber = data["ordernumber"]
            
            real_amount = float(int(amount)/100.0)

            site_url = api.portal.get().absolute_url()
            if tickets:
                language = self.get_language()
                if language:
                    webhookUrl = '%s/%s/tickets/@@mollie_webhook' %(site_url, language)
                else:
                    webhookUrl = '%s/nl/tickets/@@mollie_webhook' %(site_url)
            else:
                webhookUrl = '%s/@@mollie_webhook' %(site_url)

            mollie = Mollie.API.Client()
            mollie.setApiKey(API_KEY)

            order_redirect_url = '%s/@@mollie_payment_success?order_id=%s' %(base_url, ordernumber)

            if payment_type in ['creditcard', 'bancontact', 'giropay', 'applepay']:
                if payment_type == "bancontact":
                    payment_type = "mistercash"
                
                if payment_type == "applepay":
                    payment_type = None

                payment = mollie.payments.create({
                    'amount':real_amount, 
                    'description':str(ordernumber), 
                    'redirectUrl':order_redirect_url, 
                    'metadata':{'order_nr':ordernumber}, 
                    'webhookUrl': webhookUrl,
                    'method': payment_type
                })
            else:
                payment = mollie.payments.create({
                    'amount':real_amount, 
                    'description':str(ordernumber), 
                    'redirectUrl':order_redirect_url, 
                    'metadata':{'order_nr':ordernumber}, 
                    'webhookUrl': webhookUrl,
                    'method': payment_type, 
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
    def get_language(self):
        """
        @return: Two-letter string, the active language code
        """
        context = self.context.aq_inner
        portal_state = getMultiAdapter((context, self.request), name=u'plone_portal_state')
        current_language = portal_state.language()
        return current_language

    def shopmaster_mail(self):
        return shopmaster_mail(self.context)

    def is_ticket(self):
        result = is_context_ticket(self.context)
        return result

    def get_header_image(self, ticket):
        if ticket:
            folder = self.context
            if folder.portal_type in ["Folder", "Event"]:
                if folder.portal_type == "Event":
                    uuid = folder.UID()
                    brain = uuidToCatalogBrain(uuid)
                    if brain:
                        leadmedia = getattr(brain, 'leadMedia', None)
                        if leadmedia:
                            image = uuidToCatalogBrain(leadmedia)
                            if hasattr(image, 'getURL'):
                                url = image.getURL()
                                scale_url = "%s/%s" %(url, "@@images/image/large")
                                return scale_url
                else:
                    contents = folder.getFolderContents({"portal_type": "Image", "Title":"tickets-header"})
                    if len(contents) > 0:
                        image = contents[0]
                        url = image.getURL()
                        scale_url = "%s/%s" %(url, "@@images/image/large")
                        return scale_url
        else:
            brains = self.context.portal_catalog(Title="webwinkel-header", portal_type="Image")
            if len(brains) > 0:
                brain = brains[0]
                if brain.portal_type == "Image":
                    url = brain.getURL()
                    scale_url = "%s/%s" %(url, "@@images/image/large")
                    return scale_url

            return ""

    def verify(self):
        data = self.request.form
        context_url = self.context.absolute_url()

        tickets = is_context_ticket(self.context)

        mollie = Mollie.API.Client()
        mollie.setApiKey(API_KEY)

        order_nr = None
        order_uid = None

        # Switch between order_id or order_uid in the url
        if 'order_id' in data:
            order_nr = data['order_id']
        
        order_uid_param = None
        if 'order_uid' in data:
            order_uid_param = data['order_uid']

        if order_nr == None and order_uid_param != None:
            order_uid = order_uid_param
            order_nr = order_uid_param

        # Get payment
        payment = Payments(self.context).get('mollie_payment')
        if order_nr != None and order_uid_param == None:
            order_uid = IPaymentData(self.context).uid_for(order_nr)
        
        # Get order
        order = None
        try:
            order = OrderData(self.context, uid=order_uid)
        except:
            order = None

        # Check if order exists
        if order_uid != None and order != None:
            order = OrderData(self.context, uid=order_uid)
            order_nr = order.order.attrs['ordernumber']

            # Build order data
            order_data = {  
                "ordernumber": str(order_nr),
                "order_id": str(order_uid),
                "total": str(order.total),
                "shipping": str(order.shipping),
                "currency": str(order.currency),
                "tax": str(order.vat),
                "ticket": tickets,
                "download_link": None,
                "verified": False,
                "already_sent":False,
                "bookings":json.dumps([])
            }

            order_bookings = []
           
            for booking in order.bookings:
                try:
                    booking_uid = booking.attrs['buyable_uid']
                    #booking_buyable = get_object_by_uid(self.context, booking_uid)
                    #item_number = getattr(booking_buyable, 'item_number', None)
                    item_number = booking.attrs['item_number']

                    if item_number:
                        sku = str(item_number)
                    else:
                        sku = str(booking_uid)

                    item_category = "Product" # Default category
                    if tickets:
                        item_category = "E-Ticket"

                    order_bookings.append({
                        'id':sku,
                        'price': str(float(booking.attrs['net'])),
                        'name': str(booking.attrs['title']),
                        'category': item_category,
                        'quantity': int(booking.attrs['buyable_count']),
                    })
                except:
                    pass

            try:
                order_data['bookings'] = json.dumps(order_bookings)
            except:
                # Invalid JSON format
                order_data['bookings'] = json.dumps([])

            # Generate download link
            # TODO: Download link is deprecated. It is now created when the ticket PDF is going to be generated in bda.plone.orders
            if tickets:
                base_url = self.context.portal_url()
                language = self.get_language()
                params = "?order_id=%s" %(str(order_uid))
                download_as_pdf_link = "%s/%s/download_as_pdf?page_url=%s/%s/tickets/etickets%s" %(base_url, language, base_url, language, params)
                order_data['download_link'] = download_as_pdf_link

            if order.salaried == ifaces.SALARIED_YES:
                # Payment succeded
                order_data['verified'] = True
                if order.order.attrs['email_sent'] == 'no':
                    if order.total > 0:
                        order.order.attrs['email_sent'] = 'yes'
                        orders_soup = get_orders_soup(self.context)
                        order_record = order.order
                        orders_soup.reindex(records=[order_record])
                        #payment.succeed(self.request, order_uid, dict(), None)
                else:
                    if order.order.attrs['email_sent'] == 'yes':
                        order_data['already_sent'] = True
                    order.order.attrs['email_sent'] = 'yes'
                    orders_soup = get_orders_soup(self.context)
                    order_record = order.order
                    orders_soup.reindex(records=[order_record])
                return order_data
            else:
                return order_data
        else:
            # Order doesn't exist in the database
            # return blank ticket
            order_data = {
                "order_id": "",
                "total": "",
                "shipping": "",
                "currency": "",
                "tax": "",
                "ticket": tickets,
                "download_link": None,
                "verified": False
            }

            return order_data
    
 

class MollieWebhook(BrowserView):
    def __call__(self):
        data = self.request.form

        context_url = self.context.absolute_url()
        tickets = is_context_ticket(self.context)

        if 'id' not in data:
            return False

        mollie = Mollie.API.Client()
        mollie.setApiKey(API_KEY)

        try:
            payment_id = data['id']

            mollie_payment = mollie.payments.get(payment_id)
            order_nr = mollie_payment['metadata']['order_nr']

            payment = Payments(self.context).get('mollie_payment')
            order_uid = IPaymentData(self.context).uid_for(order_nr)
            order = OrderData(self.context, uid=order_uid)
        except:
            # Cannot get the payment with the mentioned id
            return False

        if mollie_payment.isPaid():
            if order.salaried != ifaces.SALARIED_YES:
                order.salaried = ifaces.SALARIED_YES
                order.order.attrs['email_sent'] = 'no'
                
                orders_soup = get_orders_soup(self.context)
                order_record = order.order
                orders_soup.reindex(records=[order_record])
                transaction.get().commit()

                if tickets:
                    payment.succeed(self.request, order_uid)
                else:
                    payment.succeed(self.request, order_uid)
                return True

        elif mollie_payment.isPending():
            return False
        elif mollie_payment.isOpen():
            return False
        else:
            print "payment failed"
            # Payment Fails
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

    def is_ticket(self):
        result = is_context_ticket(self.context)
        return result

    def get_header_image(self, ticket=False):
        if ticket:
            folder = self.context
            if folder.portal_type in ["Folder", "Event"]:
                if folder.portal_type == "Event":
                    uuid = folder.UID()
                    brain = uuidToCatalogBrain(uuid)
                    if brain:
                        leadmedia = getattr(brain, 'leadMedia', None)
                        if leadmedia:
                            image = uuidToCatalogBrain(leadmedia)
                            if hasattr(image, 'getURL'):
                                url = image.getURL()
                                scale_url = "%s/%s" %(url, "@@images/image/large")
                                return scale_url
                else:
                    contents = folder.getFolderContents({"portal_type": "Image", "Title":"tickets-header"})
                    if len(contents) > 0:
                        image = contents[0]
                        url = image.getURL()
                        scale_url = "%s/%s" %(url, "@@images/image/large")
                        return scale_url
        else:
            brains = self.context.portal_catalog(Title="webwinkel-header", portal_type="Image")
            if len(brains) > 0:
                brain = brains[0]
                if brain.portal_type == "Image":
                    url = brain.getURL()
                    scale_url = "%s/%s" %(url, "@@images/image/large")
                    return scale_url

            return ""
        
#
# Payment failed
#
class MolliePayFailed(BrowserView):
    def finalize(self):
        return True

    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)

    def is_ticket(self):
        result = is_context_ticket(self.context)
        return result

    def get_header_image(self, ticket=False):
        if ticket:
            folder = self.context
            if folder.portal_type in ["Folder", "Event"]:
                if folder.portal_type == "Event":
                    uuid = folder.UID()
                    brain = uuidToCatalogBrain(uuid)
                    if brain:
                        leadmedia = getattr(brain, 'leadMedia', None)
                        if leadmedia:
                            image = uuidToCatalogBrain(leadmedia)
                            if hasattr(image, 'getURL'):
                                url = image.getURL()
                                scale_url = "%s/%s" %(url, "@@images/image/large")
                                return scale_url
                else:
                    contents = folder.getFolderContents({"portal_type": "Image", "Title":"tickets-header"})
                    if len(contents) > 0:
                        image = contents[0]
                        url = image.getURL()
                        scale_url = "%s/%s" %(url, "@@images/image/large")
                        return scale_url
        else:
            brains = self.context.portal_catalog(Title="webwinkel-header", portal_type="Image")
            if len(brains) > 0:
                brain = brains[0]
                if brain.portal_type == "Image":
                    url = brain.getURL()
                    scale_url = "%s/%s" %(url, "@@images/image/large")
                    return scale_url

            return ""


class MollieError(Exception):
    """Raised if Mollie Payment return an error.
    """


    

        
