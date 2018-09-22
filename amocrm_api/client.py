import json
from copy import deepcopy
from datetime import timezone
from email.utils import format_datetime
from functools import lru_cache

from requests_client.client import BaseClient, auth_required
from requests_client.exceptions import HTTPError, AuthError, AuthRequired
from requests_client.utils import resolve_obj_path

from . import schemas, models
from .constants import LEAD_FILTER_BY_TASKS, ELEMENT_TYPE, NOTE_TYPE


class AmocrmClientErrorMixin:
    @property
    def msg(self):
        return getattr(self, '_msg', None) or self.get_data('response.error')

    @msg.setter
    def msg(self, msg):
        self._msg = msg

    @property
    def error_code(self):
        try:
            return int(self.get_data('response.error_code'))
        except (ValueError, TypeError):
            return None


class AmocrmClient(BaseClient):
    # API DOCS:
    # en https://www.amocrm.com/developers/content/api/auth
    # ru https://www.amocrm.ru/developers/content/api/auth
    # Looks like ru docs always have more info,
    # some fields in en docs not mentioned

    ClientErrorMixin = AmocrmClientErrorMixin
    contact_model = models.SystemContact

    __object_types = {
        'lead': {'objects_endpoint': 'leads'},
        'contact': {'objects_endpoint': 'contacts'},
        'company': {'objects_endpoint': 'companies'},
        'customer': {'objects_endpoint': 'customers'},
        'transaction': {'objects_endpoint': 'transactions'},
        'task': {'objects_endpoint: ''tasks'},
        'note': {'objects_endpoint': 'notes'},
    }

    debug_level = 5
    base_url = 'https://{}.amocrm.ru/api/v2/'
    login_url = 'https://{}.amocrm.ru/private/api/auth.php?type=json'
    _state_attributes = ['cookies']

    def __init__(self, login, hash, domain, **kwargs):
        self.login, self.hash, self.domain = login, hash, domain
        self.base_url = self.base_url.format(domain)
        self.login_url = self.login_url.format(domain)

        self.user_model = models.User

        # Binding custom schema and custom models
        for object_type in self.__object_types:
            schema = getattr(self, '%s_schema' % object_type,
                getattr(schemas, object_type.capitalize()))
            model = getattr(self, '%s_model' % object_type,
                getattr(models, object_type.capitalize()))

            schema.Meta = deepcopy(schema.Meta)
            schema.Meta.model = model
            setattr(self, '%s_schema' % object_type, schema)
            setattr(self, '%s_model' % object_type, model)

        super().__init__(**kwargs)

    @property
    def auth_ident(self):
        return '{}:{}'.format(self.login, self.domain)

    @property
    def is_authenticated(self):
        # Note that session_id expires only on server side,
        # so we can't be sure before first request
        return 'session_id' in self.cookies

    def authenticate(self):
        payload = dict(USER_LOGIN=self.login, USER_HASH=self.hash)
        resp = self.post(self.login_url, data=payload)
        if self.is_authenticated:
            self._set_authenticated(data=resp.data)
        return resp

    def _request(self, method, url, params=None, data=None, **kwargs):
        data = json.dumps(data) if data else data
        try:
            return super()._send_request(method, url, params=params, data=data,
                                         **kwargs)
        except HTTPError as exc:
            if exc.status == 401:
                if exc.error_code == 110:
                    # For wrong hash/password and for expired session we have same code,
                    # so just try to re-authenticate once
                    # https://www.amocrm.ru/developers/content/api/auth
                    raise AuthRequired(exc, ident=self.auth_ident)
                raise AuthError(exc, ident=self.auth_ident)
            raise

    @auth_required
    def get_account_info(self, custom_fields=True, users=True, pipelines=True,
                         groups=True, note_types=True, task_types=True):
        with_ = []
        custom_fields and with_.append('custom_fields')
        users and with_.append('users')
        pipelines and with_.append('pipelines')
        groups and with_.append('groups')
        note_types and with_.append('note_types')
        task_types and with_.append('task_types')

        return self.get('account?with=%s' % ','.join(with_))

    @property
    @lru_cache()
    def account_info(self):
        data = self.get_account_info().data
        data.update(data.pop('_embedded'))
        return data

    @property
    @lru_cache()
    def users(self):
        return {
            int(id): models.User(client=self, **data)
            for id, data in self.account_info.users.items()
        }

    @auth_required
    def _get_objects(self, object_type, params={}, ids=[],
                     query=None, responsible_user_id=None, modified_since=None,
                     cursor=None, cursor_count=500):
        params = params.copy()
        params.update({
            'id': ids and ','.join(map(str, ids)) or None,
            'limit_offset': cursor,
            'limit_rows': cursor_count,
            'query': query,
            'responsible_user_id': responsible_user_id,
        })

        if modified_since:
            if modified_since.tzinfo:
                modified_since = modified_since.astimezone(timezone.utc)
            else:
                modified_since.replace(tzinfo=timezone.utc)
            headers = {
                'If-Modified-Since': format_datetime(modified_since),
            }
        else:
            headers = None

        resp = self.get(self.__object_types[object_type]['objects_endpoint'],
                        params, headers=headers)
        if resp.status_code == 204:
            resp.data = []
        else:
            resp.data = resolve_obj_path(resp.data, '_embedded.items')
            schema = getattr(self, '%s_schema' % object_type)
            self.apply_response_schema(resp, schema, many=True)
        return resp

    def get_leads(self, ids=[], status_ids=[], datetimes_create=None,
                  datetimes_modify=None, tasks=None, is_active=None,
                  query=None, responsible_user_id=None, modified_since=None,
                  cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/leads

        params = {
            'status': status_ids and ','.join(map(str, status_ids)) or None,
            # 'filter[date_create]': datetimes_create,  # TODO dates or datetimes?
            # 'filter[date_modify]': datetimes_modify,  # TODO dates or datetimes?
            'filter[tasks]': tasks and LEAD_FILTER_BY_TASKS(tasks).value or None,
            'filter[active]': 1 if is_active else None,
        }
        return self._get_objects('lead', params, ids=ids,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count)

    def get_contacts(self, ids=[], query=None, responsible_user_id=None,
                     modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/contacts

        return self._get_objects('contact', ids=ids,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count)

    def get_companies(self, ids=[], query=None, responsible_user_id=None,
                      modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/companies

        return self._get_objects('company', ids=ids,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count)

    def get_customers(self, ids=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers
        # TODO: filters not implemented

        return self._get_objects('customer', ids=ids,
            cursor=cursor, cursor_count=cursor_count)

    def get_transactions(self, ids=[], customer_ids=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers

        params = {
            'customer_ids': customer_ids and ','.join(map(str, customer_ids)) or None
        }
        return self._get_objects('transaction', params, ids=ids,
            cursor=cursor, cursor_count=cursor_count)

    def get_tasks(self, ids=[], element_ids=[], element_type=None,
                  responsible_user_id=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/tasks

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_ids': element_ids and ','.join(map(str, element_ids)) or None,
        }
        return self._get_objects('task', params,
            ids=ids, responsible_user_id=responsible_user_id,
            cursor=cursor, cursor_count=cursor_count)

    def get_notes(self, element_type, ids=[], element_ids=[], note_type=None,
                  modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/notes

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_ids': element_ids and ','.join(map(str, element_ids)) or None,
            'note_type': note_type and NOTE_TYPE(note_type).value or None,
        }
        return self._get_objects('note', params, ids=ids, modified_since=modified_since,
            cursor=cursor, cursor_count=cursor_count)
