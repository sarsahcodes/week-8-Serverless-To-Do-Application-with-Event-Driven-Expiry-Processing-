"""Generates docs/architecture.drawio (diagrams-as-code).

Run:  python docs/make_diagram.py
Open the output in draw.io / diagrams.net (desktop app, web, or the VS Code extension).
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_name("architecture.drawio")

# --- AWS 2023 icon palette (same colours draw.io's AWS4 library uses) --------
COMPUTE, APPINT, DATABASE, SECURITY, MGMT, STORAGE, FRONTEND, GENERAL = (
    "#ED7100", "#E7157B", "#C925D1", "#DD344C", "#E7157B", "#7AA116", "#DD344C", "#232F3D")

# Flow colours
C_AUTH, C_API, C_EXP, C_CAN, C_NOTIFY, C_CICD, C_OBS = (
    "#DD344C", "#8C4FFF", "#ED7100", "#E7157B", "#01A88D", "#545B64", "#7AA116")

BASE = ("sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;dashed=0;html=1;"
        "fontSize=11;fontStyle=0;aspect=fixed;")
LABEL_BELOW = "verticalLabelPosition=bottom;verticalAlign=top;align=center;"
LABEL_RIGHT = "labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=6;"


def service(icon, color):  # square service icon (resourceIcon)
    return BASE + f"fillColor={color};strokeColor=#ffffff;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};"


def resource(icon, color):  # resource glyph (lambda_function, topic, queue ...)
    return BASE + f"fillColor={color};strokeColor=none;pointerEvents=1;shape=mxgraph.aws4.{icon};"


cells = []
_n = [0]


def nid(prefix="c"):
    _n[0] += 1
    return f"{prefix}{_n[0]}"


def vertex(label, x, y, w, h, style, cid=None):
    cid = cid or nid("v")
    cells.append(f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def icon(label, cx, cy, size, style, pos="below", cid=None, label_w=None):
    st = style + {"below": LABEL_BELOW, "right": LABEL_RIGHT,
                  "above": "verticalLabelPosition=top;verticalAlign=bottom;align=center;"}[pos]
    return vertex(label, cx - size / 2, cy - size / 2, size, size, st, cid)


def group(label, x, y, w, h, kind, align="left"):
    if kind == "cloud":
        st = ("points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;container=0;"
              "pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;"
              "strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;")
    elif kind == "region":
        st = ("points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;container=0;"
              "pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;"
              "strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=right;spacingLeft=30;spacingRight=12;fontColor=#147EBA;dashed=1;")
    else:  # section box, kind = accent colour
        st = (f"rounded=1;arcSize=3;whiteSpace=wrap;html=1;fillColor=#FAFAFA;strokeColor={kind};dashed=1;dashPattern=6 4;"
              f"verticalAlign=top;align={align};spacingLeft=10;spacingRight=10;spacingTop=4;fontStyle=1;fontSize=12;fontColor=#232F3E;")
    return vertex(label, x, y, w, h, st)


def edge(src, dst, label="", color="#232F3E", points=(), exit=None, entry=None, dashed=False, width=2, both=False, at=0):
    st = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor={color};strokeWidth={width};endArrow=block;endFill=1;"
          f"fontSize=11;fontColor={color};fontStyle=1;labelBackgroundColor=#ffffff;")
    if dashed:
        st += "dashed=1;"
    if both:
        st += "startArrow=block;startFill=1;"
    if exit:
        st += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        st += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
    arr = f'<Array as="points">{pts}</Array>' if points else ""
    cells.append(f'<mxCell id="{nid("e")}" value="{escape(label)}" style="{st}" edge="1" parent="1" source="{src}" target="{dst}">'
                 f'<mxGeometry x="{at}" relative="1" as="geometry">{arr}</mxGeometry></mxCell>')


def text(html, x, y, w, h, extra=""):
    return vertex(html, x, y, w, h, "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;fontColor=#232F3E;" + extra)


# =============================================================================
# Page 1 - architecture
# =============================================================================
A, B, C, D, E = 530, 870, 1250, 1640, 2080       # column centres
R1, R2, R3, R4 = 345, 700, 1035, 1300           # row centres

text('<b style="font-size:22px">Serverless To-Do Application with Event-Driven Expiry Processing</b><br>'
     '<span style="font-size:13px;color:#545B64">AWS SAM · Cognito · API Gateway · Lambda · DynamoDB · EventBridge Scheduler · '
     'DynamoDB Streams · SQS FIFO · SNS · Amplify · CloudWatch</span>', 820, 30, 1500, 70)

# Containers
group("AWS Cloud", 320, 150, 2060, 1400, "cloud")
group("Region eu-central-1  ·  CloudFormation stack: todo-app-dev (AWS SAM)", 350, 195, 2000, 1325, "region")
group("Frontend hosting", 390, 250, 280, 200, C_AUTH)
group("Authentication", 700, 250, 650, 200, C_AUTH)
group("Notifications", 1480, 250, 320, 200, C_NOTIFY)
group("Task API (REST)", 390, 485, 700, 395, C_API)
group("Data (single-table design)", 1120, 485, 680, 395, C_API)
group("Expiry workflow (scheduled, event-driven)", 700, 915, 740, 245, C_EXP)
group("Cancellation workflow (decoupled, idempotent)", 700, 1190, 1100, 300, C_CAN, align="right")
group("Deployment (IaC)", 390, 915, 280, 575, C_CICD)
group("Observability &amp; security", 1840, 485, 480, 1005, C_OBS)

# Outside the cloud
users = icon("<b>App users</b><br>browser running the React app<br>(Amplify JS)", 150, 520, 64,
             resource("users", GENERAL))
inbox = icon("<b>Task owner's inbox</b><br>expiry email", 2480, R1, 56, resource("email", GENERAL))
fe_repo = icon("<b>GitHub</b> · todo-frontend repo", A, 85, 48,
               "dashed=0;outlineConnect=0;html=1;fontSize=11;shape=mxgraph.weblogos.github;", pos="right")
be_repo = icon("<b>GitHub</b><br>backend repo<br>(SAM template)", 300, 1650, 48,
               "dashed=0;outlineConnect=0;html=1;fontSize=11;shape=mxgraph.weblogos.github;" + LABEL_BELOW)
gha = vertex("<b>GitHub Actions</b><br>SAM pipeline<br>test · sam build · sam deploy<br>(OIDC role, no keys)",
             440, 1610, 190, 80,
             "rounded=1;whiteSpace=wrap;html=1;fillColor=#24292F;strokeColor=none;fontColor=#ffffff;fontSize=11;")

# Frontend hosting
amplify = icon("<b>AWS Amplify Hosting</b><br>React SPA · env vars<br>VITE_* from stack outputs", A, R1 - 15, 64,
               service("amplify", FRONTEND))

# Authentication
cognito = icon("<b>Amazon Cognito</b><br>User Pool (email sign-in)", B, R1 - 15, 64, service("cognito", SECURITY))
presignup = icon("<b>PreSignUp λ</b> – auto-confirm", C - 40, 300, 44, resource("lambda_function", COMPUTE), pos="right")
postauth = icon("<b>PostAuthentication λ</b>", C - 40, 395, 44, resource("lambda_function", COMPUTE), pos="right")

# Notifications
sns = icon("<b>Amazon SNS</b> topic<br>email subs + filter policy<br>{ userId: [sub] }", D, R1 - 15, 64,
           service("sns", APPINT))

# Task API
apigw = icon("<b>Amazon API Gateway</b><br>REST · Cognito authorizer<br>/tasks · /tasks/{taskId}", A, R2 - 20, 64,
             service("api_gateway", APPINT))
crud_box = vertex("", 720, 525, 340, 335,
                  "rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#ED7100;strokeWidth=1;")
text("<b>CRUD Lambda functions</b>", 730, 528, 300, 20, "fontSize=11;")
crud = [("CreateTask", "POST /tasks"), ("ListTasks", "GET /tasks?status="), ("GetTask", "GET /tasks/{taskId}"),
        ("UpdateTask", "PUT /tasks/{taskId}"), ("DeleteTask", "DELETE /tasks/{taskId}")]
crud_ids = []
for i, (name, route) in enumerate(crud):
    crud_ids.append(icon(f"<b>{name}</b> λ<br><span style='color:#545B64'>{route}</span>", 765, 580 + i * 60, 40,
                         resource("lambda_function", COMPUTE), pos="right"))

# Data
ddb = icon("<b>Amazon DynamoDB</b><br>todo-dev-table · on-demand<br>PK/SK + GSI1 · PITR", C, R2 - 20, 64,
           service("dynamodb", DATABASE))
stream = icon("<b>DynamoDB Stream</b><br>NEW_AND_OLD_IMAGES", D, R2 - 20, 56, resource("dynamodb_stream", DATABASE))

# Expiry
scheduler = icon("<b>EventBridge Scheduler</b><br>one-time at(deadline) schedule<br>per task · auto-delete", B, R3 - 20, 60,
                 resource("eventbridge_scheduler", APPINT))
expire = icon("<b>ExpireTask λ</b><br>Pending → Expired<br>(conditional update)", C, R3 - 20, 52,
              resource("lambda_function", COMPUTE))

# Cancellation
s2q = icon("<b>StreamToQueue λ</b><br>event filter: Completed<br>or REMOVE only", D, R4 - 20, 52, resource("lambda_function", COMPUTE))
fifo = icon("<b>Amazon SQS FIFO</b><br>group = taskId · dedup id", C, R4 - 20, 56, resource("queue", APPINT), pos="above")
dlq = icon("DLQ (.fifo)", C + 150, R4 + 120, 36, resource("queue", APPINT), pos="right")
cancel = icon("<b>CancelExpiry λ</b><br>DeleteSchedule<br>(NotFound = done)", B, R4 - 20, 52, resource("lambda_function", COMPUTE))

# Deployment
cfn = icon("<b>AWS CloudFormation</b><br>SAM transform · change sets", A, R3 - 20, 60, service("cloudformation", MGMT))
s3 = icon("<b>Amazon S3</b><br>SAM artifacts bucket", A, R4 - 20, 56, service("s3", STORAGE))

# Observability & security
cw = icon("<b>Amazon CloudWatch</b><br>Logs (JSON, 14-day retention)<br>Metrics (EMF) · Dashboard", 1960, 600, 60,
          service("cloudwatch_2", MGMT))
alarm = icon("<b>CloudWatch Alarms</b><br>Lambda errors · DLQ depth<br>API 5XX", 2200, 600, 52, resource("alarm", MGMT))
xray = icon("<b>AWS X-Ray</b><br>active tracing<br>(API + Lambda)", 1960, 840, 60, service("xray", DATABASE))
iam = icon("<b>AWS IAM</b><br>one least-privilege<br>role per function", 2200, 840, 60,
           service("identity_and_access_management", SECURITY))
role = icon("<b>SchedulerInvokeRole</b><br>lambda:InvokeFunction<br>on ExpireTask only", 2080, 1080, 48, resource("role", SECURITY))
text("Every Lambda function writes structured JSON logs and EMF metrics (Powertools), "
     "and API Gateway publishes request metrics, to CloudWatch. X-Ray traces each request end to end.",
     1860, 1200, 440, 90, "fontSize=11;fontColor=#545B64;")

# ---------------------------------------------------------------------------
# Edges (numbers match the legend)
# ---------------------------------------------------------------------------
edge(users, amplify, "1 Load app", C_AUTH, points=[(270, 495), (270, R1 - 15)], exit=(1, 0.3), entry=(0, 0.5))
edge(users, cognito, "2 Sign up / sign in (SRP)", C_AUTH, points=[(300, 520), (300, 232), (B, 232)], exit=(1, 0.5), entry=(0.5, 0), at=0.45)
edge(cognito, presignup, "3", C_AUTH, exit=(1, 0.3), entry=(0, 0.5))
edge(cognito, postauth, "4", C_AUTH, points=[(980, 345), (980, 395)], exit=(1, 0.7), entry=(0, 0.5))
edge(postauth, sns, "4a Subscribe email", C_NOTIFY, points=[(C - 40, 348), (1420, 348), (1420, R1 - 5)], exit=(0.5, 0), entry=(0, 0.65), at=0.3)
edge(postauth, ddb, "4b Profile item", C_AUTH, points=[(C - 40, 640)], exit=(0.5, 1), entry=(0.2, 0))
edge(users, apigw, "5 HTTPS + ID token", C_API, points=[(240, 545), (240, R2 - 20)], exit=(1, 0.7), entry=(0, 0.5))
edge(apigw, cognito, "5a Validate JWT", C_AUTH, points=[(A, 470), (B + 15, 470)], exit=(0.5, 0), entry=(0.75, 1), dashed=True, width=1.5)
edge(apigw, crud_box, "", C_API, exit=(1, 0.5), entry=(0, 0.5 - 0.0))
edge(crud_box, ddb, "6 Read / write", C_API, exit=(1, 0.5), entry=(0, 0.5))
edge(ddb, stream, "", C_CAN, exit=(1, 0.5), entry=(0, 0.5))
edge(crud_box, scheduler, "7 CreateSchedule", C_EXP, exit=(0.44, 1), entry=(0.5, 0), at=-0.72)
edge(scheduler, expire, "8 Invoke at deadline", C_EXP, exit=(1, 0.5), entry=(0, 0.5))
edge(expire, ddb, "9 Pending→Expired", C_EXP, points=[(C, 897), (1365, 897), (1365, R2 + 2)], exit=(0.5, 0), entry=(1, 0.85), at=-0.3)
edge(expire, sns, "10 Publish (userId attr)", C_EXP, points=[(1455, R3 - 20), (1455, R1 - 30)], exit=(1, 0.5), entry=(0, 0.35), at=-0.15)
edge(sns, inbox, "11 Email to task owner only", C_NOTIFY, exit=(1, 0.5), entry=(0, 0.5))
edge(stream, s2q, "12 MODIFY→Completed / REMOVE", C_CAN, points=[(1765, R2 - 20), (1765, R4 - 20)], exit=(1, 0.5), entry=(1, 0.5), at=-0.1)
edge(s2q, fifo, "13 SendMessage", C_CAN, exit=(0, 0.5), entry=(1, 0.5))
edge(fifo, cancel, "14 Poll", C_CAN, exit=(0, 0.5), entry=(1, 0.5))
edge(cancel, scheduler, "15 DeleteSchedule", C_CAN, points=[(B, 1174), (760, 1174), (760, R3 - 20)], exit=(0.5, 0), entry=(0, 0.5), at=-0.55)
edge(fifo, dlq, "", C_CAN, points=[(C, R4 + 120)], exit=(0.5, 1), entry=(0, 0.5), dashed=True, width=1.5)
edge(fe_repo, amplify, "A git push → build", C_CICD, exit=(0.5, 1), entry=(0.5, 0), dashed=True, at=-0.82)
edge(be_repo, gha, "B git push", C_CICD, exit=(1, 0.5), entry=(0, 0.5), dashed=True)
edge(gha, s3, "C Upload artifacts", C_CICD, exit=(0.5, 0), entry=(0.5, 1), dashed=True)
edge(gha, cfn, "D Deploy stack", C_CICD, points=[(420, 1650), (420, R3 - 20)], exit=(0, 0.5), entry=(0, 0.5), dashed=True)

# Legend
legend = (
    '<div style="font-size:12px;line-height:1.45">'
    '<b style="font-size:14px">How it works</b><br>'
    '<table cellpadding="2" style="font-size:11.5px;border-collapse:collapse"><tr><td valign="top" style="padding-right:18px">'
    f'<b style="color:{C_AUTH}">Sign-up &amp; sign-in</b><br>'
    '1 Browser loads the React SPA from Amplify Hosting.<br>'
    '2 User signs up / signs in against the Cognito User Pool.<br>'
    '3 PreSignUp λ auto-confirms the user (no verification code).<br>'
    '4 PostAuthentication λ subscribes the email to SNS with a<br>&nbsp;&nbsp;&nbsp;filter policy on the user id, and saves a profile item.<br>'
    f'<b style="color:{C_API}">Task CRUD</b><br>'
    '5 SPA calls API Gateway with the Cognito ID token; the<br>&nbsp;&nbsp;&nbsp;Cognito authorizer validates it (5a).<br>'
    '6 CRUD Lambdas read/write the single DynamoDB table.<br>'
    '</td><td valign="top" style="padding-right:18px">'
    f'<b style="color:{C_EXP}">Expiry (deadline, default +5 min)</b><br>'
    '7 CreateTask creates a one-time schedule task-&lt;id&gt;.<br>'
    '8 At the deadline Scheduler invokes ExpireTask λ.<br>'
    '9 Conditional update: only a Pending task becomes Expired.<br>'
    '10 ExpireTask publishes to SNS with userId attribute …<br>'
    '11 … so only the owner\'s subscription emails them.<br>'
    f'<b style="color:{C_CAN}">Cancellation (complete / delete)</b><br>'
    '12 The change lands on the DynamoDB Stream.<br>'
    '13 StreamToQueue λ forwards it to SQS FIFO (per-task order).<br>'
    '14–15 CancelExpiry λ deletes the schedule; repeats are no-ops.<br>'
    '</td><td valign="top">'
    f'<b style="color:{C_CICD}">CI/CD</b><br>'
    'A Frontend push → Amplify build.<br>'
    'B–D Backend push → GitHub Actions →<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;sam build → S3 → CloudFormation.<br>'
    f'<b style="color:{C_OBS}">Observability</b><br>'
    'Logs, metrics, alarms in CloudWatch;<br>traces in X-Ray; one IAM role per function.<br>'
    '<b>Safety net</b><br>'
    'If a cancel loses the race, step 9\'s condition<br>still stops the expiry and the email.'
    '</td></tr></table></div>'
)
vertex(legend, 700, 1580, 1680, 250,
       "rounded=1;arcSize=2;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#AAB7B8;align=left;verticalAlign=top;"
       "spacingLeft=14;spacingTop=8;fontColor=#232F3E;")

page1 = "".join(cells)

# =============================================================================
# Page 2 - DynamoDB single-table design
# =============================================================================
cells.clear()
th = 'style="background:#C925D1;color:#fff;padding:6px 10px;text-align:left"'
td = 'style="border-bottom:1px solid #E5E7EB;padding:6px 10px;vertical-align:top"'
tbl = (
    '<div style="font-size:12px"><b style="font-size:20px">DynamoDB single-table design · todo-dev-table</b><br>'
    '<span style="color:#545B64">On-demand capacity · Streams NEW_AND_OLD_IMAGES · point-in-time recovery · SSE</span><br><br>'
    f'<table style="border-collapse:collapse;font-size:12px"><tr><th {th}>Entity</th><th {th}>PK</th><th {th}>SK</th>'
    f'<th {th}>GSI1PK</th><th {th}>GSI1SK</th><th {th}>Other attributes</th></tr>'
    f'<tr><td {td}><b>Task</b></td><td {td}>USER#&lt;sub&gt;</td><td {td}>TASK#&lt;taskId&gt;</td><td {td}>USER#&lt;sub&gt;</td>'
    f'<td {td}>STATUS#&lt;Status&gt;#&lt;timestamp&gt;</td><td {td}>TaskId (UUID), UserId, Email, Description, Date, '
    'Status (Pending | Completed | Expired), Deadline (epoch), DeadlineISO, ScheduleName, ScheduleGroup, '
    'CreatedAt, UpdatedAt, CompletedAt, ExpiredAt, NotifiedAt</td></tr>'
    f'<tr><td {td}><b>User profile</b></td><td {td}>USER#&lt;sub&gt;</td><td {td}>PROFILE</td><td {td}>–</td><td {td}>–</td>'
    f'<td {td}>Email, SubscriptionArn, SubscribedAt, UpdatedAt</td></tr></table><br>'
    f'<table style="border-collapse:collapse;font-size:12px"><tr><th {th}>Access pattern</th><th {th}>Operation</th><th {th}>Used by</th></tr>'
    f'<tr><td {td}>List a user\'s tasks</td><td {td}>Query PK = USER#sub, SK begins_with TASK#</td><td {td}>ListTasks</td></tr>'
    f'<tr><td {td}>List a user\'s tasks by status</td><td {td}>Query GSI1: GSI1PK = USER#sub, GSI1SK begins_with STATUS#&lt;status&gt;#</td><td {td}>ListTasks ?status=</td></tr>'
    f'<tr><td {td}>Get / update / delete one task</td><td {td}>Get/Update/DeleteItem on PK + SK (ownership enforced by the key)</td><td {td}>Get/Update/DeleteTask</td></tr>'
    f'<tr><td {td}>Expire a task</td><td {td}>UpdateItem with condition Status = Pending</td><td {td}>ExpireTask</td></tr>'
    f'<tr><td {td}>Read / write subscription record</td><td {td}>Get/PutItem PK = USER#sub, SK = PROFILE</td><td {td}>PostAuthentication</td></tr>'
    '</table><br>'
    '<b>Status lifecycle</b>: Pending → Completed (user, PUT status=Completed) · Pending → Expired (ExpireTask at deadline). '
    'Completed and Expired are final; every transition is a conditional write, so the two can never both happen.'
    '</div>'
)
vertex(tbl, 40, 40, 1300, 560, "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;fontColor=#232F3E;")
page2 = "".join(cells)


def diagram(name, did, body, w, h):
    return (f'<diagram name="{name}" id="{did}"><mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" '
            f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{w}" pageHeight="{h}" '
            f'math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>')


OUT.write_text('<mxfile host="app.diagrams.net" type="device">'
               + diagram("Architecture", "architecture", page1, 2600, 1860)
               + diagram("DynamoDB design", "dynamodb", page2, 1400, 650)
               + "</mxfile>", encoding="utf-8")
print(f"wrote {OUT}")
