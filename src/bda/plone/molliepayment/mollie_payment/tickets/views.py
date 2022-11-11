#!/usr/bin/env python
# -*- coding: utf-8 -*-

from Acquisition import aq_inner, aq_parent
from plone.app.uuid.utils import uuidToObject, uuidToCatalogBrain
from bda.plone.cart.browser import CartView

from bda.plone.orders.common import OrderData
from bda.plone.orders.common import get_bookings_soup
from bda.plone.orders.common import get_order
from bda.plone.orders.common import get_orders_soup
from bda.plone.orders.common import get_vendor_by_uid
from bda.plone.orders.common import get_vendor_uids_for
from bda.plone.orders.common import get_vendors_for
from bda.plone.orders.interfaces import IBuyable
from bda.plone.ticketshop.interfaces import ITicketOccurrence
from bda.plone.cart import get_object_by_uid
from bda.plone.cart import ascur
from decimal import Decimal 
from bda.plone.orders.common import get_vendors_for
from Products.Five import BrowserView
from bda.plone.orders import message_factory as _
from Products.CMFPlone.interfaces import IPloneSiteRoot
from plone.app.event.dx.traverser import OccurrenceTraverser as OccTravDX
from zope.globalrequest import getRequest
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
import urllib
import plone.api
from yafowil.utils import Tag

from souper.soup import get_soup
from souper.soup import LazyRecord

from bda.plone.orders import vocabularies as vocabs
from bda.plone.orders import interfaces as ifaces

from Products.CMFCore.utils import getToolByName
from plone.app.layout.navigation.interfaces import INavigationRoot
from Products.CMFCore.interfaces import ISiteRoot

from zope.component import getMultiAdapter

import json

DT_FORMAT = '%d.%m.%Y'

