from tornado.web import url
from service.handlers import DashboardHandler, WorkflowsHandler, WorkflowDetailHandler
from service.handlers import DataSourcesHandler, DataSourceDetailHandler
from service.handlers import DataSourceSelectHandler, DataPreprocessingFormHandler
from service.handlers import DataModelFormHandler, DataFinishFormHandler
from service.handlers import DataSourceUploadHandler, DataSourceCheckHandler
from auth.handlers import LoginHandler, RegisterHandler, LogoutHandler


url_patterns = [
    # auth
    url(r'/signin', LoginHandler, name='signin'),
    url(r'/signup', RegisterHandler, name='signup'),
    url(r'/signout', LogoutHandler, name='signout'),

    # dashboard & workflow
    url(r'/', DashboardHandler, name='dashboard'),
    url(r'/workflows', WorkflowsHandler, name='workflows'),
    url(r'/workflow/(?P<object_id>[0-9a-z-]+)', WorkflowDetailHandler, name='workflow-detail'),
    url(r'/datasources', DataSourcesHandler, name='datasources'),
    url(r'/datasources/(?P<object_id>[0-9a-z-]+)', DataSourceDetailHandler, name='datasource-detail'),
    url(r'/datasource/check', DataSourceCheckHandler, name='datasource-check'),
    url(r'/upload', DataSourceUploadHandler, name='datasource-upload'),

    # form
    url(r'/workflow/new/step1', DataSourceSelectHandler, name='workflow-new-step1'),
    url(r'/workflow/new/step2', DataPreprocessingFormHandler, name='workflow-new-step2'),
    url(r'/workflow/new/step3', DataModelFormHandler, name='workflow-new-step3'),
    url(r'/workflow/new/finish', DataFinishFormHandler, name='workflow-new-finish'),
]
