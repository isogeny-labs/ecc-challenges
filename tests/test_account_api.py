from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from ecc_challenges.app import create_app
from ecc_challenges.service import Service


def account_client(database, storage, settings):
    service = Service(database, storage, settings)
    service.upsert_account(31, "cli-person")
    secret = service.create_key(31, "laptop")
    return service, secret, TestClient(create_app(settings, db=database, storage=storage))


def age_keys(database, account_id):
    with database.connection() as conn:
        conn.execute("UPDATE ecc_public.api_keys SET created_at=now()-interval '2 minutes' "
                     "WHERE account_id=%s", (account_id,))


def test_account_endpoints_require_a_key(database, aws_resources, settings):
    client = TestClient(create_app(settings, db=database, storage=aws_resources[0]))
    assert client.get("/v1/account").status_code == 401
    assert client.get("/v1/account/runs").status_code == 401
    assert client.post("/v1/account/leaderboard", json={"visible": True}).status_code == 401
    assert client.get("/v1/account",
                      headers={"Authorization": "Bearer ecc1_bogus"}).status_code == 401


def test_account_summary_keys_leaderboard_and_runs(database, aws_resources, settings):
    service, secret, client = account_client(database, aws_resources[0], settings)
    headers = {"Authorization": f"Bearer {secret}"}

    body = client.get("/v1/account", headers=headers).json()
    assert body["account"]["login"] == "cli-person"
    assert body["account"]["leaderboard_visible"] is False
    assert [key["label"] for key in body["keys"]] == ["laptop"]
    assert body["runs"]["total_runs"] == 0

    key = service.authenticate(secret)
    run_id = service.register(key, str(uuid.uuid4()))["run_id"]
    runs = client.get("/v1/account/runs", headers=headers).json()
    assert runs["total_runs"] == 1 and runs["runs"][0]["id"] == str(run_id)
    assert runs["runs"][0]["campaign"] == "ecc2k-130"

    detail = client.get(f"/v1/account/runs/v1/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["verification_state"] == "No submissions yet"

    # Another account's run is not visible.
    service.upsert_account(32, "someone-else")
    other = service.create_key(32, "other")
    denied = client.get(f"/v1/account/runs/v1/{run_id}",
                        headers={"Authorization": f"Bearer {other}"})
    assert denied.status_code == 404

    age_keys(database, 31)
    created = client.post("/v1/account/keys", headers=headers, json={"label": "second"})
    assert created.status_code == 201 and created.json()["key"].startswith("ecc1_")
    assert client.post("/v1/account/keys", headers=headers,
                       json={"label": "too-soon"}).status_code == 429
    assert client.post("/v1/account/keys", headers=headers,
                       json={"label": 3}).status_code == 400

    listed = client.post("/v1/account/leaderboard", headers=headers, json={"visible": True})
    assert listed.json() == {"leaderboard_visible": True}
    assert service.leaderboard_visible(31) is True
    assert client.post("/v1/account/leaderboard", headers=headers,
                       json={"visible": "yes"}).status_code == 400

    keys = client.get("/v1/account/keys", headers=headers).json()["keys"]
    assert {key["label"] for key in keys} == {"laptop", "second"}
    first = next(key for key in keys if key["label"] == "laptop")
    revoked = client.post(f"/v1/account/keys/{first['id']}/revoke", headers=headers,
                          content=b"")
    assert revoked.status_code == 200 and revoked.json()["revoked"] == first["id"]
    with database.connection() as conn:
        suspended = conn.execute("SELECT suspended_at FROM ecc_public.runs WHERE run_id=%s",
                                 (run_id,)).fetchone()["suspended_at"]
    assert suspended is not None
