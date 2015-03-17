# -*- coding: utf-8 -*-

__version__ = '0.0.1'

import six
import hashlib
import os

from lxml import etree
from datetime import datetime

import requests

from decimal import Decimal as D


def text(node, xpath):
    """
    Extract the text from a node.
    """
    return ''.join(node.xpath(xpath + "/text()"))


class Signer(object):
    """
    Build signature based on a set of tokens, optionally using a
    merchant_secret
    """
    def __init__(self, merchant_secret=None):
        self.merchant_secret_token = merchant_secret or ''

    def _get_subject(self, tokens):
        if isinstance(tokens, dict):
            tokens = [p[1] for p in sorted(tokens.items(), key=lambda t: t[0])]
        tokens = [str(t) for t in tokens + [self.merchant_secret_token,]]
        return u''.join(tokens).encode('utf-8')

    def get_signature(self, tokens):
        """
        Get signature for tokens, optionally using the merchant_secret.
        """
        return hashlib.sha1(self._get_subject(tokens)).hexdigest()


class ReturnValidator(object):
    """
    Validate the validity of a return message.
    """
    def validate(self,
                 transaction_id,
                 transaction_code,
                 status,
                 salt,
                 checksum):
        """
        Validate the return url. Return True if valid. Pass the arguments
        exectly as they appear in the url.
        """
        tokens = [transaction_id, transaction_code, status, salt]
        expected_checksum = Signer().get_signature(tokens)
        return expected_checksum == checksum


class MessageBuilder(object):
    """
    Build messages into the desired xml request. It does so by taking a request
    object and using request.get_params to fill in the request.template. It
    also signs the message using self.signer.
    """
    def __init__(self, merchant_id, merchant_key, signer):
        self.merchant_id = merchant_id
        self.merchant_key = merchant_key
        self.signer = signer

    def get_message(self, request):
        """
        Build a message based on the paramaters in a request and the signing
        information supplied to this class. The reqeust.params may be a
        callable or a property.
        """
        context = dict(request.params)
        context.update({
            u'checksum': self.signer.get_signature(request.params),
            u'merchant_key': self.merchant_key,
            u'merchant_id': self.merchant_id
        })
        return request.template.format(**context)


class BaseResponse(object):
    pass


class ResponseError(RuntimeError):
    pass


class BaseRequest(object):
    pass


class TransactionStatusResponse(BaseResponse):
    TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"

    def __init__(self, timestamp, current_timestamp, transaction_id, paid,
                 definitive, merchant_id, consumer_bank, consumer_name,
                 consumer_iban):
        self.timestamp = timestamp
        self.current_timestamp = current_timestamp
        self.transaction_id = transaction_id
        self.paid = paid
        self.definitive = definitive
        self.merchant_id = merchant_id
        self.consumer_bank = consumer_bank
        self.consumer_name = consumer_name
        self.consumer_iban = consumer_iban

    @classmethod
    def parse(cls, root_node):
        timestamp = \
            datetime.strptime(text(root_node, 'Transaction/Date'),
                              cls.TIMESTAMP_FORMAT)
        current_timestamp =\
            datetime.strptime(text(root_node, 'Transaction/CurrentDate'),
                              cls.TIMESTAMP_FORMAT)

        paid = text(root_node, 'Transaction/Paid')
        if paid == 'Y':
            paid = True
        elif paid == 'N':
            paid = False
        else:
            raise ResponseError("Bad value for Paid ({0})".format(paid))

        definitive = text(root_node, 'Transaction/Definitive')
        if definitive == 'Y':
            definitive = True
        elif definitive == 'N':
            definitive = False
        else:
            raise ResponseError("Bad value for Paid ({0})".format(definitive))

        return cls(
            timestamp=timestamp,
            current_timestamp=current_timestamp,
            transaction_id=text(root_node, 'Transaction/ID'),
            paid=paid,
            definitive=definitive,
            merchant_id=text(root_node, 'Transaction/MerchantID'),
            consumer_bank=text(root_node, 'Transaction/Consumer/Bank'),
            consumer_name=text(root_node, 'Transaction/Consumer/Name'),
            consumer_iban=text(root_node, 'Transaction/Consumer/IBAN'))


class TransactionStatusRequest(BaseRequest):
    response_cls = TransactionStatusResponse

    def __init__(self, transaction_id, transaction_code):
        self.params = {
            u'transaction_id': transaction_id,
            u'transaction_code': transaction_code,
        }

    template = u"""<?xml version="1.0" encoding="UTF-8"?>
<Transaction>
     <Action>
          <Name>TRANSACTIONSTATUS</Name>
          <Version>1</Version>
     </Action>
     <Parameters>
          <TransactionID>{transaction_id}</TransactionID>
          <TransactionCode>{transaction_code}</TransactionCode>
     </Parameters>
     <Merchant>
          <ID>{merchant_id}</ID>
          <Key>{merchant_key}</Key>
          <Checksum>{checksum}</Checksum>
     </Merchant>
</Transaction>
"""


