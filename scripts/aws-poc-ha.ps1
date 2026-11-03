# scripts/aws-poc-ha.ps1 - Phase 8 helpers for scripts/aws-poc.ps1.
# Dot-sourced. Plain up never calls these. Windows PowerShell 5.1, ASCII only.
# Decisions live in ha_migration.py so the abort and single-copy rules are tested.

function Resolve-HaPython {
  if ($script:HaPyExe) { return }
  $options = @(
    @{ Exe = "py"; Prefix = @("-3") },
    @{ Exe = "python"; Prefix = @() },
    @{ Exe = "python3"; Prefix = @() }
  )
  foreach ($opt in $options) {
    $cmd = Get-Command $opt.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    & $cmd.Source @($opt.Prefix) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" | Out-Null
    if ($LASTEXITCODE -eq 0) {
      $script:HaPyExe = $cmd.Source
      $script:HaPyPrefix = @($opt.Prefix)
      return
    }
  }
  throw "Python 3.12 or newer is required for -WithHA. Plain up does not need Python."
}

function Get-HaConstants {
  if ($script:HaConst) { return $script:HaConst }
  Resolve-HaPython
  $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
  $out = & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "constants"
  if ($LASTEXITCODE -ne 0) { throw "ha_migration.py constants failed" }
  $script:HaConst = $out | ConvertFrom-Json
  return $script:HaConst
}

function Invoke-HaJson {
  param([string]$Command, [hashtable]$Body)
  Resolve-HaPython
  $json = $Body | ConvertTo-Json -Compress -Depth 8
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString("n") + ".json")
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [IO.File]::WriteAllText($tmp, $json, $utf8)
  try {
    $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
    $out = & $script:HaPyExe @($script:HaPyPrefix) $scriptPath $Command "--input" $tmp
    if ($LASTEXITCODE -ne 0) { throw "ha_migration.py $Command failed" }
    return ($out | ConvertFrom-Json)
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Read-DotEnvValue {
  param([string]$Path, [string]$Name)
  if (-not (Test-Path $Path)) { return "" }
  $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)$'
  foreach ($line in Get-Content -Path $Path) {
    if ($line -match '^\s*#') { continue }
    if ($line -match $pattern) {
      $value = $Matches[1].Trim()
      if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        return $value.Substring(1, $value.Length - 2)
      }
      return $value
    }
  }
  return ""
}

function Get-HaStatePath { return (Join-Path $RepoRoot ".ha-migration-state.json") }

function Read-HaState {
  $path = Get-HaStatePath
  if (-not (Test-Path $path)) { return $null }
  return (Get-Content -Path $path -Raw | ConvertFrom-Json)
}

function Save-HaState {
  param([hashtable]$Fields)
  $utf8 = New-Object System.Text.UTF8Encoding $false
  $json = $Fields | ConvertTo-Json -Compress
  [IO.File]::WriteAllText((Get-HaStatePath), $json, $utf8)
}

function Test-HomeHaRunning {
  $c = Get-HaConstants
  $names = & docker compose --project-directory $RepoRoot ps --status running --services
  if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed. Start Docker Desktop and rerun." }
  foreach ($name in @($names)) {
    if (-not $name) { continue }
    if ($name.Trim() -eq $c.compose_service) { return $true }
  }
  return $false
}

function Stop-HomeHa {
  $c = Get-HaConstants
  Step "Stop Home Assistant at home (docker compose service $($c.compose_service))"
  & docker compose --project-directory $RepoRoot stop $c.compose_service
  if ($LASTEXITCODE -ne 0) { throw "docker compose stop failed" }
  if (Test-HomeHaRunning) { throw "home Home Assistant is still running after stop" }
}

function Start-HomeHa {
  $c = Get-HaConstants
  if (Test-EksHaContainerRunning) {
    throw "Refusing to start home Home Assistant while EKS Home Assistant is still running."
  }
  Step "Start Home Assistant at home (docker compose service $($c.compose_service))"
  & docker compose --project-directory $RepoRoot up -d --no-deps $c.compose_service
  if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
}

