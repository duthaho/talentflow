from unittest.mock import Mock

import pytest

from app.modules.organization.application.ports import RequisitionView
from app.modules.organization.application.set_requisition_publication import (
    RequisitionNotFoundError,
    SetRequisitionPublicationHandler,
)


@pytest.mark.parametrize("found", [True, False])
def test_publication_commits_only_when_requisition_belongs_to_tenant(found):
    repository, unit_of_work = Mock(), Mock()
    view = RequisitionView("job", "Engineer", "Engineering", True)
    repository.set_publication.return_value = view if found else None
    handler = SetRequisitionPublicationHandler(repository, unit_of_work)
    command = dict(
        tenant_id="tenant",
        requisition_id="job",
        published=True,
        actor_id="admin",
        correlation_id="correlation",
    )
    if found:
        assert handler.handle(**command) == view
        unit_of_work.commit.assert_called_once_with()
    else:
        with pytest.raises(RequisitionNotFoundError):
            handler.handle(**command)
        unit_of_work.commit.assert_not_called()
    repository.set_publication.assert_called_once_with(**command)
