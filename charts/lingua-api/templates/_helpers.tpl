{{/*
Resolve the full image reference for a container.

Usage:
  {{ include "lingua-api.image" (dict "values" .Values.app "root" .) }}

Precedence:
  1. Per-image registry  (.values.registry)
  2. Top-level registry  (.root.Values.registry)
*/}}
{{- define "lingua-api.image" -}}
{{- $reg := .values.registry | default .root.Values.registry -}}
{{- printf "%s/%s:%s" $reg .values.image .values.tag -}}
{{- end -}}

{{/*
Resolve the target namespace.

Precedence:
  1. .Values.namespace  (values-kyma.yaml or --set)
  2. .Release.Namespace (helm -n flag)
*/}}
{{- define "lingua-api.namespace" -}}
{{- .Values.namespace | default .Release.Namespace -}}
{{- end -}}
