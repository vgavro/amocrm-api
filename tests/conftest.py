import pytest

from amocrm_api import AmocrmClient


@pytest.fixture()
def client():
    cl = AmocrmClient.create_from_config()
    if not cl.is_authenticated:
        cl.authenticate()
    if not hasattr(AmocrmClient, '_account_info'):
        # Just store it once for all tests
        AmocrmClient._account_info = cl.get_account_info().data
    if 'account_info' not in cl.__dict__:
        cl.__dict__['account_info'] = AmocrmClient._account_info
    yield cl
