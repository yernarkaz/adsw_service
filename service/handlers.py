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

        cursor = DataSourceModel.get_cursor(self.db, {'state': 'finished'}, **{})
        workflow_list = await WorkflowModel.find(cursor)

        cursor = DataSourceModel.get_cursor(self.db, {'state': 'new'}, **{})
        new_workflow_list = await WorkflowModel.find(cursor)

        cursor = DataSourceModel.get_cursor(self.db, {'state': 'processing'}, **{})
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
        return {'is_finished': True}


class WorkflowDetailHandler(DetailHandler):
    def __init__(self, *args, **kwargs):
        super(WorkflowDetailHandler, self).__init__(*args, **kwargs)
        self.template_name = './service/workflow-detail.html'
        self.model = WorkflowModel

    async def update_context(self):
        await super().update_context()
        self.add_additional_context({'content_title': 'workflow : {}'.format(self.obj._id)})


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
            workflow = await WorkflowModel.find_one(self.db, {'_id': self.session_get('curr_workflow_id')})
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

            if val_type == 'file':
                val = uuid.UUID(val)

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
                models = set(model_processing.get('models', None))
                if not models:
                    models = set()

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
        datasource = await DataSourceModel.find_one(self.db, {'_id': str(workflow.training_data['_id'])})

        self.redirect(self.reverse_url('workflows'))

        await self.process_workflow(workflow, datasource)

    @blocking
    def process_workflow(self, workflow, datasource):
        print('=== start processing workflow ===')

        processing_type = workflow.model_processing.get('type')

        dataset = None
        series = None
        usecols = [0]
        skiprows = None

        if processing_type == 'supervised':
            if datasource.predictor_target_name:
                usecols = [datasource.predictor_target_name]

        if datasource.content_type == 'text/csv':
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

        if datasource.content_type == 'text/csv':
            dataset = pd.read_csv(datasource.file_path,
                                  sep=datasource.file_sep,
                                  skiprows=skiprows)
        elif datasource.content_type == 'text/json':
            pass

        if dataset is not None:
            if len(workflow.preprocessing) > 0:
                print('=== dataset shape before preprocessing', dataset.columns, dataset.shape)
                dataset, y = self.preprocess_data(workflow, datasource, dataset)
                print('=== dataset shape after preprocessing', dataset.columns, dataset.shape)
                # self.train_validate(workflow, datasource, dataset, y)
            else:
                pass
                # self.train_validate(workflow, datasource, dataset, y)
        else:
            raise Exception()

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

        if 'miss_val' in workflow.preprocessing and datasource.missing_values > 0.:
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

    def train_validate(self, workflow, datasource, dataset, y=None):
        trained_models = set()
        validated_models = dict()
        model_processing_type = workflow.model_processing.get('type')
        processing_models = workflow.model_processing.get('models')
        if model_processing_type == 'supervised':

            y_predictor = None
            model_processing_detail = None

            for p in datasource.predictor_details:
                if p.get('name') == dataset.preditor_target_name:
                    y_predictor = p
                    break

            if p.get('predictor_type').get('description', None) == 'continuous':
                model_processing_detail = 'regression'
            else:
                model_processing_detail = 'classification'

            if 'rlist' in processing_models and model_processing_detail == 'classification':
                pass

            if 'xgb' in processing_models:
                import xgboost as xgb
                # xgb_params = {
                #     'seed': 0,
                #     'colsample_bytree': 0.8,
                #     'silent': 1,
                #     'subsample': 0.8,
                #     'learning_rate': 0.1,
                #     'objective': 'multi:softmax',
                #     'max_depth': 7,
                #     'num_parallel_tree': 1,
                #     'min_child_weight': 2,
                #     'num_class': len(le.classes_),
                #     'eval_metric': 'mlogloss'
                # }
                #
                # dtrain = xgb.DMatrix(train, label=y_train)
                # dtest = xgb.DMatrix(test, label=y_test)
                #
                # evals = [(dtrain, 'train'), (dtest, 'test')]
                # xgb_model = xgb.cv(xgb_params, dtrain, num_boost_round=10, nfold=5, seed=0,
                #              stratified=True, early_stopping_rounds=1,
                #              verbose_eval=True, show_stdv=True)
                # booster = xgb.train(xgb_params, dtrain, evals=evals,
                #                     num_boost_round=10, early_stopping_rounds=1,
                #                     verbose_eval=True)

            if 'frlp' in processing_models:
                pass

            if 'knn' in processing_models:
                if model_processing_detail == 'classification':
                    from sklearn.neighbors import KNeighborsClassifier
                    knn = KNeighborsClassifier(n_neighbors=3)
                else:
                    from sklearn.neighbors import KNeighborsRegressor
                    knn = KNeighborsRegressor(n_neighbors=2)
                # knn.fit(X, y)

            if 'lr' in processing_models:
                from sklearn.linear_model import LogisticRegression
                lr = LogisticRegression()

            if 'nn' in processing_models:
                if model_processing_detail == 'classification':
                    from sklearn.neural_network import MLPClassifier
                    nn = MLPClassifier()
                else:
                    from sklearn.neural_network import MLPRegressor
                    nn = MLPRegressor()
                # nn.fit(X, y)

            if 'rf' in processing_models:
                if model_processing_detail == 'classification':
                    from sklearn.ensemble import RandomForestClassifier
                    rf = RandomForestClassifier()
                else:
                    from sklearn.ensemble import RandomForestRegressor
                    rf = RandomForestRegressor()
                # rf.fit(X, y)
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

        return trained_models

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
        sep = None
        if content_type == 'text/csv':
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
            freq = {}
            feature = dataset[c][dataset[c].notnull()]

            for f in feature:
                data_type = type(f)
                if data_type in freq:
                    freq[data_type] += 1
                else:
                    freq[data_type] = 1

            sorted_freq = sorted(freq.items(), key=operator.itemgetter(1), reverse=True)
            data_type = None

            unique_count = len(feature.unique())
            miss_values = 100. * (1. - feature.count() / samples_count)

            if len(sorted_freq) > 0:
                freq_data_type = sorted_freq[0][0]

                if freq_data_type in [int, float, np.int32, np.float32, np.int64, np.float64]:
                    numeric_predictors_count += 1
                    is_discrete = unique_count / samples_count < .005
                    data_type = {
                        'name': 'numeric',
                        'description': 'discrete' if is_discrete else 'continuous'
                    }
                elif freq_data_type == str:
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
