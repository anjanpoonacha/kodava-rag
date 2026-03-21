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