function Test-EksClusterPresent {
  $n = & aws eks list-clusters --query "length(clusters[?@=='$Cluster'])" --output text
  if ($LASTEXITCODE -ne 0) { return $false }
  return ("$n".Trim() -eq "1")
}

function Get-EksHaSnapshot {
  $result = @{ Present = $false; Running = $false }
  if (-not (Test-EksClusterPresent)) { return $result }
  $previous = $env:KUBECONFIG
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("ha-kube-" + [guid]::NewGuid().ToString("n"))
  try {
    & aws eks update-kubeconfig --region $Region --name $Cluster --kubeconfig $tmp | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "update-kubeconfig failed while checking Home Assistant." }
    $env:KUBECONFIG = $tmp
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $json = & kubectl get deploy home-assistant -n grow-room -o json 2>$null
    $depCode = $LASTEXITCODE
    $pods = & kubectl get pods -n grow-room -l app.kubernetes.io/name=home-assistant -o json 2>$null
    $ErrorActionPreference = $prev
    if ($depCode -eq 0 -and $json) {
      $dep = $json | ConvertFrom-Json
      $result.Present = $true
      $desired = 0
      if ($dep.spec -and $null -ne $dep.spec.replicas) { $desired = [int]$dep.spec.replicas }
      if ($desired -gt 0) { $result.Running = $true }
    }
    if ($pods) {
      $parsed = $pods | ConvertFrom-Json
      foreach ($pod in @($parsed.items)) {
        if (-not $pod -or -not $pod.status) { continue }
        foreach ($cs in @($pod.status.containerStatuses)) {
          if ($cs -and $cs.name -eq "home-assistant" -and $cs.state -and $cs.state.running) {
            $result.Running = $true
          }
        }
      }
    }
  } finally {
    if ([string]::IsNullOrEmpty($previous)) { Remove-Item Env:\KUBECONFIG -ErrorAction SilentlyContinue }
    else { $env:KUBECONFIG = $previous }
    if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
  }
  return $result
}

function Test-EksHaPresent { return [bool](Get-EksHaSnapshot).Present }
function Test-EksHaContainerRunning { return [bool](Get-EksHaSnapshot).Running }

function Get-FileSha256B64 {
  param([string]$Path)
  $sha = [Security.Cryptography.SHA256]::Create()
  $stream = [IO.File]::OpenRead($Path)
  try { $hash = $sha.ComputeHash($stream) }
  finally { $stream.Dispose(); $sha.Dispose() }
  return [Convert]::ToBase64String($hash)
}

function Use-HaBackupRole {
  $c = Get-HaConstants
  $arn = "arn:aws:iam::${Account}:role/$($c.role_name)"
  $json = & aws sts assume-role --role-arn $arn --role-session-name grow-room-ha-backup --duration-seconds 3600 --output json
  if ($LASTEXITCODE -ne 0 -or -not $json) { throw "assume-role $($c.role_name) failed" }
  $cred = $json | ConvertFrom-Json
  $script:HaPrevAccess = $env:AWS_ACCESS_KEY_ID
  $script:HaPrevSecret = $env:AWS_SECRET_ACCESS_KEY
  $script:HaPrevToken = $env:AWS_SESSION_TOKEN
  $env:AWS_ACCESS_KEY_ID = [string]$cred.Credentials.AccessKeyId
  $env:AWS_SECRET_ACCESS_KEY = [string]$cred.Credentials.SecretAccessKey
  $env:AWS_SESSION_TOKEN = [string]$cred.Credentials.SessionToken
  $cred = $null
}

function Clear-HaBackupRole {
  if ($script:HaPrevAccess) { $env:AWS_ACCESS_KEY_ID = $script:HaPrevAccess }
  else { Remove-Item Env:\AWS_ACCESS_KEY_ID -ErrorAction SilentlyContinue }
  if ($script:HaPrevSecret) { $env:AWS_SECRET_ACCESS_KEY = $script:HaPrevSecret }
  else { Remove-Item Env:\AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue }
  if ($script:HaPrevToken) { $env:AWS_SESSION_TOKEN = $script:HaPrevToken }
  else { Remove-Item Env:\AWS_SESSION_TOKEN -ErrorAction SilentlyContinue }
  $script:HaPrevAccess = $null
  $script:HaPrevSecret = $null
  $script:HaPrevToken = $null
}

