# coding=utf-8

from tornadostreamform.multipart_streamer import MultiPartStreamer, TemporaryFileStreamedPart
from settings import location

from schematics.types import StringType, UUIDType, DateTimeType, BooleanType
from schematics.types import IntType, FloatType, BaseType
from schematics.types.compound import ListType, DictType
from base.models import BaseModel

import datetime

from sklearn.base import TransformerMixin
import pandas as pd
import numpy as np

import multiprocessing
from joblib import Parallel, delayed

from ReliefF import ReliefF
from sklearn.neighbors import KDTree


class DataFrameImputer(TransformerMixin):
    def __init__(self):
        self.fill = None

    def fit(self, X):
        l = []
        columns = []
        for c in X:
            val_counts = X[c].value_counts()
            if len(val_counts) > 0:
                if type(val_counts.index[0]) == str:
                    l.append(val_counts.index[0])
                else:
                    l.append(X[c].median())

                columns.append(c)

        self.fill = pd.Series(l, index=columns)
        return self

    def transform(self, X):
        return X.fillna(self.fill)


class FasterRelief(ReliefF):
    def fit(self, X, y):
        """Computes the feature importance scores from the training data.

                Parameters
                ----------
                X: array-like {n_samples, n_features}
                    Training instances to compute the feature importance scores from
                y: array-like {n_samples}
                    Training labels
                }

                Returns
                -------
                None

                """
        self.feature_scores = np.zeros(X.shape[1])
        self.tree = KDTree(X)

        cpu_count = multiprocessing.cpu_count()
        slice = int(X.shape[0] / cpu_count)
        slices = [slice for i in range(cpu_count)]
        slices[cpu_count - 1] += X.shape[0] % slices[cpu_count - 1]

        results = Parallel(n_jobs=cpu_count, verbose=True) \
                          (delayed(self.process_source_index)(X, y, slice) \
                          for slice in slices)

        self.top_features = np.zeros(X.shape[1])
        for result in results:
            self.top_features += result

        self.top_features = np.argsort(self.feature_scores)[::-1]

    def process_source_index(self, X, y, slice):
        feature_scores = np.zeros(X.shape[1])

        for source_index in range(slice):
            distances, indices = self.tree.query(
                X[source_index].reshape(1, -1), k=self.n_neighbors + 1)

            # Nearest neighbor is self, so ignore first match
            indices = indices[0][1:]

            # Create a binary array that is 1 when the source and neighbor
            #  match and -1 everywhere else, for labels and features..
            labels_match = np.equal(y[source_index], y[indices]) * 2. - 1.
            features_match = np.equal(X[source_index], X[indices]) * 2. - 1.

            # The change in feature_scores is the dot product of these  arrays
            feature_scores += np.dot(features_match.T, labels_match)

        return feature_scores


class DataStreamer(MultiPartStreamer):
    def create_part(self, headers):
        return TemporaryFileStreamedPart(self, headers, tmp_dir=location('uploads_tmp'))


class WorkflowModel(BaseModel):
    _id = UUIDType(required=True)

    name = StringType()
    created_at = DateTimeType(default=datetime.datetime.now())
    processing_started_at = DateTimeType()
    processing_ended_at = DateTimeType()

    training_data = DictType(BaseType, {})
    preprocessing = ListType(StringType, default=list())
    model_processing = DictType(BaseType, default={'type': 'supervised'})
    validation = DictType(BaseType, default={'type': 'fold', 'value': 3})
    trained_models = DictType(BaseType, {})
    fi_booster = StringType()

    validation_details = DictType(BaseType, default={})

    state = StringType(default='new')

    MONGO_COLLECTION = 'workflows'


class DataSourceModel(BaseModel):
    _id = UUIDType(required=True)

    file_name = StringType(required=True)
    file_path = StringType(required=True)
    file_sep = StringType()
    pickle_file_path = StringType()
    content_type = StringType(required=True)
    file_name_md5 = StringType()
    file_size = StringType()
    uploaded_at = DateTimeType(default=datetime.datetime.now())

    samples_count = IntType(default=0)
    predictors_count = IntType(default=0)
    nominal_predictors_count = IntType(default=0)
    numeric_predictors_count = IntType(default=0)
    class_count = IntType(default=0)
    missing_values = FloatType(default=.0)

    status = StringType(default='check')

    predictor_values = ListType(StringType())
    predictor_details = ListType(DictType(BaseType))

    predictor_ids = ListType(StringType())
    predictor_target_name = StringType()

    MONGO_COLLECTION = 'datasources'


class DataReport(BaseModel):
    _id = UUIDType(required=True)

    workflow_id = UUIDType(required=True)
    datasource_id = UUIDType(required=True)

    MONGO_COLLECTION = 'datareports'
