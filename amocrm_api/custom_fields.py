from functools import lru_cache

from marshmallow import fields

from .constants import FIELD_TYPE


def _get_one(items, match):
    matched = tuple(x for x in items if match(x))
    if len(matched) != 1:
        raise IndexError('matched %s items' % len(matched))
    return matched[0]


class _BaseCustomField:
    def _get_from_custom_fields_meta(self, custom_fields):
        if self.metadata.get('id'):
            try:
                meta = custom_fields[str(self.metadata['id'])]
            except KeyError as exc:
                raise RuntimeError('Custom field bind by id "%s" failed: %s' % exc)
        elif self.metadata.get('name'):
            try:
                meta = _get_one(custom_fields.values(),
                                lambda m: m.name == self.metadata['name'])
            except IndexError as exc:
                raise RuntimeError('Custom field bind by name "%s" failed: %s' %
                                   (self.metadata['name'], str(exc)))
        else:
            raise RuntimeError('Custom field must be binded by "name" or "id"')
        return meta

    def _bind_lazy_custom_fields_meta(self, custom_fields_resolve):
        self._custom_fields_resolve = custom_fields_resolve

    @property
    def custom_field_meta(self):
        if not hasattr(self, '_custom_field_meta'):
            if not hasattr(self, '_custom_fields_resolve'):
                raise RuntimeError('Field %s not binded to custom_fields' % self.__class__)
            self._custom_field_meta = \
                self._get_from_custom_fields_meta(self._custom_fields_resolve())
            del self._custom_fields_resolve
        return self._custom_field_meta

    @property
    def id(self):
        return self.custom_field_meta['id']


class Text(_BaseCustomField, fields.String):
    field_type = FIELD_TYPE.TEXT


class Numeric(_BaseCustomField, fields.Integer):
    field_type = FIELD_TYPE.NUMERIC


class Checkbox(_BaseCustomField, fields.Boolean):
    field_type = FIELD_TYPE.CHECKBOX


class Select(_BaseCustomField, fields.Field):
    field_type = FIELD_TYPE.SELECT


class Multiselect(_BaseCustomField, fields.List):
    field_type = FIELD_TYPE.MULTISELECT


class Multitext(Text):
    field_type = FIELD_TYPE.MULTITEXT


class Radiobutton(Select):
    field_type = FIELD_TYPE.RADIOBUTTON


class TextArea(Text):
    field_type = FIELD_TYPE.TEXTAREA


class CustomFieldsModelMeta(type):
    def __new__(metacls, cls, bases, classdict):
        new_cls = super().__new__(metacls, cls, bases, classdict)
        new_cls._custom_fields = {}

        for attr in dir(new_cls):
            field = getattr(new_cls, attr)
            if isinstance(field, _BaseCustomField):
                new_cls._custom_fields[attr] = field

        return new_cls


class CustomFieldsModel(metaclass=CustomFieldsModelMeta):
    @classmethod
    def _bind_lazy_custom_fields_meta(cls, custom_fields_resolve):
        for field in cls._custom_fields.values():
            field._bind_lazy_custom_fields_meta(custom_fields_resolve)

    @property
    @lru_cache()
    def _custom_fields_ids(self):
        return {int(fld.id): name for name, fld in self._custom_fields.items()}

    def _set_custom_fields_data(self, items):
        for data in items:
            if data['id'] in self._custom_fields_ids:
                name = self._custom_fields_ids[data['id']]
                field = self._custom_fields[name]  # noqa
                setattr(self, name, data['values'][0]['value'])

            elif self.client.debug_level >= 2:
                raise RuntimeError('Unknown custom field: %s' % data)