function Invoke-HaPrune {
  param([int]$Keep = 5)
  $c = Get-HaConstants
  $items = @()
  $page = $null
  do {
    $awsArgs = @("s3api", "list-objects-v2", "--bucket", $c.bucket, "--prefix", [string]$c.backup_prefix, "--output", "json")
    if ($page) { $awsArgs += @("--continuation-token", $page) }
    $json = & aws @awsArgs
    if ($LASTEXITCODE -ne 0) { throw "list ha-backups failed" }
    $parsed = $json | ConvertFrom-Json
    if ($parsed.Contents) {
      foreach ($obj in @($parsed.Contents)) {
        if (-not $obj) { continue }
        $safeKey = ([string]$obj.Key) -replace '"', ''
        $items += @{ key = $safeKey; last_modified = [string]$obj.LastModified }
      }
    }
    if ($parsed.IsTruncated -and $parsed.NextContinuationToken) { $page = [string]$parsed.NextContinuationToken }
    else { $page = $null }
  } while ($page)
  $rows = @()
  foreach ($item in $items) {
    $rows += ('{"key":"' + $item.key + '","last_modified":"' + $item.last_modified + '"}')
  }
  $raw = '{"keep":' + $Keep + ',"keys":[' + ($rows -join ",") + ']}'
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString("n") + ".json")
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [IO.File]::WriteAllText($tmp, $raw, $utf8)
  try {
    Resolve-HaPython
    $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
    $out = & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "prune" "--input" $tmp
    if ($LASTEXITCODE -ne 0) { throw "prune failed" }
    $plan = $out | ConvertFrom-Json
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
  $delete = @()
  if ($plan.delete) { $delete = @($plan.delete) }
  foreach ($key in $delete) {
    if (-not "$key".StartsWith([string]$c.backup_prefix)) { throw "prune refused a key outside ha-backups/" }
    & aws s3api delete-object --bucket $c.bucket --key $key | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "delete old backup failed" }
    Write-Host "  pruned $key"
  }
}

function Send-VerifiedBackup {
  param([string]$Archive, [string]$Key)
  $c = Get-HaConstants
  if (-not "$Key".StartsWith([string]$c.backup_prefix)) { throw "refusing backup key" }
  $localSize = (Get-Item $Archive).Length
  $localSum = Get-FileSha256B64 $Archive
  Use-HaBackupRole
  try {
    $keyArn = & aws kms describe-key --key-id $c.kms_alias --query KeyMetadata.Arn --output text
    if ($LASTEXITCODE -ne 0 -or -not $keyArn) { throw "could not resolve KMS alias" }
    $put = & aws s3api put-object --bucket $c.bucket --key $Key --body $Archive --server-side-encryption aws:kms --ssekms-key-id $c.kms_alias --checksum-algorithm SHA256 --output json
    if ($LASTEXITCODE -ne 0 -or -not $put) { throw "put-object failed for $Key" }
    $headJson = & aws s3api head-object --bucket $c.bucket --key $Key --checksum-mode ENABLED --output json
    if ($LASTEXITCODE -ne 0 -or -not $headJson) { throw "head-object failed for $Key" }
    $head = $headJson | ConvertFrom-Json
    $verdict = Invoke-HaJson "verify-head" @{
      local_size = $localSize
      local_sha256_b64 = $localSum
      expected_kms_key_arn = "$keyArn".Trim()
      head = @{
        ContentLength = $head.ContentLength
        ServerSideEncryption = [string]$head.ServerSideEncryption
        ChecksumSHA256 = [string]$head.ChecksumSHA256
        SSEKMSKeyId = [string]$head.SSEKMSKeyId
      }
    }
    if (-not $verdict.ok) {
      & aws s3api delete-object --bucket $c.bucket --key $Key | Out-Null
      throw "upload not verified for ${Key}: $($verdict.reason)"
    }
    Invoke-HaPrune -Keep $HaBackupKeep
  } finally {
    Clear-HaBackupRole
  }
  Ok "uploaded $Key ($localSize bytes, KMS, checksum matched)"
}

