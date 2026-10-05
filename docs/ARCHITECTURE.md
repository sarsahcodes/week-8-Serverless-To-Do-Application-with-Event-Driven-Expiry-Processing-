# Architecture – stage-by-stage description

This document explains every numbered stage in [`architecture.drawio`](architecture.drawio) / [`architecture.png`](architecture.png). The numbers below are the same numbers as on the diagram's arrows.

| Flow | Stages | Colour on diagram | Build status |
|---|---|---|---|
| Sign-up & sign-in | 1 – 4 | red / teal | Built (Phase 1) – Amplify Hosting itself in Phase 6 |
| Task CRUD | 5 – 6 | purple | Built (Phase 2) |
| Expiry | 7 – 11 | orange | Built (Phase 3) |
| Cancellation | 12 – 15 | pink | Planned (Phase 4) |
| CI/CD | A – D | grey, dashed | Planned (Phases 6–7) |
| Observability & security | – | green | Logs, metrics, tracing, IAM built; alarms & dashboard planned (Phase 5) |

---

## 1. Sign-up & sign-in

### Stage 1 – Load the app (Browser → AWS Amplify Hosting)

- The user opens the Amplify Hosting URL. Amplify serves the static React single-page app (built with Vite) from its managed CDN.
- At build time Amplify injects four environment variables that come from the backend stack outputs: `VITE_AWS_REGION`, `VITE_USER_POOL_ID`, `VITE_USER_POOL_CLIENT_ID`, `VITE_API_URL`.
- In `src/amplifyConfig.js` the app registers these with `Amplify.configure()` – the Cognito User Pool under `Auth.Cognito` and the REST API under `API.REST.TodoApi`. This is the "API registration / Cognito registration in frontend code" the rubric asks for.
- Locally the same values come from `.env.local` (written by `npm run env:sync`).

### Stage 2 – Sign up / sign in (Browser → Amazon Cognito User Pool)

- The Amplify `<Authenticator>` component talks directly to the Cognito User Pool `todo-<stage>-users` through the app client `todo-<stage>-web`.
- Email is the username. The password policy requires 8+ characters with upper-case, lower-case and a number.
- Sign-in uses **SRP** (Secure Remote Password), so the password itself is never sent over the network. (`USER_PASSWORD_AUTH` is also enabled on the client, only for CLI testing.)
- On success Cognito returns three JWTs: an **ID token** (who the user is – `sub`, `email`), an **access token**, and a **refresh token**. ID and access tokens are valid for 60 minutes; Amplify refreshes them automatically.

### Stage 3 – Auto-confirm (Cognito → PreSignUp Lambda)

- Before Cognito stores a new user it invokes the **PreSignUp** trigger (`src/auth/pre_signup.py`).
- The function sets `autoConfirmUser = true` and `autoVerifyEmail = true` in the response, so the account is immediately `CONFIRMED` and no verification code email is needed – this satisfies "sign-up must be auto-confirmed".

### Stage 4 – Subscribe to notifications (Cognito → PostAuthentication Lambda → SNS + DynamoDB)

After every successful sign-in Cognito invokes the **PostAuthentication** trigger (`src/auth/post_auth.py`):

1. **4b – read the profile:** it reads the item `PK = USER#<sub>`, `SK = PROFILE` from DynamoDB.
2. If the stored subscription exists and is already confirmed, it stops – sign-in is never slowed down twice.
3. **4a – subscribe:** otherwise it calls `sns:Subscribe` on the topic `todo-<stage>-task-notifications` with protocol `email` and a **filter policy** `{"userId": ["<sub>"]}`. Because the filter is on the user's own id, the user will only ever receive messages published for their tasks.
4. It saves/updates the profile item (`Email`, `SubscriptionArn`, `SubscribedAt`).

Design points:

- **Never blocks sign-in** – any error is logged and swallowed; the trigger always returns the event (a failing trigger would stop the user from logging in). Timeout is 5 s, matching Cognito's trigger limit.
- **Idempotent** – runs on every login but only subscribes when there is no confirmed subscription. If the user never confirmed, the next login simply re-sends the confirmation email.
- **SNS email confirmation** – SNS requires the user to click "Confirm subscription" once. Confirming with `--authenticate-on-unsubscribe true` stops email security scanners from unsubscribing the address by following the link.

---

## 2. Task CRUD

### Stage 5 – Authenticated API call (Browser → API Gateway, 5a Cognito authorizer)

