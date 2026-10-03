"""GET /tasks/{taskId}"""
from aws_lambda_powertools import Logger
from aws_lambda_powertools.logging import correlation_paths

import common
from common import ApiError

logger = Logger()


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
def handler(event, _context):
    try:
        uid = common.user_id(event)
        task_id = common.path_task_id(event)
        item = common.table.get_item(Key=common.task_key(uid, task_id)).get("Item")
        if not item:
            raise ApiError(404, "Task not found")
        return common.response(200, common.to_api(item))
    except ApiError as err:
        return common.error_response(err)
