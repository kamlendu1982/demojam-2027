from src.agents.agent1_drift_detector import DeviceDriftDetector


def test_networking_drift_detected():
    agent = DeviceDriftDetector()
    resp = agent.run("rtr-core-01", {"dns_servers": ["10.10.0.53"]})

    assert resp.attributes["dns_servers"].category == "networking"
    assert resp.attributes["dns_servers"].drift is True
    assert resp.attributes["dns_servers"].expected_value == ["10.10.0.53", "10.10.0.54"]
    assert "dns_servers" in resp.netbox_remediation_attributes
    assert resp.security_review_attributes == []


def test_networking_no_drift():
    agent = DeviceDriftDetector()
    resp = agent.run("rtr-core-01", {"vlan": 10})

    assert resp.attributes["vlan"].drift is False
    assert resp.netbox_remediation_attributes == []


def test_security_attribute_routed_not_compared():
    agent = DeviceDriftDetector()
    resp = agent.run("rtr-core-01", {"ssh_access_list": ["0.0.0.0/0"]})

    result = resp.attributes["ssh_access_list"]
    assert result.category == "security"
    assert result.drift == "security"
    assert result.source_of_truth == "github"
    assert "ssh_access_list" in resp.security_review_attributes
    assert resp.netbox_remediation_attributes == []


def test_num_interfaces_len_path():
    agent = DeviceDriftDetector()
    resp = agent.run("rtr-core-01", {"num_interfaces": 5})
    # rtr-core-01 fixture has exactly 5 interfaces -> no drift
    assert resp.attributes["num_interfaces"].drift is False
    assert resp.attributes["num_interfaces"].expected_value == 5


def test_response_is_json_serializable():
    agent = DeviceDriftDetector()
    resp = agent.run("rtr-core-01", {"dns_servers": ["10.10.0.53"], "ssh_access_list": ["x"]})
    payload = resp.model_dump(mode="json")
    assert payload["device"] == "rtr-core-01"
    assert isinstance(payload["attributes"], dict)
