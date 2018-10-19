import uuid

import pytest

from amocrm_api.models import Contact
from amocrm_api.constants import FIELD_TYPE, ELEMENT_TYPE
from amocrm_api.custom_fields import CUSTOM_FIELD_MAP


@pytest.mark.parametrize('field_type,value', (
    (FIELD_TYPE.TEXT, 'VALUE1'),
    (FIELD_TYPE.NUMERIC, 2),
))
def test_custom_fields(client, field_type, value):
    field = CUSTOM_FIELD_MAP[field_type](
        name=('__TEST_FIELD_%s' % uuid.uuid1()),
        element_type=ELEMENT_TYPE.CONTACT
    )

    class MyContact(Contact):
        my_field = field

    client.post_custom_fields(add=[field])
    client.update_account_info()
    client.bind_model(MyContact)

    m1 = MyContact(name='__TEST_CONTACT')
    m1.my_field=value
    m1.save()

    m2 = MyContact.get_one(id=m1.id)
    assert m2.my_field == m1.my_field
    assert m2.custom_fields[field.metadata['id']] == m1.my_field
    assert m2.custom_fields[field.metadata['name']] == m1.my_field