function Backup-HomeConfigToS3 {
  $c = Get-HaConstants
  $cfg = Join-Path $RepoRoot ([string]$c.config_dir)
  $db = Join-Path $cfg ([string]$c.db_name)
  if (-not (Test-Path $db)) { throw "backup refused: database file is not in the config folder" }
  Resolve-HaPython
  $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
  $keyJson = & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "object-key"
  if ($LASTEXITCODE -ne 0) { throw "object-key failed" }
  $key = [string]($keyJson | ConvertFrom-Json).key
  $archive = Join-Path ([IO.Path]::GetTempPath()) ("ha-" + [guid]::NewGuid().ToString("n") + ".tar.gz")
  try {
    & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "pack" "--config" $cfg "--output" $archive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pack of the Home Assistant config folder failed" }
    Send-VerifiedBackup -Archive $archive -Key $key
  } finally {
    if (Test-Path $archive) { Remove-Item $archive -Force }
  }
  return $key
}

function Assert-HaMovePreflight {
  $c = Get-HaConstants
  $cfg = Join-Path $RepoRoot ([string]$c.config_dir)
  $db = Join-Path $cfg ([string]$c.db_name)
  if (-not (Test-Path $db)) { throw "Home Assistant database file is missing. Refusing to stop Home Assistant." }
  $present = Read-DotEnvValue (Join-Path $RepoRoot ".env") "HA_TOKEN"
  if (-not $present) { throw "HA_TOKEN is missing from .env. Refusing to stop Home Assistant." }
  $present = $null
  $services = & docker compose --project-directory $RepoRoot config --services
  if ($LASTEXITCODE -ne 0) { throw "docker compose config failed. Start Docker Desktop." }
  $found = $false
  foreach ($name in @($services)) {
    if ($name -and $name.Trim() -eq $c.compose_service) { $found = $true }
  }
  if (-not $found) { throw "Compose file has no Home Assistant service." }
  & aws iam get-role --role-name $c.role_name | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "IAM role $($c.role_name) is missing. Apply infra/telemetry first. Home Assistant was not stopped."
  }
  Use-HaBackupRole
  try {
    & aws s3api list-objects-v2 --bucket $c.bucket --prefix $c.backup_prefix --max-keys 1 --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "cannot list the backup prefix with role $($c.role_name)" }
    & aws kms describe-key --key-id $c.kms_alias --query KeyMetadata.KeyId --output text | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "cannot use KMS alias $($c.kms_alias)" }
  } finally {
    Clear-HaBackupRole
  }
}

function Invoke-HaDryRunChecks {
  Assert-HaMovePreflight
  $c = Get-HaConstants
  $db = Join-Path (Join-Path $RepoRoot ([string]$c.config_dir)) ([string]$c.db_name)
  $size = (Get-Item $db).Length
  $home = Test-HomeHaRunning
  $snap = Get-EksHaSnapshot
  Write-Host "  config dir: $($c.config_dir)"
  Write-Host "  database bytes: $size"
  Write-Host "  home running: $home"
  Write-Host "  eks deployment present: $($snap.Present)"
  Write-Host "  eks container running: $($snap.Running)"
  Write-Host "  bucket: $($c.bucket)"
  Write-Host "  prefix: $($c.backup_prefix)"
  Write-Host "  kms alias: $($c.kms_alias)"
  Write-Host "  role: $($c.role_name)"
  Write-Host "  keep: $HaBackupKeep"
  if ($home -and $snap.Running) { throw "Both copies are running. Dry run did not stop either one." }
  Write-Host "  would stop home, upload ha-backups/<timestamp>.tar.gz, then start one EKS copy"
}

