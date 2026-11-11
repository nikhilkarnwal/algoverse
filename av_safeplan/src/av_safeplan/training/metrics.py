"""Masked binary metrics; one-class ranking metrics are undefined, not zero."""
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score
from av_safeplan.training.data import HAZARDS


def summarize(targets, probabilities, masks):
    report = {}
    for i, hazard in enumerate(HAZARDS):
        keep = masks[:, i].astype(bool)
        y, p = targets[keep, i], probabilities[keep, i]
        pred = p >= .5
        both = len(np.unique(y)) == 2
        report[hazard] = {
            'n': len(y), 'positives': int(y.sum()), 'threshold': .5,
            'brier': float(np.mean((p-y)**2)) if len(y) else None,
            'average_precision': float(average_precision_score(y, p)) if both else None,
            'auroc': float(roc_auc_score(y, p)) if both else None,
            'tp': int(np.sum(pred & (y == 1))), 'fp': int(np.sum(pred & (y == 0))),
            'fn': int(np.sum(~pred & (y == 1))), 'tn': int(np.sum(~pred & (y == 0))),
            'warning': None if both else 'missing_class_or_no_reviewed_labels'}
    return report
