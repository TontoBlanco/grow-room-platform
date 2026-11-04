# scripts/aws-poc.ps1  - bring the PoC up, check it, tear it down.  Windows PowerShell 5.1.
# Usage:  .\scripts\aws-poc.ps1 up       [-SkipTerraform] [-AutoApprove]
#         .\scripts\aws-poc.ps1 up -WithHA [-DryRun] [-HaBackupKeep 5] [-HaConfigPath path]
#         .\scripts\aws-poc.ps1 verify   [-WithHA]
#         .\scripts\aws-poc.ps1 down     [-SkipTerraform] [-AutoApprove]
# Keep this file plain ASCII (PowerShell 5.1 misreads UTF-8 without BOM).
# -WithHA moves Home Assistant. Plain up does not. Helpers: aws-poc-ha.ps1.
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet("up", "verify", "down")]
  [string]$Action,
  [switch]$SkipTerraform,
  [switch]$AutoApprove,
  [switch]$WithHA,
  [switch]$DryRun,
  [ValidateRange(1, 50)]
  [int]$HaBackupKeep = 5,
  [string]$HaConfigPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$TfDir      = Join-Path $RepoRoot "infra\aws-poc"
$Region     = "us-west-2"
$AwsProfile = "GrowRoom"            # NOT $Profile - that is a PowerShell automatic variable
$Account    = "590183769702"
$Cluster    = "grow-room-poc"
$AppFqdn    = "app.mygrowroom.click" # NOT $Host - also automatic
$ZoneId     = "Z10410981MCU751WUGL52"
. (Join-Path $PSScriptRoot "aws-poc-ha.ps1")

function Step([string]$m) { Write-Host "" ; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "  PASS  $m" -ForegroundColor Green }
function Bad([string]$m)  { Write-Host "  FAIL  $m" -ForegroundColor Red; $script:Failures++ }
function Check-Exit([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

function Wait-Until([scriptblock]$Test, [string]$What, [int]$TimeoutSec = 900, [int]$EverySec = 15) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (& $Test) { Ok $What; return }
    Write-Host "  ...waiting: $What"
    Start-Sleep -Seconds $EverySec
  }
  throw "Timed out after $TimeoutSec s: $What"
}

function Assert-Session {
  Step "AWS session (profile $AwsProfile, region $Region)"
  $env:AWS_PROFILE = $AwsProfile
  $env:AWS_REGION  = $Region
  $acct = aws sts get-caller-identity --query Account --output text
  if ($LASTEXITCODE -ne 0) { aws sso login --profile $AwsProfile; Check-Exit "sso login"; $acct = aws sts get-caller-identity --query Account --output text }
  if ($acct -ne $Account) { throw "Wrong account: $acct" }
  Ok "logged in to $acct"
}

function Tf-Out([string]$name) {
  $v = terraform "-chdir=$TfDir" output -raw $name
  Check-Exit "terraform output $name"
  return $v
}

function Use-Kubeconfig {
  aws eks update-kubeconfig --region $Region --name $Cluster | Out-Null
  Check-Exit "update-kubeconfig"
}

function Confirm-Or-Stop([string]$q) {
  if ($AutoApprove) { return }
  $a = Read-Host "$q Type yes to continue"
  if ($a -ne "yes") { throw "Stopped by you." }
}

function Get-AlertEmail {
  if ($env:ALERT_EMAIL -and $env:ALERT_EMAIL.Trim()) { return $env:ALERT_EMAIL.Trim() }
  $tfvarsPath = Join-Path $TfDir "terraform.tfvars"
  if (Test-Path $tfvarsPath) {
    $raw = Get-Content $tfvarsPath -Raw
    if ($raw -match '(?m)^\s*alert_email\s*=\s*"([^"]+)"') {
      $fromFile = $Matches[1].Trim()
      if ($fromFile) { return $fromFile }
    }
  }
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    $v = & gh variable get ALERT_EMAIL 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and "$v".Trim()) { return "$v".Trim() }
  }
  return ""
}

function Get-AlertsTopicArn {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $arn = & terraform "-chdir=$TfDir" output -raw alerts_topic_arn 2>$null
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  $arn = "$arn".Trim()
  if ($code -eq 0 -and $arn -match "^arn:aws:sns:") { return $arn }
  return "arn:aws:sns:${Region}:${Account}:grow-room-poc-alerts"
}

