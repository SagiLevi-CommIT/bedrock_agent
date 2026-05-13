<#
.SYNOPSIS
One-command staging deploy for the Bedrock agent.

.DESCRIPTION
Builds locally, auto-commits deployable changes, uploads the git archive to the
staging CodeBuild source bucket, builds and pushes the ECR image, updates the
local staging terraform.tfvars image_tag, applies the guarded Terraform rollout,
waits for ECS stability, and runs API + browser smoke tests over plain HTTP.

.EXAMPLE
.\scripts\deploy_staging.ps1 -Message "fix send button"

.EXAMPLE
.\scripts\deploy_staging.ps1 -Message "fix send button" -PushGit
#>

param(
  [string]$Message = "",
  [string]$AwsProfile = "cardiac-sense-staging",
  [string]$AwsRegion = "eu-central-1",
  [string]$ExpectedAccountId = "735555370207",
  [string]$ProjectPrefix = "claude-aws-agent-staging",
  [string]$SmokePrompt = "Reply with exactly DEPLOY_SEND_OK.",
  [string]$SmokeExpectedText = "DEPLOY_SEND_OK",
  [int]$CodeBuildTimeoutMinutes = 30,
  [int]$EcsTimeoutMinutes = 15,
  [switch]$SkipLocalBuild,
  [switch]$SkipBrowserSmoke,
  [switch]$AllowInfraChanges,
  [switch]$PushGit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$StartedAt = Get-Date
$TerraformPlanPath = $null

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
  param([string]$Message)
  Write-Host "OK: $Message" -ForegroundColor Green
}

