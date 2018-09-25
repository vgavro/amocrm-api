from marshmallow import fields
from requests_client.fields import DateTimeField, EntityField, BindPropertyField


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


class EntityField(EntityField):
    def resolve_entity(self, entity):
        if isinstance(entity, str):
            return getattr(self.parent.entity.client, self.entity)
        return self.entity

    def _deserialize(self, value, attr, obj):
        if not value:
            # fix for {} instead of list on empty values
            if not self.many and self.allow_none:
                return None
            if self.many:
                value = []
        elif isinstance(value, dict) and isinstance(value.get('id'), (list, tuple)):
            value = [{'id': id} for id in value['id']]

        return super()._deserialize(value, attr, obj)


class UserIdField(BindPropertyField):
    container = fields.Int

    def resolver(self, uid):
        return uid is not None and self.parent.entity.client.users[uid] or None


class GroupIdField(BindPropertyField):
    container = fields.Int

    def resolver(self, gid):
        return gid is not None and self.parent.entity.client.groups[gid] or None
