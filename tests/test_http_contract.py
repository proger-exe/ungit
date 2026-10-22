from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from ungit_core import CoreClient, CoreClientError, CoreServiceStore
from ungit_core import add_files, build_delivery_payload, create_commit
from ungit_core.service import CoreRequestHandler
from ungit_storage import ensure_repository


def test_all_mvp_http_routes_enforce_user_and_agent_boundaries(tmp_path):
    store = CoreServiceStore(tmp_path / "core")
    alice = store.create_user("alice")["token"]
    bob = store.create_user("bob")["token"]

    class Handler(CoreRequestHandler):
        core_store = store

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            owner = CoreClient(url, alice)
            stranger = CoreClient(url, bob)
            anonymous = CoreClient(url)
            assert owner.whoami()["user"]["login"] == "alice"
            repo = owner.upsert_repo("demo")
            agent = owner.upsert_agent("prod")
            agent_token = owner.create_agent_token(agent["id"])["token"]
            worker = CoreClient(url, agent_token)
            assert worker.whoami()["agent"]["id"] == agent["id"]
            assert owner.link_agent(repo["id"], agent["id"])["pipeline"] == [agent["id"]]
            assert owner.set_pipeline(repo["id"], [agent["id"]])["pipeline"] == [agent["id"]]

            source = tmp_path / "source"
            local = ensure_repository(source)
            (source / "app.txt").write_text("demo")
            add_files(local, source, ["."])
            commit = create_commit(local, "master", "test")
            archive, digest = build_delivery_payload(local, source, project="demo", branch="master",
                                                     commit_id=commit, output_dir=tmp_path / "delivery")
            push_args = dict(branch="master", commit=commit, payload_hash=digest, archive=archive)
            result = owner.push_repo(repo["id"], **push_args)
            job = result["jobs"][0]

            protected = [
                lambda c: c.whoami(),
                lambda c: c.upsert_repo("another"),
                lambda c: c.upsert_agent("another"),
                lambda c: c.create_agent_token(agent["id"]),
                lambda c: c.link_agent(repo["id"], agent["id"]),
                lambda c: c.set_pipeline(repo["id"], [agent["id"]]),
                lambda c: c.push_repo(repo["id"], **push_args),
                lambda c: c.claim_job(agent["id"]),
                lambda c: c.download_job_payload(job["id"], tmp_path / "anonymous-download"),
                lambda c: c.add_event(job["id"], "success", "not authorized"),
            ]
            for request in protected:
                with pytest.raises(CoreClientError, match="missing bearer token"):
                    request(anonymous)

            for request in protected[3:]:
                with pytest.raises(CoreClientError, match="cannot"):
                    request(stranger)
            with pytest.raises(CoreClientError, match="cannot claim"):
                owner.claim_job(agent["id"])

            assert worker.claim_job(agent["id"])["id"] == job["id"]
            downloaded = worker.download_job_payload(job["id"], tmp_path / "received.tar.gz")
            assert downloaded.read_bytes() == archive.read_bytes()
            worker.add_event(job["id"], "success", "[deploy] success")
            assert store.get_job(job["id"])["status"] == "success"
            assert worker.claim_job(agent["id"]) is None
        finally:
            server.shutdown()
            thread.join(timeout=5)
