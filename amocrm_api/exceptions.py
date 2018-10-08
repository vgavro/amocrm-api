from requests_client.exceptions import ClientError


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


class PostError(AmocrmClientErrorMixin, ClientError):
    def __init__(self, resp, msg, model, add=[], update=[], delete=[]):
        model = model if isinstance(model, str) else model.object_name
        self.model = model
        self.add = add
        self.update = update
        self.delete = delete
        super().__init__(resp, msg, model, update, delete)