function Write-Warn {
  param([string]$Message)
  Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Resolve-Tool {
  param(
    [string[]]$Names,
    [string[]]$FallbackPaths = @()
  )

  foreach ($name in $Names) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) {
      return $cmd.Source
    }
  }

  foreach ($path in $FallbackPaths) {
    if (Test-Path -LiteralPath $path) {
      return $path
    }
  }

  throw "Required tool not found: $($Names -join ', ')"
}

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$Arguments = @(),
    [string]$WorkingDirectory = "",
    [switch]$Capture
  )

  $oldLocation = Get-Location
  if ($WorkingDirectory) {
    Set-Location -LiteralPath $WorkingDirectory
  }

  try {
    if ($Capture) {
      $output = & $FilePath @Arguments 2>&1
      $exitCode = if ($global:LASTEXITCODE -is [int]) { $global:LASTEXITCODE } else { 0 }
      $text = ($output | ForEach-Object { "$_" }) -join "`n"
      if ($exitCode -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $exitCode`n$text"
      }
      return $text.Trim()
    }

    & $FilePath @Arguments
    $exitCode = if ($global:LASTEXITCODE -is [int]) { $global:LASTEXITCODE } else { 0 }
    if ($exitCode -ne 0) {
      throw "$FilePath $($Arguments -join ' ') failed with exit code $exitCode"
    }
  }
  finally {
    Set-Location $oldLocation
  }
}

function Invoke-AwsText {
  param([string[]]$Arguments)
  return Invoke-Checked -FilePath $script:AwsCli -Arguments (@("--profile", $AwsProfile, "--region", $AwsRegion) + $Arguments) -Capture
}

function Invoke-AwsJson {
  param([string[]]$Arguments)
  $text = Invoke-AwsText -Arguments ($Arguments + @("--output", "json"))
  return $text | ConvertFrom-Json
}

function Get-TerraformOutput {
  param([string]$Name)
  return Invoke-Checked -FilePath $script:Terraform -Arguments @("output", "-raw", $Name) -WorkingDirectory $script:StagingDir -Capture
}

function Assert-StagingAccount {
  Write-Step "Checking AWS identity"
  $identity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity")
  if ($identity.Account -ne $ExpectedAccountId) {
    throw "Refusing to deploy: AWS profile '$AwsProfile' points to account '$($identity.Account)', expected '$ExpectedAccountId'."
  }
  Write-Ok "AWS profile '$AwsProfile' is account $($identity.Account) ($($identity.Arn))"
}

function Assert-NoUnsafeInfraChanges {
  if ($AllowInfraChanges) {
    Write-Warn "AllowInfraChanges is set; tracked infra changes may affect terraform apply."
    return
  }

  $infraChanges = Invoke-Checked -FilePath $script:Git -Arguments @("status", "--porcelain", "--untracked-files=no", "--", "infra") -WorkingDirectory $script:RepoRoot -Capture
  if (-not [string]::IsNullOrWhiteSpace($infraChanges)) {
    throw "Refusing to deploy with tracked infra changes. Commit/review infra separately, or rerun with -AllowInfraChanges.`n$infraChanges"
  }
}

function Invoke-LocalBuild {
  if ($SkipLocalBuild) {
    Write-Warn "Skipping local UI build by request."
    return
  }

  Write-Step "Running local UI build"
  $uiDir = Join-Path $script:RepoRoot "ui"
  if (-not (Test-Path -LiteralPath (Join-Path $uiDir "node_modules"))) {
    Write-Host "node_modules missing; running npm ci"
    Invoke-Checked -FilePath $script:Npm -Arguments @("ci") -WorkingDirectory $uiDir
  }
  Invoke-Checked -FilePath $script:Npm -Arguments @("run", "build") -WorkingDirectory $uiDir
  Write-Ok "Local UI build passed"
}

function Invoke-AutoCommit {
  Write-Step "Committing deployable changes if needed"

  $deployPaths = @("app", "ui", "prompts", "knowledge", "scripts", ".gitignore")
  Invoke-Checked -FilePath $script:Git -Arguments (@("add", "--") + $deployPaths) -WorkingDirectory $script:RepoRoot

  $staged = Invoke-Checked -FilePath $script:Git -Arguments @("diff", "--cached", "--name-only") -WorkingDirectory $script:RepoRoot -Capture
  if ([string]::IsNullOrWhiteSpace($staged)) {
    Write-Ok "No deployable changes to commit; using current HEAD"
    return
  }

  if ([string]::IsNullOrWhiteSpace($Message)) {
    $script:CommitMessage = "deploy: staging $((Get-Date).ToString('yyyyMMdd-HHmmss'))"
  }
  else {
    $script:CommitMessage = $Message
  }

  Invoke-Checked -FilePath $script:Git -Arguments @("commit", "-m", $script:CommitMessage) -WorkingDirectory $script:RepoRoot
  Write-Ok "Committed deployable changes"
}

function Invoke-CodeBuildImageBuild {
  param([string]$Tag)

  Write-Step "Packaging source and starting CodeBuild image build"

  $sourceBucket = Invoke-AwsText -Arguments @(
    "s3api", "list-buckets",
    "--query", "Buckets[?starts_with(Name, '$ProjectPrefix-codebuild-src-')].Name | [0]",
    "--output", "text"
  )
  if ([string]::IsNullOrWhiteSpace($sourceBucket) -or $sourceBucket -eq "None") {
    throw "CodeBuild source bucket not found for prefix '$ProjectPrefix'."
  }

  $zipPath = Join-Path $env:TEMP "agent-source-$Tag.zip"
  if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
  }

  Invoke-Checked -FilePath $script:Git -Arguments @("archive", "--format=zip", "--output=$zipPath", "HEAD", "app", "ui", "prompts", "knowledge", "skills") -WorkingDirectory $script:RepoRoot
  Invoke-AwsText -Arguments @("s3", "cp", $zipPath, "s3://$sourceBucket/source.zip") | Out-Host

  $buildId = Invoke-AwsText -Arguments @(
    "codebuild", "start-build",
    "--project-name", "$ProjectPrefix-image-build",
    "--environment-variables-override", "name=IMAGE_TAG,value=$Tag,type=PLAINTEXT",
    "--query", "build.id",
    "--output", "text"
  )

  Write-Host "Build id: $buildId"

  $deadline = (Get-Date).AddMinutes($CodeBuildTimeoutMinutes)
  while ($true) {
    $builds = Invoke-AwsJson -Arguments @("codebuild", "batch-get-builds", "--ids", $buildId)
    $build = @($builds.builds)[0]
    $status = $build.buildStatus
    Write-Host "CodeBuild status: $status"

    if ($status -eq "SUCCEEDED") {
      Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
      Write-Ok "Image build succeeded with tag $Tag"
      return
    }

    if (@("FAILED", "FAULT", "TIMED_OUT", "STOPPED") -contains $status) {
      Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
      $phaseText = ($build.phases | ForEach-Object { "$($_.phaseType):$($_.phaseStatus)" }) -join ", "
      $logLink = if ($build.logs.deepLink) { $build.logs.deepLink } else { "(no log link)" }
      throw "CodeBuild $status. Phases: $phaseText. Logs: $logLink"
    }

    if ((Get-Date) -gt $deadline) {
      throw "CodeBuild did not finish within $CodeBuildTimeoutMinutes minutes: $buildId"
    }

    Start-Sleep -Seconds 10
  }
}

