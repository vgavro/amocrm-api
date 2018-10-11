from marshmallow import fields
from requests_client.fields import DateTimeField, SchemedEntityField, BindPropertyField


class DateTimeField(DateTimeField):
    def __init__(self, **kwargs):
        kwargs.setdefault('format', 'timestamp')
        super().__init__(**kwargs)


class TagsField(fields.Field):
    def _deserialize(self, value, attr, obj):
        return value and [tag['name'] for tag in value] or []

    def _serialize(self, value, attr, data):
        if value is not None:
            if isinstance(value, str):
                return
            return ','.join(value)


class EntityField(SchemedEntityField):
    def __init__(self, *args, **kwargs):
        self.flat_id = kwargs.pop('flat_id', None)
        super().__init__(*args, **kwargs)

    def resolve_entity(self, entity):
        if isinstance(entity, str):
            return getattr(self.parent.entity.client, self.entity)
        return self.entity

    def _deserialize(self, value, attr, data):
        if not value:
            # fix for {} instead of list on empty values
            if not self.many and self.allow_none:
                return None
            if self.many:
                value = []
        elif self.many and isinstance(value, dict):
            if isinstance(value.get('id'), (list, tuple)):
                value = [{'id': id} for id in value['id']]

        return super()._deserialize(value, attr, data)

    def _serialize(self, value, attr, obj):
        if value is not None:
            if self.many:
                if self.flat_id:
                    return [v.id for v in value]
                return {'id': [v.id for v in value]}
            elif self.flat_id:
                return value.id

        return super()._serialize(value, attr, obj)


class UserIdField(BindPropertyField):
    container = fields.Int

    def getter(self, id):
        return id is not None and self.parent.entity.client.users[id] or None


class GroupIdField(BindPropertyField):
    container = fields.Int

    def getter(self, id):
        return id is not None and self.parent.entity.client.groups[id] or None
