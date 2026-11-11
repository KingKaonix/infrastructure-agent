import pytest

from infrastructure_agent.deployment.deployer import Deployer
from infrastructure_agent.deployment.ssh_executor import SSHResult


class FakeDockerAdapter:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.commands = []

    def result_for(self, command):
        for marker, result in self.outcomes.items():
            if marker in command:
                return result
        if "docker compose ps" in command:
            return SSHResult(True, stdout="app healthy\n")
        return SSHResult(True, stdout="container-id-123456\n")


class FakeSSHExecutor:
    def __init__(self, docker):
        self.docker = docker

    async def connect(self, device_ip):
        return True

    async def execute_command(self, device_ip, command):
        self.docker.commands.append((device_ip, command))
        return self.docker.result_for(command)


def make_deployer(tmp_path, docker):
    deployer = Deployer(FakeSSHExecutor(docker))
    deployer.temp_dir = tmp_path
    return deployer


@pytest.mark.asyncio
async def test_source_checkout_failure_stops_before_build(tmp_path):
    docker = FakeDockerAdapter({"git clone": SSHResult(False, stderr="repository unavailable")})
    deployer = make_deployer(tmp_path, docker)

    result = await deployer.deploy_to_device(
        "10.0.0.8",
        {
            "repository_url": "https://github.com/example/app",
            "dockerfile": "FROM alpine",
            "docker_compose": "services: {}",
        },
    )

    assert not result.success
    assert result.message == "Source checkout failed: repository unavailable"
    assert not any("docker compose build" in command for _, command in docker.commands)


@pytest.mark.asyncio
async def test_build_failure_rolls_back_started_resources(tmp_path):
    docker = FakeDockerAdapter({"docker compose build": SSHResult(False, stderr="compile error")})
    deployer = make_deployer(tmp_path, docker)

    result = await deployer.deploy_to_device(
        "10.0.0.8", {"dockerfile": "FROM alpine", "docker_compose": "services: {}"}
    )

    assert not result.success
    assert result.message == "Docker build failed on 10.0.0.8: compile error"
    assert any("docker compose down --remove-orphans" in command for _, command in docker.commands)
    assert not any("docker compose up -d" in command for _, command in docker.commands)


@pytest.mark.asyncio
async def test_health_timeout_rolls_back_and_is_not_success(tmp_path, monkeypatch):
    docker = FakeDockerAdapter({"docker compose ps": SSHResult(False, stderr="not healthy")})
    deployer = make_deployer(tmp_path, docker)
    monkeypatch.setitem(deployer.config["deployment"], "health_check_timeout", 0)

    result = await deployer.deploy_to_device(
        "10.0.0.8", {"dockerfile": "FROM alpine", "docker_compose": "services: {}"}
    )

    assert not result.success
    assert not result.health_check
    assert result.message == "Health check timed out"
    assert any("docker compose down --remove-orphans" in command for _, command in docker.commands)
    ps_commands = [command for _, command in docker.commands if "docker compose ps" in command]
    assert len(ps_commands) == 0


@pytest.mark.asyncio
async def test_success_reports_container_and_healthy_deployment(tmp_path):
    docker = FakeDockerAdapter()
    deployer = make_deployer(tmp_path, docker)

    result = await deployer.deploy_to_device(
        "10.0.0.8", {"dockerfile": "FROM alpine", "docker_compose": "services: {}"}
    )

    assert result.success
    assert result.health_check
    assert result.docker_container_id == "container-id"
    assert any("docker compose build" in command for _, command in docker.commands)
    assert any("docker compose up -d" in command for _, command in docker.commands)
    assert not any("docker compose down" in command for _, command in docker.commands)
