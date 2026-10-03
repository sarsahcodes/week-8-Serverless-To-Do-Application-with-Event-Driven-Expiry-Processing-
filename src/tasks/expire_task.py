"""EventBridge Scheduler target: expire a task at its deadline.

Input (set by CreateTask on the schedule): {"userId": "<sub>", "taskId": "<uuid>"}

1. Conditional UpdateItem: Status Pending -> Expired. The condition makes this
   safe against races - a task that was Completed or Deleted before the
   deadline is left alone (no email), even if the cancellation workflow has
   not removed the schedule yet.
2. Publish to the SNS topic with message attribute userId. Each user's email
   subscription has a filter policy on userId, so only the owner is emailed.
3. Record NotifiedAt on the item.

Idempotent / retry-safe: Scheduler and Lambda async invocation may retry. If
the status update succeeded but the publish failed, the retry finds the task
already Expired without NotifiedAt and sends the email then; if NotifiedAt is
set, nothing more happens.
"""
import os

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

import common

logger = Logger()
metrics = Metrics()

TOPIC_ARN = os.environ["TOPIC_ARN"]
sns = boto3.client("sns")


def _mark_expired(uid: str, task_id: str):
    """Returns (item, newly_expired). item is None if the task no longer exists."""
    now = common.iso(common.now_utc())
    try:
        result = common.table.update_item(
            Key=common.task_key(uid, task_id),
            UpdateExpression="SET #Status = :expired, ExpiredAt = :now, UpdatedAt = :now, GSI1SK = :gsi1sk",
            ConditionExpression="attribute_exists(PK) AND #Status = :pending",
            ExpressionAttributeNames={"#Status": "Status"},
            ExpressionAttributeValues={
                ":expired": common.EXPIRED,
                ":pending": common.PENDING,
                ":now": now,
                ":gsi1sk": common.gsi1_sk(common.EXPIRED, now),
            },
            ReturnValues="ALL_NEW",
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
        return result["Attributes"], True
    except ClientError as err:
        if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        old = err.response.get("Item")
        if not old:
            return None, False
        # Low-level attribute format on condition failure -> plain dict
        return {k: list(v.values())[0] for k, v in old.items()}, False


def _notify(item: dict) -> None:
    description = item["Description"]
    subject = f"Task expired: {description}"
    if len(subject) > 100:  # SNS subject limit
        subject = subject[:97] + "..."
    message = (
        f"Your task has expired without being completed.\n\n"
        f"Task:      {description}\n"
        f"Due date:  {item.get('Date', '-')}\n"
        f"Deadline:  {item.get('DeadlineISO', '-')} (UTC)\n"
        f"Task ID:   {item['TaskId']}\n\n"
        f"Open the To-Do app to review your expired tasks."
    )
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=subject,
        Message=message,
        MessageAttributes={"userId": {"DataType": "String", "StringValue": item["UserId"]}},
    )
    common.table.update_item(
        Key=common.task_key(item["UserId"], item["TaskId"]),
        UpdateExpression="SET NotifiedAt = :now",
        ConditionExpression="attribute_exists(PK)",
        ExpressionAttributeValues={":now": common.iso(common.now_utc())},
    )


@logger.inject_lambda_context
@metrics.log_metrics
def handler(event, _context):
    uid, task_id = event["userId"], event["taskId"]
    logger.append_keys(user_id=uid, task_id=task_id)

    item, newly_expired = _mark_expired(uid, task_id)

    if item is None:
        logger.info("Task no longer exists (deleted before deadline); nothing to do")
        return {"result": "skipped", "reason": "deleted"}

    if not newly_expired and item.get("Status") != common.EXPIRED:
        logger.info("Task is not Pending; expiry skipped", extra={"status": item.get("Status")})
        return {"result": "skipped", "reason": item.get("Status")}

    if newly_expired:
        metrics.add_metric(name="TasksExpired", unit=MetricUnit.Count, value=1)
        logger.info("Task marked Expired")

    if item.get("NotifiedAt"):
        logger.info("Owner already notified; nothing to do")
        return {"result": "already-notified"}

    try:
        _notify(item)
    except ClientError:
        metrics.add_metric(name="ExpiryNotificationFailures", unit=MetricUnit.Count, value=1)
        logger.exception("Failed to send expiry notification; raising so the invocation is retried")
        raise
    metrics.add_metric(name="ExpiryNotificationsSent", unit=MetricUnit.Count, value=1)
    logger.info("Expiry notification published")
    return {"result": "expired", "notified": True}
