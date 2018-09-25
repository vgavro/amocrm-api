from marshmallow import fields, Schema
from requests_client.models import ClientEntityMixin, Entity, SchemaEntity

from .constants import ELEMENT_TYPE
from .utils import cached_property, get_one
from .fields import DateTimeField, TagsField, EntityField, UserIdField, GroupIdField
from . import custom_fields


class ClientMappedEntity(ClientEntityMixin, Entity):
    @classmethod
    def get(self, id=None):
        map = getattr(self.client, self.map_attr)
        if id is None:
            return map.values()
        try:
            return [map[int(id)]]
        except KeyError:
            return []

    @classmethod
    def get_one(cls, *args, **kwargs):
        return get_one(cls.get(*args, **kwargs))


class User(ClientMappedEntity):
    map_attr = 'users'


class Group(ClientMappedEntity):
    map_attr = 'groups'


class BaseEntity(ClientEntityMixin, SchemaEntity):
    object_name = None
    objects_name = None
    schema = type('Schema', (custom_fields.CustomFieldsSchemaMixin, Schema), {})

    _links = fields.Raw()

    @classmethod
    def get_one(cls, *args, **kwargs):
        return get_one(cls.get(*args, **kwargs))


class __CreatedUpdated:
    created_by_id = UserIdField(bind_attr='created_by', data_key='created_by')
    created_at = DateTimeField()
    updated_at = DateTimeField()


class __CreatedUpdatedBy(__CreatedUpdated):
    updated_by_id = UserIdField(bind_attr='updated_by', data_key='updated_by')


class __ForElement:
    element_id = fields.Int()
    element_type = fields.Int()

    @cached_property
    def element(self):
        object_name = ELEMENT_TYPE(self.element_type).name.lower()
        return get_one(self.client._get_objects(object_name, ids=[self.element_id]).data)


class Contact(__CreatedUpdatedBy, BaseEntity):
    object_name = 'contact'
    objects_name = 'contacts'

    id = fields.Int()
    name = fields.Str()
    account_id = fields.Int()
    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    tags = TagsField()
    company = EntityField('company', allow_none=True)
    customers = EntityField('customer', many=True)
    leads = EntityField('lead', many=True)
    closest_task_at = DateTimeField(allow_none=True)

    @classmethod
    def get(cls, id=[], query=None, responsible_user_id=None, modified_since=None,
            cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/contacts

        return cls.client.get_objects(cls, id=id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count).data

    # @classmethod
    # def add(cls, **kwargs):
    #     instance = cls(**kwargs)
    #     self.client.add_contacts([instance.dump()])


class SystemContact(Contact):
    # This is contact model with created custom fields in AmoCRM by default
    # This fields are deletable, so consider it more like example
    position = custom_fields.Text(name='Должность')
    phone = custom_fields.Multitext(name='Телефон')
    email = custom_fields.Multitext(name='Email')
    instant_messages = custom_fields.Multitext(name='Мгн. сообщения')


class Lead(__CreatedUpdated, BaseEntity):
    object_name = 'lead'
    objects_name = 'leads'

    id = fields.Int()
    name = fields.Str()
    account_id = fields.Int()
    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    contacts = EntityField('contacts', many=True)

    is_deleted = fields.Bool()
    status_id = fields.Int()

    closed_at = DateTimeField(allow_none=True)
    closest_task_at = DateTimeField(allow_none=True)
    sale = fields.Int()
    loss_reason_id = fields.Int()

    # main_contact, #company


class Company(__CreatedUpdatedBy, BaseEntity):
    object_name = 'company'
    objects_name = 'companies'

    id = fields.Int()
    name = fields.Str()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    contacts = EntityField('contacts', many=True)


class Customer(BaseEntity):
    object_name = 'customer'
    objects_name = 'customers'

    id = fields.Int()


class Transaction(BaseEntity):
    object_name = 'transaction'
    objects_name = 'transactions'

    id = fields.Int()


class Task(__CreatedUpdated, __ForElement, BaseEntity):
    object_name = 'task'
    objects_name = 'tasks'

    id = fields.Int()
    account_id = fields.Int()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    is_completed = fields.Bool()
    task_type = fields.Int()
    complete_till_at = DateTimeField()
    text = fields.Str()


class Note( __CreatedUpdated, __ForElement, BaseEntity):
    object_name = 'note'
    objects_name = 'notes'

    id = fields.Int()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    is_editable = fields.Bool()
    note_type = fields.Int()
    text = fields.Str(missing=None)


class Pipeline(BaseEntity):
    object_name = 'pipeline'
    objects_name = 'pipelines'

    id = fields.Int()
    name = fields.Str()
    sort = fields.Int()
    is_main = fields.Bool()
