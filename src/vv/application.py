import hmac
import time

from vv.constraints import local_report, normalize_request
from vv.errors import Code, VVError
from vv.models import Request, State, Status
from vv.provider import Provider
from vv.store import Store, checked_hash


class Application:
    def __init__(self, store: Store, provider: Provider):
        self.store = store
        self.provider = provider

    def import_request(self, name: str, request: Request):
        return self.store.import_request(name, normalize_request(request))

    def check(self, name: str, refresh: bool = False):
        with self.store.transaction() as connection:
            basket = self.store.load(connection, name)
            if refresh:
                self.provider.refresh(basket.request)
                raise VVError(Code.NOT_IMPLEMENTED, "Verified snapshot normalization is pending.")
            basket.report = local_report()
            basket.state = State.CHECKED
            basket.link = None
            basket.check_hash = checked_hash(self.store.profile, basket)
            self.store.save(connection, basket)
            return basket

    def link(self, name: str, supplied_hash: str):
        with self.store.transaction() as connection:
            basket = self.store.load(connection, name)
            if (
                basket.state not in (State.CHECKED, State.LINK_CREATED)
                or basket.report is None
                or basket.check_hash is None
                or not hmac.compare_digest(basket.check_hash, supplied_hash)
                or not hmac.compare_digest(
                    basket.check_hash, checked_hash(self.store.profile, basket)
                )
                or not basket.report.checked_at <= time.time() < basket.report.expires_at
            ):
                raise VVError(Code.REVIEW_REQUIRED, "Missing, changed or expired basket check.")
            if any(item.status != Status.PASS for item in basket.report.checks.values()):
                raise VVError(
                    Code.REVIEW_REQUIRED, "Live facts are unknown; local check is not approval."
                )
            raise VVError(
                Code.NOT_IMPLEMENTED,
                "TODO: refresh snapshots, compare, create real link, persist link_created.",
            )