function Confirm-EcrImage {
  param([string]$Tag)

  Write-Step "Verifying ECR image tag"
  $image = Invoke-AwsJson -Arguments @(
    "ecr", "describe-images",
    "--repository-name", "$ProjectPrefix-backend",
    "--image-ids", "imageTag=$Tag"
  )
  $pushed = @($image.imageDetails)[0].imagePushedAt
  Write-Ok "ECR image $ProjectPrefix-backend`:$Tag exists (pushed $pushed)"
}

function Test-EcrImageTag {
  param([string]$Tag)

  try {
    Invoke-AwsJson -Arguments @(
      "ecr", "describe-images",
      "--repository-name", "$ProjectPrefix-backend",
      "--image-ids", "imageTag=$Tag"
    ) | Out-Null
    return $true
  }
  catch {
    return $false
  }
}

function Update-TerraformTfvars {
  param([string]$Tag)

  Write-Step "Updating staging terraform.tfvars image_tag"
  $tfvarsPath = Join-Path $script:StagingDir "terraform.tfvars"
  if (-not (Test-Path -LiteralPath $tfvarsPath)) {
    throw "Missing $tfvarsPath"
  }

  $encoding = New-Object System.Text.UTF8Encoding $false
  $text = [System.IO.File]::ReadAllText($tfvarsPath)
  if ($text -notmatch '(?m)^image_tag\s*=') {
    throw "terraform.tfvars does not contain image_tag."
  }

  $updated = [regex]::Replace($text, '(?m)^image_tag\s*=\s*".*"\s*$', "image_tag         = `"$Tag`"")
  [System.IO.File]::WriteAllText($tfvarsPath, $updated, $encoding)
  Write-Ok "terraform.tfvars image_tag = $Tag"
}

function Invoke-TerraformDeploy {
  param([string]$Tag)

  Write-Step "Running Terraform plan"

  if (-not (Test-Path -LiteralPath (Join-Path $script:StagingDir ".terraform"))) {
    Invoke-Checked -FilePath $script:Terraform -Arguments @("init", "-backend-config=backend.hcl", "-input=false") -WorkingDirectory $script:StagingDir
  }

  $script:TerraformPlanPath = Join-Path $env:TEMP "bedrock-agent-$Tag.tfplan"
  if (Test-Path -LiteralPath $script:TerraformPlanPath) {
    Remove-Item -LiteralPath $script:TerraformPlanPath -Force
  }

  Invoke-Checked -FilePath $script:Terraform -Arguments @(
    "plan",
    "-input=false",
    "-var", "aws_profile=$AwsProfile",
    "-out", $script:TerraformPlanPath
  ) -WorkingDirectory $script:StagingDir

  Write-Step "Validating Terraform plan scope"
  $planJson = Invoke-Checked -FilePath $script:Terraform -Arguments @("show", "-json", $script:TerraformPlanPath) -WorkingDirectory $script:StagingDir -Capture
  $plan = $planJson | ConvertFrom-Json
  $changes = @($plan.resource_changes | Where-Object {
    ((@($_.change.actions) -join ",") -ne "no-op")
  })

  foreach ($change in $changes) {
    $address = $change.address
    $actions = @($change.change.actions) -join ","
    $allowed = $false

    if ($address -eq "module.ecs.aws_ecs_task_definition.this" -and @("delete,create", "create,delete", "create", "update") -contains $actions) {
      $allowed = $true
    }
    elseif ($address -eq "module.ecs.aws_ecs_service.this" -and $actions -eq "update") {
      $allowed = $true
    }
    elseif ($address -match "^module\.iam\.aws_iam_role_policy\." -and ($actions -eq "update" -or $actions -eq "create")) {
      $allowed = $true
    }
    elseif ($address -match "^module\.indexing\." -and (@("create", "update") -contains $actions)) {
      $allowed = $true
    }

    if (-not $allowed) {
      $summary = ($changes | ForEach-Object { "$($_.address) [$(@($_.change.actions) -join ',')]" }) -join "`n"
      throw "Terraform plan contains changes outside the allowed ECS image rollout scope:`n$summary"
    }
  }

  if ($changes.Count -eq 0) {
    Write-Warn "Terraform plan has no changes. Skipping apply."
    return
  }

  Write-Ok "Terraform plan is limited to ECS image rollout"
  Write-Step "Applying Terraform plan"
  Invoke-Checked -FilePath $script:Terraform -Arguments @("apply", "-input=false", $script:TerraformPlanPath) -WorkingDirectory $script:StagingDir
  Write-Ok "Terraform apply completed"
}

