#coding=utf-8

import logging
import uuid
from functools import wraps
import multiprocessing

from pymongo.errors import PyMongoError
from tornado import web
from tornado.platform.asyncio import to_tornado_future
from concurrent.futures import ThreadPoolExecutor
from base.handlers import AuthHandler, ListHandler, DetailHandler
from service.models import WorkflowModel, DataSourceModel

import pandas as pd
import numpy as np
import operator

import pickle
import datetime

l = logging.getLogger(__name__)


def blocking(method):
    """Wraps the method in an async method, and executes the function on `self.executor`."""
    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        future = self.executor.submit(method, self, *args, **kwargs)
        return await to_tornado_future(future)
    return wrapper


class DashboardHandler(ListHandler):
    def __init__(self, *args, **kwargs):
        super(DashboardHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/dashboard.html'
        self.model = WorkflowModel
        self.add_additional_context({'content_title': 'Dashboard'})

    async def update_context(self):
        await super().update_context()

        cursor = WorkflowModel.get_cursor(self.db, query={'state': 'processed'}, **{})
        workflow_list = await WorkflowModel.find(cursor)

        cursor = WorkflowModel.get_cursor(self.db, query={'state': 'new'}, **{})
        new_workflow_list = await WorkflowModel.find(cursor)

        cursor = WorkflowModel.get_cursor(self.db, query={'state': 'processing'}, **{})
        processing_workflow_list = await WorkflowModel.find(cursor)

        cursor = DataSourceModel.get_cursor(self.db, {}, **{})
        datasource_list = await DataSourceModel.find(cursor)

        self.add_additional_context({
            'workflows_count': len(workflow_list),
            'workflows_processing_count': len(processing_workflow_list),
            'workflows_new_count': len(new_workflow_list),
            'datasources_count': len(datasource_list)
        })


class WorkflowsHandler(ListHandler):
    def __init__(self, *args, **kwargs):
        super(WorkflowsHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/workflows.html'
        self.model = WorkflowModel
        self.add_additional_context({'content_title': 'Workflows'})

    @property
    def get_query(self):
        return {'$or': [{'state': 'processed'}, {'state': 'processing'}]}


class WorkflowDetailHandler(DetailHandler):
    def __init__(self, *args, **kwargs):
        super(WorkflowDetailHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/workflow-detail.html'
        self.model = WorkflowModel

    async def update_context(self):
        await super().update_context()
        self.add_additional_context({'content_title': self.obj.name})


class DataSourcesHandler(ListHandler):
    def __init__(self, *args, **kwargs):
        super(DataSourcesHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/data-sources.html'
        self.model = DataSourceModel
        self.add_additional_context({'content_title': 'Data Sources'})

    @property
    def get_sort_fields(self):
        return {'uploaded_at': 1}


class DataSourceDetailHandler(DetailHandler):
    def __init__(self, *args, **kwargs):
        super(DataSourceDetailHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/data-source-detail.html'
        self.model = DataSourceModel

    async def update_context(self):
        await super().update_context()
        self.add_additional_context(({
            'content_title': 'Data Source Information: {}'.format(self.obj.file_name),
            'sorted_list': sorted(self.obj.predictor_details, key=lambda x: x['order'])
        }))


class BaseFormHandler(AuthHandler):
    def __init__(self, *args, **kwargs):
        super(BaseFormHandler, self).__init__(*args, **kwargs)


class DataSourceSelectHandler(BaseFormHandler):
    def __init__(self, *args, **kwargs):
        super(DataSourceSelectHandler, self).__init__(*args, **kwargs)
        self.template_name = './forms/workflow-form-step1.html'
        self.model = DataSourceModel
        self.add_additional_context({'content_title': 'Setup workflow'})

        if not self.session_get('steps_done'):
            self.session_set('steps_done', set())

        steps_done = self.session_get('steps_done')
        steps_done.add(1)
        self.session_set('steps_done', steps_done)

    async def update_context(self, workflow):
        await super().update_context()

        cursor = DataSourceModel.get_cursor(self.db, {})
        object_list = await DataSourceModel.find(cursor)

        self.add_additional_context({
            'next_step_url': self.reverse_url('workflow-new-step2'),
            'step': 1,
            'steps_done': self.session_get('steps_done'),
            'object_list': object_list,
            'workflow': workflow
        })

    async def get_workflow(self):
        if not self.session_get('curr_workflow_id'):
            workflow = await WorkflowModel.find_one(self.db, {'state': 'new'})
            if not workflow:
                workflow = WorkflowModel({'_id': uuid.uuid4()})
                await workflow.insert(self.db)
            self.session_set('curr_workflow_id', str(workflow._id))
        else:
            workflow = await WorkflowModel.find_one(
                self.db,
                {'_id': self.session_get('curr_workflow_id'), 'state': 'new'})
            if not workflow:
                workflow = WorkflowModel({'_id': uuid.uuid4()})
                await workflow.insert(self.db)
            self.session_set('curr_workflow_id', str(workflow._id))

        return workflow

    @web.authenticated
    async def get(self, *args, **kwargs):
        workflow = await self.get_workflow()
        await self.update_context(workflow)
        self.render(self.template_name, self.context)

    @web.authenticated
    async def post(self, *args, **kwargs):
        datasource_id = self.get_argument('datasource_id')
        datasource = await self.model.find_one(self.db, {'_id': datasource_id})

        workflow_id = self.session_get('curr_workflow_id')
        workflow = await WorkflowModel.find_one(self.db, {'_id': workflow_id})
        workflow.training_data = {
            '_id': datasource._id,
            'file_path': datasource.file_path
        }

        result = await workflow.update(self.db, query={'_id': workflow_id})
        self.render_json({'result': result})


class DataPreprocessingFormHandler(BaseFormHandler):
    def __init__(self, *args, **kwargs):
        super(DataPreprocessingFormHandler, self).__init__(*args, **kwargs)
        self.template_name = './forms/workflow-form-step2.html'
        self.model = WorkflowModel
        steps_done = self.session_get('steps_done')
        steps_done.add(2)
        self.session_set('steps_done', steps_done)

    async def update_context(self):
        await super().update_context()

        workflow_id = self.session_get('curr_workflow_id')
        workflow = await self.model.find_one(self.db, {'_id': workflow_id})

        self.add_additional_context({
            'next_step_url': self.reverse_url('workflow-new-step3'),
            'prev_step_url': self.reverse_url('workflow-new-step1'),
            'step': 2,
            'steps_done': self.session_get('steps_done'),
            'workflow': workflow
        })

    # async def get(self, *args, **kwargs):
    #     pass

    @web.authenticated
    async def post(self, *args, **kwargs):
        prep = self.get_argument('prep')
        checked = self.get_argument('checked')

        workflow_id = self.session_get('curr_workflow_id')
        workflow = await self.model.find_one(self.db, {'_id': workflow_id})
        preprocessing = set(workflow.preprocessing)

        if checked == 'true':
            preprocessing.add(prep)
        else:
            preprocessing.remove(prep)

        workflow.preprocessing = list(preprocessing)

        result = await workflow.update(self.db, query={'_id': workflow_id})
        self.render_json({'result': result})


class DataModelFormHandler(BaseFormHandler):
    def __init__(self, *args, **kwargs):
        super(DataModelFormHandler, self).__init__(*args, **kwargs)
        self.template_name = './forms/workflow-form-step3.html'
        self.model = WorkflowModel

        steps_done = self.session_get('steps_done')
        steps_done.add(3)
        self.session_set('steps_done', steps_done)

    async def update_context(self):
        await super().update_context()

        workflow_id = self.session_get('curr_workflow_id')
        workflow = await self.model.find_one(self.db, {'_id': workflow_id})

        datasource = await DataSourceModel.find_one(self.db, {'_id': str(workflow.training_data['_id'])})

        cursor = DataSourceModel.get_cursor(self.db, {})
        object_list = await DataSourceModel.find(cursor)

        self.add_additional_context({
            'finish_step_url': self.reverse_url('workflow-new-finish'),
            'prev_step_url': self.reverse_url('workflow-new-step2'),
            'step': 3,
            'steps_done': self.session_get('steps_done'),
            'object_list': object_list,
            'workflow': workflow,
            'predictor_target_name': datasource.predictor_target_name,
            'predictor_list': datasource.predictor_values
        })

    @web.authenticated
    async def post(self, *args, **kwargs):
        post_type = self.get_argument('post_type')

        workflow_id = self.session_get('curr_workflow_id')
        workflow = await self.model.find_one(self.db, {'_id': workflow_id})

        if post_type == 'validation':
            validation_type_split = self.get_argument('validation_type').split('_')
            val_type = validation_type_split[0]
            val = validation_type_split[1]

            # if val_type == 'file':
            #     val = uuid.UUID(val)

            workflow.validation = {'type': val_type, 'value': val}
        elif post_type == 'class':
            datasource_id = str(workflow.training_data['_id'])
            datasource = await DataSourceModel.find_one(self.db, {'_id': datasource_id})
            datasource.predictor_target_name = self.get_argument('class_value')
            await datasource.update(self.db, query={'_id': datasource_id})
        else:
            model = self.get_argument('model')
            checked = bool(self.get_argument('checked'))

            model_processing = workflow.model_processing

            if model_processing.get('type') == post_type:
                models = model_processing.get('models', None)
                if not models:
                    models = set()
                else:
                    models = set(models)

                if checked:
                    models.add(model)
                else:
                    models.remove(model)

                model_processing['models'] = list(models)
            else:
                model_processing['type'] = post_type
                model_processing['models'] = [model]

            workflow.model_processing = model_processing

        result = await workflow.update(self.db, query={'_id': workflow_id})
        self.render_json({'result': result})


class DataFinishFormHandler(BaseFormHandler):
    def __init__(self, *args, **kwargs):
        super(DataFinishFormHandler, self).__init__(*args, **kwargs)
        self.model = WorkflowModel
        self.executor = ThreadPoolExecutor(multiprocessing.cpu_count())
        self.heuristics = {
            'max_num_samples': 100000,
            'max_num_features': 20
        }

    async def update_context(self):
        await super().update_context()

    @web.authenticated
    async def get(self, *args, **kwargs):
        workflow_id = self.session_get('curr_workflow_id')
        workflow = await self.model.find_one(self.db, {'_id': workflow_id})

        datasource_id = str(workflow.training_data['_id'])
        datasource = await DataSourceModel.find_one(self.db, {'_id': datasource_id})

        workflow.state = 'processing'
        workflow.name = datasource.file_name
        result = await workflow.update(self.db, query={'_id': workflow_id})
        print(result)

        self.redirect(self.reverse_url('workflows'))

        dataset = await self.process_workflow(workflow, datasource, self.process_workflow_finished)
        if dataset is not None:
            workflow.processing_started_at = datetime.datetime.now()
            await workflow.update(self.db, query={'_id': str(workflow._id)})

            if len(workflow.preprocessing) > 0:
                print('=== dataset shape before preprocessing', dataset.columns, dataset.shape)
                dataset, y = await self.preprocess_data(workflow, datasource, dataset)

                print('=== dataset shape after preprocessing', dataset.columns, dataset.shape)
                trained_models, model_processing_type, model_processing_detail \
                    = await self.train_models(workflow, datasource, dataset, y)
                result = await workflow.update(self.db, query={'_id': workflow_id})
                print(result)

                workflow = await self.validate_models(workflow, trained_models, y,
                                                      model_processing_type, model_processing_detail)

                workflow_name = datasource.file_name
                if model_processing_type == 'supervised':
                    if 'binary' in model_processing_detail:
                        workflow_name += ': binary classification task'
                    elif 'multi' in model_processing_detail:
                        workflow_name += ': multilabel classification task'
                    else:
                        workflow_name += ': regression task'
                else:
                    workflow_name += ': unsupervised learning'
                workflow.name = workflow_name

                result = await workflow.update(self.db, query={'_id': workflow_id})
                print(result)
                await self.process_workflow_finished(workflow)
            else:
                pass
                # self.train_validate(workflow, datasource, dataset, y)
        else:
            raise Exception()

    async def process_workflow_finished(self, workflow):
        print('process workflow has finished')
        workflow.state = 'processed'
        workflow.processing_ended_at = datetime.datetime.now()
        await workflow.update(self.db, query={'_id': str(workflow._id)})

    @blocking
    def process_workflow(self, workflow, datasource, callback):
        print('=== start processing workflow ===')

        processing_type = workflow.model_processing.get('type')

        dataset = None
        series = None
        usecols = [0]
        skiprows = None

        if processing_type == 'supervised':
            if datasource.predictor_target_name:
                usecols = [datasource.predictor_target_name]

        if datasource.content_type == 'text/csv' or datasource.content_type == 'text/plain':
            series = pd.read_csv(datasource.file_path, sep=datasource.file_sep, usecols=usecols)
        elif datasource.content_type == 'text/json':
            pass

        if len(series.index) > self.heuristics.get('max_num_samples'):
            from sklearn.model_selection import StratifiedShuffleSplit

            y = None

            if processing_type == 'supervised':
                from sklearn.preprocessing import LabelEncoder

                le = LabelEncoder()
                le.fit(series)
                y = le.transform(series)

            skf = StratifiedShuffleSplit(n_splits=1,
                                         train_size=self.heuristics.get('max_num_samples') / series.size)

            splits = skf.split(y, y) if y else skf.split(series, series)

            for index, index_test in splits:
                skiprows = index_test
                skiprows = np.sort(skiprows)
                skiprows = np.delete(skiprows, 0)

        if datasource.content_type == 'text/csv' or datasource.content_type == 'text/plain':
            dataset = pd.read_csv(datasource.file_path,
                                  sep=datasource.file_sep,
                                  skiprows=skiprows)
        elif datasource.content_type == 'text/json':
            pass

        return dataset

    def filter_predictors(self, datasource, feature_type):
        predictors = set()
        for p in datasource.predictor_details:
            if p.get('name') not in datasource.predictor_ids \
                    and p.get('name') != datasource.predictor_target_name:
                if feature_type == 'missing' and p.get('missing_values') > 0.:
                    predictors.add(p.get('name'))
                elif feature_type == 'continuous' \
                    and p.get('predictor_type').get('description', None) == 'continuous':
                    predictors.add(p.get('name'))
                elif feature_type == 'nominal' and p.get('predictor_type').get('name', None) == 'nominal':
                    predictors.add(p.get('name'))

        return predictors

    @blocking
    def preprocess_data(self, workflow, datasource, dataset):
        print('=== start preprocessing data', workflow.preprocessing)

        continuous_predictors = set()
        y = None

        if len(datasource.predictor_ids) > 0:
            dataset = dataset.drop(datasource.predictor_ids, axis=1)

        print(datasource.predictor_target_name)
        if datasource.predictor_target_name:
            y = dataset[datasource.predictor_target_name]
            dataset = dataset.drop(datasource.predictor_target_name, axis=1)

        processing_type = workflow.model_processing.get('type')

        if datasource.missing_values > 0.:
            missing_predictors = self.filter_predictors(datasource, 'missing')
            print('=== missing predictors : ', missing_predictors)

            if len(missing_predictors) > 0:
                from service.models import DataFrameImputer
                imputer = DataFrameImputer()
                features = list(missing_predictors)
                imputed = imputer.fit(dataset[features])\
                    .transform(dataset[features])

                dataset = dataset.drop(features, axis=1)
                dataset = pd.concat([dataset, imputed], axis=1)
                print(dataset.head())
                del imputed
                del imputer

        if 'discrete' in workflow.preprocessing and processing_type == 'supervised':

            continuous_predictors = self.filter_predictors(datasource, 'continuous')
            print('=== continuous predictors : ', continuous_predictors)

            if len(continuous_predictors) > 0:
                from service.vendors.MDLP import MDLP_Discretizer
                features = list(continuous_predictors)
                discretizer = MDLP_Discretizer(dataset[features], y, features)
                dataset = dataset.drop(features, axis=1)
                dataset = pd.concat([dataset, discretizer.dataset], axis=1)
                print(dataset.head())
                del discretizer

        if 'onehot' in workflow.preprocessing:
            nominal_predictors = self.filter_predictors(datasource, 'nominal')
            print('=== nominal predictors : ', nominal_predictors, continuous_predictors)

            if len(nominal_predictors) > 0 or len(continuous_predictors) > 0:
                nominal_predictors = nominal_predictors.union(continuous_predictors)
                dummies = pd.get_dummies(dataset[list(nominal_predictors)], drop_first=True)
                dataset = dataset.drop(list(nominal_predictors), axis=1)
                dataset = pd.concat([dataset, dummies], axis=1)
                print(dataset.head())
                del dummies
        else:
            nominal_predictors = self.filter_predictors(datasource, 'nominal')
            if len(nominal_predictors) > 0 or len(continuous_predictors) > 0:
                nominal_predictors = nominal_predictors.union(continuous_predictors)
                print('=== nominal predictors : ', nominal_predictors, continuous_predictors)

                from sklearn.preprocessing import LabelEncoder
                for p in nominal_predictors:
                    le = LabelEncoder()
                    le.fit(dataset[p])
                    dataset[p] = le.transform(dataset[p])
                    # del le
                print(dataset.head())

        if 'fi' in workflow.preprocessing and processing_type == 'supervised':
            print('=== start selecting features')
            from service.models import FasterRelief

            fs = FasterRelief(n_neighbors=100, n_features_to_keep=self.heuristics.get('max_num_features'))
            fs.fit(dataset.values, y.values)
            dataset = dataset[fs.top_features[:self.heuristics.get('max_num_features')]]
            print(dataset.head())
            del fs

        if 'od' in workflow.preprocessing:
            print('=== start detecting outliers')
            from sklearn.ensemble import IsolationForest

            iforest = IsolationForest(max_samples=dataset.shape[0], contamination=.25, n_jobs=-1)
            iforest.fit(dataset)
            y_pred = iforest.predict(dataset)

            dataset = dataset.ix[y_pred == 1, :]
            if y is not None:
                y = y.ix[y_pred == 1]
            del iforest

        dataset.to_csv(datasource.file_path + '_preprocessed', index=False)
        return dataset, y

    @blocking
    def train_models(self, workflow, datasource, dataset, y=None, test_dataset=None):

        print('start training models')

        trained_models = dict()
        model_processing_type = workflow.model_processing.get('type')
        processing_models = workflow.model_processing.get('models')
        validation_type = workflow.validation.get('type')
        validation_value = workflow.validation.get('value')

        print(model_processing_type, processing_models, validation_type, validation_value)

        if model_processing_type == 'supervised':

            y_predictor = None

            for p in datasource.predictor_details:
                if p.get('name') == datasource.predictor_target_name:
                    y_predictor = p
                    break

            if y_predictor.get('predictor_type').get('description', None) == 'continuous':
                model_processing_detail = 'regression'
            else:
                y_value_counts = y.value_counts()
                if len(y_value_counts) > 2:
                    model_processing_detail = 'classification_multi'
                else:
                    model_processing_detail = 'classification_binary'

            print(model_processing_detail)

            from sklearn.preprocessing import LabelEncoder
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)

            if validation_type == 'fold':
                from sklearn.model_selection import cross_val_predict
                from sklearn.model_selection import StratifiedKFold
                skf = StratifiedKFold(n_splits=validation_value)

            if 'rlist' in processing_models and 'classification' in model_processing_detail:
                pass

            if 'xgb' in processing_models:

                objective = 'binary:logistic' \
                if 'binary' in model_processing_detail else 'multi:softprob'
                n_estimators = 20
                silent = 1
                subsample = .7
                colsample_bytree = .7
                learning_rate = .1
                max_depth = 7
                min_child_weight = 2

                if 'classification' in model_processing_detail:
                    from xgboost import XGBClassifier
                    xgb = XGBClassifier(
                        n_estimators=n_estimators,
                        objective=objective,
                        silent=silent,
                        subsample=subsample,
                        colsample_bytree=colsample_bytree,
                        learning_rate=learning_rate,
                        max_depth=max_depth,
                        min_child_weight=min_child_weight
                    )
                else:
                    from xgboost import XGBRegressor
                    xgb = XGBRegressor(
                        n_estimators=n_estimators,
                        objective=objective,
                        silent=silent,
                        subsample=subsample,
                        colsample_bytree=colsample_bytree,
                        learning_rate=learning_rate,
                        max_depth=max_depth,
                        min_child_weight=min_child_weight
                    )

                if validation_type == 'fold':
                    y_pred = cross_val_predict(xgb, dataset.values, y_encoded,
                                               cv=skf, n_jobs=-1, verbose=9)
                    xgb.fit(dataset.values, y_encoded)
                    from settings import location
                    import xgbfir
                    workflow.fi_booster = location('workflow_data') + '/' + str(workflow._id) + '_fi.xlsx'
                    print('save xgbfi', xgb._Booster, workflow.fi_booster)
                    xgbfir.saveXgbFI(xgb._Booster, OutputXlsxFile=workflow.fi_booster)
                else:
                    pass
                    # knn.fit(X, y)
                    # y_pred = knn.predict(test_dataset.values) \
                    #     if 'binary' in model_processing_detail \
                    #     else knn.predict_proba(test_dataset.values)

                trained_models['xgb'] = y_pred

            if 'frlp' in processing_models:
                pass

            if 'knn' in processing_models:
                if 'classification' in model_processing_detail:
                    from sklearn.neighbors import KNeighborsClassifier
                    knn = KNeighborsClassifier(n_neighbors=5, algorithm='auto', n_jobs=-1)
                else:
                    from sklearn.neighbors import KNeighborsRegressor
                    knn = KNeighborsRegressor(n_neighbors=5, algorithm='auto', n_jobs=-1)

                from sklearn import preprocessing
                X = preprocessing.scale(dataset)

                if validation_type == 'fold':
                    y_pred = cross_val_predict(knn, X, y_encoded,
                                               cv=skf, n_jobs=-1, verbose=9)
                else:
                    pass
                    # knn.fit(X, y)
                    # y_pred = knn.predict(test_dataset.values) \
                    #     if 'binary' in model_processing_detail \
                    #     else knn.predict_proba(test_dataset.values)

                trained_models['knn'] = y_pred
                del X

            if 'lr' in processing_models:
                '''
                solver : {‘newton-cg’, ‘lbfgs’, ‘liblinear’, ‘sag’}

                Algorithm to use in the optimization problem.
                For small datasets, ‘liblinear’ is a good choice, whereas ‘sag’ is
                faster for large ones.

                For multiclass problems, only ‘newton-cg’, ‘sag’ and ‘lbfgs’ handle
                multinomial loss; ‘liblinear’ is limited to one-versus-rest schemes.
                ‘newton-cg’, ‘lbfgs’ and ‘sag’ only handle L2 penalty.

                ‘liblinear’ might be slower in LogisticRegressionCV because it does
                not handle warm-starting.

                Note that ‘sag’ fast convergence is only guaranteed on features with approximately the same scale.
                You can preprocess the data with a scaler from sklearn.preprocessing.
                New in version 0.17: Stochastic Average Gradient descent solver.
                '''

                if 'classification' in model_processing_detail:

                    multi_class = 'ovr' if 'binary' in model_processing_detail else 'multinomial'
                    if dataset.shape[0] <= 1000:
                        if multi_class == 'ovr':
                            solver = 'liblinear'
                        else:
                            solver = 'lbfgs'
                    elif dataset.shape[0] >= 10000:
                        solver = 'sag'
                    else:
                        solver = 'lbfgs'

                    class_weight = 'balanced'
                    n_jobs = -1

                    from sklearn.linear_model import LogisticRegression
                    lr = LogisticRegression(
                        solver=solver,
                        class_weight=class_weight,
                        n_jobs=n_jobs,
                        multi_class=multi_class
                    )

                    from sklearn import preprocessing
                    X = preprocessing.scale(dataset)

                    if validation_type == 'fold':
                        y_pred = cross_val_predict(lr, X, y_encoded,
                                                   cv=skf, n_jobs=-1, verbose=9)
                    else:
                        pass
                        # lr.fit(X, y)
                        # y_pred = lr.predict(test_dataset.values) \
                        # if multi_class == 'ovr' else lr.predict_proba(test_dataset.values)

                    trained_models['lr'] = y_pred
                    del X
                else:
                    pass

            if 'nn' in processing_models:
                '''
                solver : {‘lbfgs’, ‘sgd’, ‘adam’}, default ‘adam’
                The solver for weight optimization.
                ‘lbfgs’ is an optimizer in the family of quasi-Newton methods.
                ‘sgd’ refers to stochastic gradient descent.
                ‘adam’ refers to a stochastic gradient-based optimizer proposed by Kingma, Diederik, and Jimmy Ba
                Note: The default solver ‘adam’ works pretty well on relatively large datasets
                (with thousands of training samples or more) in terms of both training time and validation score.
                For small datasets, however, ‘lbfgs’ can converge faster and perform better.
                '''
                solver = None
                if dataset.shape[0] >= 1000.:
                    solver = 'adam'
                else:
                    solver = 'lbfgs'

                if 'classification' in model_processing_detail:
                    from sklearn.neural_network import MLPClassifier
                    nn = MLPClassifier(solver=solver, hidden_layer_sizes=(50, 3))
                else:
                    from sklearn.neural_network import MLPRegressor
                    nn = MLPRegressor(solver=solver, hidden_layer_sizes=(50, 3))

                from sklearn import preprocessing
                X = preprocessing.scale(dataset)

                if validation_type == 'fold':
                    y_pred = cross_val_predict(nn, X, y_encoded,
                                               cv=skf, n_jobs=-1, verbose=9)
                else:
                    pass
                    # nn.fit(X, y)
                    # y_pred = nn.predict(test_dataset.values) \
                    #     if 'binary' in model_processing_detail \
                    #     else nn.predict_proba(test_dataset.values)

                trained_models['nn'] = y_pred
                del X

            if 'rf' in processing_models:

                n_estimators = 50
                n_jobs = -1
                max_depth = 7

                if 'classification' in model_processing_detail:
                    from sklearn.ensemble import RandomForestClassifier
                    rf = RandomForestClassifier(
                        n_estimators=n_estimators,
                        max_depth=max_depth,
                        class_weight='balanced',
                        n_jobs=n_jobs
                    )
                else:
                    from sklearn.ensemble import RandomForestRegressor
                    rf = RandomForestRegressor(
                        n_estimators=n_estimators,
                        max_depth=max_depth,
                        n_jobs=n_jobs
                    )

                if validation_type == 'fold':
                    y_pred = cross_val_predict(rf, dataset.values, y_encoded,
                                               cv=skf, n_jobs=-1, verbose=9)
                else:
                    pass
                    # rf.fit(X, y)
                    # y_pred = rf.predict(test_dataset.values) \
                    #     if 'binary' in model_processing_detail \
                    #     else rf.predict_proba(test_dataset.values)

                trained_models['rf'] = y_pred
        else:
            if 'gm' in processing_models:
                from sklearn.mixture import GaussianMixture
                gm = GaussianMixture()
                # gm.fit(X)

            if 'kmean' in processing_models:
                from sklearn.cluster import KMeans
                kmean = KMeans()
                # kmean.fit(X)

            if 'dbscan' in processing_models:
                from sklearn.cluster import DBSCAN
                dbscan = DBSCAN()
                # dbscan.fit(X)

            if 'pca' in processing_models:
                from sklearn.decomposition import PCA
                pca = PCA()
                # pca.fit(X)

            if 'rbm' in processing_models:
                from sklearn.neural_network import BernoulliRBM
                rbm = BernoulliRBM()
                # rbm.fit(X)

        return trained_models, model_processing_type, model_processing_detail

    @blocking
    def validate_models(self, workflow, trained_models, y, model_processing_type, model_processing_detail):
        print('validate models', trained_models)
        validation_details = workflow.validation_details
        if model_processing_type == 'supervised':

            from sklearn.preprocessing import LabelEncoder
            le = LabelEncoder()
            le.fit(y)
            y_true = le.transform(y)

            from sklearn.metrics import accuracy_score, roc_auc_score, log_loss, classification_report

            for model, y_pred in trained_models.items():
                validation_details[model] = {}
                print(model, y_pred, len(y_true), le.classes_)
                # if 'multi' in model_processing_detail:
                #     validation_details[model]['logloss'] = log_loss(y, le.inverse_transform(y_pred), labels=le.classes_)

                if 'binary' in model_processing_detail:
                    validation_details[model]['roc_auc_score'] = roc_auc_score(y_true, y_pred)

                validation_details[model]['acc_score'] = accuracy_score(y_true, y_pred)
                # report = classification_report(
                #     y_true, y_pred, target_names=le.classes_)
                # report_list = []
                # splits = report.strip().split('\n')
                # for item in splits:
                #     if len(item) > 0:
                #         split_items = item.strip().split(' ')
                #         for item_ in split_items:
                #             if len(item) == 0:
                #                 split_items.remove(item_)
                #
                #         report_list.append({
                #             'precision': split_items[0],
                #             'recall': split_items[1],
                #             'f1score': split_items[2]
                #         })
                validation_details[model]['classification_report'] = classification_report(
                    y_true, y_pred, target_names=le.classes_)

            workflow.validation_details = validation_details
        else:
            pass

        return workflow

    def models_ensembling(self):
        pass

    def models_stacking(self):
        pass


class DataSourceUploadHandler(AuthHandler):
    def __init__(self, *args, **kwargs):
        super(DataSourceUploadHandler, self).__init__(*args, **kwargs)

    @web.authenticated
    async def post(self, *args, **kwargs):
        file_name = self.get_argument('data[].name')
        file_path = self.get_argument('data[].path')
        content_type = self.get_argument('data[].content_type')
        file_name_md5 = self.get_argument('data[].md5')
        file_size = self.get_argument('data[].size')

        model = DataSourceModel({
            '_id': uuid.uuid4(),
            'file_name': file_name,
            'file_path': file_path,
            'content_type': content_type,
            'file_name_md5': file_name_md5,
            'file_size': file_size
        })

        result = 'success'
        try:
            await model.insert(self.db)
        except PyMongoError as e:
            result = 'failure'

        cursor = DataSourceModel.get_cursor(self.db, query={})
        object_list = await DataSourceModel.find(cursor)

        self.add_additional_context({'object_list': object_list})

        if self.is_ajax:
            data = {
                'result': result,
                'obj_id': model._id,
                'html': self.render_template('service/data-source-list.html')
            }
            self.render_json(data)
        else:
            self.render(self.template_name, self.context)


class DataSourceCheckHandler(AuthHandler):
    def __init__(self, *args, **kwargs):
        super(DataSourceCheckHandler, self).__init__(*args, **kwargs)
        self.delimiters = [',', ';', '|', ':', '.', '/']
        self.model = DataSourceModel
        self.executor = ThreadPoolExecutor(multiprocessing.cpu_count())

    @web.authenticated
    async def post(self, *args, **kwargs):
        datasource_id = self.get_argument('obj_id')
        datasource = await self.model.find_one(self.db, {'_id': datasource_id})

        result = 'success'
        if not datasource:
            result = 'failure'
        else:
            await self.check_data(datasource, datasource_id)

        cursor = DataSourceModel.get_cursor(self.db, query={})
        object_list = await DataSourceModel.find(cursor)

        self.add_additional_context({'object_list': object_list})
        self.render_json({'result': result,
                          'html': self.render_template('service/data-source-list.html')})

    async def check_data(self, datasource, datasource_id):

        dataset, sep = await self.read_data(datasource.file_path, datasource.content_type)

        samples_count, predictors_count, missing_values, nominal_predictors_count, \
        numeric_predictors_count, predictor_details = await self.count_data(dataset)

        datasource.file_sep = sep
        datasource.samples_count = int(samples_count)
        datasource.predictors_count = int(predictors_count)
        datasource.missing_values = float(missing_values)
        datasource.nominal_predictors_count = int(nominal_predictors_count)
        datasource.numeric_predictors_count = int(numeric_predictors_count)
        datasource.status = 'ready'
        # datasource.pickle_file_path = datasource.file_path + '.pickle'
        predictor_values = list(dataset.columns.values)

        predictor_ids = list()
        for predictor in predictor_values:
            predictor_lower = predictor.lower()
            if predictor_lower == 'id' or predictor_lower[-2:] == 'id':
                predictor_ids.append(predictor)

        datasource.predictor_ids = predictor_ids
        datasource.predictor_values = list(dataset.columns.values)
        datasource.predictor_details = list(predictor_details)

        await datasource.update(self.db, query={'_id': datasource_id})
        # await self.pickle_dataset(dataset, datasource.pickle_file_path)

    @blocking
    def read_data(self, file_path, content_type):
        sep = ' '
        if content_type == 'text/csv' or content_type == 'text/plain':
            f = open(file_path)
            line = f.readline()
            for delimiter in self.delimiters:
                if delimiter in line:
                    sep = delimiter
                    break
            dataset = pd.read_csv(file_path, sep=sep)
        elif content_type == 'text/json':
            dataset = pd.read_json(file_path)
        else:
            raise Exception('unsupported dataset format, sorry')

        return dataset, sep

    @blocking
    def count_data(self, dataset):
        samples_count = len(dataset.index)
        predictors_count = len(dataset.columns)
        missing_values = 100. * (1. - np.sum(dataset.count().values) / dataset.size)
        nominal_predictors_count = 0
        numeric_predictors_count = 0
        predictor_details = list()
        order = 0

        for c in dataset.columns:
            # freq = {}
            feature = dataset[c][dataset[c].notnull()]

            # for f in feature:
            #     data_type = type(f)
            #     if data_type in freq:
            #         freq[data_type] += 1
            #     else:
            #         freq[data_type] = 1
            if len(feature) > 0:

                unique_count = len(feature.unique())
                miss_values = 100. * (1. - feature.count() / samples_count)

                from collections import defaultdict
                freq = defaultdict(int)
                for val in feature:
                    try:
                        is_number = val.isdigit()
                    except AttributeError:
                        is_number = np.isfinite(val)

                    if is_number:
                        freq['numeric'] += 1
                    else:
                        freq['nominal'] += 1

                # sorted_freq = sorted(freq.items(), key=operator.itemgetter(1), reverse=True)
                # data_type = None

                # freq_data_type = sorted_freq[0][0]

                if freq['numeric'] > freq['nominal']:
                    numeric_predictors_count += 1
                    is_discrete = unique_count / samples_count < .005
                    data_type = {
                        'name': 'numeric',
                        'description': 'discrete' if is_discrete else 'continuous'
                    }
                else:
                    nominal_predictors_count += 1
                    data_type = {
                        'name': 'nominal'
                    }

                value_counts = feature.value_counts()
                barchart = {
                    'labels': list(str(i) for i in value_counts.index.values[:10]),
                    'data': list(int(i) for i in value_counts.values[:10])
                }
                predictor_details.append({
                    'use_predictor': True,
                    'name': c,
                    'predictor_type': data_type,
                    'unique_values_count': int(unique_count),
                    'missing_values': float(miss_values),
                    'barchart': barchart,
                    'order': int(order)
                })

                order += 1

        return samples_count, predictors_count, missing_values, nominal_predictors_count, \
        numeric_predictors_count, predictor_details

    @blocking
    def pickle_dataset(self, dataset, path):
        dataset.to_pickle(path)
