import pytest

from app.modules.offers.domain.approval_policy import ApprovalPolicy, ApprovalStep


def test_standard_offer_requires_hiring_manager_then_tenant_admin() -> None:
    policy = ApprovalPolicy.standard()
    assert policy.steps == (ApprovalStep(1, "hiring_manager"), ApprovalStep(2, "tenant_admin"))


def test_policy_rejects_unknown_step() -> None:
    with pytest.raises(ValueError, match="Unknown approval step"):
        ApprovalPolicy.standard().required_role(3)


def test_policy_returns_steps_owned_by_each_role() -> None:
    policy = ApprovalPolicy.standard()

    assert policy.steps_for_role("hiring_manager") == frozenset({1})
    assert policy.steps_for_role("tenant_admin") == frozenset({2})
    assert policy.steps_for_role("recruiter") == frozenset()
