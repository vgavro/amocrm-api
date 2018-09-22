from marshmallow import fields
from requests_client.schemas import ResponseSchema

from . import models


class Nested(fields.Nested):
    # NOTE: as far as not merged:
    # https://github.com/marshmallow-code/marshmallow/pull/963
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('unknown', 'exclude')
        super().__init__(*args, **kwargs)


class Company(ResponseSchema):
    class Meta:
        model = models.Company


class Contact(ResponseSchema):
    class Meta:
        model = models.Contact

    # company = fields.Nested(CompanySchema)


class Lead(ResponseSchema):
    class Meta:
        model = models.Lead


class Customer(ResponseSchema):
    class Meta:
        model = models.Lead


class Transaction(ResponseSchema):
    class Meta:
        model = models.Lead


class Task(ResponseSchema):
    class Meta:
        model = models.Lead


class Note(ResponseSchema):
    class Meta:
        model = models.Lead
