import os
import tempfile
import pytest
import json
import hmac
import hashlib
import time
from unittest.mock import patch

# =================================================================
# SET ENVIRONMENT VARIABLES BEFORE IMPORT
# =================================================================
TEST_API_KEY = "admin_master_key"
TEST_ADMIN_TOKEN = "super_secret_admin_token"

os.environ["BUS_SECRET"] = TEST_API_KEY
os.environ["BUS_ADMIN_SECRET"] = TEST_ADMIN_TOKEN
os.environ["BUS_REQUIRE_SIGNATURES"] = "false"

import flask_app

@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp()
    flask_app.app.config["TESTING"] = True
    
    # FIX: Dynamically patch the module-level DB_PATH so the 
    # test doesn't accidentally use your real infrastructure.db
    original_db_path = flask_app.DB_PATH
    flask_app.DB_PATH = db_path
    
    with flask_app.app.test_client() as client:
        with flask_app.app.app_context():
            flask_app.init_db()
        yield client

    flask_app.DB_PATH = original_db_path
    os.close(db_fd)
    os.unlink(db_path)

# =================================================================
# 1. CAPABILITY ROUTING TEST
# =================================================================
def test_capability_routing(client):
    headers = {"X-API-KEY": TEST_API_KEY}
    
    # Publish a job that strictly requires an 'ffmpeg' worker
    client.post("/intent", headers=headers, json={
        "goal": "process_video",
        "payload": {},
        "required_capability": "ffmpeg"
    })
    
    # 1. Worker with NO capabilities -> Should get 204 No Content
    res1 = client.post("/claim?goal=process_video", headers=headers)
    assert res1.status_code == 204
    
    # 2. Worker with WRONG capability -> Should get 204 No Content
    res2 = client.post("/claim?goal=process_video", headers={
        "X-API-KEY": TEST_API_KEY,
        "X-Worker-Capabilities": "gpu,imagemagick"
    })
    assert res2.status_code == 204
    
    # 3. Worker with the RIGHT capability -> Should get 200 OK
    res3 = client.post("/claim?goal=process_video", headers={
        "X-API-KEY": TEST_API_KEY,
        "X-Worker-Capabilities": "cpu,ffmpeg,gpu"
    })
    assert res3.status_code == 200
    assert res3.json["goal"] == "process_video"

# =================================================================
# 2. RATE LIMITING TEST
# =================================================================
def test_rate_limiting(client):
    admin_headers = {"X-Admin-Token": TEST_ADMIN_TOKEN}
    
    # 1. Generate a restricted 'tester' key using Admin endpoint
    res = client.post("/admin/generate_key", headers=admin_headers, json={"owner": "ci_test"})
    tester_key = res.json["api_key"]
    tester_headers = {"X-API-KEY": tester_key}

    # 2. Blast the server with exactly 60 requests (the max limit)
    for _ in range(60):
        r = client.post("/intent", headers=tester_headers, json={"goal": "spam", "payload": {}})
        assert r.status_code == 201

    # 3. The 61st request MUST be rejected by the server
    r_fail = client.post("/intent", headers=tester_headers, json={"goal": "spam", "payload": {}})
    assert r_fail.status_code == 429
    assert "Too many requests" in r_fail.json["error"]["message"]

# =================================================================
# 3. CRYPTOGRAPHIC SIGNATURE & REPLAY TEST
# =================================================================
def test_cryptographic_signatures(client):
    # Note: Even if REQUIRE_SIGNATURES=false, providing X-Signature forces validation.
    timestamp = str(int(time.time()))
    nonce = "unique-nonce-001"
    body = b'{"goal":"secure_task","payload":{}}'
    
    # Construct the exact canonical message the server expects
    msg = b"POST\n/intent\n" + timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    sig = hmac.new(TEST_API_KEY.encode(), msg, hashlib.sha256).hexdigest()

    headers = {
        "X-API-KEY": TEST_API_KEY,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": sig
    }

    # 1. Valid Signature should pass
    res = client.post("/intent", headers=headers, data=body, content_type="application/json")
    assert res.status_code == 201

    # 2. Replay Attack (Using the exact same signature and nonce a second time)
    res_replay = client.post("/intent", headers=headers, data=body, content_type="application/json")
    assert res_replay.status_code == 403
    assert "Replay detected" in res_replay.json["error"]["message"]

    # 3. Forged Signature
    headers["X-Nonce"] = "unique-nonce-002"
    headers["X-Signature"] = "deadbeef1234567890badsignature"
    res_bad = client.post("/intent", headers=headers, data=body, content_type="application/json")
    assert res_bad.status_code == 403
    assert "Bad signature" in res_bad.json["error"]["message"]

# =================================================================
# 4. DEAD-LETTER & BACKOFF TEST (Time Travel)
# =================================================================
@patch("flask_app.now")
def test_dead_letters_and_backoff(mock_now, client):
    # We mock time so we don't have to literally wait for the backoff delay
    current_time = time.time()
    mock_now.return_value = current_time
    headers = {"X-API-KEY": TEST_API_KEY}
    admin_headers = {"X-Admin-Token": TEST_ADMIN_TOKEN}

    # Publish intent with a strict limit of 2 attempts
    client.post("/intent", headers=headers, json={
        "goal": "fragile_task",
        "payload": {},
        "max_attempts": 2
    })

    # ATTEMPT 1: Claim and Fail
    claim1 = client.post("/claim?goal=fragile_task", headers=headers)
    iid = claim1.json["id"]
    client.post(f"/fail/{iid}", headers=headers, json={"error": "first crash"})

    # Fast-forward time by 100 seconds to bypass the exponential backoff jitter
    current_time += 100
    mock_now.return_value = current_time

    # ATTEMPT 2: Claim and Fail again (Hitting the max_attempts limit)
    claim2 = client.post("/claim?goal=fragile_task", headers=headers)
    assert claim2.status_code == 200
    client.post(f"/fail/{iid}", headers=headers, json={"error": "fatal crash"})

    # FAST-FORWARD AGAIN
    current_time += 100
    mock_now.return_value = current_time

    # ATTEMPT 3: The queue should be empty because the intent is DEAD
    claim3 = client.post("/claim?goal=fragile_task", headers=headers)
    assert claim3.status_code == 204 

    # Verify it was safely archived into the Dead Letter Queue
    dead_res = client.get("/admin/dead", headers=admin_headers)
    assert dead_res.status_code == 200
    assert len(dead_res.json) == 1
    assert dead_res.json[0]["reason"] == "fatal crash"

# =================================================================
# 5. ADMIN ISOLATION TEST
# =================================================================
def test_admin_isolation(client):
    # Generate a tester key using the correct admin token
    res = client.post("/admin/generate_key", headers={"X-Admin-Token": TEST_ADMIN_TOKEN}, json={"owner": "hacker"})
    tester_key = res.json["api_key"]
    
    # Try to execute an admin command (purge DB) using the standard tester key
    hacker_res = client.post("/admin/purge", headers={"X-API-KEY": tester_key}, json={"confirm": True})
    
    # Must be denied
    assert hacker_res.status_code == 401
    assert "Authentication required" in hacker_res.text
