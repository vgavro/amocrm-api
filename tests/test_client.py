from amocrm_api.constants import LEAD_STATUS, FIELD_TYPE, ELEMENT_TYPE
from amocrm_api.custom_fields import CUSTOM_FIELD_MAP


def test_account_info(client):
    assert client.subdomain == client.account_info.subdomain
    assert client.login == client.current_user.login


def test_contact(client):
    contact = client.contact(name='__TEST_CONTACT', tags=['x', 'y'])
    assert not contact.id

    contact.save()
    assert contact.id
    assert not contact.created_at
    assert not contact.updated_at

    contact.get()
    assert contact.created_at
    assert contact.updated_at
    assert contact.responsible_user.id == contact.responsible_user_id == client.current_user.id
    assert contact.responsible_user.name == client.current_user.name
    assert contact.group.id == client.current_user.group_id
    assert contact.account_id == client.account_info.id

    contact_id = contact.id
    contact = client.contact.get_one(id=contact_id)
    assert contact.id == contact_id
    assert contact.name == '__TEST_CONTACT'
    assert contact.tags == ['x', 'y']

    contact.delete()
    assert len(client.contact.get(id=contact_id)) == 0


def test_lead(client):
    lead = client.lead(name='__TEST_LEAD')
    assert not lead.id

    contact1 = client.contact(name='__TEST_CONTACT1')
    contact2 = client.contact(name='__TEST_CONTACT2')
    client.post_objects([contact1, contact2])
    assert all(c.id for c in (contact1, contact2))

    lead.contacts = [client.contact(id=contact1.id), contact2]
    pipeline, *_ = client.pipelines.values()
    lead.pipeline = pipeline
    lead.status_id = LEAD_STATUS.SUCCESS.value
    lead.save()
    assert lead.id
    assert not lead.created_at
    assert not lead.updated_at

    lead.get()
    assert lead.created_at
    assert lead.updated_at
    assert len(lead.contacts) == 2
    assert lead.contacts[0].id == contact1.id
    assert lead.contacts[1].id == contact2.id
    assert lead.main_contact.id == contact1.id
    assert all(isinstance(c, client.contact) for c in [lead.main_contact] + lead.contacts)
    assert lead.pipeline.id == pipeline.id
    # assert lead.pipeline.name == pipeline.name

    contact2_ = lead.contacts[1]
    assert not contact2_.name
    contact2_.get()
    assert contact2_.name == contact2.name

    lead_id = lead.id
    lead = client.lead.get_one(id=lead_id)
    assert lead.id == lead_id

    client.post_objects(delete=[lead, contact1, contact2])
    assert len(client.lead.get(id=lead_id)) == 0
    assert len(client.contact.get(id=[contact1, contact2])) == 0


def test_post_custom_fields(client):
    fields = []
    for i, field_type in enumerate(['TEXT', 'NUMERIC', 'CHECKBOX']):
        fields.append(CUSTOM_FIELD_MAP[FIELD_TYPE[field_type]](
            name='__TEST_CUSTOM_FIELD_{}'.format(i + 1),
            element_type=ELEMENT_TYPE.CONTACT
        ))

    resp = client.post_custom_fields(add=fields)
    client.update_account_info()
    custom_fields = client.account_info.custom_fields
    for i, field in enumerate(fields):
        assert field.metadata['id']
        assert field.metadata['id'] == resp.data[i]['id']
        assert custom_fields.contacts[str(field.metadata['id'])]['name'] ==\
            field.metadata['name']

    resp = client.post_custom_fields(delete=fields)
    assert len(resp.data) == 0
    client.update_account_info()
    custom_fields = client.account_info.custom_fields
    for field in fields:
        assert not custom_fields.contacts.get(str(fields[i].metadata['id']))
