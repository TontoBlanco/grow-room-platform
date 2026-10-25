# GitOps snippets (Week 5)

Week 5 is mostly **app + docs**. No new Argo Application is required.

If you add the optional SQLite PVC (`charts/snippets/audit-sqlite-pvc.yaml`),
either:

1. Fold it into the existing `charts/sensor-service` templates and let the
   Week 3 Argo app sync it, or
2. Keep it out of GitOps until you decide the DB should outlive the Pod.

Do not point anything at a paid EKS/RDS path for Week 5.
