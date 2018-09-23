from marshmallow import fields
from requests_client.schemas import ResponseSchema

from . import models


class Nested(fields.Nested):
    # NOTE: as far as not merged:
    # https://github.com/marshmallow-code/marshmallow/pull/963
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('unknown', 'exclude')
        super().__init__(*args, **kwargs)


class CustomFieldsMixin:
    # It's list if not empty, but dict if empty
    # Amocrm truly have great api design... *sarcastic*
    custom_fields = fields.Raw(required=True)

    def create_model(self, data):
        custom_fields = data.pop('custom_fields') or []
        instance = super().create_model(data)
        if hasattr(instance, '_set_custom_fields_data'):
            instance._set_custom_fields_data(custom_fields)
        return instance


class Company(CustomFieldsMixin, ResponseSchema):
    class Meta:
        model = models.Company


class Contact(CustomFieldsMixin, ResponseSchema):
    class Meta:
        model = models.Contact

    # company = fields.Nested(CompanySchema)


class Lead(CustomFieldsMixin, ResponseSchema):
    class Meta:
        model = models.Lead


class Customer(CustomFieldsMixin, ResponseSchema):
    class Meta:
        model = models.Customer


class Transaction(ResponseSchema):
    class Meta:
        model = models.Transaction


class Task(ResponseSchema):
    class Meta:
        model = models.Task


class Note(ResponseSchema):
    class Meta:
        model = models.Note
