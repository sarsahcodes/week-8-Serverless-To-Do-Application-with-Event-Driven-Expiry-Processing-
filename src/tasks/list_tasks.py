"""GET /tasks[?status=Pending|Completed|Expired]

Without a status filter: Query the base table (PK = USER#<sub>, SK begins_with TASK#).
With a status filter:    Query GSI1 (GSI1PK = USER#<sub>, GSI1SK begins_with STATUS#<status>#).
"""
from aws_lambda_powertools import Logger
from aws_lambda_powertools.logging import correlation_paths
from boto3.dynamodb.conditions import Key

import common
from common import ApiError

logger = Logger()


def _query_all(**kwargs) -> list:
    items, start_key = [], None
    while True:
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        page = common.table.query(**kwargs)
        items.extend(page.get("Items", []))
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return items


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
def handler(event, _context):
    try:
        uid = common.user_id(event)
        status = (event.get("queryStringParameters") or {}).get("status")

        if status:
            if status not in common.STATUSES:
                raise ApiError(400, f"status must be one of {', '.join(common.STATUSES)}")
            items = _query_all(
                IndexName="GSI1",
                KeyConditionExpression=Key("GSI1PK").eq(f"USER#{uid}")
                & Key("GSI1SK").begins_with(f"STATUS#{status}#"),
            )
        else:
            items = _query_all(
                KeyConditionExpression=Key("PK").eq(f"USER#{uid}") & Key("SK").begins_with("TASK#"),
            )

        tasks = sorted((common.to_api(i) for i in items), key=lambda t: t["createdAt"] or "", reverse=True)
        logger.info("Tasks listed", extra={"status_filter": status, "count": len(tasks)})
        return common.response(200, {"items": tasks, "count": len(tasks)})
    except ApiError as err:
        return common.error_response(err)
