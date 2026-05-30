"""RQ worker entrypoint."""
from __future__ import annotations

from redis import Redis
from rq import Connection, Queue, Worker
from shotclassify_common import (
    configure_logging,
    get_logger,
    get_settings,
    init_sentry,
    validate_for_production,
)
from shotclassify_store import init_db

log = get_logger(__name__)


def main() -> None:
    s = get_settings()
    configure_logging(level=s.app_log_level, fmt=s.app_log_format)
    # Match the API: refuse to come up in prod/staging with dev defaults.
    validate_for_production(s)
    init_sentry(service_name="shotclassify-worker")
    init_db()
    redis = Redis.from_url(s.redis_url)
    log.info("worker_starting", queue=s.queue_name, redis=s.redis_url)
    with Connection(redis):
        Worker([Queue(s.queue_name)]).work(with_scheduler=True)


if __name__ == "__main__":
    main()
