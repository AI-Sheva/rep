"""
 wrapper for http://mirror.yandex.ru/gentoo-distfiles/distfiles/TMVAUsersGuide-v4.03.pdf
"""
from __future__ import division, print_function, absolute_import
from abc import ABCMeta
from logging import getLogger
import os
import tempfile
import subprocess
from subprocess import PIPE
import shutil
import sys

import root_numpy
import numpy

from .interface import Classifier, Regressor
from .utils import check_inputs, score_to_proba, proba_to_two_dimension
from six.moves import cPickle
from ..utils import get_columns_dict


__author__ = 'Tatiana Likhomanenko'

logger = getLogger(__name__)
_PASS_PARAMETERS = {'random_state'}


class _AdditionalInformation():
    """
    Additional information for tmva factory
    """

    def __init__(self, directory, features_names, model_type='classification'):
        self.directory = directory
        self.filename = os.path.join(self.directory, 'train.root')
        self.treename = 'train_tree'
        self.tmva_root = 'result.root'
        self.tmva_job = "TMVAEstimation"
        self.weight_column = 'REP_Weight__'
        self.target_column = 'REP_Signal__'
        self.model_type = model_type
        self.features = features_names


class _AdditionalInformationPredict():
    """
    Additional information for tmva factory
    """

    def __init__(self, directory, xml_file, features_names, method_name, model_type=('classification', None)):
        self.directory = directory
        self.xml_file = xml_file
        self.features = features_names
        self.treename = 'test_tree'
        self.filename = os.path.join(self.directory, 'test.root')
        self.method_name = method_name
        self.model_type = model_type


class TMVABase(object):
    """
    TMVABase - base estimator for tmva wrappers.

    Parameters:
    -----------
    :param str method: algorithm method (default='kBDT')
    :param features: features used in training
    :type features: list[str] or None
    :param str factory_options: system options
    :param dict method_parameters: estimator options

    .. note:: TMVA doesn't support staged predictions and features importances =((
    """

    __metaclass__ = ABCMeta

    def __init__(self,
                 factory_options="",
                 method='kBDT',
                 **method_parameters):

        self.method = method
        self._method_name = 'REP_Estimator'
        self.factory_options = factory_options
        self.method_parameters = method_parameters

        # contents of xml file with formula, read into memory
        self.formula_xml = None

    @staticmethod
    def _create_tmp_directory():
        return tempfile.mkdtemp(dir=os.getcwd())

    @staticmethod
    def _remove_tmp_directory(directory):
        shutil.rmtree(directory, ignore_errors=True)

    def _fit(self, X, y, sample_weight=None, features_names=None, model_type='classification'):
        """
        Train the classifier

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :param list | numpy.array y: values - array-like of shape [n_samples]
        :param list | numpy.array sample_weight: weight of events,
               array-like of shape [n_samples] or None if all weights are equal
        :return: self
        """
        # saving data to 2 different root files.
        directory = self._create_tmp_directory()
        add_info = _AdditionalInformation(directory, features_names, model_type=model_type)
        try:
            X[add_info.weight_column] = sample_weight
            X[add_info.target_column] = y
            root_numpy.array2root(X.to_records(), filename=add_info.filename,
                                  treename=add_info.treename)
            self._run_tmva_training(add_info)
        finally:
            self._remove_tmp_directory(directory)

        return self

    def _run_tmva_training(self, info):
        """
        Run subprocess to train tmva factory

        :param info: class with additional information
        """
        tmva_process = subprocess.Popen(
            'cd {directory}; {executable} -c "from rep.estimators import _tmvaFactory; _tmvaFactory.main()"'.format(
                directory=info.directory,
                executable=sys.executable),
            stdin=PIPE, stdout=PIPE, stderr=subprocess.STDOUT,
            shell=True)

        cPickle.dump(self, tmva_process.stdin)
        cPickle.dump(info, tmva_process.stdin)
        stdout, stderr = tmva_process.communicate()
        assert tmva_process.returncode == 0, \
            'ERROR: TMVA process is incorrect finished \n LOG: %s \n %s' % (stderr, stdout)

        assert 'TrainTree' in root_numpy.list_trees(os.path.join(info.directory, info.tmva_root)), \
            'ERROR: Result file has not TrainTree'

        xml_filename = os.path.join(info.directory, 'weights',
                                    '{job}_{name}.weights.xml'.format(job=info.tmva_job, name=self._method_name))
        with open(xml_filename, 'r') as xml_file:
            self.formula_xml = xml_file.read()

    def _check_fitted(self):
        assert self.formula_xml is not None, "Classifier wasn't fitted, please call `fit` first"

    def _predict(self, X, features_names=None, model_type=('classification', None)):
        """
        Predict data

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :return: predicted values of shape n_samples
        """
        self._check_fitted()

        directory = self._create_tmp_directory()
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix='.xml', dir=directory, delete=True) as file_xml:
                file_xml.write(self.formula_xml)
                file_xml.flush()
                add_info = _AdditionalInformationPredict(directory, file_xml.name, features_names, self._method_name,
                                                         model_type=model_type)
                root_numpy.array2root(X.astype(numpy.float32).to_records(), filename=add_info.filename,
                                      treename=add_info.treename)
                prediction = self._run_tmva_predict(add_info)
        finally:
            self._remove_tmp_directory(directory)

        return prediction

    def _run_tmva_predict(self, info):
        """
        Run subprocess to train tmva factory

        :param info: class with additional information
        """
        tmva_process = subprocess.Popen(
            'cd {directory}; {executable} -c "from rep.estimators import _tmvaReader; _tmvaReader.main()"'.format(
                directory=info.directory,
                executable=sys.executable),
            stdin=PIPE, stdout=PIPE, stderr=subprocess.STDOUT,
            shell=True)

        cPickle.dump(info, tmva_process.stdin)
        stdout, stderr = tmva_process.communicate()
        assert tmva_process.returncode == 0, \
            'ERROR: TMVA process is incorrect finished \n LOG: %s \n %s' % (stderr, stdout)

        return root_numpy.root2array(info.filename, treename=info.treename, branches=[self._method_name])[self._method_name]


