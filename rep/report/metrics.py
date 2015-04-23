from __future__ import division, print_function, absolute_import
import numpy
from sklearn.base import BaseEstimator
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.utils import check_arrays
from rep.utils import check_sample_weight


__author__ = 'Alex Rogozhnikov'

"""
About
this file contains definitions for useful metrics.

In general case, metrics follows standard sklearn convention for **estimators**, provides:

Constructor
>>> m = metrics(parameter=1)

Fitting, where checks and heavy computations performed.
>>> m.fit(X, y, sample_weight=None)

Computation of metrics by probabilities:
>>> proba = classifier.predict_proba(X)
>>> m(y, proba, sample_weight=None)
"""


class MetricMixin(object):
    """Class with helpful methods for metrics,
     metrics are expected (but not obliged) to be derived from it."""
    def prepare(self, X, y, sample_weight):
        assert len(X) == len(y), 'Lengths are different!'
        sample_weight = check_sample_weight(y, sample_weight=sample_weight)
        self.classes_, indices = numpy.unique(y, return_inverse=True)
        self.probabilities_shape = (len(y), len(self.classes_))
        return X, y, sample_weight, indices

    def fit(self, X, y, sample_weight=None):
        """Prepare metrics for usage, preprocessing is done in this function. """
        return self


class RocAuc(BaseEstimator, MetricMixin):
    def __init__(self, positive_label=1):
        """
        Computes area under the ROC curve.
        :param positive_label: int, label of class, in case of more then two classes,
         will compute ROC AUC for this specific class vs others
        """
        self.positive_label = positive_label

    def fit(self, X, y, sample_weight=None):
        X, y, self.sample_weight, _ = self.prepare(X, y, sample_weight=sample_weight)
        # computing index of positive label
        self.positive_index = self.classes_.tolist().index(self.positive_label)
        self.true_class = (numpy.array(y) == self.positive_label)
        return self

    def __call__(self, y, proba, sample_weight=None):
        assert numpy.all(self.classes_ < proba.shape[1])
        return roc_auc_score(self.true_class, proba[:, self.positive_index],
                             sample_weight=self.sample_weight)


class LogLoss(BaseEstimator, MetricMixin):
    def __init__(self, regularization=1e-15):
        """
        Log loss,
        which is the same as minus log-likelihood,
        and the same as logistic loss,
        and the same as cross-entropy loss.
        """
        self.regularization = regularization

    def fit(self, X, y, sample_weight=None):
        X, y, sample_weight, self.class_indices = self.prepare(X, y, sample_weight=sample_weight)
        self.sample_weight = sample_weight / sample_weight.sum()
        self.samples_indices = numpy.arange(len(X))
        return self

    def __call__(self, y, proba, sample_weight=None):
        # assert proba.shape == self.probabilities_shape, 'Wrong shape of probabilities'
        assert numpy.all(self.classes_ < proba.shape[1])
        correct_probabilities = proba[self.samples_indices, self.class_indices]
        return - (numpy.log(correct_probabilities + self.regularization) * self.sample_weight).sum()


class OptimalMetric(BaseEstimator, MetricMixin):
    def __init__(self, metric, expected_s=1., expected_b=1., signal_label=1):
        """
        Class to calculate optimal threshold on predictions using some metric

        Parameters:
        -----------
        :param function metric: metrics(s, b) -> float
        :param expected_s: float, total weight of signal
        :param expected_b: float, total weight of background
        """
        self.metric = metric
        self.expected_s = expected_s
        self.expected_b = expected_b
        self.signal_label = signal_label

    def compute(self, y_true, proba, sample_weight=None):
        """
        Compute metric for each possible prediction threshold

        :param y_true: array-like true labels
        :param proba: array-like of shape [n_samples, 2] with predicted probabilities
        :param sample_weight: array-like weight

        :rtype: tuple(array, array)
        :return: thresholds and corresponding metric values
        """
        y_true, proba, sample_weight = check_arrays(y_true, proba, sample_weight)
        pred = proba[:, self.signal_label]
        b, s, thresholds = roc_curve(y_true == self.signal_label, pred,
                                     sample_weight=sample_weight)

        metric_values = self.metric(s * self.expected_s, b * self.expected_b)
        thresholds = numpy.clip(thresholds, pred.min() - 1e-6, pred.max() + 1e-6)
        return thresholds, metric_values

    def plot_vs_cut(self, y_true, proba, sample_weight=None):
        """
        Compute metric for each possible prediction threshold

        :param y_true: array-like true labels
        :param proba: array-like of shape [n_samples, 2] with predicted probabilities
        :param sample_weight: array-like weight

        :rtype: plotting.FunctionsPlot
        """
        from .. import plotting

        y_true, proba, sample_weight = check_arrays(y_true, proba, sample_weight)
        ordered_proba, metrics_val = self.compute(y_true, proba, sample_weight)
        ind = numpy.argmax(metrics_val)

        print('Optimal cut=%1.4f, quality=%1.4f' % (ordered_proba[ind], metrics_val[ind]))

        plot_fig = plotting.FunctionsPlot({self.metric.__name__: (ordered_proba, metrics_val)})
        plot_fig.xlabel = 'cut'
        plot_fig.ylabel = 'metrics ' + self.metric.__name__
        return plot_fig

    def __call__(self, y_true, proba, sample_weight=None):
        """ proba is predicted probabilities of shape [n_samples, 2] """
        thresholds, metrics_val = self.compute(y_true, proba, sample_weight)
        return numpy.max(metrics_val)


def significance(s, b):
    """
    Approximate significance of discovery:
     s / sqrt(b).
    Here we use normalization, so maximal s and b are equal to 1.
    """
    return s / numpy.sqrt(b + 1e-6)


class OptimalSignificance(OptimalMetric):
    def __init__(self, expected_s=1., expected_b=1.):
        OptimalMetric.__init__(self, metric=significance,
                               expected_s=expected_s,
                               expected_b=expected_b)


def ams(s, b, br=10.):
    """
    Regularized approximate median significance
    :param s: amount of signal passed
    :param b: amount of background passed
    :param br: regularization
    """
    radicand = 2 * ((s + b + br) * numpy.log(1.0 + s / (b + br)) - s)
    return numpy.sqrt(radicand)


class OptimalAMS(OptimalMetric):
    def __init__(self, expected_s=691.988607712, expected_b=410999.847):
        """
        Optimal values of AMS (average median significance)
        default values of expected_s and expected_b are from HiggsML challenge.
        :param expected_s: float, expected amount of signal
        :param expected_b: float, expected amount of background
        """
        OptimalMetric.__init__(self, metric=ams,
                               expected_s=expected_s,
                               expected_b=expected_b)