function Invoke-WithHaPrepare {
  $script:HaDryRunStop = $false
  $script:HaStoppedHome = $false
  $script:HaWasRunning = $false
  $script:HaAlreadyOnEks = $false
  $script:HaUploadVerified = $false
  $script:HaBackupKey = ""
  $home = Test-HomeHaRunning
  $script:HaWasRunning = $home
  $snap = Get-EksHaSnapshot
  $plan = Invoke-HaJson "plan-up" @{
    with_ha = $true
    dry_run = [bool]$DryRun
    phase = "preflight"
    home_running = [bool]$home
    eks_running = [bool]$snap.Running
    backup_ok = $false
    upload_verified = $false
    home_stopped_by_us = $false
    was_running = [bool]$home
    already_on_eks = $false
  }
  if ($plan.action -eq "refuse") { throw $plan.reason }
  if ($plan.action -eq "dry-run") {
    Invoke-HaDryRunChecks
    $script:HaDryRunStop = $true
    return
  }
  if ($plan.action -eq "already-on-eks") {
    $script:HaAlreadyOnEks = $true
    $script:HaUploadVerified = $true
    $state = Read-HaState
    if ($state -and $state.backupKey) { $script:HaBackupKey = [string]$state.backupKey }
    Write-Host "  Home Assistant is already the EKS copy. Skipping the backup."
    return
  }
  if ($plan.action -ne "backup-then-move") { throw "unexpected up plan $($plan.action)" }
  Assert-HaMovePreflight
  try {
    if ($plan.stop_home) {
      Stop-HomeHa
      $script:HaStoppedHome = $true
    }
    if (Test-HomeHaRunning) { throw "home Home Assistant is still running" }
    $key = Backup-HomeConfigToS3
    $after = Invoke-HaJson "plan-up" @{
      with_ha = $true
      phase = "after-backup"
      home_running = (Test-HomeHaRunning)
      eks_running = $false
      backup_ok = $true
      upload_verified = $true
      home_stopped_by_us = [bool]$script:HaStoppedHome
      was_running = [bool]$script:HaWasRunning
      already_on_eks = $false
      dry_run = $false
    }
    if ($after.action -ne "continue-up") { throw $after.reason }
    $script:HaBackupKey = $key
    $script:HaUploadVerified = $true
    Save-HaState @{ location = "moving"; backupKey = $key }
  } catch {
    $failed = Invoke-HaJson "plan-up" @{
      with_ha = $true
      phase = "after-backup"
      home_running = $false
      eks_running = $false
      backup_ok = $false
      upload_verified = $false
      home_stopped_by_us = [bool]$script:HaStoppedHome
      was_running = [bool]$script:HaWasRunning
      already_on_eks = $false
      dry_run = $false
    }
    if ($failed.action -eq "abort-restart-home" -and $failed.start_home) {
      try {
        Start-HomeHa
        $script:HaStoppedHome = $false
      } catch {
        Write-Host "  FAIL  Home Assistant at home did not restart." -ForegroundColor Red
      }
    }
    throw
  }
}

function Set-HaTokenSecret {
  $c = Get-HaConstants
  $value = Read-DotEnvValue (Join-Path $RepoRoot ".env") "HA_TOKEN"
  if (-not $value) { throw "HA_TOKEN is missing from .env" }
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("ha-token-" + [guid]::NewGuid().ToString("n"))
  $utf8 = New-Object System.Text.UTF8Encoding $false
  try {
    [IO.File]::WriteAllText($tmp, $value, $utf8)
    $value = $null
    kubectl -n $c.namespace create secret generic $c.secret_name --from-file=token=$tmp --dry-run=client -o yaml | kubectl apply -f - | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not apply the Home Assistant token secret (value not logged)" }
  } finally {
    $value = $null
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
  }
}

function Add-HaSensorValues {
  param([string]$Manifest)
  $c = Get-HaConstants
  $extra = @"
        env:
          SENSOR_SOURCE: homeassistant
          HA_URL: $($c.ha_url)
        homeAssistant:
          existingSecret: $($c.secret_name)
          secretKey: token

"@
  $needle = "alb.ingress.kubernetes.io/wafv2-acl-arn:"
  $idx = $Manifest.IndexOf($needle)
  if ($idx -lt 0) { throw "sensor-service manifest is missing the WAF annotation" }
  $lineEnd = $Manifest.IndexOf("`n", $idx)
  if ($lineEnd -lt 0) { throw "sensor-service manifest line ending missing" }
  return $Manifest.Insert($lineEnd + 1, $extra)
}

