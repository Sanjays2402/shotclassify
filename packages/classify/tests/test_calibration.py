from shotclassify_classify.calibration import above_threshold, renormalise
from shotclassify_common import Category, Classification, Confidence


def _c(score):
    return Classification(
        primary=Category.receipt,
        confidences=[Confidence(category=Category.receipt, score=score)],
    )


def test_threshold_pass():
    assert above_threshold(_c(0.9), {Category.receipt: 0.7}) is True


def test_threshold_fail():
    assert above_threshold(_c(0.5), {Category.receipt: 0.7}) is False


def test_renormalise_sums_to_one():
    c = Classification(
        primary=Category.receipt,
        confidences=[
            Confidence(category=Category.receipt, score=0.4),
            Confidence(category=Category.meme, score=0.4),
        ],
    )
    r = renormalise(c)
    assert round(sum(x.score for x in r.confidences), 4) == 1.0
