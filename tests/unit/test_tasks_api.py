import importlib
import json
import time

import boto3
import pytest
from moto import mock_aws

USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000002"


class Ctx:
    function_name = "test"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test"
    aws_request_id = "req"


def api_event(user=USER_A, body=None, task_id=None, query=None):
    return {
        "body": None if body is None else json.dumps(body),
        "pathParameters": {"taskId": task_id} if task_id else None,
        "queryStringParameters": query,
        "requestContext": {
            "requestId": "abc",
            "authorizer": {"claims": {"sub": user, "email": f"{user[:4]}@example.com"}},
        },
    }


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "todo-test-table")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="todo-test-table",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "GSI1PK", "GSI1SK")
            ],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        boto3.client("scheduler").create_schedule_group(Name="todo-test-task-expiry")
        import common
        importlib.reload(common)
        mods = {}
        for name in ("create_task", "list_tasks", "get_task", "update_task", "delete_task"):
            mods[name] = importlib.reload(importlib.import_module(name))
        yield mods


def call(mod, event):
    res = mod.handler(event, Ctx())
    assert res["headers"]["Access-Control-Allow-Origin"] == "*"
    return res["statusCode"], (json.loads(res["body"]) if res["body"] else None)


def create(api, user=USER_A, **body):
    body.setdefault("description", "Write the report")
    return call(api["create_task"], api_event(user=user, body=body))


def test_create_defaults_to_pending_with_five_minute_deadline(api):
    status, task = create(api)
    assert status == 201
    assert task["status"] == "Pending"
    assert task["userId"] == USER_A
    assert 290 <= task["deadlineEpoch"] - int(time.time()) <= 301
    assert len(task["taskId"]) == 36


def test_create_validates_input(api):
    assert create(api, description="  ")[0] == 400
    assert create(api, date="03-10-2026")[0] == 400
    assert create(api, deadlineMinutes=0)[0] == 400
    assert create(api, deadlineMinutes=2)[0] == 201


def test_list_and_filter_by_status(api):
    _, t1 = create(api, description="one")
    create(api, description="two")
    call(api["update_task"], api_event(task_id=t1["taskId"], body={"status": "Completed"}))

    _, all_tasks = call(api["list_tasks"], api_event())
    assert all_tasks["count"] == 2
    _, pending = call(api["list_tasks"], api_event(query={"status": "Pending"}))
    _, completed = call(api["list_tasks"], api_event(query={"status": "Completed"}))
    assert [t["description"] for t in pending["items"]] == ["two"]
    assert [t["description"] for t in completed["items"]] == ["one"]
    assert call(api["list_tasks"], api_event(query={"status": "Bogus"}))[0] == 400


def test_users_cannot_see_or_touch_each_others_tasks(api):
    _, task = create(api, user=USER_A)
    tid = task["taskId"]
    assert call(api["get_task"], api_event(user=USER_B, task_id=tid))[0] == 404
    assert call(api["update_task"], api_event(user=USER_B, task_id=tid, body={"description": "x"}))[0] == 404
    assert call(api["delete_task"], api_event(user=USER_B, task_id=tid))[0] == 404
    assert call(api["list_tasks"], api_event(user=USER_B))[1]["count"] == 0


def test_update_edit_then_complete_then_locked(api):
    _, task = create(api)
    tid = task["taskId"]
    status, updated = call(api["update_task"], api_event(task_id=tid, body={"description": "Edited", "date": "2026-12-01"}))
    assert status == 200 and updated["description"] == "Edited" and updated["date"] == "2026-12-01"

    status, done = call(api["update_task"], api_event(task_id=tid, body={"status": "Completed"}))
    assert status == 200 and done["status"] == "Completed" and done["completedAt"]

    status, err = call(api["update_task"], api_event(task_id=tid, body={"description": "again"}))
    assert status == 409 and "Completed" in err["message"]


def test_update_rejects_bad_status_and_fields(api):
    _, task = create(api)
    tid = task["taskId"]
    assert call(api["update_task"], api_event(task_id=tid, body={"status": "Expired"}))[0] == 400
    assert call(api["update_task"], api_event(task_id=tid, body={"userId": USER_B}))[0] == 400
    assert call(api["update_task"], api_event(task_id=tid, body={}))[0] == 400


def test_get_and_delete(api):
    _, task = create(api)
    tid = task["taskId"]
    assert call(api["get_task"], api_event(task_id=tid))[1]["taskId"] == tid
    assert call(api["delete_task"], api_event(task_id=tid)) == (204, None)
    assert call(api["get_task"], api_event(task_id=tid))[0] == 404
    assert call(api["delete_task"], api_event(task_id=tid))[0] == 404


def test_create_schedules_one_time_expiry(api):
    _, task = create(api, deadlineMinutes=2)
    sched = boto3.client("scheduler").get_schedule(Name=f"task-{task['taskId']}", GroupName="todo-test-task-expiry")
    assert sched["ScheduleExpression"].startswith("at(")
    assert json.loads(sched["Target"]["Input"]) == {"userId": USER_A, "taskId": task["taskId"]}
    assert sched["Target"]["Arn"].endswith("todo-test-expire-task")
