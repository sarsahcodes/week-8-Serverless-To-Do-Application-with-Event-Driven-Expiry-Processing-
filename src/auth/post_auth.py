"""Cognito PostAuthentication trigger.

Subscribes the signed-in user's email address to the task notifications SNS
topic. The subscription carries a filter policy on ``userId`` so that each
user only receives notifications published for their own tasks.

The trigger runs on every sign-in, so it is idempotent:
  * a USER#<sub> / PROFILE item records the subscription;
  * if that subscription is confirmed, nothing happens;
  * if it is still pending (or was removed / expired), Subscribe is called
    again, which re-sends the confirmation email.

Errors are logged but never raised: a failing PostAuthentication trigger
would block the user from signing in.
"""
import json
import os
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

logger = Logger()
metrics = Metrics(namespace="TodoApp")

TABLE_NAME = os.environ["TABLE_NAME"]
TOPIC_ARN = os.environ["TOPIC_ARN"]

sns = boto3.client("sns")
table = boto3.resource("dynamodb").Table(TABLE_NAME)


def _profile_key(user_id: str) -> dict:
    return {"PK": f"USER#{user_id}", "SK": "PROFILE"}


def _is_confirmed(subscription_arn: str) -> bool:
    """True if the SNS subscription exists and the user has confirmed it."""
    if not subscription_arn or not subscription_arn.startswith("arn:"):
        return False
    try:
        attrs = sns.get_subscription_attributes(SubscriptionArn=subscription_arn)["Attributes"]
        return attrs.get("PendingConfirmation") == "false"
    except ClientError as err:
        if err.response["Error"]["Code"] == "NotFound":
            return False  # unsubscribed, or pending subscription expired
        raise


def _subscribe(user_id: str, email: str) -> str:
    resp = sns.subscribe(
        TopicArn=TOPIC_ARN,
        Protocol="email",
        Endpoint=email,
        Attributes={"FilterPolicy": json.dumps({"userId": [user_id]})},
        ReturnSubscriptionArn=True,
    )
    return resp["SubscriptionArn"]


@logger.inject_lambda_context
@metrics.log_metrics
def handler(event, _context):
    attrs = event.get("request", {}).get("userAttributes", {})
    user_id = attrs.get("sub")
    email = attrs.get("email")
    logger.append_keys(user_id=user_id)

    if not user_id or not email:
        logger.warning("PostAuthentication event without sub/email; skipping subscription")
        return event

    try:
        profile = table.get_item(Key=_profile_key(user_id)).get("Item")

        if profile and profile.get("Email") == email and _is_confirmed(profile.get("SubscriptionArn", "")):
            logger.info("User already subscribed and confirmed")
            return event

        subscription_arn = _subscribe(user_id, email)
        now = datetime.now(timezone.utc).isoformat()
        table.put_item(
            Item={
                **_profile_key(user_id),
                "EntityType": "PROFILE",
                "UserId": user_id,
                "Email": email,
                "SubscriptionArn": subscription_arn,
                "SubscribedAt": profile.get("SubscribedAt", now) if profile else now,
                "UpdatedAt": now,
            }
        )
        metrics.add_metric(name="NotificationSubscriptionsRequested", unit=MetricUnit.Count, value=1)
        logger.info("Subscription requested; confirmation email sent", extra={"subscription_arn": subscription_arn})
    except Exception:  # never block sign-in
        logger.exception("Failed to subscribe user to task notifications")

    return event