function Ensure-AlertEmailSubscription([string]$TopicArn, [string]$Email) {
  Step "SNS email subscription on $TopicArn"
  if (-not $Email) {
    Write-Host "  WARN  No alert email. Set `$env:ALERT_EMAIL, alert_email in terraform.tfvars, or GitHub variable ALERT_EMAIL, then rerun up." -ForegroundColor Yellow
    Write-Host "  WARN  $TopicArn has no email subscription until then. Alerts will not arrive." -ForegroundColor Yellow
    return
  }
  $subsJson = & aws sns list-subscriptions-by-topic --topic-arn $TopicArn --output json
  Check-Exit "list SNS subscriptions"
  $subs = @()
  if ($subsJson) {
    $parsed = $subsJson | ConvertFrom-Json
    if ($null -ne $parsed.Subscriptions) { $subs = @($parsed.Subscriptions) }
  }
  $match = $null
  foreach ($s in $subs) {
    if ($s -and $s.Protocol -eq "email" -and $s.Endpoint -eq $Email) { $match = $s; break }
  }
  if ($match) {
    if ($match.SubscriptionArn -eq "PendingConfirmation") {
      Write-Host "  WARN  SNS subscription for $Email is PendingConfirmation." -ForegroundColor Yellow
      Write-Host "  WARN  Click Confirm subscription in the AWS Notifications email (check spam). Alerts are dropped until you do." -ForegroundColor Yellow
      return
    }
    Ok "SNS email $Email confirmed"
    return
  }
  Write-Host "  subscribing $Email (AWS Notifications will send the confirm email)"
  & aws sns subscribe --topic-arn $TopicArn --protocol email --notification-endpoint $Email | Out-Null
  Check-Exit "sns subscribe"
  Write-Host "  WARN  SNS subscription for $Email is PendingConfirmation." -ForegroundColor Yellow
  Write-Host "  WARN  Click Confirm subscription in the AWS Notifications email (check spam). Alerts are dropped until you do." -ForegroundColor Yellow
}

function Get-PocVpcId {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $id = & terraform "-chdir=$TfDir" output -raw vpc_id 2>$null
  $code = $LASTEXITCODE
  $ErrorActionPreference = $prev
  $id = "$id".Trim()
  if ($code -eq 0 -and $id -match "^vpc-") { return $id }
  $id = & aws ec2 describe-vpcs --filters "Name=tag:Name,Values=grow-room-poc-vpc" --query "Vpcs[0].VpcId" --output text
  if ($LASTEXITCODE -ne 0) { return "" }
  $id = "$id".Trim()
  if ($id -match "^vpc-") { return $id }
  return ""
}

# Deletes ONLY status=available ENIs, and ONLY in the PoC VPC. In-use ENIs
# (NAT, RDS, nodes, ALB) are left alone. VPC CNI orphans show up as available
# with a description like aws-K8S-i-... and block subnet / node-SG deletion.
function Remove-AvailableEnis([string]$VpcId) {
  if (-not $VpcId) { return 0 }
  $json = & aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VpcId" "Name=status,Values=available" --output json
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARN  describe available ENIs in $VpcId failed; will retry" -ForegroundColor Yellow
    return 0
  }
  $nics = @()
  if ($json) {
    $parsed = $json | ConvertFrom-Json
    if ($null -ne $parsed.NetworkInterfaces) { $nics = @($parsed.NetworkInterfaces) }
  }
  $deleted = 0
  foreach ($nic in $nics) {
    if (-not $nic) { continue }
    if ($nic.Status -ne "available") { continue }
    $id = $nic.NetworkInterfaceId
    $desc = $nic.Description
    Write-Host "  deleting available ENI $id in $VpcId ($desc)"
    & aws ec2 delete-network-interface --network-interface-id $id | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "  WARN  delete $id failed (will retry if it is still available)" -ForegroundColor Yellow
    } else {
      Ok "deleted available ENI $id"
      $deleted++
    }
  }
  return $deleted
}