class BanksResponse(BaseResponse):
    """
    Response to a BanksRequest
    """
    def __init__(self, banks):
        self.banks = banks

    @classmethod
    def parse(cls, root_node):
        banks = []
        for bank_node in root_node.xpath('Banks/Bank'):
            banks += [{
                'id': text(bank_node, 'Id'),
                'name': text(bank_node, 'Name')
            }]
        return cls(banks=banks)


class BanksRequest(BaseRequest):
    response_cls = BanksResponse
    template = u"""<?xml version="1.0" encoding="UTF-8"?>
<Transaction>
     <Action>
          <Name>IDEAL.GETBANKS</Name>
          <Version>1</Version>
     </Action>
     <Merchant>
          <ID>{merchant_id}</ID>
          <Key>{merchant_key}</Key>
          <Checksum>{checksum}</Checksum>
     </Merchant>
</Transaction>
"""
    params = {}


class TransactionResponse(BaseRequest):
    def __init__(self, transaction_id, transaction_code,
                 bank_url, acquirer, checksum):
        self.transaction_id = transaction_id
        self.transaction_code = transaction_code
        self.bank_url = bank_url
        self.checksum = checksum
        self.acquirer = acquirer

    @classmethod
    def parse(cls, root_node):
        return cls(
            transaction_id=text(root_node, 'Response/TransactionID'),
            transaction_code=text(root_node, 'Response/Code'),
            bank_url=text(root_node, 'Response/BankURL'),
            checksum=text(root_node, 'Checksum'),
            acquirer=text(root_node, 'Response/Acquirer')
        )


class TransactionRequest(BaseRequest):
    """
    A request for a transaction.
    """
    response_cls = TransactionResponse

    def __init__(self, amount, bank, description, return_url):
        if not isinstance(amount, (six.string_types, D)):
            raise RuntimeError(u"Amount should be a string or decimal.Decimal")

        self.params = {
            u'amount': D(amount).quantize(D("0.00")),
            u'currency': 'EUR',
            u'bank': bank,
            u'description': description,
            u'return': return_url,
        }

    template = u"""<?xml version="1.0" encoding="UTF-8"?>
<Transaction>
     <Action>
          <Name>IDEAL.EXECUTE</Name>
          <Version>1</Version>
     </Action>
     <Parameters>
          <Amount>{amount}</Amount>
          <Currency>{currency}</Currency>
          <Bank>{bank}</Bank>
          <Description>{description}</Description>
          <Return>{return}</Return>
     </Parameters>
     <Merchant>
          <ID>{merchant_id}</ID>
          <Key>{merchant_key}</Key>
          <Checksum>{checksum}</Checksum>
     </Merchant>
</Transaction>
"""


class Endpoint(object):
    ENDPOINT = 'https://www.qantanipayments.com/api/'

    def do_request(self, message):
        """
        """
        data = {'data': message.encode('utf-8')}
        response = requests.post(self.ENDPOINT, data, verify=True)
        return response.text.encode('utf-8')


class EasyIdeal(object):
    """
    Main class for interfacing with
    Qantani Easy Ideal (http://www.easy-ideal.com/)
    """

    def __init__(self, merchant_id, merchant_key, merchant_secret):
        self.signer = Signer(merchant_secret)
        self.message_builder = MessageBuilder(
            merchant_id=merchant_id,
            merchant_key=merchant_key,
            signer=self.signer)
        self.endpoint = Endpoint()

    def do_request(self, request):
        request_message = self.message_builder.get_message(request)
        response_message = self.endpoint.do_request(request_message)

        response_root = etree.fromstring(response_message)
        status = text(response_root, 'Status')
        if status != 'OK':
            error_id = text(response_root, 'Error/ID')
            error_description = text(response_root, 'Error/Description')
            raise RuntimeError('Error: {0}; {1}; {2}'.format(status,
                                                             error_id,
                                                             error_description))
        return request.response_cls.parse(response_root)

    def request_banks(self, *args, **kwargs):
        """
        Request a list of available banks.
        """
        request = BanksRequest(*args, **kwargs)
        return self.do_request(request)

    def request_transaction(self, *args, **kwargs):
        """
        Request a transaction.
        """
        request = TransactionRequest(*args, **kwargs)
        return self.do_request(request)

    def request_transaction_status(self, *args, **kwargs):
        """
        Request the status of a transaction
        """
        request = TransactionStatusRequest(*args, **kwargs)
        return self.do_request(request)
        