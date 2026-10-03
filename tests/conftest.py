import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "auth"))
sys.path.insert(0, str(ROOT / "src" / "tasks"))

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "todo-app-test")
os.environ.setdefault("POWERTOOLS_METRICS_NAMESPACE", "TodoAppTest")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
os.environ.setdefault("TABLE_NAME", "todo-test-table")
os.environ.setdefault("SCHEDULE_GROUP", "todo-test-task-expiry")
os.environ.setdefault("EXPIRE_FUNCTION_ARN", "arn:aws:lambda:eu-central-1:123456789012:function:todo-test-expire-task")
os.environ.setdefault("SCHEDULER_ROLE_ARN", "arn:aws:iam::123456789012:role/todo-test-scheduler")
os.environ.setdefault("TOPIC_ARN", "arn:aws:sns:eu-central-1:123456789012:todo-test-task-notifications")
