from marshmallow import fields
from requests_client.models import ClientEntityMixin, Entity, SchemedEntity

from .constants import ELEMENT_TYPE
from .utils import cached_property, get_one
from .fields import DateTimeField, TagsField, EntityField, UserIdField, GroupIdField
from . import custom_fields


class ClientMappedEntity(ClientEntityMixin, Entity):
    @classmethod
    def get(cls, id=None):
        map = getattr(cls.client, cls.map_attr)
        if id is None:
            return tuple(map.values())
        try:
            return [map[int(id)]]
        except KeyError:
            return []

    @classmethod
    def get_one(cls, id):
        return get_one(cls.get(id))


class User(ClientMappedEntity):
    map_attr = 'users'


class Group(ClientMappedEntity):
    map_attr = 'groups'


class BaseEntity(ClientEntityMixin, SchemedEntity):
    model_name = None
    model_plural_name = None
    schema = custom_fields.CustomFieldsSchema()

    _links = fields.Raw()

    @classmethod
    def get(cls, *args, **kwargs):
        return getattr(cls.client, 'get_%s' % cls.model_plural_name)(*args, **kwargs).data

    @classmethod
    def get_iterator(cls, *args, **kwargs):
        return getattr(cls.client, 'get_%s_iterator' % cls.model_plural_name)(*args, **kwargs)

    @classmethod
    def get_one(cls, *args, **kwargs):
        return get_one(cls.get(*args, **kwargs))

    def save(self):
        self.client.post_objects(add_or_update=[self], raise_on_errors=True)

    def delete(self):
        self.client.post_objects(delete=[self], raise_on_errors=True)


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
        model_name = ELEMENT_TYPE(self.element_type).name.lower()
        return self.client.models[model_name].get_one(id=self.element_id)


class Contact(__CreatedUpdatedBy, BaseEntity):
    model_name = 'contact'
    model_plural_name = 'contacts'

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


class SystemContact(Contact):
    # This is contact model with created custom fields in AmoCRM by default
    # This fields are deletable, so consider it more like example
    position = custom_fields.TextField(code='POSITION')
    phone = custom_fields.MultiTextField(code='PHONE')
    email = custom_fields.MultiTextField(code='EMAIL')
    im = custom_fields.MultiTextField(code='IM')


class Lead(__CreatedUpdated, BaseEntity):
    model_name = 'lead'
    model_plural_name = 'leads'

    id = fields.Int()
    name = fields.Str()
    account_id = fields.Int()
    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    contacts = EntityField('contact', many=True)

    is_deleted = fields.Bool()
    status_id = fields.Int()

    closed_at = DateTimeField(allow_none=True)
    closest_task_at = DateTimeField(allow_none=True)
    sale = fields.Int()
    loss_reason_id = fields.Int()

    # main_contact, #company


class Company(__CreatedUpdatedBy, BaseEntity):
    model_name = 'company'
    model_plural_name = 'companies'

    id = fields.Int()
    name = fields.Str()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    contacts = EntityField('contact', many=True)


class Customer(BaseEntity):
    model_name = 'customer'
    model_plural_name = 'customers'

    id = fields.Int()


class Transaction(BaseEntity):
    model_name = 'transaction'
    model_plural_name = 'transactions'

    id = fields.Int()


class Task(__CreatedUpdated, __ForElement, BaseEntity):
    model_name = 'task'
    model_plural_name = 'tasks'

    id = fields.Int()
    account_id = fields.Int()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    is_completed = fields.Bool()
    task_type = fields.Int()
    complete_till_at = DateTimeField()
    text = fields.Str()


class Note( __CreatedUpdated, __ForElement, BaseEntity):
    model_name = 'note'
    model_plural_name = 'notes'

    id = fields.Int()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    is_editable = fields.Bool()
    note_type = fields.Int()
    text = fields.Str(missing=None)


class Pipeline(BaseEntity):
    model_name = 'pipeline'
    model_plural_name = 'pipelines'

    id = fields.Int()
    name = fields.Str()
    sort = fields.Int()
    is_main = fields.Bool()