function Invoke-WithHaCluster {
  param([string]$EbsKey)
  $c = Get-HaConstants
  $home = Test-HomeHaRunning
  $snap = Get-EksHaSnapshot
  $plan = Invoke-HaJson "plan-up" @{
    with_ha = $true
    phase = "before-eks"
    home_running = [bool]$home
    eks_running = [bool]$snap.Running
    backup_ok = [bool]$script:HaUploadVerified
    upload_verified = [bool]$script:HaUploadVerified
    home_stopped_by_us = [bool]$script:HaStoppedHome
    was_running = [bool]$script:HaWasRunning
    already_on_eks = [bool]$script:HaAlreadyOnEks
    dry_run = $false
  }
  if ($plan.action -eq "refuse" -or $plan.action -eq "abort-restart-home" -or -not $plan.start_eks_ha) {
    throw $plan.reason
  }
  if (-not $script:HaBackupKey -and -not $script:HaAlreadyOnEks) { throw "no backup key for the EKS restore" }
  Step "EBS CSI addon"
  $deadline = (Get-Date).AddMinutes(15)
  $ready = $false
  $status = ""
  while ((Get-Date) -lt $deadline) {
    $status = & aws eks describe-addon --cluster-name $Cluster --addon-name aws-ebs-csi-driver --query addon.status --output text
    if ($LASTEXITCODE -eq 0 -and "$status".Trim() -eq "ACTIVE") { $ready = $true; break }
    Write-Host "  ...waiting: aws-ebs-csi-driver $status"
    Start-Sleep -Seconds 15
  }
  if (-not $ready) { throw "aws-ebs-csi-driver did not become ACTIVE" }
  Ok "aws-ebs-csi-driver ACTIVE"

  kubectl create namespace $c.namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "namespace $($c.namespace) failed" }
  Set-HaTokenSecret

  $values = Join-Path ([IO.Path]::GetTempPath()) ("ha-values-" + [guid]::NewGuid().ToString("n") + ".yaml")
  $utf8 = New-Object System.Text.UTF8Encoding $false
  $key = [string]$script:HaBackupKey
  $yaml = "bucket: $($c.bucket)`nbackupKey: `"$key`"`nregion: $Region`npersistence:`n  ebsKmsKeyId: `"$EbsKey`"`n"
  [IO.File]::WriteAllText($values, $yaml, $utf8)
  try {
    Step "Helm install home-assistant"
    $chart = Join-Path $RepoRoot "charts\home-assistant"
    helm upgrade --install home-assistant $chart -n $c.namespace --create-namespace -f $values --wait --timeout 15m
    if ($LASTEXITCODE -ne 0) { throw "helm upgrade home-assistant failed" }
  } finally {
    Remove-Item $values -Force -ErrorAction SilentlyContinue
  }
  kubectl rollout status deployment/home-assistant -n $c.namespace --timeout=900s
  if ($LASTEXITCODE -ne 0) { throw "home-assistant did not become ready" }
  Ok "home-assistant ready"
  Save-HaState @{ location = "eks"; backupKey = [string]$script:HaBackupKey }
}

function Stop-EksHa {
  $c = Get-HaConstants
  kubectl scale deployment $c.deployment -n $c.namespace --replicas=0 | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "scale home-assistant to 0 failed" }
  $deadline = (Get-Date).AddMinutes(5)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-EksHaContainerRunning)) { return }
    Start-Sleep -Seconds 5
  }
  throw "timed out waiting for EKS Home Assistant to stop"
}

function Start-EksHa {
  $c = Get-HaConstants
  if (Test-HomeHaRunning) { throw "Refusing to start EKS Home Assistant while home Home Assistant is running." }
  kubectl scale deployment $c.deployment -n $c.namespace --replicas=1 | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "scale home-assistant to 1 failed" }
}

