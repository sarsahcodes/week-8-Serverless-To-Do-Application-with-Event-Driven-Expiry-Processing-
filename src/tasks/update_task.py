"""PUT /tasks/{taskId}

Body (any of): {"description": str, "date": "YYYY-MM-DD", "status": "Completed"}

Rules
  * Only Pending tasks can be changed. Completed and Expired are final states.
  * The only status a user may set is Completed (Expired is set by the system).
  * The check and the write are one conditional UpdateItem, so a task that
    expires at the same moment cannot be completed afterwards (and vice versa).

Marking a task Completed is what the Phase 4 cancellation workflow reacts to
(DynamoDB Stream MODIFY Pending -> Completed).
"""
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

import common
from common import ApiError

logger = Logger()
metrics = Metrics()

ALLOWED_FIELDS = {"description", "date", "status"}


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@metrics.log_metrics
def handler(event, _context):
    try:
        uid = common.user_id(event)
        task_id = common.path_task_id(event)
        body = common.json_body(event)

        unknown = set(body) - ALLOWED_FIELDS
        if unknown:
            raise ApiError(400, f"Unsupported field(s): {', '.join(sorted(unknown))}")
        if not body:
            raise ApiError(400, "Nothing to update: send description, date and/or status")

        now = common.iso(common.now_utc())
        sets = ["UpdatedAt = :now"]
        names = {"#Status": "Status"}
        values = {":now": now, ":pending": common.PENDING}

        if "description" in body:
            sets.append("Description = :description")
            values[":description"] = common.validate_description(body["description"])
        if "date" in body:
            sets.append("#Date = :date")
            names["#Date"] = "Date"
            values[":date"] = common.validate_date(body["date"])

        completing = False
        if "status" in body:
            if body["status"] == common.PENDING:
                pass  # already Pending (the condition below guarantees it)
            elif body["status"] == common.COMPLETED:
                completing = True
                sets += ["#Status = :completed", "CompletedAt = :now", "GSI1SK = :gsi1sk"]
                values[":completed"] = common.COMPLETED
                values[":gsi1sk"] = common.gsi1_sk(common.COMPLETED, now)
            else:
                raise ApiError(400, "status can only be set to Completed")

        try:
            result = common.table.update_item(
                Key=common.task_key(uid, task_id),
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression="attribute_exists(PK) AND #Status = :pending",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
                ReturnValuesOnConditionCheckFailure="ALL_OLD",
            )
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            current = err.response.get("Item")
            if not current:
                raise ApiError(404, "Task not found")
            raise ApiError(409, f"Task is {current['Status']['S']}; only Pending tasks can be changed")

        if completing:
            metrics.add_metric(name="TasksCompleted", unit=MetricUnit.Count, value=1)
        logger.info("Task updated", extra={"task_id": task_id, "fields": sorted(body), "completed": completing})
        return common.response(200, common.to_api(result["Attributes"]))
    except ApiError as err:
        return common.error_response(err)
