# -*- coding: utf-8 -*-
"""Password processing mostly taken from
https://github.com/hmarr/mongoengine/blob/master/mongoengine/django/auth.py
"""
from django.utils.encoding import smart_str

try:
    from hashlib import sha1 as sha_constructor
except ImportError:
    from django.utils.hashcompat import sha_constructor


def get_hexdigest(salt, raw_password):
    raw_password, salt = smart_str(raw_password), smart_str(salt)
    raw_str = (salt + raw_password).encode('utf-8')
    return sha_constructor(raw_str).hexdigest()


def check_password(raw_password, password):
    salt, hash_ = password.split('$')
    return hash_ == get_hexdigest(salt, raw_password)


def make_password(raw_password):
    from random import random
    salt = get_hexdigest(str(random()), str(random()))[:5]
    hash_ = get_hexdigest(salt, raw_password)
    return '%s$%s' % (salt, hash_)
