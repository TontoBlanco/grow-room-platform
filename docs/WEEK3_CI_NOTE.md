# Week 3 CI note

Do **not** copy a finished GitOps bump workflow from this pack into
`.github/workflows/`.

Week 3 deliverable is the **Helm chart + Argo CD loop on k3d**. Extending CI so
a green image build automatically bumps `image.tag` in Git is a follow-on you
should author yourself once sync/health feel boring.

Write that workflow using `docs/WEEK3_GITOPS_GUIDE.md` Step 7 (manual sync) as
the mental model and the **SAMPLE** block at the bottom of that guide as a
shape reference only.

Suggested direction when you are ready:

1. CI already pushes `ghcr.io/tontoblanco/grow-room-platform:<tag>`.
2. A separate job or workflow updates `charts/sensor-service/values.yaml`
   (or an Argo Helm parameter) to that same tag.
3. Prefer opening a PR over pushing straight to `main` until you trust the bump.
4. Argo CD syncs after merge — that is CD, not more CI.

Until then, bump the tag by hand in Git and sync. That is a valid Week 3 done
state.
