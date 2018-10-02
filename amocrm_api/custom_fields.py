from marshmallow import fields, pre_load, post_dump

from .constants import FIELD_TYPE
from .utils import get_one, cached_property


class CustomFieldsSchemaMixin:
    @pre_load
    def __pre_load(self, data):
        custom_fields_data = data.pop('custom_fields', [])
        for val in custom_fields_data:
            try:
                custom_field = self.custom_fields[val['id']]
            except KeyError:
                # Unbinded custom field, we can't create it dynamically
                # because of cyrillic to eng ugly transliterations
                # and possible name conflict issues
                # TODO:
                # BUT - we can have additional field to store custom fields
                # as dict by key name, not attr name
                self.entity.client.logger.warn('Unbinded custom field: %s', val)
                continue
            else:
                assert custom_field.name not in data
                self.entity.client.logger.debug('Setting: meta=%s data=%s',  # WIP
                                                custom_field.custom_field_meta, val)
                data[custom_field.name] = val['values']
        return data

    @post_dump
    def __pre_dump(self, data):
        custom_fields_data = []
        for field in self.custom_fields.values():
            value = data.pop(field.name, None)
            if value:
                custom_fields_data.append({'id': field.custom_field_id, 'values': value})
        data['custom_fields'] = custom_fields_data
        return data

    @cached_property
    def custom_fields(self):
        rv = {}
        for field in self.fields.values():
            if isinstance(field, _BaseCustomField):
                rv[field.custom_field_id] = field
        return rv


class _BaseCustomField:
    def _get_from_custom_fields_meta(self, custom_fields):
        if self.metadata.get('id'):
            try:
                meta = custom_fields[str(self.metadata['id'])]
            except KeyError as exc:
                raise RuntimeError('Custom field bind by id "%s" failed: %s' % exc)
        elif self.metadata.get('name'):
            try:
                meta = get_one(custom_fields.values(),
                               lambda m: m.name == self.metadata['name'])
            except IndexError as exc:
                raise RuntimeError('Custom field bind by name "%s" failed: %s' %
                                   (self.metadata['name'], str(exc)))
        else:
            raise RuntimeError('Custom field must be binded by "name" or "id"')
        return meta

    @property
    def custom_field_meta(self):
        if not hasattr(self, '_custom_field_meta'):
            entity = self.parent.entity
            self._custom_field_meta = self._get_from_custom_fields_meta(
                entity.client.account_info['custom_fields'][entity.model_plural_name]
            )
        return self._custom_field_meta

    @property
    def custom_field_id(self):
        return self.custom_field_meta['id']


class _Single(_BaseCustomField):
    def _deserialize(self, value, attr, data):
        assert len(value) == 1
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


class Select(_BaseCustomField, fields.Field):
    field_type = FIELD_TYPE.SELECT


class Multiselect(_BaseCustomField, fields.List):
    field_type = FIELD_TYPE.MULTISELECT


class Multitext(_BaseCustomField, fields.Dict):
    field_type = FIELD_TYPE.MULTITEXT

    def _deserialize(self, value, attr, data):
        return {
            self.custom_field_meta['enums'][val['enum']]: val['value']
            for val in value
        }

    def _serialize(self, value, attr, data):
        if value is not None:
            return [{'enum': k, 'value': v} for k, v in value.items()]


class Radiobutton(Select):
    field_type = FIELD_TYPE.RADIOBUTTON


class TextArea(Text):
    field_type = FIELD_TYPE.TEXTAREA
