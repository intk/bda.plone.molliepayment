# -*- coding: utf-8 -*-
from dicttoxml import dicttoxml
from bda.plone.orders import get_country_alpha
from decimal import Decimal
from bda.plone.cart.utils import ascur

#
# Order XML connector
#
class OrderXMLGenerator():

    DEFAULT_PAYMENT = "PSP"
    DEFAULT_IS_PAID = True

    def __init__(self, data, context):
        self.order_data = data
        self.order_attrs = self.order_data.order.attrs
        self.context = context

    def get_order_number(self):

        return self.order_attrs.get('ordernumber', '')

    def create_general_fields(self):
        general_fields = {}

        payment_method = self.DEFAULT_PAYMENT
        is_paid = self.DEFAULT_IS_PAID

        order_number = self.order_attrs.get('ordernumber', '')
        
        general_fields['payment_method'] = payment_method
        general_fields['is_paid'] = is_paid
        general_fields['order_number'] = order_number
        
        return general_fields

    def create_delivery_address(self):
        delivery_address = {}

        delivery_address['street'] = self.order_attrs.get('delivery_address.street', '')
        delivery_address['house_number'] = self.order_attrs.get('delivery_address.housenumber', '')
        delivery_address['house_number_addition'] = self.order_attrs.get('delivery_address.housenumber_addition', '')
        delivery_address['postal_code'] = self.order_attrs.get('delivery_address.zip', '')
        delivery_address['city'] = self.order_attrs.get('delivery_address.city', '')
        delivery_address['country'] = get_country_alpha(self.order_attrs.get('delivery_address.country', ''))
        delivery_address['company_name'] = self.order_attrs.get('delivery_address.company', '')
        delivery_address['first_name'] = self.order_attrs.get('delivery_address.firstname', '')
        delivery_address['last_name'] = self.order_attrs.get('delivery_address.lastname', '')

        return delivery_address

    def create_invoice_address(self):

        invoice_address = {}

        invoice_address['street'] = self.order_attrs.get('billing_address.street', '')
        invoice_address['house_number'] = self.order_attrs.get('billing_address.housenumber', '')
        invoice_address['house_number_addition'] = self.order_attrs.get('billing_address.housenumber_addition', '')
        invoice_address['postal_code'] = self.order_attrs.get('billing_address.zip', '')
        invoice_address['city'] = self.order_attrs.get('billing_address.city', '')
        invoice_address['country'] = get_country_alpha(self.order_attrs.get('billing_address.country', ''))
        invoice_address['company_name'] = self.order_attrs.get('personal_data.company', '')
        invoice_address['first_name'] = self.order_attrs.get('personal_data.firstname', '')
        invoice_address['last_name'] = self.order_attrs.get('personal_data.lastname', '')

        return invoice_address

    def create_items(self):
        items = []

        bookings = self.order_data.bookings

        for booking in bookings:

            net = booking.attrs.get('net', '')
            vat_percentage = booking.attrs.get('vat', '')
            vat = Decimal(net)*(Decimal(vat_percentage)/Decimal(100.0))
            total = Decimal(net) + vat

            new_item = {
                "order_line_number":str(booking.attrs.get('uid', '')),
                "quantity_sku": booking.attrs.get('buyable_count', ''),
                "quantity_unit": booking.attrs.get('buyable_count', ''),
                "article_number":booking.attrs.get('item_number', ''),
                'price_incl_vat': ascur(total, False),
                'price_excl_vat': ascur(net, False),
                'price_vat': ascur(vat, False)
            }

            items.append(new_item)

        return items

    def generate_xml(self):

        final_order = {"order": ""}

        general_fields = self.create_general_fields()
        delivery_address = self.create_delivery_address()
        invoice_address = self.create_invoice_address()
        items = self.create_items()

        if general_fields.get('order_number', None):
            general_fields['items'] = items
            general_fields['invoice_address'] = invoice_address

            if not delivery_address['street']:
                general_fields['delivery_address'] = invoice_address
            else:
                general_fields['delivery_address'] = delivery_address
            
            final_order['order'] = general_fields
            
        if final_order.get('order', None):
            final_order_xml = dicttoxml(final_order.get('order'), custom_root='order', attr_type=False)
            return final_order_xml

        return None