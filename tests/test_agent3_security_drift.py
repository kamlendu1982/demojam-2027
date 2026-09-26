from src.agents.agent1_drift_detector import DeviceDriftDetector
from src.agents.agent3_security_drift import SecurityPolicyDriftChecker


def test_security_drift_detected_against_github():
    agent1 = DeviceDriftDetector().run("rtr-core-01", {"ssh_access_list": ["0.0.0.0/0"]})
    agent3 = SecurityPolicyDriftChecker().run(agent1)

    result = agent3.attributes["ssh_access_list"]
    assert result.drift is True
    assert result.expected_value == ["10.10.0.0/24", "10.20.0.0/24"]
    assert "ssh_access_list" in agent3.github_remediation_attributes


def test_security_no_drift_against_github():
    agent1 = DeviceDriftDetector().run(
        "rtr-core-01", {"snmp_community": "REDACTED_RO_v2c"}
    )
    agent3 = SecurityPolicyDriftChecker().run(agent1)

    result = agent3.attributes["snmp_community"]
    assert result.drift is False
    assert agent3.github_remediation_attributes == []
