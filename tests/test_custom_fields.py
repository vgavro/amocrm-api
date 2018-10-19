import pytest

from amocrm_api.models import Contact
from amocrm_api.constants import LEAD_STATUS, FIELD_TYPE, ELEMENT_TYPE
from amocrm_api.custom_fields import create_custom_field, CUSTOM_FIELD_MAP


@pytest.mark.parametrize('custom_field_type', FIELD_TYPE)
def test_custom_fields(client, custom_field_type):
    class MyContact(Contact):
        my_field = CUSTOM_FIELD_MAP[custom_field_type](
            name='__TEST_FIELD_NAME',
            element_type=ELEMENT_TYPE.CONTACT
        )

    client.post_custom_fields(add=[MyContact.schema.fields['my_field']])

    client.update_account_info()

    client.bind_model(MyContact)

    m1 = MyContact(name='__TEST_CONTACT_#')
    m1.my_field='VALUE1'
    m1.save()

    m2 = MyContact.get_one(id=m1.id)
    assert m2.my_field == m1.my_field
    assert m2[m2.my_field.metadata['id']] == m1.my_field
    assert m2[m2.myfield.metadata['name']] == m1.my_field
