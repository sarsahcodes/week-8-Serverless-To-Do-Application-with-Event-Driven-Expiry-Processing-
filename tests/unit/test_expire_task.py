import importlib
import json

import boto3
import pytest
from moto import mock_aws

USER = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER = "bbbbbbbb-0000-0000-0000-000000000002"
TOPIC_NAME = "todo-test-task-notifications"


class Ctx:
    function_name = "expire"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:expire"
    aws_request_id = "req"


@pytest.fixture
def env():
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="todo-test-table",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK")],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        )
        sns = boto3.client("sns")
        topic = sns.create_topic(Name=TOPIC_NAME)["TopicArn"]
        sqs = boto3.client("sqs")

        # One SQS "inbox" per user, subscribed with the same filter policy the email subscriptions use.
        inbox = {}
        for user in (USER, OTHER):
            url = sqs.create_queue(QueueName=f"inbox-{user[:4]}")["QueueUrl"]
            arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn,
                          Attributes={"FilterPolicy": json.dumps({"userId": [user]}), "RawMessageDelivery": "false"})
            inbox[user] = url

        import common
        importlib.reload(common)
        import expire_task
        importlib.reload(expire_task)
        table = boto3.resource("dynamodb").Table("todo-test-table")
        yield expire_task, table, sqs, inbox


def put_task(table, status="Pending", task_id="t-1", user=USER):
    table.put_item(Item={
        "PK": f"USER#{user}", "SK": f"TASK#{task_id}", "TaskId": task_id, "UserId": user,
        "Description": "Submit lab report", "Date": "2026-10-04", "Status": status,
        "Deadline": 1, "DeadlineISO": "2026-10-03T19:05:00Z",
    })


def messages(sqs, url):
    return sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])


def item(table, task_id="t-1", user=USER):
    return table.get_item(Key={"PK": f"USER#{user}", "SK": f"TASK#{task_id}"}).get("Item")


def test_pending_task_expires_and_only_owner_is_notified(env):
    expire_task, table, sqs, inbox = env
    put_task(table)
    result = expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx())

    assert result == {"result": "expired", "notified": True}
    saved = item(table)
    assert saved["Status"] == "Expired" and saved["ExpiredAt"] and saved["NotifiedAt"]
    assert saved["GSI1SK"].startswith("STATUS#Expired#")
    owner_msgs = messages(sqs, inbox[USER])
    assert len(owner_msgs) == 1
    assert "Submit lab report" in json.loads(owner_msgs[0]["Body"])["Message"]
    assert messages(sqs, inbox[OTHER]) == []


def test_completed_task_is_not_expired(env):
    expire_task, table, sqs, inbox = env
    put_task(table, status="Completed")
    assert expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx())["result"] == "skipped"
    assert item(table)["Status"] == "Completed"
    assert messages(sqs, inbox[USER]) == []


def test_deleted_task_is_ignored(env):
    expire_task, table, sqs, inbox = env
    assert expire_task.handler({"userId": USER, "taskId": "missing"}, Ctx()) == {"result": "skipped", "reason": "deleted"}
    assert messages(sqs, inbox[USER]) == []


def test_retry_after_success_sends_no_second_email(env):
    expire_task, table, sqs, inbox = env
    put_task(table)
    expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx())
    assert expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx()) == {"result": "already-notified"}
    assert len(messages(sqs, inbox[USER])) == 1


def test_retry_after_failed_publish_sends_the_email(env, monkeypatch):
    expire_task, table, sqs, inbox = env
    put_task(table)
    from botocore.exceptions import ClientError

    real_publish = expire_task.sns.publish
    def failing(**_kw):
        raise ClientError({"Error": {"Code": "Throttling", "Message": "x"}}, "Publish")
    monkeypatch.setattr(expire_task.sns, "publish", failing)
    with pytest.raises(ClientError):
        expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx())
    assert item(table)["Status"] == "Expired" and "NotifiedAt" not in item(table)

    monkeypatch.setattr(expire_task.sns, "publish", real_publish)
    assert expire_task.handler({"userId": USER, "taskId": "t-1"}, Ctx()) == {"result": "expired", "notified": True}
    assert len(messages(sqs, inbox[USER])) == 1
