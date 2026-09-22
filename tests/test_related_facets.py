import pytest
from pydantic import ValidationError
from app.domain import ReviewIssue
from tests.test_story import issue

def test_multiple_related_facets():
    data=issue();data['related_facets']=['props','plot','actions']
    assert ReviewIssue.model_validate(data).related_facets == ['props','plot','actions']

def test_unknown_facet_rejected():
    data=issue();data['related_facets']=['invented']
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(data)

def test_old_review_compatible():
    assert ReviewIssue.model_validate(issue()).related_facets == []
