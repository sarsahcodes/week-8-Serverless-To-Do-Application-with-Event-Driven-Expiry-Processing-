"""Cognito PreSignUp trigger.

Auto-confirms every new user and marks their email as verified, so users can
sign in straight after sign-up without entering a verification code.
"""
from aws_lambda_powertools import Logger

logger = Logger()


@logger.inject_lambda_context
def handler(event, _context):
    attrs = event.get("request", {}).get("userAttributes", {})
    response = event.setdefault("response", {})

    response["autoConfirmUser"] = True
    if "email" in attrs:
        response["autoVerifyEmail"] = True

    logger.info(
        "Auto-confirmed new user",
        extra={"trigger_source": event.get("triggerSource"), "email_verified": "email" in attrs},
    )
    return event
