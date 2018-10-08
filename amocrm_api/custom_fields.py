from copy import deepcopy
from collections import UserDict, defaultdict, Mapping, namedtuple

from marshmallow import Schema, fields, pre_load, pre_dump, validate, ValidationError
from multidict import MultiDict
from requests_client.models import Entity

from .constants import FIELD_TYPE
from .utils import get_one, cached_property


class SmartAddress(Entity):
    __slots__ = 'address1 address2 city region index country'.split()
    # country code should be in ISO 3166-1 alpha-2 format


class LegalEntity(Entity):
    __slots__ = (
        'name entity_type vat_id tax_registration_reason_code address kpp external_uid'
    ).split()


class _CustomFieldsData(UserDict):
    """
    Maps str keys as field "name", while internally storing "id" binding.
    Mostly we need it to work properly with fields which have duplicate names,
    and raise error on accessing such fields (if they were not binded to model)
    only as last resort!
    """
    def _get_key(self, key):
        if isinstance(key, str):
            ids = self._name_ids_map.get(key)
            if not ids:
                raise ValueError('Unknown field name "%s"' % key)
            elif len(self._name_ids_map[key]) > 1:
                raise ValueError('Field name "%s" binded to multiple fields: %s' %
                                 (key, self._name_ids_map[key]))
            return ids[0]
        return key

    def __getitem__(self, key):
        return self.data[self._get_key(key)]

    def __contains__(self, key):
        return self._get_key(key) in self.data

    def __setitem__(self, key, item):
        self.data[self._get_key(key)] = item

    def __str__(self):
        return '<CustomFieldsData(' + ', '.join(
            '%d:%s=%s' % (id, self._id_name_map.get(id, '__NAME_NOT_FOUND'), value)
            for id, value in self.data.items()
        ) + ')>'

    __repr__ = __str__

    @classmethod
    def create_data_cls(cls, custom_fields):
        cls = deepcopy(cls)
        cls._id_name_map = {id: f.custom_field_meta['name']
                            for id, f in custom_fields.items()}
        cls._name_ids_map = defaultdict(list)
        for id, name in cls._id_name_map.items():
            cls._name_ids_map[name].append(id)
        return cls


class _CustomFields(fields.Field):
    """
    This is composite field for binded and unbinded custom fields.
    Unbinded custom fields created dynamically from client.account_info.custom_fields
    """
    custom_fields = None

    def _bind_model_custom_field_property(self, name, field_id):
        prop = property(lambda self: self.custom_fields.get(field_id))

        def setter(obj, data):
            if obj.custom_fields is None:
                obj.custom_fields = self.data_cls()
            obj.custom_fields[field_id] = data

        setattr(self.parent.entity, name, prop)
        setattr(self.parent.entity, name, prop.setter(setter))

    def _bind_custom_fields(self, custom_fields_meta, schema, pop=True):
        custom_fields = {}

        # Binded to model fields
        for name, field in tuple(self.parent.fields.items()):
            if isinstance(field, _CustomFieldMixin):
                id = field._bind_from_custom_fields_meta(custom_fields_meta)
                assert id not in custom_fields, 'Custom field bind failed: duplicate id %s' % id
                custom_fields[id] = field
                if pop:
                    del schema.fields[name]  # removing from schema
                self._bind_model_custom_field_property(field.name, id)

        # Unbinded fields
        for id in (set(custom_fields_meta.keys()) - set(custom_fields.keys())):
            custom_fields[id] = create_custom_field(custom_fields_meta[id])

        self.custom_fields = custom_fields

    @cached_property
    def data_cls(self):
        return _CustomFieldsData.create_data_cls(self.custom_fields)

    def _deserialize(self, value, attr, data):
        return self.data_cls({
            v['id']: self.custom_fields[v['id']].deserialize(v['values'], attr, data)
            for v in value
        })

    def _serialize(self, value, attr, obj):
        if not value:
            value = dict()
        elif not isinstance(value, Mapping):
            raise ValidationError('custom_fields must be mapping, not %s' % type(value))

        # We should do this because we may have custom fields property binded after
        # some data was set to fields, because of tricky lazy binding
        for id, field in self.custom_fields.items():
            if field.name and field.name in obj.__dict__:
                # Field is binded to model, but proxy property was not set yet
                value[id] = obj.__dict__[field.name]

        return [
            {'id': id, 'values': self.custom_fields[id]._serialize(v, attr, obj)}
            for id, v in self.data_cls(value).items()
        ]


