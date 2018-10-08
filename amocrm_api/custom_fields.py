from copy import deepcopy
from collections import UserDict, defaultdict, Mapping

from marshmallow import Schema, fields, pre_load, pre_dump

from .constants import FIELD_TYPE
from .utils import get_one, cached_property


class _CustomFieldsData(UserDict):
    """
    Maps str keys as field "name", while internally storing "id" binding.
    Mostly we need it to work properly with fields which have duplicate names,
    and raise error on accessing such fields (if they were not binded)
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
            '%d:%s=%s' % (id, self._id_name_map[id], value)
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
    Unbinded custom fields created dynamically from account_info.custom_fields.
    """
    custom_fields = None

    def _bind_model_custom_fields_property(self, field_name, field_id):
        prop = property(lambda self: self.custom_fields.get(field_id))

        def setter(obj, data):
            if obj.custom_fields is None:
                obj.custom_fields = self.data_cls()
            obj.custom_fields[field_id] = data

        setattr(self.parent.entity, field_name, prop)
        setattr(self.parent.entity, field_name, prop.setter(setter))

    def _bind_custom_fields(self):
        custom_fields = {}

        model = self.parent.entity
        custom_fields_meta = model.client.account_info['custom_fields'][model.model_plural_name]
        custom_fields_meta = {m.id: m for m in (custom_fields_meta or {}).values()}

        # Binded
        for name, field in tuple(self.parent.fields.items()):
            if isinstance(field, _CustomFieldMixin):
                id = field._bind_from_custom_fields_meta(custom_fields_meta)
                assert id not in custom_fields, 'Custom field bind failed: duplicate id %s' % id
                custom_fields[id] = field
                del self.parent.fields[name]  # removing from parent
                self._bind_model_custom_fields_property(field.name, id)

        # Unbinded
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
            raise ValueError('custom_fields must be mapping, not %s' % type(value))

        # We should do this because we may have custom fields binded after
        # some data was set to fields, because of tricky lazy binding
        for id, field in self.custom_fields.items():
            if field.name and field.name in obj.__dict__:
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
            self.fields['custom_fields']._bind_custom_fields()
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


class _Single(_CustomFieldMixin):
    def _deserialize(self, value, attr, data):
        assert len(value) == 1, 'Unexpected format: %s' % value
        return super()._deserialize(value[0]['value'], attr, data)

    def _serialize(self, value, attr, obj):
        if value is not None:
            return [{'value': super()._serialize(value, attr, obj)}]


class Text(_Single, fields.String):
    field_type = FIELD_TYPE.TEXT


class Numeric(_Single, fields.Integer):
    field_type = FIELD_TYPE.NUMERIC


class Checkbox(_Single, fields.Boolean):
    field_type = FIELD_TYPE.CHECKBOX


class Select(_CustomFieldMixin, fields.Field):
    field_type = FIELD_TYPE.SELECT


class Multiselect(_CustomFieldMixin, fields.List):
    field_type = FIELD_TYPE.MULTISELECT


class Multitext(_CustomFieldMixin, fields.Dict):
    field_type = FIELD_TYPE.MULTITEXT

    def _deserialize(self, value, attr, data):
        return {
            self.custom_field_meta['enums'][val['enum']]: val['value']
            for val in value
        }

    def _serialize(self, value, attr, data):
        enums = set(self.custom_field_meta['enums'].values())
        if value is not None:
            if not isinstance(value, Mapping):
                raise ValueError('Expected enum mapping %s, got %s' %
                                 (enums, type(value)))
            unknown = set(value.keys()) - enums
            if unknown:
                raise ValueError('Unexpected enums %s not in %s' %
                                 (unknown, enums))
            return [{'enum': k, 'value': v} for k, v in value.items()]


class Radiobutton(Select):
    field_type = FIELD_TYPE.RADIOBUTTON


class Textarea(Text):
    field_type = FIELD_TYPE.TEXTAREA


def create_custom_field(meta):
    """
    Factory for dynamically creating custom field from metadata based on field_type.
    """
    field_cls = globals()[FIELD_TYPE(meta['field_type']).name.replace('_', '').capitalize()]
    return field_cls(custom_field_meta=meta)
