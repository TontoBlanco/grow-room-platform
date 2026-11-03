{{- define "grow-alerts.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: grow-alerts
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: grow-room-platform
{{- end }}

{{- define "grow-alerts.alertmanagerURL" -}}
{{- if .Values.delivery.alertmanagerURL -}}
{{- .Values.delivery.alertmanagerURL -}}
{{- else -}}
http://monitoring-alertmanager.{{ .Release.Namespace }}.svc:9093
{{- end -}}
{{- end }}

{{- define "grow-alerts.credentialURI" -}}
http://grow-alerts-credentials.{{ .Release.Namespace }}.svc:{{ .Values.identity.port }}/credentials
{{- end }}

{{- define "grow-alerts.decode" -}}
python -c 'import base64,pathlib; pathlib.Path("/tmp/grow_alerts.py").write_bytes(base64.b64decode(pathlib.Path("/scripts/grow_alerts.py.b64").read_text(encoding="utf-8").strip()))'
{{- end }}

{{- define "grow-alerts.jobPodSecurity" -}}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 65534
  runAsGroup: 65534
  seccompProfile:
    type: RuntimeDefault
{{- end }}

{{- define "grow-alerts.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 65534
  runAsGroup: 65534
  capabilities:
    drop:
      - ALL
{{- end }}
