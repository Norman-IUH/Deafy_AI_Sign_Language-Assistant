"""Rank real softmax output, without inventing labels or confidence values."""
import math
from sign_vocabulary import VOCABULARY


def ranked_labels(probabilities, class_to_idx):
    if len(probabilities) != len(class_to_idx) or sorted(class_to_idx.values()) != list(range(len(probabilities))) \
            or not all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities) \
            or not math.isclose(sum(probabilities), 1, abs_tol=1e-4):
        raise ValueError('Invalid model probabilities')
    inverse = {index: label.lower() for label, index in class_to_idx.items()}
    return [{'label': inverse[i], 'text': VOCABULARY.get(inverse[i], inverse[i]), 'confidence': probabilities[i]}
            for i in sorted(range(len(probabilities)), key=lambda i: probabilities[i], reverse=True)[:3]]
