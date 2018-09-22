from marshmallow import fields
from requests_client.schemas import DateTime
from requests_client.models import ClientEntity

from . import custom_fields


class User(ClientEntity):
    pass


class Contact(ClientEntity):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    created_by_id = fields.Int(required=True, data_key='created_by')
    created_at = DateTime(required=True, format='timestamp')
    updated_at = DateTime(required=True, format='timestamp')
    account_id = fields.Int(required=True)
    updated_by_id = fields.Int(required=True, data_key='updated_by')

    @property
    def created_by(self):
        return self.client.users[self.updated_by_id]

    @property
    def updated_by(self):
        return self.client.users[self.updated_by_id]


class SystemContact(Contact):
    position = custom_fields.Text(name='Должность')
    phone = custom_fields.Multitext(name='Телефон')
    email = custom_fields.Multitext(name='Email')
    instant_messages = custom_fields.Multitext(name='Мгн. сообщения')


class Lead(ClientEntity):
    pass


class Company(ClientEntity):
    pass


class Customer(ClientEntity):
    pass


class Transaction(ClientEntity):
    pass


class Task(ClientEntity):
    pass


class Note(ClientEntity):
    pass
