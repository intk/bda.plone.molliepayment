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
from collective.sendaspdf.browser.base import BaseView
from collective.sendaspdf.browser.send import SendForm

from plone import api

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

import json
import Mollie

logger = logging.getLogger('bda.plone.payment')
_ = MessageFactory('bda.plone.payment')

#
# Mollie Data
#

testing = True

TEST_API_KEY = "test_aUZkTbRsiUcDnjSX4D7AqvxTp5TKJP"
LIVE_API_KEY = "live_BndGVkfjTnHuijrMPeKjnpGgV4rL7n"

API_KEY = LIVE_API_KEY
if testing:
    API_KEY = TEST_API_KEY
#
# Util functions
#
def shopmaster_mail(context):
    props = getToolByName(context, 'portal_properties')
    return props.site_properties.email_from_address

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

    def init_url(self, uid, bank_id, payment_type):
        return '%s/@@mollie_payment?uid=%s&bank_id=%s&payment=%s' % (self.context.absolute_url(), uid, bank_id, payment_type)

# 
# Mollie implementation
#
class MolliePay(BrowserView):
    def __call__(self):
        base_url = self.context.absolute_url()
        order_uid = self.request['uid']
        bank_id = self.request['bank_id']
        payment_type = self.request['payment']

        data = IPaymentData(self.context).data(order_uid)
        amount = data["amount"]
        ordernumber = data["ordernumber"]
        
        real_amount = float(int(amount)/100.0)

        site_url = api.portal.get().absolute_url()
        webhookUrl = '%s/nl/@@mollie_webhook' %(site_url)
        
        #if testing:
        #    #webhookUrl = webhookUrl

        try:
            mollie = Mollie.API.Client()
            mollie.setApiKey(API_KEY)

            order_redirect_url = '%s/@@mollie_payment_success?order_id=%s' %(base_url, ordernumber)

            if payment_type == 'creditcard':
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
    def get_header_image(self, is_ticket):
        if is_ticket:
            folder = self.context
            if folder.portal_type == "Folder":
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
        
        tickets = False
        if '/tickets' in context_url:
            tickets = True

        mollie = Mollie.API.Client()
        mollie.setApiKey(API_KEY)

        order_nr = None
        if 'order_id' in data:
            order_nr = data['order_id']
        
        order_uid_param = None
        if 'order_uid' in data:
            order_uid_param = data['order_uid']

        if order_nr == None and order_uid_param != None:
            order_uid = order_uid_param
            order_nr = order_uid_param

        payment = Payments(self.context).get('mollie_payment')
        if order_nr != None and order_uid_param == None:
            order_uid = IPaymentData(self.context).uid_for(order_nr)
        
        if order_uid != None:
            order = OrderData(self.context, uid=order_uid)
            order_nr = order.order.attrs['ordernumber']
            order_data = {  
                "ordernumber": str(order_nr),
                "order_id": str(order_uid),
                "total": order.total,
                "shipping": order.shipping,
                "currency": str(order.currency),
                "tax": order.vat,
                "ticket": tickets,
                "download_link": None,
                "verified": False,
                "already_sent":False,
                "bookings":json.dumps([])
            }

            order_bookings = []
           
            for booking in order.bookings:
                try:
                    order_bookings.append({
                        'sku':str(booking.attrs['buyable_uid']),
                        'name': str(booking.attrs['title']),
                        'price': float(booking.attrs['net']),
                        'quantity': int(booking.attrs['buyable_count']),
                        'category': 'Product'
                    })
                except:
                    pass

            try:
                order_data['bookings'] = json.dumps(order_bookings)
            except:
                order_data['bookings'] = json.dumps([])

            # Generate download link
            if tickets:
                base_url = self.context.portal_url()
                language = self.context.language
                params = "?order_id=%s" %(str(order_uid))
                download_as_pdf_link = "%s/%s/download_as_pdf?page_url=%s/%s/tickets/etickets%s" %(base_url, language, base_url, language, params)
                order_data['download_link'] = download_as_pdf_link


            print order.order.attrs['email_sent']

            if order.salaried == ifaces.SALARIED_YES:
                order_data['verified'] = True
                if order.order.attrs['email_sent'] == 'no':
                    if order.total > 0:
                        order.order.attrs['email_sent'] = 'yes'
                        orders_soup = get_orders_soup(self.context)
                        orders_soup.reindex(records=[order.order])
                        payment.succeed(self.context, order_uid, dict(), None)
                        
                else:
                    order_data['already_sent'] = True
                    order.order.attrs['email_sent'] = 'yes'
                    orders_soup = get_orders_soup(self.context)
                    orders_soup.reindex(records=[order.order])
                return order_data
            else:
                return order_data
        else:
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

    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)
 

class MollieWebhook(BrowserView):
    def __call__(self):
        data = self.request.form
        
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
            return False

        if mollie_payment.isPaid():
            if order.salaried != ifaces.SALARIED_YES:
                order.salaried = ifaces.SALARIED_YES
                order.order.attrs['salaried'] = ifaces.SALARIED_YES
                order.order.attrs['email_sent'] = 'no'
                orders_soup = get_orders_soup(self.context)
                orders_soup.reindex(records=[order.order])

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


    

        