function Do-Up {
  if ($DryRun -and -not $WithHA) { throw "-DryRun is only valid with -WithHA." }
  $script:HaStoppedHome = $false
  if (-not $WithHA) {
    Invoke-UpStack
    return
  }
  Assert-Session
  Invoke-WithHaPrepare
  if ($script:HaDryRunStop) {
    Write-Host ""
    Write-Host "DRY RUN. Home Assistant was not stopped. Nothing was uploaded. Terraform was not applied." -ForegroundColor Green
    return
  }
  try {
    Invoke-UpStack
  } catch {
    $err = $_
    if ($script:HaStoppedHome) {
      $eksUp = $false
      try { $eksUp = Test-EksHaContainerRunning } catch { $eksUp = $false }
      if (-not $eksUp) {
        try {
          if ((Test-EksClusterPresent) -and (Test-EksHaPresent)) {
            Use-Kubeconfig
            Stop-EksHa
          }
          Start-HomeHa
        } catch {
          Write-Host "  FAIL  Home Assistant at home did not restart. Run: $(Get-HaStartHint)" -ForegroundColor Red
        }
      }
    }
    throw $err
  }
}

function Invoke-UpStack {
  Assert-Session
  $alertEmail = Get-AlertEmail
  if (-not $SkipTerraform) {
    Step "Terraform apply (about 25-35 min, mostly EKS and Multi-AZ RDS)"
    $ip = (Invoke-RestMethod https://checkip.amazonaws.com).Trim()
    $tfvars = Get-Content (Join-Path $TfDir "terraform.tfvars") -Raw
    if ($tfvars -notmatch [regex]::Escape("$ip/32")) { throw "Your IP is now $ip/32. Update my_ip_cidr in terraform.tfvars and the MY_IP_CIDR repo variable." }
    terraform "-chdir=$TfDir" init -input=false | Out-Null; Check-Exit "init"
    # -var beats terraform.tfvars and the empty default, so a local up subscribes
    # the same address CI passes as TF_VAR_alert_email.
    $planArgs = @("-chdir=$TfDir", "plan", "-input=false", "-lock-timeout=5m")
    if ($alertEmail) {
      $planArgs += @("-var", "alert_email=$alertEmail")
      Write-Host "  SNS alert_email is set; the plan includes the email subscription"
    } else {
      Write-Host "  WARN  No alert email. Terraform will not create an SNS email subscription." -ForegroundColor Yellow
    }
    if ($WithHA) {
      $planArgs += @("-var", "enable_ha_migration=true")
    }
    $planArgs += "-out=up.tfplan"
    & terraform @planArgs
    Check-Exit "plan"
    Confirm-Or-Stop "Apply this plan? Cost starts now (about 0.70 USD/hour while up)."
    terraform "-chdir=$TfDir" apply -input=false -lock-timeout=5m up.tfplan; Check-Exit "apply"
  }

  # Runs after apply and on -SkipTerraform. Idempotent: a confirmed subscription
  # is left alone; PendingConfirmation is reported instead of subscribing again.
  Ensure-AlertEmailSubscription (Get-AlertsTopicArn) $alertEmail

  Step "Read Terraform outputs"
  $vpcId   = Tf-Out "vpc_id"
  $queue   = Tf-Out "karpenter_queue_name"
  $domain  = Tf-Out "domain"
  $rdsAddr = Tf-Out "rds_address"
  $rdsSec  = Tf-Out "rds_secret_arn"
  $certArn = Tf-Out "certificate_arn"
  $wafArn  = Tf-Out "waf_arn"
  $ebsKey  = Tf-Out "ebs_kms_key_arn"

  Step "kubeconfig and nodes"
  Use-Kubeconfig
  kubectl wait --for=condition=Ready nodes --all --timeout=600s; Check-Exit "nodes ready"

  Step "Helm controllers"
  helm repo add eks https://aws.github.io/eks-charts | Out-Null
  helm repo add external-secrets https://charts.external-secrets.io | Out-Null
  helm repo add argo https://argoproj.github.io/argo-helm | Out-Null
  helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/ | Out-Null
  helm repo update | Out-Null
  helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.6.2 -n kube-system --set "clusterName=$Cluster" --set "region=$Region" --set "vpcId=$vpcId" --set "serviceAccount.name=aws-load-balancer-controller" --wait; Check-Exit "LBC"
  helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter --version 1.15.1 -n kube-system --set "settings.clusterName=$Cluster" --set "settings.interruptionQueue=$queue" --set "controller.resources.requests.cpu=500m" --set "controller.resources.requests.memory=512Mi" --wait; Check-Exit "karpenter"
  helm upgrade --install external-secrets external-secrets/external-secrets --version 2.14.0 -n external-secrets --create-namespace --set "installCRDs=true" --wait; Check-Exit "ESO"
  helm upgrade --install argocd argo/argo-cd --version 10.11.6 -n argocd --create-namespace --wait; Check-Exit "argocd"
  helm upgrade --install external-dns external-dns/external-dns --version 1.23.0 -n kube-system --set "provider.name=aws" --set "serviceAccount.name=external-dns" --set "domainFilters={$domain}" --set "sources={ingress}" --set "policy=sync" --set "txtOwnerId=grow-room-poc" --set "env[0].name=AWS_DEFAULT_REGION" --set "env[0].value=$Region" --wait; Check-Exit "external-dns"

  Step "Karpenter NodePool (EBS KMS key ARN changes on every rebuild, so patch it in)"
  $karp = Get-Content (Join-Path $RepoRoot "k8s\aws-poc\karpenter.yaml") -Raw
  $karp = $karp -replace 'arn:aws:kms:us-west-2:590183769702:key/[0-9a-f-]+', $ebsKey
  $karp | kubectl apply -f -; Check-Exit "karpenter.yaml"
  kubectl apply -f (Join-Path $RepoRoot "k8s\aws-poc\cluster-secret-store.yaml"); Check-Exit "cluster-secret-store"

  Step "Argo CD apps (fresh ARNs injected with valuesObject, nothing to commit)"
  $app = @"
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sensor-service
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/TontoBlanco/grow-room-platform.git
    targetRevision: HEAD
    path: charts/sensor-service
    helm:
      valueFiles:
        - values.yaml
        - values-eks.yaml
      valuesObject:
        externalSecret:
          remoteKey: "$rdsSec"
          dbHost: "$rdsAddr"
        ingress:
          annotations:
            alb.ingress.kubernetes.io/certificate-arn: "$certArn"
            alb.ingress.kubernetes.io/wafv2-acl-arn: "$wafArn"
  destination:
    server: https://kubernetes.default.svc
    namespace: grow-room
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
"@
  if ($WithHA) {
    Invoke-WithHaCluster -EbsKey $ebsKey
    $app = Add-HaSensorValues $app
  }
  $app | kubectl apply -f -; Check-Exit "sensor-service app"
  $mon = Join-Path $RepoRoot "gitops\eks\monitoring.yaml"     # Phase 4 adds this file
  if (-not (Test-Path $mon)) { $mon = Join-Path $RepoRoot "gitops\apps\monitoring.yaml" }
  kubectl apply -f $mon; Check-Exit "monitoring app"

  Step "Wait for DNS and HTTPS (ALB + ExternalDNS, about 3-8 min)"
  Wait-Until { (Resolve-DnsName $AppFqdn -ErrorAction SilentlyContinue) -ne $null } "$AppFqdn resolves" 900 20
  Wait-Until { (curl.exe -s -o NUL -w "%{http_code}" "https://$AppFqdn/healthz") -eq "200" } "https://$AppFqdn/healthz is 200" 900 20
  Write-Host ""
  Write-Host "UP. Run: .\scripts\aws-poc.ps1 verify" -ForegroundColor Green
  Write-Host "Cost is running. When finished: .\scripts\aws-poc.ps1 down" -ForegroundColor Yellow
}

function Do-Verify {
  $script:Failures = 0
  Assert-Session
  Use-Kubeconfig

  Step "Cluster"
  $nodes = (kubectl get nodes -o json | ConvertFrom-Json).items
  $ready = @($nodes | Where-Object { ($_.status.conditions | Where-Object { $_.type -eq "Ready" }).status -eq "True" })
  if ($ready.Count -ge 3) { Ok "$($ready.Count) nodes Ready" } else { Bad "only $($ready.Count) nodes Ready" }
  $apps = (kubectl get applications -n argocd -o json | ConvertFrom-Json).items
  foreach ($a in $apps) {
    $s = "$($a.status.sync.status)/$($a.status.health.status)"
    if ($s -eq "Synced/Healthy") { Ok "argo $($a.metadata.name) $s" } else { Bad "argo $($a.metadata.name) $s" }
  }

  Step "Edge: HTTP->HTTPS, TLS, app, database"
  $c = curl.exe -s -o NUL -w "%{http_code}" "http://$AppFqdn/healthz"
  if ($c -eq "301") { Ok "http redirects (301)" } else { Bad "http returned $c, expected 301" }
  $h = curl.exe -s "https://$AppFqdn/healthz"
  if ($h -match '"status":\s*"ok"') { Ok "healthz $h" } else { Bad "healthz returned: $h" }
  $c = curl.exe -s -o NUL -w "%{http_code}" "https://$AppFqdn/readings"
  if ($c -eq "200") { Ok "/readings 200" } else { Bad "/readings $c" }
  if ($WithHA) {
    $r = curl.exe -s "https://$AppFqdn/readings"
    if ($r -match '"source":\s*"homeassistant"') { Ok "readings source homeassistant" } else { Bad "readings source is not homeassistant" }
  }
  try {
    $b = Invoke-RestMethod -Method Post -Uri "https://$AppFqdn/audit/batches" -ContentType "application/json" -Body (@{ name = "verify-$(Get-Date -Format yyyyMMdd-HHmmss)" } | ConvertTo-Json)
    Ok "POST /audit/batches created id $($b.id) (RDS write works)"
  } catch { Bad "POST /audit/batches: $($_.Exception.Message)" }

  Step "AWS side"
  $albArn = aws elbv2 describe-load-balancers --names grow-room-poc --query "LoadBalancers[0].LoadBalancerArn" --output text
  $waf = aws wafv2 get-web-acl-for-resource --resource-arn $albArn --query "WebACL.Name" --output text
  if ($waf -eq "grow-room-poc-alb") { Ok "WAF grow-room-poc-alb on the ALB" } else { Bad "WAF on ALB: $waf" }
  $maz = aws rds describe-db-instances --db-instance-identifier grow-room-poc-audit --query "DBInstances[0].MultiAZ" --output text
  if ($maz -eq "True") { Ok "RDS Multi-AZ" } else { Bad "RDS MultiAZ=$maz" }

  Write-Host ""
  if ($script:Failures -eq 0) { Write-Host "ALL CHECKS PASSED" -ForegroundColor Green } else { Write-Host "$script:Failures CHECK(S) FAILED" -ForegroundColor Red; exit 1 }
}

function Do-Down {
  Assert-Session
  if ($DryRun) { throw "-DryRun is only valid with up -WithHA." }
  Invoke-HaReturnHomeIfNeeded
  $clusterExists = (aws eks list-clusters --query "length(clusters[?@=='grow-room-poc'])" --output text) -eq "1"
  if ($clusterExists) {
    Use-Kubeconfig
    Step "1. Delete Argo apps (their finalizer deletes Ingress, Deployments, ExternalSecrets)"
    kubectl delete application sensor-service monitoring -n argocd --ignore-not-found --wait=true --timeout=10m

    Step "2. Ingress gone -> LBC deletes the ALB"
    Wait-Until { @((kubectl get ingress -A -o json | ConvertFrom-Json).items).Count -eq 0 } "no Ingress objects" 600 10
    Wait-Until { (aws elbv2 describe-load-balancers --query "length(LoadBalancers[?LoadBalancerName=='grow-room-poc'])" --output text) -eq "0" } "ALB grow-room-poc deleted" 900 15

    Step "3. ExternalDNS removes app records (the _xxx.app ACM validation CNAME stays until terraform destroy)"
    Wait-Until { (aws route53 list-resource-record-sets --hosted-zone-id $ZoneId --query "length(ResourceRecordSets[?contains(Name, 'app.mygrowroom.click') && !starts_with(Name, '_')])" --output text) -eq "0" } "app records removed from Route 53" 600 15

    Step "4. Karpenter: delete NodePool, wait for its EC2 nodes to terminate"
    kubectl delete nodepool default --ignore-not-found
    Wait-Until { @((kubectl get nodeclaims -o json | ConvertFrom-Json).items).Count -eq 0 } "no NodeClaims" 900 15

    Step "5. Uninstall controllers (reverse of install)"
    # Phase 8 release. Missing on a plain up, so --ignore-not-found keeps that path quiet.
    # The config was already copied home. Delete the volume while the CSI addon still exists.
    helm uninstall home-assistant -n grow-room --ignore-not-found
    helm uninstall external-dns -n kube-system --ignore-not-found
    helm uninstall argocd -n argocd --ignore-not-found
    helm uninstall external-secrets -n external-secrets --ignore-not-found
    helm uninstall karpenter -n kube-system --ignore-not-found
    helm uninstall aws-load-balancer-controller -n kube-system --ignore-not-found
  } else { Write-Host "Cluster not found; skipping Kubernetes steps." }

  $vpcId = Get-PocVpcId
  if ($vpcId) {
    Step "Delete available ENIs in $vpcId (VPC CNI leftovers; in-use ENIs are kept)"
    $removed = Remove-AvailableEnis $vpcId
    if ($removed -eq 0) { Ok "available ENIs in $vpcId = 0" }
  } else {
    Write-Host "  WARN  PoC VPC not found; skipped the available-ENI delete" -ForegroundColor Yellow
  }

  if (-not $SkipTerraform) {
    Step "6. terraform destroy (about 15-25 min)"
    terraform "-chdir=$TfDir" plan -destroy -input=false -lock-timeout=5m "-out=destroy.tfplan"; Check-Exit "plan -destroy"
    Confirm-Or-Stop "Destroy everything in this plan?"
    if ($vpcId) { Write-Host "  Watching $vpcId for available ENIs while terraform destroy runs" }
    # terraform stays in this console. The loop deletes available ENIs that the
    # VPC CNI releases only after the node group starts terminating. Those are
    # what hung the private subnet and the EKS node security group.
    $tf = (Get-Command terraform -ErrorAction Stop).Source
    $tfArgs = @("-chdir=$TfDir", "apply", "-input=false", "-lock-timeout=5m", "-no-color", "destroy.tfplan")
    $proc = Start-Process -FilePath $tf -ArgumentList $tfArgs -NoNewWindow -PassThru
    while (-not $proc.HasExited) {
      if ($vpcId) {
        # A sweep error must not abandon the terraform process.
        try { [void](Remove-AvailableEnis $vpcId) } catch {
          Write-Host "  WARN  available-ENI sweep: $($_.Exception.Message)" -ForegroundColor Yellow
        }
      }
      Start-Sleep -Seconds 10
      $proc.Refresh()
    }
    $proc.WaitForExit()
    $proc.Refresh()
    if ($proc.ExitCode -ne 0) { throw "destroy failed (exit $($proc.ExitCode))" }
    if ($vpcId) {
      $left = Remove-AvailableEnis $vpcId
      if ($left -eq 0) { Ok "available ENIs in $vpcId = 0 after destroy" }
    }
  }

  Step "7. Leftover sweep (all should be 0)"
  $checks = [ordered]@{
    "EKS clusters"          = "aws eks list-clusters --query 'length(clusters)' --output text"
    "Load balancers"        = "aws elbv2 describe-load-balancers --query 'length(LoadBalancers)' --output text"
    "NAT gateways (avail)"  = "aws ec2 describe-nat-gateways --filter Name=state,Values=available --query 'length(NatGateways)' --output text"
    "Elastic IPs"           = "aws ec2 describe-addresses --query 'length(Addresses)' --output text"
    "Running instances"     = "aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running --query 'length(Reservations[].Instances[])' --output text"
    "Unattached EBS vols"   = "aws ec2 describe-volumes --filters Name=status,Values=available --query 'length(Volumes)' --output text"
    "Available ENIs"        = "aws ec2 describe-network-interfaces --filters Name=status,Values=available --query 'length(NetworkInterfaces)' --output text"
    "RDS instances"         = "aws rds describe-db-instances --query 'length(DBInstances)' --output text"
    "EKS log groups"        = "aws logs describe-log-groups --log-group-name-prefix /aws/eks/grow-room-poc --query 'length(logGroups)' --output text"
  }
  foreach ($k in $checks.Keys) {
    $n = Invoke-Expression $checks[$k]
    if ($n -eq "0") { Ok "$k = 0" } else { Write-Host "  WARN  $k = $n  (look in the console and delete if it is from the PoC)" -ForegroundColor Yellow }
  }
  Write-Host ""
  Write-Host "DOWN. Kept on purpose: state bucket, tfstate KMS key, OIDC roles, budget, hosted zone, telemetry stack (Phase 3)." -ForegroundColor Green
}

switch ($Action) {
  "up"     { Do-Up }
  "verify" { Do-Verify }
  "down"   { Do-Down }
}