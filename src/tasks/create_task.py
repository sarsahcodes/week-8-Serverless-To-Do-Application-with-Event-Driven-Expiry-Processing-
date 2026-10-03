"""POST /tasks

Body: {"description": str, "date"?: "YYYY-MM-DD", "deadlineMinutes"?: int (1-1440)}

Creates a Pending task whose deadline defaults to DEFAULT_DEADLINE_MINUTES (5)
after creation, plus a one-time EventBridge Scheduler schedule
("task-<taskId>") that invokes the ExpireTask Lambda at the deadline.

Order matters: the schedule is created first. If the DynamoDB write then
fails, the schedule is deleted again; and even if that clean-up failed, the
schedule would fire for a task that does not exist, which ExpireTask ignores.
"""
import json
import os
import uuid
from datetime import timedelta

import boto3

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.metrics import MetricUnit

import common
from common import ApiError

logger = Logger()
metrics = Metrics()

DEFAULT_DEADLINE_MINUTES = int(os.environ.get("DEFAULT_DEADLINE_MINUTES", "5"))
SCHEDULE_GROUP = os.environ["SCHEDULE_GROUP"]
EXPIRE_FUNCTION_ARN = os.environ["EXPIRE_FUNCTION_ARN"]
SCHEDULER_ROLE_ARN = os.environ["SCHEDULER_ROLE_ARN"]

scheduler = boto3.client("scheduler")


def schedule_name(task_id: str) -> str:
    return f"task-{task_id}"


def _create_expiry_schedule(uid: str, task_id: str, deadline) -> str:
    name = schedule_name(task_id)
    scheduler.create_schedule(
        Name=name,
        GroupName=SCHEDULE_GROUP,
        Description=f"Expire task {task_id} at its deadline",
        ScheduleExpression=f"at({deadline:%Y-%m-%dT%H:%M:%S})",
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",  # one-time schedule cleans itself up after firing
        Target={
            "Arn": EXPIRE_FUNCTION_ARN,
            "RoleArn": SCHEDULER_ROLE_ARN,
            "Input": json.dumps({"userId": uid, "taskId": task_id}),
            "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
        },
    )
    return name


def _deadline_minutes(body: dict) -> int:
    value = body.get("deadlineMinutes", DEFAULT_DEADLINE_MINUTES)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ApiError(400, "deadlineMinutes must be a whole number")
    value = int(value)
    if not 1 <= value <= 1440:
        raise ApiError(400, "deadlineMinutes must be between 1 and 1440")
    return value


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@metrics.log_metrics
def handler(event, _context):
    try:
        uid = common.user_id(event)
        email = common.claims(event).get("email")
        body = common.json_body(event)

        description = common.validate_description(body.get("description"))
        now = common.now_utc()
        due_date = common.validate_date(body["date"]) if body.get("date") else now.date().isoformat()
        deadline = now + timedelta(minutes=_deadline_minutes(body))
        task_id = str(uuid.uuid4())

        item = {
            **common.task_key(uid, task_id),
            "GSI1PK": f"USER#{uid}",
            "GSI1SK": common.gsi1_sk(common.PENDING, common.iso(deadline)),
            "EntityType": "TASK",
            "TaskId": task_id,
            "UserId": uid,
            "Email": email,
            "Description": description,
            "Date": due_date,
            "Status": common.PENDING,
            "Deadline": int(deadline.timestamp()),
            "DeadlineISO": common.iso(deadline),
            "CreatedAt": common.iso(now),
            "UpdatedAt": common.iso(now),
        }
        item["ScheduleName"] = _create_expiry_schedule(uid, task_id, deadline)
        item["ScheduleGroup"] = SCHEDULE_GROUP
        try:
            common.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except Exception:
            logger.exception("DynamoDB write failed; removing the expiry schedule", extra={"task_id": task_id})
            try:
                scheduler.delete_schedule(Name=item["ScheduleName"], GroupName=SCHEDULE_GROUP)
            except Exception:
                logger.exception("Could not delete orphan schedule (ExpireTask will ignore it)")
            raise

        logger.info(
            "Task created with expiry schedule",
            extra={"task_id": task_id, "deadline": item["DeadlineISO"], "schedule": item["ScheduleName"]},
        )
        metrics.add_metric(name="TasksCreated", unit=MetricUnit.Count, value=1)
        return common.response(201, common.to_api(item))
    except ApiError as err:
        return common.error_response(err)
