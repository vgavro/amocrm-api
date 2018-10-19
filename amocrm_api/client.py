from copy import deepcopy
from datetime import timezone
from email.utils import format_datetime
from collections import defaultdict
from functools import wraps

from requests_client.client import BaseClient, auth_required
from requests_client.cursor_fetch import CursorFetchIterator
from requests_client.exceptions import HTTPError, AuthError, AuthRequired
from requests_client.utils import resolve_obj_path, utcnow, cached_property

from . import models
from .exceptions import AmocrmClientErrorMixin, PostError
from .constants import LEAD_FILTER_BY_TASKS, ELEMENT_TYPE, NOTE_TYPE, FIELD_TYPE
from .utils import maybe_qs_list


def _get_objects_iterator(func, cursor_count=500):
    # NOTE: because of bad amocrm api design, we have offset instead of real cursor ident,
    # so we can't be sure that we're not skipping some entities if some new
    # were added while iteration is in progress

    @wraps(func)
    def iterator(*args, cursor=None, cursor_count=cursor_count, cursor_kwargs={}, **kwargs):
        def fetch(generator):
            resp = func(*args, **kwargs, cursor=generator.cursor, cursor_count=cursor_count)
            generator.has_more = (len(resp.data) >= cursor_count)
            generator.cursor += len(resp.data)
            return resp.data
        return CursorFetchIterator(fetch, cursor=cursor, **cursor_kwargs)
    return iterator


