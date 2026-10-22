from concurrent.futures import ThreadPoolExecutor

from ungit_core import CoreServiceStore
import ungit_core.service_store as service_store


def test_jobs_claim_in_push_order_once_under_concurrent_polling(tmp_path, monkeypatch):
    store = CoreServiceStore(tmp_path / "core")
    repo = store.upsert_repo("demo")
    agent = store.upsert_agent("prod")
    store.link_agent(repo["id"], agent["id"])
    archive = tmp_path / "archive"
    archive.write_bytes(b"test delivery")
    # Reverse IDs must not reorder pushes created in the same second.
    ids = iter(["push_z", "job_z", "push_a", "job_a"])
    monkeypatch.setattr(service_store, "_random_id", lambda _: next(ids))
    for n in (1, 2):
        store.create_push(repo["id"], branch="master", commit=f"commit{n}",
                          payload_hash="test", payload_path=archive)
    assert store.claim_job(agent["id"])["id"] == "job_z"
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: store.claim_job(agent["id"]), range(8)))
    assert [j["id"] for j in jobs if j] == ["job_a"]
