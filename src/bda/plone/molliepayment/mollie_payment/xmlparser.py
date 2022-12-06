# -*- coding: utf-8 -*-
from dicttoxml import dicttoxml
from bda.plone.orders import get_country_alpha
from decimal import Decimal
from bda.plone.cart.utils import ascur
import plone.api
from bda.plone.orders.mailnotify import MailNotify
from bda.plone.payment.interfaces import IPaymentData
from bda.plone.orders.common import OrderData
from Products.Five import BrowserView
from zExceptions import Redirect
from Products.statusmessages.interfaces import IStatusMessage

#
# Order XML connector
#

class HexspoorXMLParser():

    def __init__(self, stock_file, shipment_file):
        self.stock_file = stock_file
        self.shipment_file = shipment_file
        self.stock_data = self.generate_stock_data()

    def get_text_from_xml_element(self, element):
        if element != None:
            return element.text
        else:
            return ''

    def generate_stock_data(self):
        stock_data = {}

        if self.stock_file:
            products = self.stock_file.find('Products')
            
            for product in products.findall('Product'):

                item_number = product.find("ArticleNumber")
                if item_number != None:
                    product_stock = {}
                    
                    item_number = self.get_text_from_xml_element(item_number)

                    stockvalues = product.find("StockValues")
                    if stockvalues != None:
                        for stockvalue in stockvalues.findall('StockValue'):
                            status = self.get_text_from_xml_element(stockvalue.find('Status'))
                            quantity = self.get_text_from_xml_element(stockvalue.find('QuantitySku'))

                            product_stock[status] = quantity
                        
                        stock_data[item_number] = product_stock

        return stock_data

    def generate_shipment_data(self, shipment_file):

        shipment_data = {
            "order_number": "",
            "track_and_trace_code": "",
            "track_and_trace_url": ""
        }

        shipment_data['order_number'] = self.get_text_from_xml_element(shipment_file.find('OrderNumber'))
        shipment_data['track_and_trace_code'] = self.get_text_from_xml_element(shipment_file.find('TrackAndTraceCode'))
        shipment_data['track_and_trace_url'] = self.get_text_from_xml_element(shipment_file.find('TrackAndTraceLink'))

        return shipment_data

    def get_stock_by_item_number(self, item_number):

        item_stock_data = self.stock_data.get(item_number, '')

        if item_stock_data:
            stock = item_stock_data.get('Sellable', '')
            return stock
        else:
            return None


SUBJECT_NL = "Uw bestelling met bestelnummer %s"
EMAIL_TEMPLATE_NL = "<p>Uw bestelling met bestelnummer %s is verzonden!</p><p><a href='%s'>Klik hier om uw bestelling te volgen.</a><br>Uw Track and Trace code: %s</p><p>Hartelijke groeten,<br>Uitgeverij Komma<br><img src='https://uitgeverijkomma-stage.intk.com/nl/intk/shop/images/komma-logo.jpg' style='max-width: 120px;'/><br><a href='https://www.uitgeverijkomma.nl'>uitgeverijkomma.nl</a></p>"

EMAIL_TEMPLATE_TEXT = u"""
Uw bestelling met bestelnummer %s is verzonden!

Klik hier om uw bestelling te volgen: %s
Uw Track and Trace code: %s

Veel plezier met je aankoop!
Met vriendelijke groet,
Uitgeverij Komma
"""

#
# TESTS
#
def test_update_stock_by_id():
    with plone.api.env.adopt_user(username="admin"):
        from bda.plone.molliepayment.mollie_payment.sftpconnector import sFTPConnector

        sftp_connector = sFTPConnector()
        stock_file = sftp_connector.get_stock_file()
        xml_parser = HexspoorXMLParser(stock_file=stock_file, shipment_file=None)
        
        print(xml_parser.get_stock_by_item_number("978-94-91525-73-5"))

        return None

def test_update_stock_all_products():
    with plone.api.env.adopt_user(username="admin"):
        from bda.plone.molliepayment.mollie_payment.sftpconnector import sFTPConnector
        import transaction

        sftp_connector = sFTPConnector()
        stock_file = sftp_connector.get_stock_file()
        
        xml_parser = HexspoorXMLParser(stock_file=stock_file, shipment_file=None)
        
        all_products_en = plone.api.content.find(portal_type="product", Language="en")
        all_products_nl = plone.api.content.find(portal_type="product", Language="nl")
        all_products = all_products_nl + all_products_en

        for product in all_products:
            obj = product.getObject()
            item_number = getattr(obj, 'item_number', None)
            new_stock = xml_parser.get_stock_by_item_number(item_number)

            if new_stock:
                obj.item_available = float(new_stock)
                obj.reindexObject()
                transaction.get().commit()
            else:
                pass

        return None

def process_shipment_data(shipment_data):
    with plone.api.env.adopt_user(username="admin"):
        import transaction
        
        try:
            portal = plone.api.portal.get()
            order_number = shipment_data.get('order_number', '')
            #order_number = "11799751002719460818"
            track_and_trace_code = shipment_data.get('track_and_trace_code', '')
            track_and_trace_code_url = shipment_data.get('track_and_trace_url', '')

            order_uid = IPaymentData(portal).uid_for(order_number)

            if order_uid:
                order_data = OrderData(portal, uid=order_uid)
                if order_data:
                    receiver = order_data.order.attrs.get('personal_data.email', '')

                    subject = SUBJECT_NL % (order_number)
                    html_message = EMAIL_TEMPLATE_NL % (order_number, track_and_trace_code_url, track_and_trace_code)
                    text_message = EMAIL_TEMPLATE_TEXT % (order_number, track_and_trace_code_url, track_and_trace_code)
                    
                    mail_notify = MailNotify(portal)
                    mail_notify.send(subject, receiver, text=text_message, html=html_message)
                    transaction.get().commit()
        except:
            return False

        return True

def process_shipments():
    with plone.api.env.adopt_user(username="admin"):
        from bda.plone.molliepayment.mollie_payment.sftpconnector import sFTPConnector
        import os

        SHIPMENTS_BASE_PATH = "hexspoor/Shipments/"
        SHIPMENTS_ARCHIVE_BASE_PATH = "hexspoor/Shipments/Archive/"

        sftp_connector = sFTPConnector()
        xml_parser = HexspoorXMLParser(stock_file=None, shipment_file=None)

        shipments = sftp_connector.get_shipments()

        for shipment_file_path in shipments:
            shipment_file = sftp_connector.get_shipment_file(shipment_file_path)
            shipment_data = xml_parser.generate_shipment_data(shipment_file)

            final_result = process_shipment_data(shipment_data)

            if final_result:
                shipment_original_path = "%s%s" %(SHIPMENTS_BASE_PATH, shipment_file_path)
                shipment_archive_path = "%s%s" %(SHIPMENTS_ARCHIVE_BASE_PATH, shipment_file_path)

                sftp_connector.sftp_connector.rename(shipment_original_path, shipment_archive_path)

        return True



class ShipmentsView(BrowserView):

    def __call__(self):
        return self.process()

    def process(self):
        redirect_url = self.context.absolute_url()
        messages = IStatusMessage(self.request)

        try:
            final_result = process_shipments()
            messages.add(u"Processed shipment files.", type=u"info")
        except:
            messages.add(u"Failed to process the shipment files.", type=u"error")
        
        raise Redirect(redirect_url)