- The SPA calls the REST API (`TodoApi`, stage `dev`) through Amplify's REST client (`src/api.js`) and adds `Authorization: <Cognito ID token>` to every request.
- **5a:** API Gateway's **Cognito User Pool authorizer** validates the token before any Lambda runs – signature, expiry, issuer (our User Pool) and audience (our app client). Invalid/expired tokens are rejected with `401` and no Lambda is invoked or billed.
- Valid requests are forwarded with the token's claims in `requestContext.authorizer.claims`; the Lambdas read the user id (`sub`) from there – **never from the request body**.
- Other API settings: CORS (`*` origin, `Authorization`/`Content-Type` headers), CORS headers on API Gateway's own 4XX/5XX responses, `OPTIONS` pre-flights without auth, throttling 20 req/s (burst 50), detailed CloudWatch metrics and X-Ray tracing.

| Method | Path | Lambda |
|---|---|---|
| POST | `/tasks` | CreateTask |
| GET | `/tasks?status=Pending\|Completed\|Expired` | ListTasks |
| GET | `/tasks/{taskId}` | GetTask |
| PUT | `/tasks/{taskId}` | UpdateTask |
| DELETE | `/tasks/{taskId}` | DeleteTask |

### Stage 6 – Read / write tasks (CRUD Lambdas → DynamoDB)

All five functions share `src/tasks/common.py` and use one DynamoDB table, `todo-<stage>-table` (on-demand capacity, point-in-time recovery, encryption at rest, streams enabled). The table uses a **single-table design** (see page 2 of the diagram / `dynamodb-design.png`):

| Item | PK | SK | GSI1PK | GSI1SK |
|---|---|---|---|---|
| Task | `USER#<sub>` | `TASK#<taskId>` | `USER#<sub>` | `STATUS#<Status>#<timestamp>` |
| Profile | `USER#<sub>` | `PROFILE` | – | – |

Task attributes: `TaskId` (UUID v4), `UserId`, `Email`, `Description`, `Date` (due date), `Status` (`Pending` \| `Completed` \| `Expired`), `Deadline` (epoch seconds), `DeadlineISO`, `ScheduleName`, `ScheduleGroup`, `CreatedAt`, `UpdatedAt`, `CompletedAt`, `ExpiredAt`, `NotifiedAt`.

- **CreateTask** – validates the description (1–500 chars) and date (`YYYY-MM-DD`, default today), sets `Status = Pending` and `Deadline = now + deadlineMinutes` (default **5 minutes**, allowed 1–1440), then performs stage 7 and writes the item with `attribute_not_exists(PK)`. Returns `201`.
- **ListTasks** – without a filter it queries `PK = USER#<sub>` and `SK begins_with TASK#`; with `?status=` it queries **GSI1** with `GSI1SK begins_with STATUS#<status>#`, so filtering by status never scans the table.
- **GetTask** – `GetItem` on `PK + SK`; `404` if absent.
- **UpdateTask** – one conditional `UpdateItem` with `attribute_exists(PK) AND Status = Pending`. Users may edit the description/date or set `status = Completed` (which also sets `CompletedAt` and moves the item to `STATUS#Completed#…` in GSI1). Completed and Expired are final: changing them returns `409`; a missing task returns `404`.
- **DeleteTask** – conditional `DeleteItem` (`attribute_exists(PK)`); `204` on success, `404` if absent.

Because every key starts with the caller's `USER#<sub>`, a user physically cannot read or change another user's task – a request for someone else's task id simply returns `404`.

---

## 3. Expiry workflow (event-driven, scheduled)

### Stage 7 – Create the expiry schedule (CreateTask → EventBridge Scheduler)

When a task is created, CreateTask calls `scheduler:CreateSchedule`:

| Setting | Value | Why |
|---|---|---|
| Name / group | `task-<taskId>` in `todo-<stage>-task-expiry` | one schedule per task; the name lets cancellation find it |
| Expression | `at(<deadline>)`, timezone UTC | one-time, fires once at the deadline |
| Flexible window | `OFF` | fire on time |
| Target | ExpireTask Lambda, input `{"userId", "taskId"}` | |
| Role | `SchedulerInvokeRole` | Scheduler needs permission to invoke the Lambda |
| Retry policy | 3 attempts, max event age 1 hour | survives transient Lambda errors |
| After completion | `DELETE` | the schedule removes itself after firing – nothing to clean up |

The schedule is created **before** the DynamoDB write. If the write then fails, CreateTask deletes the schedule again. Even if that clean-up failed, the schedule would fire for a task that does not exist, which ExpireTask ignores – so a failure can never leave a task without an expiry or produce a wrong email. The task item stores `ScheduleName` and `ScheduleGroup` for the cancellation workflow.

### Stage 8 – Fire at the deadline (EventBridge Scheduler → ExpireTask Lambda)