function Backup-EksConfigToS3 {
  $c = Get-HaConstants
  $pod = kubectl get pod -n $c.namespace -l "app.kubernetes.io/name=home-assistant" -o jsonpath="{.items[0].metadata.name}"
  if ($LASTEXITCODE -ne 0 -or -not $pod) { throw "no home-assistant pod to back up" }
  kubectl exec -n $c.namespace $pod -c $c.container -- python3 /scripts/pack_config.py | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "pack inside the EKS pod failed" }
  $archive = Join-Path ([IO.Path]::GetTempPath()) ("ha-eks-" + [guid]::NewGuid().ToString("n") + ".tar.gz")
  try {
    kubectl cp "$($c.namespace)/${pod}:/tmp/ha-backup.tar.gz" $archive -c $c.container
    if ($LASTEXITCODE -ne 0) { throw "kubectl cp of the EKS backup failed" }
    kubectl exec -n $c.namespace $pod -c $c.container -- rm -f /tmp/ha-backup.tar.gz | Out-Null
    Resolve-HaPython
    $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
    & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "check-archive" "--archive" $archive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "EKS archive is missing the Home Assistant database" }
    $keyJson = & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "object-key"
    if ($LASTEXITCODE -ne 0) { throw "object-key failed" }
    $key = [string]($keyJson | ConvertFrom-Json).key
    Send-VerifiedBackup -Archive $archive -Key $key
    return $key
  } finally {
    if (Test-Path $archive) { Remove-Item $archive -Force }
  }
}

function Restore-HomeFromS3Key {
  param([string]$Key)
  $c = Get-HaConstants
  if (-not "$Key".StartsWith([string]$c.backup_prefix) -or "$Key".Contains("..")) { throw "refusing backup key" }
  $archive = Join-Path ([IO.Path]::GetTempPath()) ("ha-restore-" + [guid]::NewGuid().ToString("n") + ".tar.gz")
  Use-HaBackupRole
  try {
    & aws s3api get-object --bucket $c.bucket --key $Key --checksum-mode ENABLED $archive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "get-object failed" }
    $headJson = & aws s3api head-object --bucket $c.bucket --key $Key --checksum-mode ENABLED --output json
    if ($LASTEXITCODE -ne 0 -or -not $headJson) { throw "head-object failed" }
    $head = $headJson | ConvertFrom-Json
    $keyArn = & aws kms describe-key --key-id $c.kms_alias --query KeyMetadata.Arn --output text
    if ($LASTEXITCODE -ne 0 -or -not $keyArn) { throw "could not resolve KMS alias" }
    $verdict = Invoke-HaJson "verify-head" @{
      local_size = (Get-Item $archive).Length
      local_sha256_b64 = (Get-FileSha256B64 $archive)
      expected_kms_key_arn = "$keyArn".Trim()
      head = @{
        ContentLength = $head.ContentLength
        ServerSideEncryption = [string]$head.ServerSideEncryption
        ChecksumSHA256 = [string]$head.ChecksumSHA256
        SSEKMSKeyId = [string]$head.SSEKMSKeyId
      }
    }
    if (-not $verdict.ok) { throw "downloaded backup not verified: $($verdict.reason)" }
  } finally {
    Clear-HaBackupRole
  }
  $cfg = Join-Path $RepoRoot ([string]$c.config_dir)
  Resolve-HaPython
  $scriptPath = Join-Path $PSScriptRoot "ha_migration.py"
  & $script:HaPyExe @($script:HaPyPrefix) $scriptPath "restore-home" "--archive" $archive "--config" $cfg | Out-Null
  $code = $LASTEXITCODE
  if (Test-Path $archive) { Remove-Item $archive -Force }
  if ($code -ne 0) { throw "restore into the home config folder failed" }
}

