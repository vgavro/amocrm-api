from .constants import FIELD_TYPE
from marshmallow import fields


class CustomField:
    pass


class Text(CustomField, fields.String):
    field_type = FIELD_TYPE.TEXT


class Numeric(CustomField, fields.Integer):
    field_type = FIELD_TYPE.NUMERIC


class Checkbox(CustomField, fields.Boolean):
    field_type = FIELD_TYPE.CHECKBOX


class Select(CustomField, fields.Field):
    field_type = FIELD_TYPE.SELECT


class Multiselect(CustomField, fields.List):
    field_type = FIELD_TYPE.MULTISELECT


class Multitext(Text):
    field_type = FIELD_TYPE.MULTITEXT


class Radiobutton(Select):
    field_type = FIELD_TYPE.RADIOBUTTON


class TextArea(Text):
    field_type = FIELD_TYPE.TEXTAREA
