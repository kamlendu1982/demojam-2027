from src.pipeline.orchestrator import run_pipeline


def test_full_pipeline_networking_drift_triggers_agent2_only():
    resp = run_pipeline("rtr-core-01", {"dns_servers": ["10.10.0.53"]}, dry_run=True)

    assert resp.agent2_netbox_remediation is not None
    assert resp.agent2_netbox_remediation.extra_vars["dns_servers"] == [
        "10.10.0.53",
        "10.10.0.54",
    ]
    assert resp.agent2_netbox_remediation.dry_run is True
    assert resp.agent2_netbox_remediation.launched is False
    assert resp.agent3_security_drift is None
    assert resp.agent4_github_remediation is None


def test_full_pipeline_security_drift_triggers_agent3_and_agent4():
    resp = run_pipeline("rtr-core-01", {"ssh_access_list": ["0.0.0.0/0"]}, dry_run=True)

    assert resp.agent2_netbox_remediation is None
    assert resp.agent3_security_drift is not None
    assert "ssh_access_list" in resp.agent3_security_drift.github_remediation_attributes
    assert resp.agent4_github_remediation is not None
    assert resp.agent4_github_remediation.extra_vars["ssh_access_list"] == [
        "10.10.0.0/24",
        "10.20.0.0/24",
    ]


def test_full_pipeline_no_drift_no_remediation():
    resp = run_pipeline(
        "rtr-core-01",
        {"dns_servers": ["10.10.0.53", "10.10.0.54"], "vlan": 10},
        dry_run=True,
    )

    assert resp.any_drift is False
    assert resp.agent2_netbox_remediation is None
    assert resp.agent3_security_drift is None


def test_pipeline_response_is_valid_json():
    resp = run_pipeline("rtr-core-01", {"num_interfaces": 5}, dry_run=True)
    dumped = resp.model_dump_json()
    assert '"device": "rtr-core-01"' in dumped or '"device":"rtr-core-01"' in dumped