function Wait-EcsStable {
  param(
    [string]$Cluster,
    [string]$Service,
    [string]$Tag
  )

  Write-Step "Waiting for ECS service stability"
  $deadline = (Get-Date).AddMinutes($EcsTimeoutMinutes)
  while ($true) {
    $result = Invoke-AwsJson -Arguments @("ecs", "describe-services", "--cluster", $Cluster, "--services", $Service)
    $svc = @($result.services)[0]
    $deployments = @($svc.deployments)
    $primary = @($deployments | Where-Object { $_.status -eq "PRIMARY" })[0]
    $rollout = if ($primary) { $primary.rolloutState } else { "UNKNOWN" }
    Write-Host "ECS desired=$($svc.desiredCount) running=$($svc.runningCount) deployments=$($deployments.Count) rollout=$rollout"

    if ($svc.desiredCount -eq $svc.runningCount -and $deployments.Count -eq 1 -and $rollout -eq "COMPLETED") {
      $taskDefArn = $svc.taskDefinition
      $image = Invoke-AwsText -Arguments @(
        "ecs", "describe-task-definition",
        "--task-definition", $taskDefArn,
        "--query", "taskDefinition.containerDefinitions[0].image",
        "--output", "text"
      )
      if (-not $image.EndsWith(":$Tag")) {
        throw "ECS is stable but task definition image is '$image', expected tag '$Tag'."
      }
      Write-Ok "ECS stable on $taskDefArn using $image"
      return
    }

    if ((Get-Date) -gt $deadline) {
      throw "ECS service did not become stable within $EcsTimeoutMinutes minutes."
    }

    Start-Sleep -Seconds 15
  }
}

function Invoke-HttpSmokeTests {
  param([string]$AlbUrl)

  Write-Step "Running HTTP/API smoke tests"

  $root = Invoke-WebRequest -UseBasicParsing -Uri "$AlbUrl/" -Method Get -TimeoutSec 30
  if ($root.StatusCode -ne 200 -or $root.Content -notmatch '<div id="root"') {
    throw "UI root smoke test failed. Status=$($root.StatusCode)"
  }

  $health = Invoke-RestMethod -Uri "$AlbUrl/api/health" -Method Get -TimeoutSec 30
  if ($health.status -ne "ok") {
    throw "Health smoke test failed: $($health | ConvertTo-Json -Compress)"
  }

  $body = @{ prompt = $SmokePrompt; session_id = $null } | ConvertTo-Json -Compress
  $chat = Invoke-RestMethod -Uri "$AlbUrl/api/chat" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 300
  if ([string]::IsNullOrWhiteSpace($chat.request_id) -or [string]::IsNullOrWhiteSpace($chat.text)) {
    throw "Chat smoke test returned an invalid response: $($chat | ConvertTo-Json -Compress)"
  }

  Write-Ok "HTTP/API smoke tests passed (model=$($health.model), tools=$($health.tools), request_id=$($chat.request_id))"
}

function Resolve-BrowserPath {
  $candidates = @(
    "msedge.exe",
    "chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
  )

  foreach ($candidate in $candidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) {
      return $cmd.Source
    }
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }

  throw "Neither Edge nor Chrome was found for browser smoke testing. Rerun with -SkipBrowserSmoke only if you intentionally want API-only smoke tests."
}

