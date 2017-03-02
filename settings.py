import os
import logging
import tornado.template
from tornado.options import define, options
from jinja2 import Environment, FileSystemLoader


def location(x):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), x)

define('port', default=8000, help='run on the given port', type=int)
define('config', default=None, help='tornado config file')
define('debug', default=False, help='debug mode')
define('server_delay', default=2.0)
define('client_delay', default=1.0)
define('num_chunks', default=40)

tornado.options.parse_command_line()

STATIC_ROOT = location('static')
TEMPLATE_ROOT = location('templates')

# deployment configuration

settings = {
    'debug': options.debug,
    'static_path': STATIC_ROOT,
    'cookie_secret': '2404salt',
    'cookie_expires': 30,  # number of days
    'xsrf_cookies': True,
    'login_url': '/login/',
}

# jinja settings

jinja_settings = {
    'autoescape': True,
    'extensions': [
        'jinja2.ext.with_'
    ],
}
jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_ROOT), **jinja_settings)

# mongo settings

mongo_settings = {
    'host': '127.0.0.1',
    'port': 27017,
    'db_name': 'adsw_app',
    'reconnect_tries': 5,
    'reconnect_timeout': 2  # number of seconds
}

# see PEP 391 and logconfig for formatting help.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'main_formatter': {
            'format': '%(levelname)s:%(name)s: %(message)s '
                      '(%(asctime)s; %(filename)s:%(lineno)d)',
            'datefmt': "%Y-%m-%d %H:%M:%S",
        },
    },
    'handlers': {
        'rotate_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': location('logs/main.log'),
            'when': 'midnight',
            'interval': 1,  # day
            'backupCount': 7,
            'formatter': 'main_formatter',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'main_formatter',
            # 'filters': ['require_local_true'],
        },
    },
    'loggers': {
        '': {
            'handlers': ['rotate_file', 'console'],
            'level': 'DEBUG',
        }
    }
}

logging.basicConfig(**LOGGING)

if options.config:
    tornado.options.parse_config_file(options.config)

MB = 1024 * 1024
GB = 1024 * MB
TR = 1024 * GB

MAX_BUFFER_SIZE = 1 * MB
MAX_BODY_SIZE = 1 * MB
