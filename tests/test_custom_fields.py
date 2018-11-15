import uuid
from datetime import date

import pytest

from amocrm_api.models import Contact
from amocrm_api.constants import FIELD_TYPE, ELEMENT_TYPE
from amocrm_api.custom_fields import CUSTOM_FIELD_MAP  # , SmartAddress, LegalEntity


@pytest.mark.parametrize('field_type,value', (
    (FIELD_TYPE.TEXT, 'VALUE1'),
    (FIELD_TYPE.NUMERIC, 2),
    (FIELD_TYPE.SELECT, 'yellow'),
    # (FIELD_TYPE.MULTISELECT, ['yellow', ]), # TODO: wtf
    (FIELD_TYPE.DATE, date(1999, 1, 1)),
    (FIELD_TYPE.URL, 'https://google.com'),
    # (FIELD_TYPE.MULTITEXT, 'text'),  # TODO
    (FIELD_TYPE.TEXTAREA, 'text'),
    (FIELD_TYPE.RADIOBUTTON, 'yellow'),
    (FIELD_TYPE.STREETADDRESS, 'Volkova, 9'),
    # (FIELD_TYPE.SMART_ADDRESS,
    #  SmartAddress(address1='Volkova, 9', city='Kiev', country='Ukraine')),  # TODO
    (FIELD_TYPE.BIRTHDAY, date(1999, 1, 1)),
    # (FIELD_TYPE.legal_entity,
    #  [LegalEntity(name='entity1', entity_type='type1', vat_id=1), ]),  # TODO wtf
    # (FIELD_TYPE.ITEMS, ),  # TODO: not implemented
))
def test_custom_fields(client, field_type, value):
    enums = None
    need_enums = [FIELD_TYPE.SELECT, FIELD_TYPE.MULTISELECT,
                  FIELD_TYPE.RADIOBUTTON, FIELD_TYPE.ITEMS]
    if field_type in need_enums:
        enums = ['red', 'yellow', 'green']

    field = CUSTOM_FIELD_MAP[field_type](
        name=('__TEST_FIELD_%s' % uuid.uuid1()),
        element_type=ELEMENT_TYPE.CONTACT,
        enums=enums,
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
    if field_type == FIELD_TYPE.SMART_ADDRESS:
        assert m2.my_field.address1 == m1.my_field.address1
        assert m2.my_field.city == m1.my_field.city
        assert m2.my_field.country == m1.my_field.country
    elif field_type == FIELD_TYPE.legal_entity:
        assert m2.my_field.name == m1.my_field.name
        assert m2.my_field.entity_type == m1.my_field.entity_type
        assert m2.my_field.vat_id == m1.my_field.vat_id
    else:
        assert m2.my_field == m1.my_field
    assert m2.custom_fields[field.metadata['id']] == m1.my_field
    assert m2.custom_fields[field.metadata['name']] == m1.my_field
    m1.delete()