function Invoke-BrowserSmokeTest {
  param([string]$AlbUrl)

  if ($SkipBrowserSmoke) {
    Write-Warn "Skipping browser smoke test by request."
    return
  }

  Write-Step "Running browser Send smoke test over plain HTTP"
  $browserPath = Resolve-BrowserPath
  $debugPort = Get-Random -Minimum 9300 -Maximum 9700
  $profileDir = Join-Path $env:TEMP ("codex-staging-browser-smoke-" + [guid]::NewGuid().ToString("N"))
  $browser = $null

  try {
    $browser = Start-Process -FilePath $browserPath -ArgumentList @(
      "--headless=new",
      "--remote-debugging-port=$debugPort",
      "--user-data-dir=$profileDir",
      "--disable-gpu",
      "about:blank"
    ) -WindowStyle Hidden -PassThru

    $deadline = (Get-Date).AddSeconds(20)
    do {
      Start-Sleep -Milliseconds 500
      $listener = Get-NetTCPConnection -LocalPort $debugPort -State Listen -ErrorAction SilentlyContinue
    } until ($listener -or (Get-Date) -gt $deadline)

    if (-not $listener) {
      throw "Browser CDP port $debugPort did not open."
    }

    $env:DEPLOY_SMOKE_URL = $AlbUrl
    $env:DEPLOY_SMOKE_PROMPT = $SmokePrompt
    $env:DEPLOY_SMOKE_EXPECT = $SmokeExpectedText
    $env:DEPLOY_CDP_PORT = "$debugPort"

    $nodeScript = @'
const targetUrl = process.env.DEPLOY_SMOKE_URL;
const promptText = process.env.DEPLOY_SMOKE_PROMPT;
const expectedText = process.env.DEPLOY_SMOKE_EXPECT;
const cdpPort = process.env.DEPLOY_CDP_PORT;

const target = await fetch(`http://127.0.0.1:${cdpPort}/json/new?${encodeURIComponent(targetUrl)}`, { method: 'PUT' }).then((r) => r.json());
const ws = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const exceptions = [];

ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    exceptions.push(msg.params.exceptionDetails?.text || 'runtime exception');
  }
});

await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true });
  ws.addEventListener('error', reject, { once: true });
});

function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evalValue(expression) {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Runtime evaluation failed');
  }
  return result.result.value;
}