- At the deadline (EventBridge Scheduler's precision is about one minute) the scheduler assumes `SchedulerInvokeRole` – trusted only by `scheduler.amazonaws.com` from this account, and allowed only `lambda:InvokeFunction` on ExpireTask – and invokes the function with `{"userId": "<sub>", "taskId": "<id>"}`.

### Stage 9 – Mark the task Expired (ExpireTask → DynamoDB)

ExpireTask (`src/tasks/expire_task.py`) performs one **conditional** `UpdateItem`:

```
SET Status = Expired, ExpiredAt = now, UpdatedAt = now, GSI1SK = STATUS#Expired#now
CONDITION attribute_exists(PK) AND Status = Pending
```

| Situation at the deadline | Result |
|---|---|
| Task still Pending | becomes Expired → continue to stage 10 |
| Task already Completed | condition fails → logged as "skipped", **no email** |
| Task deleted | condition fails → "skipped (deleted)", **no email** |

This condition is the **safety net** for the cancellation workflow: even if a schedule was not cancelled in time, a completed or deleted task can never be expired or trigger an email.

### Stage 10 – Publish the notification (ExpireTask → SNS)

- ExpireTask publishes to the SNS topic with subject `Task expired: <description>` (trimmed to SNS's 100-character limit), a message with the description, due date, deadline and task id, and a **message attribute `userId = <sub>`**.
- It then records `NotifiedAt` on the task.
- **Retry-safe:** if the publish fails, the function raises so the invocation is retried. The retry finds the task already Expired but without `NotifiedAt` and sends the email then. If `NotifiedAt` is already set, a retry does nothing – the user gets exactly one email.
- Metrics emitted: `TasksExpired`, `ExpiryNotificationsSent`, `ExpiryNotificationFailures`.

### Stage 11 – Email only the owner (SNS → user's inbox)

- SNS compares the message attribute `userId` with each subscription's filter policy. Only the subscription whose filter is `{"userId": ["<that sub>"]}` matches, so **only the task owner** receives the email, even though all users share one topic. The sender name is "To-Do Alerts".
- In the app, the 15-second auto-refresh moves the task to the **Expired** tab.

---

## 4. Cancellation workflow (decoupled, idempotent) – Phase 4

When a task is completed or deleted before its deadline, its schedule should be removed so it never fires. This is done asynchronously, outside the API request, through DynamoDB Streams → SQS FIFO → Lambda.

### Stage 12 – Change captured (DynamoDB → DynamoDB Stream → StreamToQueue Lambda)

- The table's stream (`NEW_AND_OLD_IMAGES`) records every change with the item's before and after images.
- The event source mapping for **StreamToQueue** uses **event filtering**, so the Lambda is only invoked for the two events that need cancelling:
  - `MODIFY` where the old status is `Pending` and the new status is `Completed` (on `TASK#` items),
  - `REMOVE` of a `TASK#` item (deleted task).
- Other changes – creating tasks, editing descriptions, expiries, profile items – never invoke it.

### Stage 13 – Enqueue a cancellation (StreamToQueue → SQS FIFO)

- For each matching record it sends a message `{taskId, userId, scheduleName, scheduleGroup, reason}` to the FIFO queue `todo-<stage>-expiry-cancellations.fifo`.
- `MessageGroupId = taskId` – messages for the same task are processed in order, while different tasks are processed in parallel.
- `MessageDeduplicationId` per task and event – if a stream record is delivered twice, SQS drops the duplicate within its 5-minute deduplication window.

### Stages 14 – 15 – Delete the schedule (SQS FIFO → CancelExpiry Lambda → EventBridge Scheduler)

- **CancelExpiry** polls the queue (Lambda event source mapping) and calls `scheduler:DeleteSchedule` for `task-<taskId>`.
- **Idempotent:** if the schedule is already gone (already deleted, or it already fired and removed itself), `ResourceNotFoundException` is treated as success.
- **Partial batch failures:** only the failed messages are returned to the queue. After 3 failed receives a message moves to the **dead-letter queue** (`.fifo`), where an alarm flags it for investigation.
- The queue's visibility timeout is set to at least six times the function timeout, so a message is never processed twice concurrently.

**Why decoupled?** The API responds immediately without waiting for the scheduler call. Scheduler throttling or outages cannot break completing or deleting a task. Failures are retried automatically and are visible in the DLQ. Even if cancellation is late, stage 9's condition prevents a wrong expiry or email.

---

## 5. CI/CD (A – D)

| Stage | What happens |
|---|---|
| **A** – Frontend push → Amplify build | A push to `main` of the frontend repo triggers an Amplify Hosting build (`npm ci` → `npm run build` → publish `dist/`). The Amplify app, branch, build spec and `VITE_*` environment variables are defined in the SAM template, so the frontend is always built against the current backend outputs. |
| **B** – Backend push → GitHub Actions | A push to the backend repo runs the workflow created by `sam pipeline init`: install dependencies, run unit tests, `sam validate --lint`. |
| **C** – Upload artifacts → S3 | `sam build` and `sam package` upload the Lambda code and the template to the SAM-managed S3 artifacts bucket. |
| **D** – Deploy stack → CloudFormation | `sam deploy` creates and executes a CloudFormation change set for the `todo-app-<stage>` stack. GitHub authenticates with **OIDC** to an IAM role created by `sam pipeline bootstrap`, so no long-lived AWS keys are stored in GitHub. After the deploy the workflow can trigger an Amplify release so the frontend picks up changed outputs. |

---

## 6. Observability & security

**Amazon CloudWatch**

- **Logs** – every Lambda writes structured JSON logs (AWS Lambda Powertools Logger) with request id, cold start, `user_id`, `task_id` and the API Gateway correlation id. Each function has a log group with 14-day retention defined in the template.
- **Metrics** – custom metrics in the `TodoApp` namespace via Embedded Metric Format: `TasksCreated`, `TasksCompleted`, `TasksDeleted`, `TasksExpired`, `ExpiryNotificationsSent`, `ExpiryNotificationFailures`, `NotificationSubscriptionsRequested`. API Gateway publishes request count, latency, 4XX and 5XX per method.
- **Alarms & dashboard** (Phase 5) – alarms on Lambda errors (ExpireTask, CancelExpiry), DLQ depth > 0 and API 5XX; a dashboard showing the whole task lifecycle.

**AWS X-Ray** – active tracing on API Gateway and all Lambdas shows each request end to end, including the DynamoDB, Scheduler and SNS calls.

**Security & least privilege**

| Principal | Allowed actions | Resource |
|---|---|---|
| PostAuthentication | `sns:Subscribe`, `sns:GetSubscriptionAttributes`, `dynamodb:GetItem/PutItem` | the notifications topic, the table |
| CreateTask | `dynamodb:PutItem`; `scheduler:CreateSchedule/DeleteSchedule`; `iam:PassRole` | the table; only schedules in the expiry group; only `SchedulerInvokeRole`, only to `scheduler.amazonaws.com` |
| ListTasks | `dynamodb:Query` | the table and GSI1 |
| GetTask / UpdateTask / DeleteTask | `dynamodb:GetItem` / `UpdateItem` / `DeleteItem` (one each) | the table |
| ExpireTask | `dynamodb:UpdateItem`, `sns:Publish` | the table, the topic |
| SchedulerInvokeRole | `lambda:InvokeFunction` | ExpireTask only; trusted only by `scheduler.amazonaws.com` in this account |
| StreamToQueue / CancelExpiry (Phase 4) | stream read + `sqs:SendMessage` / SQS receive + `scheduler:DeleteSchedule` | the stream and queue; schedules in the expiry group |

Plus: the Cognito authorizer on every API route; per-user data isolation through the partition key; DynamoDB encryption at rest and point-in-time recovery; HTTPS everywhere; and no AWS credentials in the browser (it holds only Cognito tokens).

---

## 7. One task, end to end (example timeline)

| Time | Event |
|---|---|
| 10:00:00 | User creates "Submit lab report" (default deadline). CreateTask creates schedule `task-7f3c…` for **10:05:00 UTC**, writes the item as **Pending**, returns `201`. The UI shows a 5:00 countdown. |
| *Path A – the user does nothing* | |
| 10:05:00 | Scheduler invokes ExpireTask → conditional update to **Expired** → publish to SNS (`userId` attribute) → `NotifiedAt` set. The schedule deletes itself. |
| ≈10:05:05 | The owner receives "Task expired: Submit lab report". The UI moves the task to the Expired tab on its next refresh. |
| *Path B – the user completes it at 10:02* | |
| 10:02:00 | UpdateTask sets **Completed** (conditional on Pending) → `200`. |
| 10:02:01 | Stream `MODIFY` (Pending → Completed) → StreamToQueue → SQS FIFO (group = task id) → CancelExpiry deletes `task-7f3c…`. Nothing fires at 10:05 and no email is sent. |
| *Path C – the user deletes it at 10:03* | Stream `REMOVE` → same cancellation path → schedule deleted. |
| *Race – completed at 10:04:59 while the schedule fires at 10:05* | Whichever conditional write lands first wins. If Completed won, ExpireTask's condition fails, so there is no expiry and no email; the cancellation later finds the schedule already gone, which counts as success. |
