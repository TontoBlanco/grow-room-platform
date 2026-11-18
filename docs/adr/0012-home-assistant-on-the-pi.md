# ADR-0012: Home Assistant on the Pi, k3d stays on the PC

- Status: Accepted
- Date: 2026-11-18

## Context

[ADR-0011](0011-k3d-instead-of-a-pi.md) kept daily Kubernetes on the PC and left an always-on machine for later. On 18 November 2026 I moved Home Assistant off the PC's Docker Compose stack and onto a Raspberry Pi 5. The hostname is `berry`, the address is `10.0.0.62` (DHCP reservation), and the user is `cole`. The laptop still sleeps. Two Home Assistant processes must not log into the AC Infinity account at the same time.

## Decision

Home Assistant runs on `berry` as a Compose project at `/opt/homeassistant`. The container uses host networking, `restart: unless-stopped`, `TZ=America/Denver`, and the volumes `./config:/config` and `/etc/localtime:/etc/localtime:ro`. It is not privileged. sensor-service on the PC calls `http://10.0.0.62:8123`.

The PC service `homeassistant` is behind the Compose profile `local-ha`. `docker compose up -d` does not start it. That profile is rollback only, and only after the Pi container is stopped.

k3d, Prometheus, Grafana, and sensor-service stay on the PC. Ansible inventory `ansible/inventories/pi` and `ansible/playbooks/berry.yml` manage the Pi. A nightly backup writes a tar.gz on the Pi and keeps 14. It does not upload to S3 or anywhere else.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Leave Home Assistant in the PC Compose file | The lid still stops the controller integration, and a plain `docker compose up` is how a second copy starts |
| Move k3d onto the Pi | The Pi is the edge box for Home Assistant. The cluster stays where ADR-0011 put it |
| Nightly backup into the telemetry bucket | That bucket is the Phase 8 session copy. I do not want the token material in S3 on a timer |

## Consequences

Good: Home Assistant stays up when the laptop sleeps. The AC Infinity integration is not tied to the lid. A plain `docker compose up -d` on the PC cannot start a second copy by accident.

Bad / accepted risk: the Grafana scrape still stops when the laptop sleeps, because sensor-service and Prometheus are on the PC. `docker compose --profile local-ha up` still starts the PC copy if I ask it to. The Phase 8 scripts still look for a local Compose container and `ha-config`. I did not point them at the Pi.

## SAA exam tie-in

Put the process that has to stay up on the machine that stays up. Do not move the rest of the lab with it. The cloud version of that rule is the same one as ADR-0011: do not leave a control plane running so a laptop-shaped job has somewhere to sit.
