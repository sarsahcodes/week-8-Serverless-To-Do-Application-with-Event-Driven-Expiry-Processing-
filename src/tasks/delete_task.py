"""DELETE /tasks/{taskId}

Deleting a Pending task is what the Phase 4 cancellation workflow reacts to
(DynamoDB Stream REMOVE event).
"""
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

import common
from common import ApiError

logger = Logger()
metrics = Metrics()


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@metrics.log_metrics
def handler(event, _context):
    try:
        uid = common.user_id(event)
        task_id = common.path_task_id(event)
        try:
            common.table.delete_item(
                Key=common.task_key(uid, task_id),
                ConditionExpression="attribute_exists(PK)",
            )
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ApiError(404, "Task not found")
            raise

        metrics.add_metric(name="TasksDeleted", unit=MetricUnit.Count, value=1)
        logger.info("Task deleted", extra={"task_id": task_id})
        return common.response(204)
    except ApiError as err:
        return common.error_response(err)