class AmocrmClient(BaseClient):
    # API DOCS:
    # en https://www.amocrm.com/developers/content/api/auth
    # ru https://www.amocrm.ru/developers/content/api/auth
    # Looks like ru docs always have more info,
    # some fields in en docs not mentioned

    ClientErrorMixin = AmocrmClientErrorMixin
    contact = models.SystemContact  # WIP

    __model_names = ('user', 'group', 'lead', 'contact', 'company', 'customer',
                     'transaction', 'task', 'note', 'pipeline')
    __model_names_ajax_delete = ('contact', 'lead')

    debug_level = 5
    base_url = 'https://{}.amocrm.ru/api/v2/'
    login_url = 'https://{}.amocrm.ru/private/api/auth.php?type=json'
    _state_attributes = ['cookies']

    def __init__(self, login, hash, subdomain, **kwargs):
        self.login, self.hash, self.subdomain = login, hash, subdomain
        self.base_url = self.base_url.format(subdomain)
        self.login_url = self.login_url.format(subdomain)

        # Binding models to client and creating client.get_*_iterator
        self.models = {}
        for model_name in self.__model_names:
            self.bind_model(model_name)

        super().__init__(**kwargs)

    def bind_model(self, model):
        if isinstance(model, str):
            model_name = model
            model = deepcopy(getattr(self, model_name,
                                     getattr(models, model_name.capitalize())))
        else:
            model_name = model.model_name

        model._client = self
        setattr(self, model_name, model)
        self.models[model_name] = model

    @property
    def auth_ident(self):
        return '{}:{}'.format(self.login, self.subdomain)

    @property
    def is_authenticated(self):
        # Note that session_id expires only on server side,
        # so we can't be sure before first request
        return 'session_id' in self.cookies

    def authenticate(self):
        payload = dict(USER_LOGIN=self.login, USER_HASH=self.hash)
        resp = self.post(self.login_url, json=payload)
        if self.is_authenticated:
            self._set_authenticated(data=resp.data)
        return resp

    def _request(self, method, url, params=None, data=None, **kwargs):
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
        resp = self.get('account?with=%s' % ','.join(with_ is None and with__ or with_))
        resp.data.update(resp.data.pop('_embedded'))
        return resp

    def update_account_info(self):
        for key in 'account_info users current_user groups pipelines'.split():
            if key in self.__dict__:
                del self.__dict__[key]
        self.__dict__['account_info'] = self.get_account_info().data

    @cached_property
    def account_info(self):
        return self.get_account_info().data

    @cached_property
    def users(self):
        return {
            int(id): self.user(**data)
            for id, data in self.account_info.users.items()
        }

    @cached_property
    def current_user(self):
        return self.users[self.account_info.current_user]

    @cached_property
    def groups(self):
        return {group['id']: self.group(**group) for group in self.account_info.groups}

    @cached_property
    def pipelines(self):
        return {
            int(id): self.pipeline.load(data)
            for id, data in self.account_info.pipelines.items()
        }

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
    def _ajax_delete_objects(self, model, delete_map):
        # Actually this is fix for models that can't be deleted using
        # standard api interface (for some reason), but obviously should be
        resp = self.post('/ajax/%s/multiple/delete/' % model.model_plural_name,
                         data=list(('ID[]', id) for id in delete_map),
                         headers={'X-Requested-With': 'XMLHttpRequest'})
        if isinstance(delete_map, dict):
            # Allowing delete only by id otherwise
            for obj in delete_map.values():
                if resp.data.status != 'success':
                    obj.meta['error'] = resp.data.message
                else:
                    obj.meta.pop('error', None)
        return resp

    @auth_required
    def _post_objects(self, model, add, update_map, delete_map):
        payload = {
            'add': [obj.dump() for obj in add],
            'update': [obj.dump() for obj in update_map.values()],
            'delete': tuple(delete_map.keys()),
        }
        resp = self.post(model.model_plural_name, json=payload)

        errors = resolve_obj_path(resp.data, '_embedded.errors', {}) or {}
        # Fixing this PHP array shit
        if isinstance(errors, list):
            errors = {'add': errors[0] or {}}
        elif '0' in errors:
            errors['add'] = errors.pop('0')
        errors.setdefault('add', {})
        errors.setdefault('update', {})
        errors.setdefault('delete', {})

        # We should have adding errors as dict with add index binded as keys,
        # and in some enpoints (leads) items[].request_id corresponds to add index,
        # BUT for some endpoints (contacts) we may have adding errors as lists instead
        # and request_id=0 for all added, then we can't determine WHICH entities were ok
        # and which were failed, so we can't bind new id or errors to specific objects,
        # so we should consider all added objects were failed with corresponding message.
        if isinstance(errors['add'], list):
            if len(errors['add']) == len(add):
                errors['add'] = {str(i): err for i, err in enumerate(errors['add'])}
            else:
                errors['add'] = {
                    str(i): 'Maybe not added (possible errors %s)' % set(errors['add'])
                    for i in range(len(add))
                }

        resp.errors = errors
        resp.data = resolve_obj_path(resp.data, '_embedded.items') or []

        if (
            (len(resp.data) + sum(len(errors[k]) for k in errors)) !=
            (len(add) + len(update_map) + len(delete_map))
        ):
            raise self.ClientError(resp, 'Response items count not matched')

        added_idxs = sorted(set(range(len(add))) - set(map(int, errors['add'])))
        for i, item in enumerate(resp.data):
            if added_idxs:
                assert 'updated_at' not in item
                added = add[added_idxs[0]]
                added.id = int(item['id'])
                added_idxs = added_idxs[1:]

            # No updated_at may be in "maybe not added" scenario (see above)
            elif 'updated_at' in item:
                updated = update_map[int(item['id'])]

                field = updated.schema.fields['updated_at']
                updated_at = field._deserialize(item['updated_at'], 'updated_at', item)
                if updated.updated_at and updated.updated_at.replace(microsecond=0) != updated_at:
                    self.logger.warn('updated_at mismatch: %s != %s', updated_at,
                                     updated.updated_at.replace(microsecond=0))
                updated.updated_at = updated_at

        for action, obj_map in (
            ('add', dict(enumerate(add))), ('update', update_map), ('delete', delete_map)
        ):
            # Iterating over objs instead of errors to clear previous message if any
            for id, obj in obj_map.items():
                error = errors.get(action, {}).get(str(id))
                if error:
                    self.logger.error('%s failed: %s "%s" for %s', action, id, error, obj)
                    obj.meta['error'] = error
                else:
                    obj.meta.pop('error', None)
        return resp

    def post_objects(self, add_or_update=[], delete=[], updated_at=True,
                     raise_on_errors=False):
        """
        add_or_update - add (without obj.id) or update(with obj.id)
        delete - delete objs
        updated_at - should renew updated_at field?
        """

        if updated_at:
            if updated_at is True:
                updated_at = utcnow()
            updated_at = updated_at.replace(microsecond=0)

        add_or_update_map = defaultdict(lambda: ([], {}))  # add, update
        for obj in add_or_update:
            add, update = add_or_update_map[obj.__class__]
            if obj.id is not None:
                if updated_at:
                    if not obj.updated_at or obj.updated_at <= updated_at:
                        obj.updated_at = updated_at
                    else:
                        # This will cause error on backend side in case of older updated_at
                        self.logger.warn('Skipping updated_at set: %s already has newer '
                                         '%s > %s', obj.model_name, obj.updated_at, updated_at)

                assert int(obj.id) not in update, 'Duplicated id: %s' % obj.id
                update[int(obj.id)] = obj
            else:
                add.append(obj)

        delete_map = defaultdict(dict)
        for obj in delete:
            assert obj.id is not None
            delete_map[obj.__class__][int(obj.id)] = obj

        rv = []
        for model in (set(add_or_update_map.keys()) | set(delete_map.keys())):
            add, update = add_or_update_map[model]
            delete = delete_map[model]

            if delete and model.model_name in self.__model_names_ajax_delete:
                resp = self._ajax_delete_objects(model, delete)
                if raise_on_errors and resp.data.status != 'success':
                    raise PostError(resp, resp.data.message, delete=tuple(delete.values()))
                rv.append(resp)
                delete = {}
                if not (add or update):
                    continue

            resp = self._post_objects(model, add, update, delete)
            if raise_on_errors and sum(len(v) for v in resp.errors.values()):
                raise PostError(resp, str(resp.errors), model,
                    [obj for obj in add if 'error' in obj.meta],
                    [obj for obj in update.values() if 'error' in obj.meta],
                    [obj for obj in delete.values() if 'error' in obj.meta],
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

    get_contacts_iterator = _get_objects_iterator(get_contacts)

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
        return self._get_objects(self.lead, id, params,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count
        )

    get_leads_iterator = _get_objects_iterator(get_leads)

    def get_companies(self, id=[], query=None, responsible_user_id=None,
                      modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/companies

        return self._get_objects(self.company, id,
            query=query, responsible_user_id=responsible_user_id,
            modified_since=modified_since, cursor=cursor, cursor_count=cursor_count
        )

    get_companies_iterator = _get_objects_iterator(get_companies)

    def get_customers(self, id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers
        # TODO: filters not implemented

        return self._get_objects(self.customer, id,
            cursor=cursor, cursor_count=cursor_count
        )

    get_customers_iterator = _get_objects_iterator(get_customers)

    def get_transactions(self, id=[], customer_id=[], cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/customers

        params = {
            'customer_id': customer_id and ','.join(map(str, customer_id)) or None
        }
        return self._get_objects(self.transaction, id, params,
            cursor=cursor, cursor_count=cursor_count
        )

    get_transactions_iterator = _get_objects_iterator(get_transactions)

    def get_tasks(self, id=[], element_id=[], element_type=None,
                  responsible_user_id=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/tasks

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
        }
        return self._get_objects(self.task, id, params,
            responsible_user_id=responsible_user_id,
            cursor=cursor, cursor_count=cursor_count
        )

    get_tasks_iterator = _get_objects_iterator(get_tasks)

    def get_notes(self, element_type, id=[], element_id=[], note_type=None,
                  modified_since=None, cursor=None, cursor_count=500):
        # https://www.amocrm.ru/developers/content/api/notes

        params = {
            'type': element_type and ELEMENT_TYPE(element_type).name.lower() or None,
            'element_id': element_id and ','.join(map(str, element_id)) or None,
            'note_type': note_type and NOTE_TYPE(note_type).value or None,
        }
        return self._get_objects(self.note, id, params, modified_since=modified_since,
            cursor=cursor, cursor_count=cursor_count
        )

    get_notes_iterator = _get_objects_iterator(get_notes)

    def get_pipelines(self, id=[]):
        # https://www.amocrm.ru/developers/content/api/pipelines
        # TODO: pipelines can have cursor and cursor_count?

        return self._get_objects(self.pipeline, id, cursor_count=None)

    @auth_required
    def post_custom_fields(self, add=[], delete=[]):
        # We got PostError even only if one field failed

        payload = {'add': [], 'delete': []}
        for field in add:
            payload['add'].append({
                'name': field.metadata['name'],
                'field_type': FIELD_TYPE(field.field_type).value,
                'element_type': ELEMENT_TYPE(field.metadata['element_type']).value,
                'origin': field.metadata.get('origin', self.subdomain),
                'enums': field.metadata.get('enums'),
                'is_deletable': field.metadata.get('is_deleteble', False),
                'is_visible': field.metadata.get('is_visible', True)
            })
        for field in delete:
            payload['delete'].append({
                'id': field.metadata['id'],
                'origin': field.metadata.get('origin', self.subdomain)
            })

        try:
            resp = self.post('fields', json=payload)
        except HTTPError as exc:
            # We get an HTTPError even if only one field failed,
            # if field was failed on add, delete will not be processed
            raise PostError(exc.resp, exc.get_data('detail') or 'UNKNOWN ERROR',
                            'custom_field', add=add, delete=delete)

        resp.data = resolve_obj_path(resp.data, '_embedded.items') or []
        if len(resp.data) != len(add):
            raise self.ClientError(resp, 'Response fields count not matched')

        for i, item in enumerate(resp.data):
            add[i].metadata['id'] = item['id']

        return resp