class CustomFieldsSchema(Schema):
    custom_fields = _CustomFields()

    @pre_dump
    @pre_load
    def _maybe_bind_custom_fields(self, data):
        if self.fields['custom_fields'].custom_fields is None:
            custom_fields_meta ={
                m.id: m for m in
                (self.entity.client.account_info['custom_fields']
                 [self.entity.model_plural_name] or {}).values()
            }
            self.fields['custom_fields']._bind_custom_fields(custom_fields_meta, self, pop=True)
        return data


class _CustomFieldMixin:
    field_type = None

    def __init__(self, *args, custom_field_meta=None, **kwargs):
        self.custom_field_meta = custom_field_meta
        super().__init__(*args, **kwargs)

    def _get_from_custom_fields_meta(self, data):
        for attr in ('id', 'code', 'name'):
            if self.metadata.get(attr):
                try:
                    return get_one(data.values(), lambda m: m[attr] == self.metadata[attr])
                except IndexError as exc:
                    raise RuntimeError('Custom field bind by %s "%s" failed: %s' %
                                       (attr, self.metadata[attr], str(exc)))
        raise RuntimeError('Custom field must be binded by "id", "code" or "name"')

    def _bind_from_custom_fields_meta(self, data):
        meta = self._get_from_custom_fields_meta(data)
        if self.field_type != FIELD_TYPE(meta['field_type']):
            raise RuntimeError('Custom field bind %s %s failed: expected type %s got %s instead',
                               meta['id'], meta['name'], self.field_type, meta['field_type'])
        self.custom_field_meta = meta
        return meta['id']

    def __repr__(self):
        return ('<fields.{ClassName}(custom_field_meta={self.custom_field_meta})>'
                .format(ClassName=self.__class__.__name__, self=self))


class _SingleMixin:
    def _deserialize(self, value, attr, data):
        assert len(value) == 1, 'Unexpected format for %s: %s' % (self.field_type, value)
        return super()._deserialize(value[0]['value'], attr, data)

    def _serialize(self, value, attr, obj):
        if value is not None:
            return [{'value': super()._serialize(value, attr, obj)}]


class _EnumsMixin:
    @cached_property
    def enums(self):
        rv = set(self.custom_field_meta['enums'].values())
        if len(rv) != len(self.custom_field_meta['enums']):
            # TODO: Actually we can have enums with duplicated names,
            # consider it as wrapper restriction.
            # Maybe this should be raised only on enum with duplicated name usage?
            # Merge requests are welcome, maybe something like in CustomFieldsData
            raise RuntimeError('Enums are not unique: %s' % self)
        return rv

    @cached_property
    def enum_validator(self):
        return validate.OneOf(self.enums)


class TextField(_SingleMixin, _CustomFieldMixin, fields.String):
    field_type = FIELD_TYPE.TEXT


class NumericField(_SingleMixin, _CustomFieldMixin, fields.Integer):
    field_type = FIELD_TYPE.NUMERIC


class CheckboxField(_SingleMixin, _CustomFieldMixin, fields.Boolean):
    field_type = FIELD_TYPE.CHECKBOX


class SelectField(_EnumsMixin, TextField):
    field_type = FIELD_TYPE.SELECT

    def _validate(self, value):
        if not self.validators:
            self.validators.append(self.enum_validator)
        return super()._validate(value)

    def _serialize(self, value, attr, obj):
        self._validate(value)
        return super()._serialize(value, attr, obj)