class TMVAClassifier(TMVABase, Classifier):
    """
    TMVAClassifier wraps estimators from TMVA (CERN library for machine learning)

    Parameters:
    -----------
    :param str method: algorithm method (default='kBDT')
    :param features: features used in training
    :type features: list[str] or None
    :param str factory_options: system options, for example::

        "!V:!Silent:Color:Transformations=I;D;P;G,D"

    :param str sigmoid_function: function which is used to convert TMVA output to probabilities;

        * *identity* (svm, mlp) --- the same output, use this for methods returning class probabilities

        * *sigmoid* --- sigmoid transformation, use it if output varies in range [-infinity, +infinity]

        * *bdt* (for bdt algorithms output varies in range [-1, 1])

        * *sig_eff=0.4* --- for rectangular cut optimization methods,
        and 0.4 will be used as signal efficiency to evaluate MVA,
        (put any float number from [0, 1])

    :param dict method_parameters: estimator options, example: NTrees=100, BoostType='Grad'

    .. warning::
        TMVA doesn't support *staged_predict_proba()* and *feature_importances__*

    .. warning::
        TMVA doesn't support multiclassification, only two-classes classification
    """

    def __init__(self,
                 method='kBDT',
                 features=None,
                 factory_options="",
                 sigmoid_function='bdt',
                 **method_parameters):

        # !V:!Silent:Color:Transformations=I;D;P;G,D
        TMVABase.__init__(self, factory_options=factory_options, method=method, **method_parameters)
        Classifier.__init__(self, features=features)
        self.sigmoid_function = sigmoid_function

    def _set_classes_special(self, y):
        self._set_classes(y)
        assert self.n_classes_ == 2, "Support only 2 classes (data contain {})".format(self.n_classes_)

    def set_params(self, **params):
        """
        Set the parameters of this estimator.

        :param dict params: parameters to set in model
        """
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                if k in _PASS_PARAMETERS:
                    continue
                self.method_parameters[k] = v

    def get_params(self, deep=True):
        """
        Get parameters for this estimator.

        deep: boolean, optional

            If True, will return the parameters for this estimator and contained subobjects that are estimators.

        params : mapping of string to any

            Parameter names mapped to their values.
        """
        parameters = self.method_parameters.copy()
        parameters['method'] = self.method
        parameters['factory_options'] = self.factory_options
        parameters['features'] = self.features
        return parameters

    def fit(self, X, y, sample_weight=None):
        """
        Train the classifier

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :param y: labels of events - array-like of shape [n_samples]
        :param sample_weight: weight of events,
               array-like of shape [n_samples] or None if all weights are equal

        :return: self
        """
        X, y, sample_weight = check_inputs(X, y, sample_weight=sample_weight, allow_none_weights=False)
        X = self._get_train_features(X).copy()
        self._set_classes_special(y)
        if self.n_classes_ == 2:
            self.factory_options = '{}:AnalysisType=Classification'.format(self.factory_options)
        else:
            self.factory_options = '{}:AnalysisType=Multiclass'.format(self.factory_options)
        features_names = get_columns_dict(self.features).keys()
        return self._fit(X, y, sample_weight=sample_weight, features_names=features_names)

    def predict_proba(self, X):
        """
        Predict data

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :rtype: numpy.array of shape [n_samples, n_classes] with probabilities
        """
        X = self._get_train_features(X)
        features_names = get_columns_dict(self.features).keys()
        prediction = self._predict(X, features_names=features_names, model_type=('classification', self.sigmoid_function))
        return self._convert_output(prediction)

    def _convert_output(self, prediction):
        variants = {'bdt', 'sigmoid', 'identity'}
        if 'sig_eff' in self.sigmoid_function:
            return proba_to_two_dimension(prediction)
        assert self.sigmoid_function in variants, \
            'sigmoid_function parameter must be one of {}, instead of {}'.format(variants, self.sigmoid_function)
        if self.sigmoid_function == 'sigmoid':
            return score_to_proba(prediction)
        elif self.sigmoid_function == 'bdt':
            return proba_to_two_dimension((prediction + 1.) / 2.)
        else:
            return proba_to_two_dimension(prediction)

    def staged_predict_proba(self, X):
        """
        Predicts probabilities on each stage

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :return: iterator

        .. warning:: Doesn't support for TMVA (**AttributeError** will be thrown)
        """
        raise AttributeError("Not supported for TMVA")