###
### Tickets view
###
class TicketView(CartView):
    def get_qr_code(self, ticket_uid):
        request = "https://chart.googleapis.com/chart?chs=150x150&cht=qr&chl=%s&chld=L|1&choe=UTF-8" %(ticket_uid)
        return request

    def get_tickets(self):
        return self.data_provider.data["cart_items"]

    def toLocalizedTime(self, time, long_format=None, time_only=None):
        """Convert time to localized time
        """
        context = aq_inner(self.context)
        util = getToolByName(context, 'translation_service')
        return util.ulocalized_time(time, long_format, time_only,
                                    context=context, domain='plonelocales',
                                    request=self.request)

    def get_language(self):
        """
        @return: Two-letter string, the active language code
        """
        context = self.context.aq_inner
        portal_state = getMultiAdapter((context, self.request), name=u'plone_portal_state')
        current_language = portal_state.language()
        return current_language

    def get_etickets(self, order_id):
        tickets = {
          "tickets": [],
          "customer": "",
          "total_tickets": 0,
          "event_date":""
        }

        language = self.get_language()

        try:
            data = OrderData(self.context, uid=order_id)
            bookings = data.bookings
            total_items = 0

            first_name = data.order.attrs['personal_data.firstname']
            last_name =  data.order.attrs['personal_data.lastname']
            created_date = data.order.attrs['created']
            b_uids = data.order.attrs['buyable_uids']
            customer_name = "%s %s" %(first_name, last_name)
            tickets['customer'] = customer_name
            tickets['event_date'] = ""

            ticket_info = ""

            if b_uids:
                b_uid = ""
                for b in b_uids:
                    if uuidToCatalogBrain(b).portal_type not in ['product', 'Product']:
                        b_uid = b
                        break
                if b_uid:        
                    b_obj = uuidToObject(b_uid)
                else:
                    b_uid = b_uids[0]
                    b_obj = uuidToObject(b_uid)

                if ITicketOccurrence.providedBy(b_obj):
                    occ_id = b_obj.id
                    e = aq_parent(aq_parent(b_obj))
                    traverser = OccTravDX(e, getRequest())
                    b_parent = traverser.publishTraverse(getRequest(), occ_id)
                else:
                    b_parent = b_obj.aq_parent

                if b_parent.portal_type in ["Event", "Occurrence"]:
                    start_date = b_parent.start.date()
                    end_date = b_parent.end.date()
                    formatted_date = ""
                    if start_date == end_date:
                        formatted_date = "%s, %s" %(self.toLocalizedTime(b_parent.start.strftime('%d %B %Y')), self.toLocalizedTime(b_parent.start, time_only=1))
                    else:
                        formatted_date = "%s - %s" %(self.toLocalizedTime(b_parent.start.strftime('%d %B %Y')), self.toLocalizedTime(b_parent.end.strftime('%d %B %Y')))
                    tickets["event_date"] = formatted_date

                    contents = self.context.portal_catalog(portal_type="Document", Title="ticket-info", path={"query": "/zm/%s/tickets/texts" %(language)})

                    if len(contents) > 0:
                        ticket_info_brain = contents[0]
                        ticket_info_obj = ticket_info_brain.getObject()
                        if hasattr(ticket_info_obj, "text"):
                            ticket_info = ticket_info_obj.text
                    else:
                        ticket_info = ""


            footer_info = ""
            footer_texts = self.context.portal_catalog(portal_type="Document", Title="footer-info", path={"query": "/zm/%s/tickets/texts"%(language)})
            if len(footer_texts) > 0:
                footer_info_brain = footer_texts[0]
                footer_info_obj = footer_info_brain.getObject()
                if hasattr(footer_info_obj, "text"):
                    footer_info = footer_info_obj.text
            else:
                footer_info = ""

            if not ticket_info:
                info_texts = self.context.portal_catalog(portal_type="Document", Title="ticket-info", path={"query": "/zm/%s/tickets/texts" %(language)})
                if len(info_texts) > 0:
                    info_brain = info_texts[0]
                    info_obj = info_brain.getObject()
                    if hasattr(info_obj, "text"):
                        ticket_info = info_obj.text
                else:
                    ticket_info = ""
            
            timeslot_title = ""

            for booking in bookings:
                # Check if booking is an event
                is_event = False
                append = True

                buyable_uid = booking.attrs['buyable_uid']
                b_brain = uuidToCatalogBrain(buyable_uid)

                if "event" in b_brain.Subject or b_brain.portal_type in ['Ticket', 'Ticket Occurrence']:
                    is_event = True
                    append = False


                if booking.attrs.get('discount_net', '') > 0:
                    original_price = (abs(Decimal(str(booking.attrs['net'])) - Decimal(str(booking.attrs['discount_net'])))) * 1
                else:
                    original_price = (Decimal(str(booking.attrs['net']))) * 1


                price_total = original_price + original_price / Decimal(100) * Decimal(str(booking.attrs['vat']))

                if append:
                    total_items += booking.attrs['buyable_count']

                ticket_title = booking.attrs['title']
                
                if is_event:
                    timeslot_title = ticket_title

                    try:
                        ticket_title = booking.attrs['title'].split('-')[0]+")"
                        if not timeslot_title:
                            timeslot_title = ticket_title
                    except:
                        ticket_title = booking.attrs['title']
                        if not timeslot_title:
                            timeslot_title = ticket_title
                
                if append:
                    tickets['tickets'].append({
                      "cart_item_title": ticket_title,
                      "cart_item_price": ascur(price_total),
                      "timeslot_title": timeslot_title,
                      "cart_item_count": len(booking.attrs['to_redeem']),
                      "booking_uid": booking.attrs['uid'],
                      "cart_item_original_price": "",
                      "order_created_date": created_date,
                      "to_redeem": booking.attrs['to_redeem'],
                      "is_event": is_event,
                      "ticket_info": ticket_info,
                      "footer_info": footer_info
                    })

                tickets["total_tickets"] = total_items
                tickets["timeslot_title"] = timeslot_title
        except:
            return tickets
        
        return tickets