async function waitFor(expression, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await evalValue(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${expression}`);
}

await send('Runtime.enable');
await send('Page.enable');

await waitFor('document.readyState === "complete" || document.readyState === "interactive"', 15000);
await waitFor('Boolean(document.querySelector("textarea"))', 15000);

const context = JSON.parse(await evalValue('JSON.stringify({ secure: window.isSecureContext, randomUUIDType: typeof crypto.randomUUID, url: location.href })'));

await evalValue(`(() => {
  const ta = document.querySelector('textarea');
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, ${JSON.stringify(promptText)});
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  return !document.querySelector('button[type="submit"]').disabled;
})()`);

const rect = JSON.parse(await evalValue(`JSON.stringify((() => {
  const r = document.querySelector('button[type="submit"]').getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
})())`));

await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x, y: rect.y });
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });

await waitFor(`document.body.innerText.includes(${JSON.stringify(promptText)})`, 10000);
await waitFor(`document.querySelectorAll('.prose-tight').length > 0 || document.body.innerText.includes('Request failed')`, 120000);

const body = await evalValue('document.body.innerText');
const assistantCount = await evalValue("document.querySelectorAll('.prose-tight').length");

if (exceptions.length) throw new Error(`Browser exceptions: ${exceptions.join('; ')}`);
if (body.includes('Request failed')) throw new Error(body);
if (expectedText && !body.includes(expectedText)) throw new Error(`Expected browser response to include "${expectedText}". Body: ${body}`);

console.log(JSON.stringify({
  ok: true,
  context,
  assistantCount,
  sawPrompt: body.includes(promptText),
  sawExpectedText: expectedText ? body.includes(expectedText) : true
}));
'@

    $output = $nodeScript | & $script:Node "--input-type=module" 2>&1
    $exitCode = if ($global:LASTEXITCODE -is [int]) { $global:LASTEXITCODE } else { 0 }
    $text = ($output | ForEach-Object { "$_" }) -join "`n"
    if ($exitCode -ne 0) {
      throw "Browser smoke test failed with exit code $exitCode`n$text"
    }

    $result = $text | ConvertFrom-Json
    if (-not $result.ok) {
      throw "Browser smoke test returned ok=false: $text"
    }

    Write-Ok "Browser Send smoke test passed (secure=$($result.context.secure), randomUUIDType=$($result.context.randomUUIDType), assistantCount=$($result.assistantCount))"
  }
  finally {
    $owners = @(Get-NetTCPConnection -LocalPort $debugPort -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -ErrorAction SilentlyContinue)
    $ids = @($owners + $(if ($browser) { $browser.Id })) | Where-Object { $_ } | Sort-Object -Unique
    foreach ($id in $ids) {
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $profileDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}

try {
  $script:Git = Resolve-Tool -Names @("git.exe", "git")
  $script:AwsCli = Resolve-Tool -Names @("aws.exe", "aws")
  $script:Npm = Resolve-Tool -Names @("npm.cmd", "npm")
  $script:Node = Resolve-Tool -Names @("node.exe", "node")
  $script:Terraform = Resolve-Tool -Names @("terraform.exe", "terraform") -FallbackPaths @((Join-Path $HOME "bin\terraform.exe"))

  $script:RepoRoot = Invoke-Checked -FilePath $script:Git -Arguments @("rev-parse", "--show-toplevel") -Capture
  $script:StagingDir = Join-Path $script:RepoRoot "infra\envs\staging"
  Set-Location -LiteralPath $script:RepoRoot

  Write-Host "Deploy staging started at $($StartedAt.ToString('s'))"
  Write-Host "Repo: $script:RepoRoot"
  Write-Host "AWS profile: $AwsProfile"
  Write-Host "AWS region: $AwsRegion"

  Assert-StagingAccount
  Assert-NoUnsafeInfraChanges
  Invoke-LocalBuild
  Invoke-AutoCommit

  $tag = Invoke-Checked -FilePath $script:Git -Arguments @("rev-parse", "--short=8", "HEAD") -WorkingDirectory $script:RepoRoot -Capture
  Write-Ok "Deploy tag: $tag"

  if (Test-EcrImageTag -Tag $tag) {
    Write-Warn "ECR image tag $tag already exists; skipping CodeBuild rebuild."
  }
  else {
    Invoke-CodeBuildImageBuild -Tag $tag
  }
  Confirm-EcrImage -Tag $tag
  Update-TerraformTfvars -Tag $tag
  Invoke-TerraformDeploy -Tag $tag

  $cluster = Get-TerraformOutput -Name "ecs_cluster_name"
  $service = Get-TerraformOutput -Name "ecs_service_name"
  $albDns = Get-TerraformOutput -Name "alb_dns_name"
  $albUrl = "http://$albDns"

  Wait-EcsStable -Cluster $cluster -Service $service -Tag $tag
  Invoke-HttpSmokeTests -AlbUrl $albUrl
  Invoke-BrowserSmokeTest -AlbUrl $albUrl

  if ($PushGit) {
    Write-Step "Pushing git branch"
    $branch = Invoke-Checked -FilePath $script:Git -Arguments @("branch", "--show-current") -WorkingDirectory $script:RepoRoot -Capture
    Invoke-Checked -FilePath $script:Git -Arguments @("push", "origin", $branch) -WorkingDirectory $script:RepoRoot
    Write-Ok "Pushed origin/$branch"
  }

  $elapsed = New-TimeSpan -Start $StartedAt -End (Get-Date)
  Write-Host ""
  Write-Host "SUCCESS staging deploy completed" -ForegroundColor Green
  Write-Host "Tag: $tag"
  Write-Host "URL: $albUrl"
  Write-Host "Elapsed: $([math]::Round($elapsed.TotalMinutes, 1)) minutes"
  exit 0
}
catch {
  Write-Host ""
  Write-Host "FAIL staging deploy failed" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Red
  if ($TerraformPlanPath -and (Test-Path -LiteralPath $TerraformPlanPath)) {
    Write-Host "Terraform plan file: $TerraformPlanPath"
  }
  exit 1
}