class TMVARegressor(TMVABase, Regressor):
    """
    TMVARegressor wraps regressors from TMVA (CERN library for machine learning)

    Parameters:
    -----------
    :param str method: algorithm method (default='kBDT')
    :param features: features used in training
    :type features: list[str] or None
    :param str factory_options: system options, for example::

        "!V:!Silent:Color:Transformations=I;D;P;G,D"

    :param dict method_parameters: estimator options, example: NTrees=100, BoostType=Grad

    .. note::
        TMVA doesn't support *staged_predict()* and *feature_importances__*
    """

    def __init__(self,
                 method='kBDT',
                 features=None,
                 factory_options="",
                 **method_parameters):

        TMVABase.__init__(self, factory_options=factory_options, method=method, **method_parameters)
        Regressor.__init__(self, features=features)

    def set_params(self, **params):
        """
        Set the parameters of this estimator.

        :param dict params: parameters to set in model
        """
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                if k in _PASS_PARAMETERS:
                    continue
                self.method_parameters[k] = v

    def get_params(self, deep=True):
        """
        Get parameters for this estimator.

        deep: boolean, optional

            If True, will return the parameters for this estimator and contained subobjects that are estimators.

        params : mapping of string to any

            Parameter names mapped to their values.
        """
        parameters = self.method_parameters.copy()
        parameters['method'] = self.method
        parameters['factory_options'] = self.factory_options
        parameters['features'] = self.features
        return parameters

    def fit(self, X, y, sample_weight=None):
        """
        Train the classifier

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :param y: values - array-like of shape [n_samples]
        :param sample_weight: weight of events,
               array-like of shape [n_samples] or None if all weights are equal
        :return: self
        """
        X, y, sample_weight = check_inputs(X, y, sample_weight=sample_weight, allow_none_weights=False)
        X = self._get_train_features(X).copy()
        features_names = get_columns_dict(self.features).keys()
        self.factory_options = '{}:AnalysisType=Regression'.format(self.factory_options)
        return self._fit(X, y, sample_weight=sample_weight, features_names=features_names, model_type='regression')

    def predict(self, X):
        """
        Predict data

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :return: numpy.array of shape n_samples with values
        """
        X = self._get_train_features(X)
        features_names = get_columns_dict(self.features).keys()
        return self._predict(X, features_names=features_names, model_type=('regression', None))

    def staged_predict(self, X):
        """
        Predicts values on each stage

        :param pandas.DataFrame X: data shape [n_samples, n_features]
        :return: iterator

        .. warning:: Doesn't support for TMVA (**AttributeError** will be thrown)
        """
        raise AttributeError("Not supported for TMVA")