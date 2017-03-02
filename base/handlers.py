import logging
import json
from tornado import web
from auth.models import UserModel

from settings import jinja_env

logger = logging.getLogger(__name__)


class BaseHandler(web.RequestHandler):
    def __init__(self, *args, **kwargs):
        super(BaseHandler, self).__init__(*args, **kwargs)
        self.db = self.settings['db']
        self.template_name = None
        self.model = None
        self.context = {}
        self.current_user_object = None

        curr_user = self.get_current_user()
        if curr_user:
            curr_user_email = curr_user.decode('utf-8')
            if not self.application.mc.get(curr_user_email):
                self.application.mc[curr_user_email] = {}

    def check_xsrf_cookie(self):
        if self.is_ajax:
            return
        else:
            super().check_xsrf_cookie()

    def set_current_user(self, user):
        if user:
            self.set_secure_cookie('user', user)
        else:
            self.clear_cookie('user')

    def get_current_user(self):
        expire = self.settings.get('cookie_expires', 31)
        return self.get_secure_cookie('user', max_age_days=expire)

    def get_login_url(self):
        return self.reverse_url('signin')

    async def get_current_user_object(self):
        email = self.current_user
        if email:
            # TODO cache
            user = await UserModel.find_one(self.db, {'email': email.decode('utf-8')})
        else:
            user = None

        self.current_user_object = user
        return user

    @property
    def is_ajax(self):
        request_x = self.request.headers.get('X-Requested-With')
        return request_x == 'XMLHttpRequest'

    def session_get(self, key):
        curr_user = self.get_current_user().decode('utf-8')
        return self.application.mc[curr_user].get(key, None)

    def session_set(self, key, value):
        curr_user = self.get_current_user().decode('utf-8')
        d = self.application.mc.get(curr_user)
        d[key] = value
        self.application.mc.set(curr_user, d)

    def render_json(self, data):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(data))
        self.finish()

    def data_received(self, chunk):
        pass

    def add_additional_context(self, additional_context):
        self.context.update(additional_context)

    def render_template(self, template_name):
        # render template using jinja2
        self.context.update(self.get_template_namespace())
        return jinja_env.get_template(template_name).render(self.context)

    def render(self, template_name, context=None):
        self.write(self.render_template(template_name))
        # set xsrf token
        self.xsrf_token
        self.flush()
        self.finish()

    async def update_context(self):
        pass

    async def get(self, *args, **kwargs):
        await self.update_context()
        self.render(self.template_name, self.context)


class AuthHandler(BaseHandler):
    def __init__(self, *args, **kwargs):
        super(AuthHandler, self).__init__(*args, **kwargs)

    @web.authenticated
    async def get(self, *args, **kwargs):
        await super().get(*args, **kwargs)

    async def update_context(self):
        user_object = await self.get_current_user_object()
        self.add_additional_context({'user_object': user_object})


class ListHandler(AuthHandler):
    def __init__(self, *args, **kwargs):
        super(ListHandler, self).__init__(*args, **kwargs)
        self.object_list = None

    @property
    def get_query(self):
        return {}

    @property
    def get_fields(self):
        return {}

    @property
    def get_sort_fields(self):
        return {}

    async def get_object_list(self, page=1):
        cursor = self.model.get_cursor(self.db, query=self.get_query,
                                       fields=self.get_fields,
                                       sort_fields=self.get_sort_fields)

        if page > 1:
            cursor.skip(page - self.model.get_list_len())

        self.object_list = await self.model.find(cursor)

    async def update_context(self):
        await super().update_context()
        page = self.get_argument('page', 1)
        await self.get_object_list(page)
        self.add_additional_context({'page': page, 'object_list': self.object_list})


class DetailHandler(AuthHandler):
    def __init__(self, *args, **kwargs):
        super(DetailHandler, self).__init__(*args, **kwargs)
        self.obj = None

    async def get_object(self):
        obj_id = self.path_kwargs['object_id']
        self.obj = await self.model.find_one(self.db, {'_id': obj_id})

    async def update_context(self):
        await super().update_context()
        await self.get_object()
        self.add_additional_context({'object': self.obj})
