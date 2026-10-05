import os

import pytest

from vv.application import Application
from vv.errors import Code, VVError
from vv.models import State, Status
from vv.store import Store, checked_hash


def assert_error(code, operation):
    with pytest.raises(VVError) as caught:
        operation()
    assert caught.value.code == code


def test_import_check_and_unknown_link(service, shopping_request):
    imported = service.import_request("dinner", shopping_request)
    assert imported.state == State.DRAFT
    assert imported.check_hash is None
    checked = service.check("dinner")
    assert checked.state == State.CHECKED
    assert checked.report.goods_total is None
    assert checked.report.checks["budget"].status == Status.UNKNOWN
    assert checked.report.checks["hard_exclusions"].status == Status.UNKNOWN
    assert checked.report.checks["quantity"].status == Status.UNKNOWN
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", checked.check_hash))
    assert service.store.show("dinner").state == State.CHECKED


def test_reimport_invalidates_hash_even_if_identical(service, shopping_request):
    service.import_request("dinner", shopping_request)
    previous = service.check("dinner")
    imported = service.import_request("dinner", shopping_request)
    assert imported.revision == 2
    assert imported.state == State.DRAFT
    assert imported.check_hash is None
    assert imported.report is None
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", previous.check_hash))
    assert service.check("dinner").check_hash != previous.check_hash


def test_missing_or_wrong_hash(service, shopping_request):
    service.import_request("dinner", shopping_request)
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", "wrong"))
    service.check("dinner")
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", "wrong"))


def test_expired_check(service, shopping_request, monkeypatch):
    service.import_request("dinner", shopping_request)
    checked = service.check("dinner")
    monkeypatch.setattr("vv.application.time.time", lambda: checked.report.expires_at + 1)
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", checked.check_hash))


def test_hash_covers_constraints_revision_scope_and_report(service, shopping_request):
    service.import_request("dinner", shopping_request)
    checked = service.check("dinner")
    for field in ("revision", "request", "report"):
        changed = checked.model_copy(deep=True)
        if field == "revision":
            changed.revision += 1
        elif field == "request":
            changed.request.constraints.preferences.append("new preference")
        else:
            changed.report.checks["availability"].status = Status.PASS
        assert checked_hash("default", changed) != checked.check_hash
    assert checked_hash("another-profile", checked) != checked.check_hash


def test_hash_detects_modified_stored_request(service, shopping_request):
    service.import_request("dinner", shopping_request)
    checked = service.check("dinner")
    with service.store.transaction() as connection:
        changed = service.store.load(connection, "dinner")
        changed.request.items[0].quantity = "3"
        service.store.save(connection, changed)
    assert_error(Code.REVIEW_REQUIRED, lambda: service.link("dinner", checked.check_hash))


def test_refresh_failure_is_atomic(service, shopping_request):
    service.import_request("dinner", shopping_request)
    before = service.store.show("dinner")
    assert_error(Code.NETWORK_ERROR, lambda: service.check("dinner", refresh=True))
    assert service.store.show("dinner") == before


def test_invalid_import_preserves_existing_basket(service, shopping_request):
    service.import_request("dinner", shopping_request)
    before = service.store.show("dinner")
    invalid = shopping_request.model_copy(deep=True)
    invalid.items.append(invalid.items[0].model_copy(update={"unit": "kg"}))
    assert_error(Code.CONSTRAINT_FAILED, lambda: service.import_request("dinner", invalid))
    assert service.store.show("dinner") == before


def test_profile_isolation(service, shopping_request):
    service.import_request("dinner", shopping_request)
    other = Application(Store(service.store.directory, "other"), service.provider)
    assert_error(Code.NOT_FOUND, lambda: other.store.show("dinner"))


def test_sql_and_path_names_rejected(service, shopping_request):
    for name in ("../escape", "'; DROP TABLE baskets;--", "$(touch bad)", "bad/name"):
        assert_error(
            Code.INVALID_INPUT, lambda name=name: service.import_request(name, shopping_request)
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_private_storage_permissions(service, shopping_request):
    service.import_request("dinner", shopping_request)
    assert service.store.directory.stat().st_mode & 0o777 == 0o700
    assert (service.store.directory / "baskets.sqlite3").stat().st_mode & 0o777 == 0o600
