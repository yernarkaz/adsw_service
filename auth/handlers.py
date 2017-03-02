from base.handlers import BaseHandler
from auth.forms import LoginForm, RegistrationForm
from auth.models import UserModel
from pymongo.errors import DuplicateKeyError


class AuthMixin(object):
    def post_success(self):
        self.redirect(self.reverse_url('dashboard'))

    def post_failed(self, form):
        self.add_additional_context({'form': form})
        self.render(self.template_name, self.context)


class LoginHandler(BaseHandler, AuthMixin):
    def __init__(self, *args, **kwargs):
        super(LoginHandler, self).__init__(*args, **kwargs)
        self.template_name = './auth/signin.html'

    async def update_context(self):
        form = LoginForm()
        self.add_additional_context({'form': form})

    async def post(self):
        form = LoginForm(self.request.arguments)
        if form.validate():
            usr = await UserModel.find_one(self.db, {'email': form.email.data})
            if usr:
                if usr.check_password(form.password.data):
                    self.set_current_user(usr.email)
                    self.post_success()
                    return
                else:
                    form.set_nonfield_error('wrong_password')
            else:
                form.set_nonfield_error('not_found')
        self.post_failed(form)


class RegisterHandler(BaseHandler, AuthMixin):
    def __init__(self, *args, **kwargs):
        super(RegisterHandler, self).__init__(*args, **kwargs)
        self.template_name = './auth/signup.html'

    async def update_context(self):
        form = RegistrationForm()
        self.add_additional_context({'form': form})

    async def post(self):
        form = RegistrationForm(self.request.arguments)
        if form.validate():
            usr = form.get_object()
            usr.set_password(usr.password)
            try:
                await usr.insert(self.db)
            except DuplicateKeyError:
                form.set_field_error('email', 'email_occupied')
            else:
                # user save succeeded
                self.set_current_user(usr.email)
                self.post_success()
                return
        self.post_failed(form)


class LogoutHandler(BaseHandler):
    async def get(self, *args, **kwargs):
        self.set_current_user(None)
        self.redirect(self.reverse_url('signin'))