class MultiSelectField(_SingleMixin, _EnumsMixin, _CustomFieldMixin, fields.Raw):
    field_type = FIELD_TYPE.MULTISELECT

    def _deserialize(self, value, attr, data):
        values = [v['value'] for v in (value or [])]
        for v in values:
            self.enum_validator(v)
        return values

    def _serialize(self, value, attr, obj):
        if value is not None:
            if not isinstance(value, (list, set, tuple)):
                raise ValidationError('Expected enum list %s, got %s' %
                                      (self.enums, type(value)))
            if set(value) - self.enums:
                raise ValidationError('Unexpected enums %s not in %s' %
                                      (set(value) - self.enums, self.enums))
            return [{'value': v} for v in value]


class DateField(_SingleMixin, _CustomFieldMixin, fields.Date):
    field_type = FIELD_TYPE.DATE


class UrlField(TextField):
    field_type = FIELD_TYPE.URL


class MultiTextField(_SingleMixin, _EnumsMixin, _CustomFieldMixin, fields.Raw):
    field_type = FIELD_TYPE.MULTITEXT

    def _deserialize(self, value, attr, data):
        return MultiDict(
            (self.custom_field_meta['enums'][v['enum']], v['value'])
            for v in value
        )

    def _serialize(self, value, attr, obj):
        if value is not None:
            if not isinstance(value, Mapping):
                raise ValidationError('Expected enum mapping %s, got %s' %
                                      (self.enums, type(value)))
            if set(value.keys()) - self.enums:
                raise ValidationError('Unexpected enums %s not in %s' %
                                      (set(value.keys()) - self.enums, self.enums))
            return [{'enum': k, 'value': v} for k, v in value.items()]


class TextAreaField(TextField):
    field_type = FIELD_TYPE.TEXTAREA


class RadioButtonField(SelectField):
    field_type = FIELD_TYPE.RADIOBUTTON


class StreetAddressField(TextField):
    field_type = FIELD_TYPE.STREETADDRESS


class SmartAddressField(_SingleMixin, _CustomFieldMixin, fields.Raw):
    field_type = FIELD_TYPE.SMART_ADDRESS

    def _deserialize(self, value, attr, data):
        return SmartAddress(**{
            SmartAddress._fields[int(v['subtype']) - 1]: v['value']
            for v in value
        })

    def _serialize(self, value, attr, obj):
        if value is not None:
            if not isinstance(value, SmartAddress):
                raise ValidationError('Expected SmartAddress, got %s' % type(value))
            return [
                {'subtype': i + 1, 'value': getattr(value, name)}
                for i, name in enumerate(SmartAddress._fields) if hasattr(value, name)
            ]


class BirthdayField(DateField):
    field_type = FIELD_TYPE.BIRTHDAY


class LegalEntityField(_CustomFieldMixin, fields.Raw):
    field_type = FIELD_TYPE.legal_entity

    def _deserialize(self, value, attr, data):
        if value:
            return [LegalEntity(**v['value']) for v in value]

    def _serialize(self, value, attr, data):
        if not isinstance(value, (tuple, set, list)):
            raise ValidationError('Expected list, got %s' % type(value))
        if not all(isinstance(v, LegalEntity) for v in value):
            raise ValidationError('list should contain LegalEntity instances')
        return [{'value': {k: getattr(v, k, None)
                for k in LegalEntity._fields}} for v in value]


class ItemsField(_CustomFieldMixin, fields.Raw):
    # TODO: not implemented
    field_type = FIELD_TYPE.ITEMS


CUSTOM_FIELD_MAP = {
    obj.field_type: obj for obj in globals().values()
    if isinstance(obj, type) and issubclass(obj, _CustomFieldMixin) and obj.field_type
}


def create_custom_field(meta):
    """
    Factory for dynamically creating custom field from metadata based on field_type.
    """
    return CUSTOM_FIELD_MAP[FIELD_TYPE(meta['field_type'])](custom_field_meta=meta)
