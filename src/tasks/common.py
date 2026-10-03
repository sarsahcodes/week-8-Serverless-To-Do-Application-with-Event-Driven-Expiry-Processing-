"""Shared helpers for the task CRUD Lambdas.

Single-table design (see docs/PLAN.md):

    Task item    PK = USER#<sub>   SK = TASK#<taskId>
                 GSI1PK = USER#<sub>   GSI1SK = STATUS#<Status>#<timestamp>

The user id always comes from the Cognito authorizer claims, never from the
request body, so a user can only ever reach items under their own partition.
"""
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
table = boto3.resource("dynamodb").Table(TABLE_NAME)

PENDING, COMPLETED, EXPIRED = "Pending", "Completed", "Expired"
STATUSES = (PENDING, COMPLETED, EXPIRED)
MAX_DESCRIPTION = 500

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


class ApiError(Exception):
    """Raised by handlers to return a 4xx response with a message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Request / response
# ---------------------------------------------------------------------------
def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")


def response(status: int, body=None) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": "" if body is None else json.dumps(body, default=_json_default),
    }


def error_response(err: ApiError) -> dict:
    return response(err.status, {"message": err.message})


def claims(event: dict) -> dict:
    try:
        return event["requestContext"]["authorizer"]["claims"]
    except (KeyError, TypeError):
        raise ApiError(401, "Unauthorized")


def user_id(event: dict) -> str:
    sub = claims(event).get("sub")
    if not sub:
        raise ApiError(401, "Unauthorized")
    return sub


def path_task_id(event: dict) -> str:
    task_id = (event.get("pathParameters") or {}).get("taskId")
    if not task_id:
        raise ApiError(400, "taskId is required in the path")
    return task_id


def json_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_description(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "description is required")
    value = value.strip()
    if len(value) > MAX_DESCRIPTION:
        raise ApiError(400, f"description must be at most {MAX_DESCRIPTION} characters")
    return value


def validate_date(value) -> str:
    """Due date as YYYY-MM-DD."""
    if not isinstance(value, str):
        raise ApiError(400, "date must be a string in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ApiError(400, "date must be in YYYY-MM-DD format")


# ---------------------------------------------------------------------------
# Keys and mapping
# ---------------------------------------------------------------------------
def task_key(uid: str, task_id: str) -> dict:
    return {"PK": f"USER#{uid}", "SK": f"TASK#{task_id}"}


def gsi1_sk(status: str, timestamp: str) -> str:
    return f"STATUS#{status}#{timestamp}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_api(item: dict) -> dict:
    """DynamoDB item -> API representation (drops key attributes)."""
    return {
        "taskId": item["TaskId"],
        "userId": item["UserId"],
        "description": item["Description"],
        "date": item.get("Date"),
        "status": item["Status"],
        "deadline": item.get("DeadlineISO"),
        "deadlineEpoch": item.get("Deadline"),
        "createdAt": item.get("CreatedAt"),
        "updatedAt": item.get("UpdatedAt"),
        "completedAt": item.get("CompletedAt"),
        "expiredAt": item.get("ExpiredAt"),
        "notifiedAt": item.get("NotifiedAt"),
    }
