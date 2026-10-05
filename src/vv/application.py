import hmac
import time

from vv.constraints import comparable_report, live_report, local_report, normalize_request
from vv.errors import Code, VVError
from vv.models import Basket, Request, State, Status
from vv.provider import Provider
from vv.store import Store, checked_hash


def idle(basket: Basket):
    if basket.link_attempt != "none":
        raise VVError(
            Code.OUTCOME_UNKNOWN, "A prior link attempt is pending or uncertain; do not retry."
        )


class Application:
    def __init__(self, store: Store, provider: Provider):
        self.store = store
        self.provider = provider

    def import_request(self, name: str, request: Request):
        return self.store.import_request(name, normalize_request(request))

    def check(self, name: str, refresh: bool = False):
        basket = self.store.show(name)
        idle(basket)
        report = (
            live_report(basket.request, self.provider.refresh(basket.request))
            if refresh
            else local_report()
        )
        with self.store.transaction() as connection:
            current = self.store.load(connection, name)
            idle(current)
            if current != basket:
                raise VVError(Code.REVIEW_REQUIRED, "Basket changed during refresh.")
            basket.report = report
            basket.state = State.CHECKED
            basket.link = None
            basket.check_hash = checked_hash(self.store.profile, basket)
            self.store.save(connection, basket)
        return basket

    def validate_check(self, basket: Basket, supplied_hash: str):
        idle(basket)
        if (
            basket.state not in (State.CHECKED, State.LINK_CREATED)
            or basket.report is None
            or basket.check_hash is None
            or not supplied_hash.isascii()
            or not hmac.compare_digest(basket.check_hash, supplied_hash)
            or not hmac.compare_digest(basket.check_hash, checked_hash(self.store.profile, basket))
            or not basket.report.checked_at <= time.time() < basket.report.expires_at
        ):
            raise VVError(Code.REVIEW_REQUIRED, "Missing, changed or expired basket check.")
        for finding in basket.report.checks.values():
            if finding.blocking and finding.status != Status.PASS:
                code = (
                    Code.CONSTRAINT_FAILED
                    if finding.status == Status.FAIL
                    else Code.REVIEW_REQUIRED
                )
                raise VVError(code, "A required basket check failed or remains unknown.")
        if basket.report.scope != "public_live" or basket.report.payload is None:
            raise VVError(Code.REVIEW_REQUIRED, "Run basket check --refresh first.")

    def link(self, name: str, supplied_hash: str):
        basket = self.store.show(name)
        self.validate_check(basket, supplied_hash)
        if basket.state == State.LINK_CREATED:
            return basket
        fresh = live_report(basket.request, self.provider.refresh(basket.request))
        if comparable_report(fresh) != comparable_report(basket.report):
            raise VVError(
                Code.REVIEW_REQUIRED, "Provider facts changed; run check --refresh and review."
            )
        with self.store.transaction() as connection:
            current = self.store.load(connection, name)
            self.validate_check(current, supplied_hash)
            if current.state == State.LINK_CREATED:
                return current
            if current != basket:
                raise VVError(Code.REVIEW_REQUIRED, "Basket changed before link creation.")
            current.link_attempt = "pending"
            self.store.save(connection, current)
        try:
            link = self.provider.create_link(fresh.payload)
        except Exception as error:
            with self.store.transaction() as connection:
                current = self.store.load(connection, name)
                current.link_attempt = "unknown"
                if isinstance(error, VVError) and error.code in (
                    Code.AUTH_REQUIRED,
                    Code.PROVIDER_ERROR,
                    Code.NETWORK_ERROR,
                ):
                    current.link_attempt = "none"
                self.store.save(connection, current)
            raise
        with self.store.transaction() as connection:
            current = self.store.load(connection, name)
            current.link = link
            current.state = State.LINK_CREATED
            current.link_attempt = "none"
            self.store.save(connection, current)
        return current
