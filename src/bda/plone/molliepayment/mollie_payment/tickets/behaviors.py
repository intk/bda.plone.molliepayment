#!/usr/bin/env python
# -*- coding: utf-8 -*-

from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope.interface import provider
from zope import schema
from zope.i18nmessageid import MessageFactory
from bda.plone.cart import get_item_stock

_ = MessageFactory('plonetheme.museumbase')

@provider(IFormFieldProvider)
class ITicketsBehavior(model.Schema):
	model.fieldset(
		'shop',
		label=u"Shop",
		fields=[
			"use_barcodes",
			"barcode_list",

		]
	)

	use_barcodes = schema.Bool(
        title=_(u'label_use_barcodes', default=u'Use custom barcodes'),
        required=False
    )

	barcode_list = schema.Text(
        title=_(
            u"label_barcode_list",
            default=u"List of custom barcodes available"
        ),
        required=False
    )

NOT_ALLOWED = ['', ' ', None, '\n', '\r']

def get_barcodes(product, total):
	barcodes = []

	return barcodes

def get_barcode(product):
	barcodes_dirty = getattr(product, 'barcode_list', None)
	barcodes = get_cleaned_list_of_barcodes(product, barcodes_dirty, True)

	if barcodes:
		barcode = barcodes.pop(0)
		updated_barcode_list = "\r\n".join(barcodes)
		setattr(product, 'barcode_list', updated_barcode_list)
		return barcode
	else:
		return "" 


def get_cleaned_list_of_barcodes(ob, field_value, clean=False):
	barcodes_cleaned = []
	if field_value:
		barcodes = field_value.split('\r\n')
		barcodes_cleaned = []
		for barcode in barcodes:
			real_barcode = barcode.strip()
			if real_barcode not in NOT_ALLOWED:
				barcodes_cleaned.append(real_barcode)

		if clean:
			new_barcodes_field_cleaned = "\r\n".join(barcodes_cleaned)
			ob.barcode_list = new_barcodes_field_cleaned

	return barcodes_cleaned

def get_number_of_barcodes(ob, field_value, clean):
	barcodes = get_cleaned_list_of_barcodes(ob, field_value, clean)
	number_of_barcodes = float(len(barcodes))
	return number_of_barcodes

def update_stock(ob, event):

	if getattr(ob, 'use_barcodes' , None):
		new_stock = get_number_of_barcodes(ob, ob.barcode_list, True)
		
		item_stock = get_item_stock(ob)
		if item_stock:
			item_stock.available = new_stock

	return True
