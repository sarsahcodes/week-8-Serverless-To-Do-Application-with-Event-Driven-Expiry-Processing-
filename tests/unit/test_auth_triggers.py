import importlib
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

EVENTS = Path(__file__).resolve().parents[2] / "events"


class FakeContext:
    function_name = "test-fn"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-fn"
    aws_request_id = "req-1"


def load(name):
    return json.loads((EVENTS / name).read_text())


def test_pre_signup_auto_confirms_and_verifies_email():
    import pre_signup

    result = pre_signup.handler(load("pre_signup.json"), FakeContext())
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is True


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        ddb = boto3.client("dynamodb")
        ddb.create_table(
            TableName="todo-test-table",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
        )
        topic_arn = boto3.client("sns").create_topic(Name="todo-test-topic")["TopicArn"]
        monkeypatch.setenv("TABLE_NAME", "todo-test-table")
        monkeypatch.setenv("TOPIC_ARN", topic_arn)
        import post_auth

        importlib.reload(post_auth)  # pick up env + mocked clients
        yield post_auth, topic_arn


def _subs(topic_arn):
    return boto3.client("sns").list_subscriptions_by_topic(TopicArn=topic_arn)["Subscriptions"]


def test_post_auth_subscribes_with_user_filter_policy(aws):
    post_auth, topic_arn = aws
    event = load("post_auth.json")

    result = post_auth.handler(event, FakeContext())

    assert result is event  # Cognito requires the event back
    subs = _subs(topic_arn)
    assert len(subs) == 1
    assert subs[0]["Endpoint"] == "test.user@example.com"
    attrs = boto3.client("sns").get_subscription_attributes(SubscriptionArn=subs[0]["SubscriptionArn"])["Attributes"]
    assert json.loads(attrs["FilterPolicy"]) == {"userId": ["11111111-2222-3333-4444-555555555555"]}

    item = boto3.resource("dynamodb").Table("todo-test-table").get_item(
        Key={"PK": "USER#11111111-2222-3333-4444-555555555555", "SK": "PROFILE"}
    )["Item"]
    assert item["SubscriptionArn"] == subs[0]["SubscriptionArn"]


def test_post_auth_is_idempotent_on_repeat_sign_in(aws):
    post_auth, topic_arn = aws
    post_auth.handler(load("post_auth.json"), FakeContext())
    post_auth.handler(load("post_auth.json"), FakeContext())
    assert len(_subs(topic_arn)) == 1


def test_post_auth_never_blocks_sign_in(aws, monkeypatch):
    post_auth, _ = aws

    def boom(*_a, **_k):
        raise RuntimeError("SNS down")

    monkeypatch.setattr(post_auth, "_subscribe", boom)
    event = load("post_auth.json")
    assert post_auth.handler(event, FakeContext()) is event
