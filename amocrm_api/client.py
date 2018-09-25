import json
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime

from requests_client.client import BaseClient, auth_required
from requests_client.exceptions import HTTPError, AuthError, AuthRequired
from requests_client.utils import resolve_obj_path

from . import models
from .constants import LEAD_FILTER_BY_TASKS, ELEMENT_TYPE, NOTE_TYPE
from .utils import cached_property, maybe_qs_list


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
    contact = models.SystemContact

    __object_names = [
        'user', 'group',
        'lead', 'contact', 'company', 'customer', 'transaction', 'task',
        'note', 'pipeline'
    ]

    debug_level = 5
    base_url = 'https://{}.amocrm.ru/api/v2/'
    login_url = 'https://{}.amocrm.ru/private/api/auth.php?type=json'
    _state_attributes = ['cookies']

    def __init__(self, login, hash, domain, **kwargs):
        self.login, self.hash, self.domain = login, hash, domain
        self.base_url = self.base_url.format(domain)
        self.login_url = self.login_url.format(domain)

        # Binding custom schema and custom models
        for object_name in self.__object_names:
            model = deepcopy(getattr(self, object_name,
                getattr(models, object_name.capitalize())))
            model._client = self
            setattr(self, object_name, model)

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
    def get_account_info(self, with_=None):
        # https://www.amocrm.ru/developers/content/api/account
        with__ = ['custom_fields', 'users', 'pipelines', 'groups', 'note_types', 'task_types']
        return self.get('account?with=%s' % ','.join(with_ is None and with__ or with_))

    @cached_property
    def account_info(self):
        data = self.get_account_info().data
        data.update(data.pop('_embedded'))
        return data

    @cached_property
    def users(self):
        return {
            int(id): self.user(**data)
            for id, data in self.account_info.users.items()
        }

    @cached_property
    def groups(self):
        return {group['id']: self.group(**group) for group in self.account_info.groups}

    @auth_required
    def get_objects(self, model, params={}, id=[], query=None, responsible_user_id=None,
                    modified_since=None, cursor=None, cursor_count=500):
        params = params.copy()
        params.update({
            'id': maybe_qs_list(id),
            'limit_offset': cursor,
            'limit_rows': cursor_count,
            'query': query,
            'responsible_user_id': responsible_user_id,
        })

        if modified_since:
            # Documentation insist that If-Modified-Since should be in UTC
            if modified_since.tzinfo:
                modified_since = modified_since.astimezone(timezone.utc)
            else:
                modified_since.replace(tzinfo=timezone.utc)
            headers = {
                'If-Modified-Since': format_datetime(modified_since),
            }
        else:
            headers = None

        resp = self.get(model.objects_name, params, headers=headers)
        if resp.status_code == 204 or '_embedded' not in resp.data:
            # Looks like we get 204 on "not found",
            # and no "_embedded" key if not any model exists (even without filter)
            # Got "_embedded" key error on "customers"
            resp.data = []
        else:
            resp.data = resolve_obj_path(resp.data, '_embedded.items')
            resp.data = model.load(resp.data, many=True)
        return resp

    @auth_required
    def add_or_update_objects(self, instances, updated_at=True):
        data = {}
        for instance in instances:
            data.setdefault(instance.objects_name, ([], {}))  # add, update
            add, update = data[instance.objects_name]
            if instance.id:
                update[int(instance.id)] = instance
            else:
                add.append(instance)

        rv = []
        for objects_name, (add, update) in data.items():
            if updated_at:
                # Renewing update_at
                for u in update.values():
                    u.updated_at = datetime.utcnow() if updated_at is True else updated_at

            payload = {
                'add': [obj.dump() for obj in add],
                'update': [obj.dump() for obj in update.values()]
            }
            resp = self.post(objects_name, data=payload)
            resp.data = resolve_obj_path(resp.data, '_embedded')

            items = resp.data.get('items', [])
            # TODO: reproduce add error? How to bind new ids in that case?
            errors = resp.data.get('errors', {}).get('update', {})
            errors = {int(id): msg for id, msg in errors.items()}
            assert (len(items) + len(errors)) == (len(add) + len(update))

            for id, msg in errors.items():
                entity = update[id]
                entity._update_error = errors[id]
                self.logger.error('Update failed: "%s" for %s', errors[id], entity)
                continue

            for i, item in enumerate(items):
                if i < len(add):
                    # Actually, I wasn't able to get error on add,
                    # so it's not obvious how to bind new ids in that case
                    assert 'updated_at' not in item
                    added = add[i]
                    added.id = int(item['id'])
                else:
                    updated = update[int(item['id'])]

                    field = updated.schema.fields['updated_at']
                    updated_at = field._deserialize(item['updated_at'], 'updated_at', item)
                    if updated.updated_at != updated_at:
                        self.logger.warn('updated_at != %s: %s', updated_at, updated)
                    updated.updated_at = updated_at

            rv.append(resp)
        return rv

    def get_leads(self, id=[], status_id=[], datetimes_create=None,
                  datetimes_modify=None, tasks=None, is_active=None,
                  query=None, responsible_user_id=None, modified_since=None,
                  cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/leads

        params = {
            'status': maybe_qs_list(status_id),
            # 'filter[date_create]': datetimes_create,  # TODO dates or datetimes?
            # 'filter[date_modify]': datetimes_modify,  # TODO dates or datetimes?
            'filter[tasks]': tasks and LEAD_FILTER_BY_TASKS(tasks).value or None,
            'filter[active]': 1 if is_active else None,
        }
        return self._get_objects('lead', params, id=id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count)

    def get_companies(self, id=[], query=None, responsible_user_id=None,
                      modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/companies

        return self._get_objects('company', id=id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count)

    def get_customers(self, id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers
        # TODO: filters not implemented

        return self._get_objects('customer', id=id,
            cursor=cursor, cursor_count=cursor_count)

    def get_transactions(self, id=[], customer_id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers

        params = {
            'customer_id': customer_id and ','.join(map(str, customer_id)) or None
        }
        return self._get_objects('transaction', params, id=id,
            cursor=cursor, cursor_count=cursor_count)

    def get_tasks(self, id=[], element_id=[], element_type=None,
                  responsible_user_id=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/tasks

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
        }
        return self._get_objects('task', params,
            id=id, responsible_user_id=responsible_user_id,
            cursor=cursor, cursor_count=cursor_count)

    def get_notes(self, element_type, id=[], element_id=[], note_type=None,
                  modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/notes

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
            'note_type': note_type and NOTE_TYPE(note_type).value or None,
        }
        return self._get_objects('note', params, id=id, modified_since=modified_since,
            cursor=cursor, cursor_count=cursor_count)

    def get_pipelines(self, id=[]):
        # https://www.amocrm.ru/developers/content/api/pipelines

        return self._get_objects('pipeline', id=id, cursor_count=None)
