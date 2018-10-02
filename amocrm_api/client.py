import json
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime
from collections import defaultdict

from requests_client.client import BaseClient, auth_required
from requests_client.cursor_fetch import CursorFetchGenerator
from requests_client.exceptions import HTTPError, AuthError, AuthRequired
from requests_client.utils import resolve_obj_path

from . import models
from .exceptions import AmocrmClientErrorMixin, PostError
from .constants import LEAD_FILTER_BY_TASKS, ELEMENT_TYPE, NOTE_TYPE
from .utils import cached_property, maybe_qs_list


class AmocrmClient(BaseClient):
    # API DOCS:
    # en https://www.amocrm.com/developers/content/api/auth
    # ru https://www.amocrm.ru/developers/content/api/auth
    # Looks like ru docs always have more info,
    # some fields in en docs not mentioned

    ClientErrorMixin = AmocrmClientErrorMixin
    contact = models.SystemContact

    __model_names = ['user', 'group', 'lead', 'contact', 'company', 'customer',
                     'transaction', 'task', 'note', 'pipeline']

    debug_level = 5
    base_url = 'https://{}.amocrm.ru/api/v2/'
    login_url = 'https://{}.amocrm.ru/private/api/auth.php?type=json'
    _state_attributes = ['cookies']

    def __init__(self, login, hash, domain, **kwargs):
        self.login, self.hash, self.domain = login, hash, domain
        self.base_url = self.base_url.format(domain)
        self.login_url = self.login_url.format(domain)

        # Binding models to client and creating client.get_*_iterator
        self.models = {}
        for model_name in self.__model_names:
            model = self.models[model_name] = self._bind_model(model_name)
            if hasattr(self, 'get_%s' % model.model_plural_name):
                self._bind_get_objects_iterator('get_%s' % model.model_plural_name)

        super().__init__(**kwargs)

    def _bind_model(self, model_name):
        model = deepcopy(getattr(self, model_name, getattr(models, model_name.capitalize())))
        model._client = self
        setattr(self, model_name, model)
        return model

    def _bind_get_objects_iterator(self, method_name, cursor_count=500):
        # NOTE: because of bad amocrm api design, we have offset instead of real cursor ident,
        # so we can't be sure that we're not skipping some entities if some new
        # were added while iteration is in progress
        method = getattr(self, method_name)

        def iterator(*args, cursor=None, cursor_count=cursor_count, cursor_kwargs={}, **kwargs):
            def fetch(generator):
                resp = method(*args, **kwargs, cursor=generator.cursor, cursor_count=cursor_count)
                generator.has_more = (len(resp.data) >= cursor_count)
                generator.cursor += len(resp.data)
                return resp.data
            return CursorFetchGenerator(cursor=cursor, reverse_iterable=False,
                                        fetch_callback=fetch, **cursor_kwargs)
        setattr(self, '%s_iterator' % method_name, iterator)

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
    def _get_objects(self, model, id=[], params={}, query=None, responsible_user_id=None,
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

        resp = self.get(model.model_plural_name, params, headers=headers)
        if resp.status_code == 204 or '_embedded' not in resp.data:
            # Looks like we get 204 on "not found",
            # and no "_embedded" key if not any object of model exists (even without filter)
            # Got "_embedded" key error on "customers"
            resp.data = []
        else:
            resp.data = resolve_obj_path(resp.data, '_embedded.items')
            resp.data = model.load(resp.data, many=True)
        return resp

    @auth_required
    def _post_objects(self, model, add, update_map, delete_map):
        payload = {
            'add': [obj.dump() for obj in add],
            'update': [obj.dump() for obj in update_map.values()],
            'delete': tuple(delete_map.keys()),
        }
        resp = self.post(model.model_plural_name, data=payload)
        resp.data = resolve_obj_path(resp.data, '_embedded.items') or []
        resp.errors = errors = resp.data.get('errors', {})

        if (
            (len(resp.data) + len(errors.get('update', {})) + len(errors.get('delete', {}))) !=
            (len(add) + len(update_map) + len(delete_map))
        ):
            raise self.ClientError(resp, 'Items count not matched')

        for i, item in enumerate(resp.data):
            if i < len(add):
                # Actually, I wasn't able to get error on add,
                # so it's not obvious how to bind new ids in that case
                assert 'updated_at' not in item
                added = add[i]
                added.id = int(item['id'])
            else:
                updated = update_map[int(item['id'])]

                field = updated.schema.fields['updated_at']
                updated_at = field._deserialize(item['updated_at'], 'updated_at', item)
                if updated.updated_at != updated_at:
                    self.logger.warn('updated_at != %s: %s', updated_at, updated)
                updated.updated_at = updated_at

        for action, obj_map in (('update', update_map), ('delete', delete_map)):
            # Iterating over objs instead of errors to clear previous message if any
            for id, obj in obj_map.items():
                error = errors.get(action, {}).get(str(id))
                if error:
                    self.logger.error('%s failed: "%s" for %s', action, error, obj)
                    obj.meta['%s_error' % action] = error
                else:
                    obj.meta.pop('%s_error' % action, None)
        return resp

    def post_objects(self, add_or_update=[], delete=[], updated_at=True,
                     raise_on_errors=False):
        # add_or_update - add (without obj.id) or update(with obj.id)
        # delete - delete objs
        # updated_at - should renew updated_at field?

        add_or_update_map = defaultdict(lambda: ([], {}))  # add, update
        for obj in add_or_update:
            add, update = add_or_update_map[obj.__class__]
            if obj.id is not None:
                if updated_at:
                    obj.updated_at = datetime.utcnow() if updated_at is True else updated_at

                assert int(obj.id) not in update, 'Duplicated id: %s' % obj.id
                update[int(obj.id)] = obj
            else:
                add.append(obj)

        delete_map = defaultdict(dict)
        for obj in delete:
            assert obj.id is not None
            delete_map[obj._class__][int(obj.id)] = obj

        rv = []
        for model in (set(add_or_update_map.keys()) | set(delete_map.keys())):
            add, update = add_or_update_map[model]
            delete = delete_map[model]
            resp = self._post_objects(model, add, update, delete)
            if raise_on_errors and resp.errors:
                raise PostError(resp, str(resp.errors), model,
                    [obj for obj in update.values() if 'update_error' in obj.meta],
                    [obj for obj in delete.values() if 'delete_error' in obj.meta],
                )
            rv.append(resp)
        return rv

    def get_contacts(self, id=[], query=None, responsible_user_id=None, modified_since=None,
                     cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/contacts

        return self._get_objects(self.contact, id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count
        )

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
        return self._get_objects(self.lead, params, id=id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count
        )

    def get_companies(self, id=[], query=None, responsible_user_id=None,
                      modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/companies

        return self._get_objects(self.company, id=id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count
        )

    def get_customers(self, id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers
        # TODO: filters not implemented

        return self._get_objects(self.customer, id=id,
            cursor=cursor, cursor_count=cursor_count
        )

    def get_transactions(self, id=[], customer_id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers

        params = {
            'customer_id': customer_id and ','.join(map(str, customer_id)) or None
        }
        return self._get_objects(self.transaction, params, id=id,
            cursor=cursor, cursor_count=cursor_count
        )

    def get_tasks(self, id=[], element_id=[], element_type=None,
                  responsible_user_id=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/tasks

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
        }
        return self._get_objects(self.task, params,
            id=id, responsible_user_id=responsible_user_id,
            cursor=cursor, cursor_count=cursor_count
        )

    def get_notes(self, element_type, id=[], element_id=[], note_type=None,
                  modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/notes

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
            'note_type': note_type and NOTE_TYPE(note_type).value or None,
        }
        return self._get_objects(self.note, params, id=id, modified_since=modified_since,
            cursor=cursor, cursor_count=cursor_count
        )

    def get_pipelines(self, id=[]):
        # https://www.amocrm.ru/developers/content/api/pipelines
        # TODO: pipelines can have cursor and cursor_count?

        return self._get_objects(self.pipeline, id=id, cursor_count=None)
