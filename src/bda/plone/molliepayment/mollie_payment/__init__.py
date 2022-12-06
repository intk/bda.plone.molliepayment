#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from zExceptions import Redirect
from zope.i18nmessageid import MessageFactory
from Products.Five import BrowserView
from Products.CMFCore.utils import getToolByName
from bda.plone.payment.interfaces import IPaymentData
from bda.plone.orders.common import OrderData
from bda.plone.orders.mailnotify import get_order_uid

from plone import api

from bda.plone.payment import (
    Payment,
    Payments,
)

import json
from mollie.api.client import Client

from bda.plone.molliepayment.mollie_payment.xmlgenerator import OrderXMLGenerator
from bda.plone.molliepayment.mollie_payment.sftpconnector import sFTPConnector


logger = logging.getLogger('bda.plone.payment')
_ = MessageFactory('bda.plone.payment')

#
# Mollie Data
#
API_KEY = "live_Ku2AFE4ccB2VcNKDWSsDCEK52cAypG"
test_api_key = "test_kg5xqtgB8urVB9HdxrDHT3E7jtB7eE"
live_api_key = "live_Ku2AFE4ccB2VcNKDWSsDCEK52cAypG"


#
# Util functions
# 
def get_mollie_client():
    mollie = Client()
    mollie.set_api_key(API_KEY)
    return mollie

def create_order_xml(event):

    if API_KEY != test_api_key:

        data =  OrderData(event.context, uid=get_order_uid(event))
        xml_generator = OrderXMLGenerator(data, event.context)
        sftp_connector = sFTPConnector()

        order_number = xml_generator.get_order_number()
        sftp_connector.set_order_number(order_number)
        
        order_xml = xml_generator.generate_xml()
        if order_xml:
            final_result = sftp_connector.write_file_to_ftp(order_xml)

    return True

def shopmaster_mail(context):
    try:
        props = getToolByName(context, 'portal_properties')
        return props.site_properties.email_from_address
    except:
        return "info@uitgeverijkomma.nl"

def get_ideal_issuers():
    mollie = get_mollie_client()

    issuers = mollie.methods.get('ideal', include='issuers').issuers
    list_ideal_issuers = []

    for issuer in issuers:
        list_ideal_issuers.append(issuer)

    return list_ideal_issuers

class MolliePayment(Payment):
    pid = 'mollie_payment'
    label = _('mollie_payment', 'Mollie Payment')

    def init_url(self, uid, payment_method='ideal', issuer_id=None):
        return '%s/@@mollie_payment?uid=%s&payment_method=%s&issuer_id=%s' % (self.context.absolute_url(), uid, payment_method, issuer_id)

# 
# Mollie implementation
#
class MolliePay(BrowserView):
    def __call__(self):
        base_url = self.context.absolute_url()
        order_uid = self.request['uid']

        try:
            mollie = get_mollie_client()
            site_url = api.portal.get().absolute_url()
            webhookUrl = '%s/@@mollie_webhook' %(site_url)

            issuer_id = self.request['issuer_id']
            payment_method = self.request['payment_method']
            data = IPaymentData(self.context).data(order_uid)
            amount = data["amount"]
            currency = "EUR"
            ordernumber = data["ordernumber"]
            real_amount = "%.2f" % (float(int(amount)/100.0))

            order_redirect_url = '%s/@@payment?order_id=%s' %(base_url, order_uid)

            if payment_method in ['creditcard', 'paypal']:
                payment = mollie.payments.create({
                    'amount':{"currency": currency, "value": real_amount}, 
                    'description':str(ordernumber), 
                    'redirectUrl':order_redirect_url, 
                    'metadata':{'order_nr':ordernumber}, 
                    'webhookUrl': webhookUrl,
                    'method': payment_method
                })
            else:
                payment = mollie.payments.create({
                    'amount':{"currency": currency, "value": real_amount}, 
                    'description':str(ordernumber), 
                    'redirectUrl':order_redirect_url, 
                    'metadata':{'order_nr':ordernumber}, 
                    'webhookUrl': webhookUrl,
                    'method': payment_method, 
                    'issuer': issuer_id
                })

            redirect_url = payment.checkout_url
        except Exception as e:
            logger.error(u"Could not initialize payment: '%s'" % str(e))
            redirect_url = '%s/@@payment?order_id=%s' % (base_url, order_uid)
        raise Redirect(redirect_url)

#
# Payment success
#
class MolliePayRedirect(BrowserView):
    
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)


    def build_order_data(self):
    
        return {}

    def generate_bookings(self, order_data):



        return json.dumps([])

    def verify(self):
        data = self.request.form
        context_url = self.context.absolute_url()
        order_uid = data.get('order_id', None)

        if not order_uid:
            return {"verified": False}

        try:
            order = OrderData(self.context, uid=order_uid)
        except:
            return {"verified": False}

        if order_uid and order:
            order_number = order.order.attrs['ordernumber']

            order_data = {  
                "ordernumber": str(order_number),
                "order_id": str(order_uid),
                "total": str(order.total),
                "shipping": str(order.shipping),
                "currency": str(order.currency),
                "tax": str(order.vat),
                "verified": False,
                "bookings":self.generate_bookings(order),
                "custom_text": None
            }

            brains = api.content.find(Subject="shop-success-page")
            if brains:
                obj = brains[0]
                try:
                    order_data['custom_text'] = getattr(obj.getObject(), 'text', None).output
                except:
                    order_data['custom_text'] = None

            if order.salaried == "yes":
                order_data['verified'] = True

            return order_data
        else:
            order_data = {
                "order_id": "",
                "total": "",
                "shipping": "",
                "currency": "",
                "tax": "",
                "verified": False,
                "custom_text": None
            }

            return order_data
 

class MollieWebhook(BrowserView):
    def __call__(self):
        data = self.request.form

        if 'id' not in data:
            return False # Unknown payment ID

        mollie = get_mollie_client()

        try:
            payment_id = data['id']

            mollie_payment = mollie.payments.get(payment_id)
            order_nr = mollie_payment['metadata']['order_nr']

            payment = Payments(self.context).get('mollie_payment')
            order_uid = IPaymentData(self.context).uid_for(order_nr)
        except:
            return False

        if mollie_payment.is_paid():
            payment.succeed(self.request, order_uid)
            return True
        elif mollie_payment.is_pending():
            return False
        elif mollie_payment.is_open():
            return False
        else:
            payment.failed(self.context, order_uid)
            return False

        return True
        
#
# Payment failed
#
class MolliePayFailed(BrowserView):
    def verified(self):
        return False

    @property
    def shopmaster_mail(self):
        return shopmaster_mail(self.context)


class MollieError(Exception):
    """Raised if Mollie Payment return an error.
    """


    

        
