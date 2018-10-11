from marshmallow import Schema, fields
from requests_client.models import BindedEntityMixin, Entity, SchemedEntity
from requests_client.schemas import DumpKeySchemaMixin
from requests_client.utils import cached_property

from .constants import ELEMENT_TYPE
from .utils import get_one
from .fields import DateTimeField, TagsField, EntityField, UserIdField, GroupIdField
from .custom_fields import CustomFieldsSchemaMixin
from . import custom_fields


_Schema = type('_Schema', (DumpKeySchemaMixin, Schema), {})
_CustomFieldsSchema = type('_CustomFieldsSchema', (CustomFieldsSchemaMixin, _Schema), {})


class ClientMappedEntity(BindedEntityMixin, Entity):
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


class BaseEntity(BindedEntityMixin, SchemedEntity):
    model_name = None
    model_plural_name = None
    schema = _Schema

    id = fields.Int(default=None)
    _links = fields.Raw()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def get():
            if self.id is None:
                raise ValueError('No id')
            self.update(self.__class__.get_one(id=self.id))
        self.get = get
        self.get_one, self.get_iterator = None, None

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
    schema = _CustomFieldsSchema

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
    """
    This is contact model with created custom fields in AmoCRM by default.
    This fields are deletable, so consider it more like example.
    """
    position = custom_fields.TextField(code='POSITION')
    phone = custom_fields.MultiTextField(code='PHONE')
    email = custom_fields.MultiTextField(code='EMAIL')
    im = custom_fields.MultiTextField(code='IM')


class Lead(__CreatedUpdated, BaseEntity):
    model_name = 'lead'
    model_plural_name = 'leads'
    schema = _CustomFieldsSchema

    name = fields.Str()
    account_id = fields.Int()
    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')
    tags = TagsField()

    # For some reason it can't be changed using api
    # (tested with main_contact: {id:..} and changing order of contacts_id)
    main_contact = EntityField('contact', load_only=True)

    contacts = EntityField('contact', dump_key='contacts_id', flat_id=True, many=True)
    company = EntityField('company')
    pipeline = EntityField('pipeline', only=['id'], unknown='exclude')

    status_id = fields.Int()
    is_deleted = fields.Bool(default=False)
    closed_at = DateTimeField(allow_none=True)
    closest_task_at = DateTimeField(allow_none=True, default=None)
    sale = fields.Int(default=0)
    loss_reason_id = fields.Int(default=0)


class Company(__CreatedUpdatedBy, BaseEntity):
    model_name = 'company'
    model_plural_name = 'companies'
    schema = _CustomFieldsSchema

    name = fields.Str()

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    contacts = EntityField('contact', many=True)


class Customer(BaseEntity):
    model_name = 'customer'
    model_plural_name = 'customers'
    schema = _CustomFieldsSchema


class Transaction(BaseEntity):
    model_name = 'transaction'
    model_plural_name = 'transactions'


class Task(__CreatedUpdated, __ForElement, BaseEntity):
    model_name = 'task'
    model_plural_name = 'tasks'

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

    responsible_user_id = UserIdField('responsible_user')
    group_id = GroupIdField('group')

    is_editable = fields.Bool()
    note_type = fields.Int()
    text = fields.Str(missing=None)


class PipelineStatus(SchemedEntity):
    id = fields.Int()
    name = fields.Str()
    color = fields.Str()
    sort = fields.Int()
    is_editable = fields.Bool()


class Pipeline(BaseEntity):
    model_name = 'pipeline'
    model_plural_name = 'pipelines'

    name = fields.Str()
    sort = fields.Int()
    is_main = fields.Bool()
    statuses = fields.Dict(keys=fields.Int, values=EntityField(PipelineStatus))
