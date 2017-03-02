from base.forms import BaseForm, ModelForm
from wtforms import StringField, PasswordField, validators
from wtforms.validators import ValidationError
from auth.models import UserModel


class RegistrationForm(ModelForm):
    name = StringField('Your name', [validators.InputRequired()])
    email = StringField('Email address', [validators.InputRequired()])
    password = PasswordField('Password', [validators.InputRequired()])
    password2 = PasswordField('Confirm password', [validators.InputRequired()])

    _model = UserModel

    text_errors = {
        'password_mismatch': 'Password mismatch',
        'email_occupied': 'Already taken, sorry'
    }

    def validate_password2(self, value):
        print(self.password.data, value)
        if self.password.data != value.data:
            raise ValidationError(self.text_errors['password_mismatch'])


class LoginForm(BaseForm):
    email = StringField('Email address', [validators.InputRequired()])
    password = PasswordField('Password', [validators.InputRequired()])

    text_errors = {
        'not found': 'Email and password mismatch',
        'wrong_password': 'Email and password mismatch'
    }
