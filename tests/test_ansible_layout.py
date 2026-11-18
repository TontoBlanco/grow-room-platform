"""Repo-root Ansible commands can find roles, and check mode can read the probe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_roles_path_works_from_the_repo_root_and_from_ansible():
    nested = (ROOT / "ansible/ansible.cfg").read_text(encoding="utf-8")
    assert "roles_path = roles:ansible/roles" in nested
    root = (ROOT / "ansible.cfg").read_text(encoding="utf-8")
    assert "roles_path = ansible/roles" in root
    for path in (ROOT / "ansible.cfg", ROOT / "ansible/ansible.cfg"):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" not in raw


def test_python_probe_is_safe_in_check_mode():
    text = (ROOT / "ansible/playbooks/berry.yml").read_text(encoding="utf-8")
    probe, install = text.split("- name: Install Python 3", 1)
    assert "check_mode: false" in probe
    assert "berry_python3.rc is defined" in install
    assert "when: berry_python3.rc != 0" not in text
    docker = (ROOT / "ansible/roles/docker/tasks/main.yml").read_text(encoding="utf-8")
    assert "docker_info.rc | default(1)" in docker
    assert "not ansible_check_mode" in docker
    assert "selectattr('stat', 'defined')" in docker
