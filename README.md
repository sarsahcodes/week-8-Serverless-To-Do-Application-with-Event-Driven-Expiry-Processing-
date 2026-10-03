# Serverless To-Do App with Event-Driven Expiry Processing

Backend for a serverless task manager built with AWS SAM. Users sign up with Cognito, manage tasks through API Gateway → Lambda → DynamoDB, and get an email through SNS when a task passes its deadline. Expiry is scheduled with EventBridge Scheduler and cancelled through DynamoDB Streams → SQS FIFO → Lambda.

See [docs/PLAN.md](docs/PLAN.md) for the full architecture and build plan. The frontend lives in a separate repo (`todo-frontend`).

## API

All routes require a Cognito **ID token** in the `Authorization` header.

| Method | Path | Body | Result |
|---|---|---|---|
| POST | `/tasks` | `{description, date?, deadlineMinutes?}` | 201 task (Pending, deadline = now + 5 min by default) |
| GET | `/tasks?status=Pending\|Completed\|Expired` | – | 200 `{items, count}` |
| GET | `/tasks/{taskId}` | – | 200 task / 404 |
| PUT | `/tasks/{taskId}` | `{description?, date?, status?: "Completed"}` | 200 task / 404 / 409 if not Pending |
| DELETE | `/tasks/{taskId}` | – | 204 / 404 |

## Status

- [x] Phase 0 – SAM project scaffold
- [x] Phase 1 – Cognito user pool (auto-confirm), PostAuthentication → SNS subscription, DynamoDB table
- [x] Phase 2 – CRUD API (API Gateway + Cognito authorizer + 5 Lambdas)
- [x] Phase 3 – Expiry (EventBridge Scheduler → Lambda → DynamoDB + SNS)
- [ ] Phase 4 – Cancellation (Streams → SQS FIFO → Lambda)
- [ ] Phase 5 – Observability and least privilege
- [ ] Phase 6 – Amplify frontend
- [ ] Phase 7 – SAM pipeline

## Layout

```
template.yaml          SAM template (all infrastructure)
samconfig.toml         sam build / deploy settings
src/auth/              Cognito triggers: pre_signup.py, post_auth.py
src/tasks/             CRUD handlers, expire_task.py (Scheduler target) + shared common.py
events/                sample events for `sam local invoke`
tests/unit/            unit tests (moto)
docs/                  plan and architecture diagram
```

## Deploy

```powershell
sam validate --lint
sam build
sam deploy
```

## Test

```powershell
pip install -r tests/requirements.txt
python -m pytest tests
```