function Invoke-HaReturnHomeIfNeeded {
  $state = Read-HaState
  $location = ""
  $backupKey = ""
  if ($state) {
    if ($state.location) { $location = [string]$state.location }
    if ($state.backupKey) { $backupKey = [string]$state.backupKey }
  }
  $snap = @{ Present = $false; Running = $false }
  if ($location -eq "eks" -or $location -eq "moving" -or (Test-EksClusterPresent)) {
    $snap = Get-EksHaSnapshot
  }
  $moved = ($location -eq "eks" -or $location -eq "moving" -or [bool]$snap.Present)
  if (-not $moved) { return }

  $home = Test-HomeHaRunning
  $plan = Invoke-HaJson "plan-down" @{
    phase = "preflight"
    home_running = [bool]$home
    eks_running = [bool]$snap.Running
    ha_on_eks = [bool]$snap.Present
    location = $location
    backup_ok = $false
    upload_verified = $false
    restore_ok = $false
  }
  if ($plan.action -eq "refuse") { throw $plan.reason }
  if ($plan.action -eq "plain-down") { return }
  if ($plan.action -eq "restart-home-then-down") {
    if ($plan.stop_eks -and (Test-EksClusterPresent)) {
      Use-Kubeconfig
      Stop-EksHa
    }
    if ($plan.start_home) { Start-HomeHa }
    if (-not (Test-HomeHaRunning)) { throw "home Home Assistant did not start. Teardown did not start." }
    Save-HaState @{ location = "home"; backupKey = $backupKey }
    return
  }

  $key = $backupKey
  if ($plan.action -eq "backup-eks") {
    Use-Kubeconfig
    try { $key = Backup-EksConfigToS3 }
    catch {
      $abort = Invoke-HaJson "plan-down" @{
        phase = "after-eks-backup"
        home_running = (Test-HomeHaRunning)
        eks_running = $true
        ha_on_eks = $true
        location = "eks"
        backup_ok = $false
        upload_verified = $false
        restore_ok = $false
      }
      if (-not $abort.continue_teardown) { throw $abort.reason }
      throw
    }
    $after = Invoke-HaJson "plan-down" @{
      phase = "after-eks-backup"
      home_running = (Test-HomeHaRunning)
      eks_running = $true
      ha_on_eks = $true
      location = "eks"
      backup_ok = $true
      upload_verified = $true
      restore_ok = $false
    }
    if ($after.action -ne "stop-eks-then-restore") { throw $after.reason }
    Save-HaState @{ location = "eks"; backupKey = $key }
    Stop-EksHa
    if (Test-EksHaContainerRunning) { throw "EKS Home Assistant is still running. Home was not started." }
  } elseif ($plan.action -eq "restore-from-s3") {
    if (-not $key) { throw "No backup key is recorded. Refusing to guess which object to restore. Teardown did not start." }
  } else {
    throw "unexpected down plan $($plan.action)"
  }

  $restoreOk = $true
  try { Restore-HomeFromS3Key -Key $key }
  catch { $restoreOk = $false }
  $before = Invoke-HaJson "plan-down" @{
    phase = "before-start-home"
    home_running = (Test-HomeHaRunning)
    eks_running = (Test-EksHaContainerRunning)
    ha_on_eks = (Test-EksHaPresent)
    location = "eks"
    backup_ok = $true
    upload_verified = $true
    restore_ok = [bool]$restoreOk
  }
  if ($before.action -eq "refuse" -or $before.action -eq "abort-no-teardown") {
    if ($before.restart_eks -and (Test-EksClusterPresent)) {
      try {
        Use-Kubeconfig
        Start-EksHa
      } catch {
        Write-Host "  WARN  could not scale EKS Home Assistant back up" -ForegroundColor Yellow
      }
    }
    throw $before.reason
  }
  if ($before.start_home -ne $true) { throw $before.reason }
  Start-HomeHa
  $started = Test-HomeHaRunning
  $done = Invoke-HaJson "plan-down" @{
    phase = "after-home-started"
    home_running = [bool]$started
    eks_running = (Test-EksHaContainerRunning)
    ha_on_eks = (Test-EksHaPresent)
    location = "home"
    backup_ok = $true
    upload_verified = $true
    restore_ok = $true
  }
  if (-not $done.continue_teardown) { throw $done.reason }
  Save-HaState @{ location = "home"; backupKey = $key }
}
