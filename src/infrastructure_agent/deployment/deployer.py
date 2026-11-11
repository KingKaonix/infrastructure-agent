"""Deployment Engine for Infrastructure Agent"""

import asyncio
import json
import logging
from typing import Dict, Any
from pathlib import Path
import os
import uuid

from ..core.config import get_config
from .ssh_executor import SSHResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeploymentResult:
    """Result from a deployment operation"""

    def __init__(
        self,
        success: bool,
        message: str = "",
        docker_container_id: str = "",
        health_check: bool = True,
    ):
        self.success = success
        self.message = message
        self.docker_container_id = docker_container_id
        self.health_check = health_check

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "docker_container_id": self.docker_container_id,
            "health_check": self.health_check,
        }


class Deployer:
    """Handles deployment of applications to remote devices"""

    def __init__(self, ssh_executor=None):
        self.config = get_config()
        self.ssh_executor = ssh_executor
        self.temp_dir = (
            Path(__file__).resolve().parents[3] / "state" / "deployments" / f"deploy_{os.getpid()}"
        )
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def deploy_from_github(
        self, github_url: str, target_device_ip: str = None
    ) -> DeploymentResult:
        """
        Deploy an application from a GitHub URL.
        Automatically detects stack type and generates Docker configuration.
        """
        logger.info(f"Starting deployment from GitHub: {github_url}")

        # Step 1: Analyze the repository to detect stack type
        repo_analysis = await self.analyze_repository(github_url)
        if not repo_analysis.success:
            return DeploymentResult(
                success=False, message=f"Failed to analyze repository: {repo_analysis.stderr}"
            )

        # Step 2: Generate Docker configuration based on detected stack
        docker_config = await self.generate_docker_config(repo_analysis)

        # Step 3: Deploy to target device
        if target_device_ip:
            return await self.deploy_to_device(target_device_ip, docker_config)
        else:
            # Deploy to all available devices
            devices = self.ssh_executor.get_all_devices()
            results = []
            for ip, device in devices.items():
                if device.ssh_available:
                    result = await self.deploy_to_device(ip, docker_config)
                    results.append((ip, result))
            # Return result for first successful deployment
            for ip, result in results:
                if result.success:
                    return result
            return DeploymentResult(success=False, message="Failed to deploy to any device")

    async def analyze_repository(self, github_url: str) -> SSHResult:
        """
        Analyze a GitHub repository to detect the application stack.
        Downloads repo and determines the framework/language.
        """
        logger.info(f"Analyzing repository: {github_url}")

        # Clone the repository
        repo_name = github_url.rstrip("/").split("/")[-1]
        clone_dir = self.temp_dir / repo_name

        try:
            # Remove if exists
            if clone_dir.exists():
                import shutil

                shutil.rmtree(clone_dir)

            # Clone the repo
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                github_url,
                str(clone_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return SSHResult(
                    success=False, stderr=f"Failed to clone repository: {stderr.decode()}"
                )

        except Exception as e:
            return SSHResult(success=False, stderr=f"Error cloning repository: {str(e)}")

        # Analyze the repository
        analysis = await self.detect_stack_type(clone_dir)

        analysis["repo_name"] = repo_name
        analysis["repo_path"] = str(clone_dir)
        analysis["repository_url"] = github_url
        return SSHResult(success=True, stdout=json.dumps(analysis))

    async def detect_stack_type(self, repo_path: Path) -> Dict[str, Any]:
        """Detect the application stack type from the repository"""
        analysis = {
            "language": "unknown",
            "framework": "unknown",
            "dockerfile": None,
            "docker_compose": None,
            "build_command": None,
            "start_command": None,
        }

        # Check for common indicators
        files = list(repo_path.rglob("*"))

        # Check package.json (Node.js/React)
        if any(f.name == "package.json" for f in files):
            analysis["language"] = "javascript"
            package_json = repo_path / "package.json"
            if package_json.exists():
                import json

                try:
                    with open(package_json) as f:
                        pkg = json.load(f)
                    analysis["framework"] = pkg.get("framework", "unknown")
                    if pkg.get("scripts", {}).get("build"):
                        analysis["build_command"] = pkg["scripts"]["build"]
                    if pkg.get("scripts", {}).get("start"):
                        analysis["start_command"] = pkg["scripts"]["start"]
                except Exception:
                    pass

        # Check requirements.txt (Python)
        if any(f.name == "requirements.txt" for f in files):
            analysis["language"] = "python"
            analysis["framework"] = "flask/django/fastapi"

        # Check setup.py or pyproject.toml (Python)
        if any(f.suffix == ".py" for f in files):
            analysis["language"] = "python"

        # Check go.mod (Go)
        if any(f.name == "go.mod" for f in files):
            analysis["language"] = "go"

        # Check Cargo.toml (Rust)
        if any(f.name == "Cargo.toml" for f in files):
            analysis["language"] = "rust"

        # Check for Dockerfile already
        if any(f.name == "Dockerfile" for f in files):
            dockerfile_path = repo_path / "Dockerfile"
            analysis["dockerfile"] = str(dockerfile_path)

        # Check for docker-compose.yml
        if any(f.name == "docker-compose.yml" for f in files):
            compose_path = repo_path / "docker-compose.yml"
            analysis["docker_compose"] = str(compose_path)

        # Generate basic Docker config if none exists
        if not analysis["dockerfile"] and not analysis["docker_compose"]:
            analysis = await self.generate_basic_docker_config(repo_path, analysis)

        return analysis

    async def generate_basic_docker_config(
        self, repo_path: Path, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate basic Docker configuration for detected stack"""
        language = analysis.get("language", "unknown")

        if language == "javascript":
            # Node.js Docker config
            dockerfile_content = """FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
"""

            compose_content = """services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
    restart: unless-stopped
"""

        elif language == "python":
            # Python Docker config
            dockerfile_content = """FROM python:3.12-alpine

WORKDIR /app

COPY requirements*.txt ./

RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "app.py"]
"""

            compose_content = """services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
    restart: unless-stopped
"""

        else:
            # Generic Docker config
            dockerfile_content = """FROM alpine:latest

WORKDIR /app

COPY . .

CMD ["sh", "-c", "echo 'Hello from Docker'"]
"""

            compose_content = """services:
  app:
    image: alpine:latest
    working_dir: /app
    command: ["sh", "-c", "echo 'Hello from Docker'"]
    restart: unless-stopped
"""

        # Write Dockerfile
        dockerfile_path = repo_path / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        # Write docker-compose.yml
        compose_path = repo_path / "docker-compose.yml"
        compose_path.write_text(compose_content)

        analysis["dockerfile"] = str(dockerfile_path)
        analysis["docker_compose"] = str(compose_path)

        return analysis

    async def generate_docker_config(self, repo_analysis: SSHResult) -> Dict[str, Any]:
        """Generate Docker configuration from analysis"""
        import json

        data = json.loads(repo_analysis.stdout)
        # If Dockerfile/docker-compose already exist, use them
        if data.get("dockerfile") and Path(data["dockerfile"]).exists():
            with open(data["dockerfile"]) as f:
                dockerfile = f.read()
        else:
            # Generate basic Dockerfile
            dockerfile = await self._generate_dockerfile(data)

        if data.get("docker_compose") and Path(data["docker_compose"]).exists():
            with open(data["docker_compose"]) as f:
                docker_compose = f.read()
        else:
            # Generate basic docker-compose.yml
            docker_compose = await self._generate_docker_compose(data)

        return {
            "dockerfile": dockerfile,
            "docker_compose": docker_compose,
            "language": data.get("language", "unknown"),
            "build_command": data.get("build_command"),
            "start_command": data.get("start_command"),
            "repo_path": data.get("repo_path"),
            "repository_url": data.get("repository_url"),
        }

    async def _generate_dockerfile(self, analysis: Dict[str, Any]) -> str:
        """Generate Dockerfile based on language"""
        language = analysis.get("language", "unknown")

        if language == "javascript":
            return """FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
"""

        elif language == "python":
            return """FROM python:3.12-alpine

WORKDIR /app

COPY requirements*.txt ./

RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "app.py"]
"""

        elif language == "go":
            return """FROM golang:1.21-alpine AS builder

WORKDIR /app

COPY go.* ./

RUN go build -o app .

FROM alpine:latest

WORKDIR /app

COPY --from=builder /app/app .

CMD ["./app"]
"""

        else:
            # Generic fallback
            return """FROM alpine:latest

WORKDIR /app

COPY . .

CMD ["sh", "-c", "echo 'Hello from Docker'"]
"""

    async def _generate_docker_compose(self, analysis: Dict[str, Any]) -> str:
        """Generate docker-compose.yml based on language"""
        language = analysis.get("language", "unknown")

        if language == "javascript":
            return """services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
    restart: unless-stopped
"""

        elif language == "python":
            return """services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
    restart: unless-stopped
"""

        else:
            return """services:
  app:
    build: .
    ports:
      - "8080:8080"
    restart: unless-stopped
"""

    async def deploy_to_device(
        self, device_ip: str, docker_config: Dict[str, Any]
    ) -> DeploymentResult:
        """Deploy Docker application to a specific device"""
        logger.info(f"Deploying to device: {device_ip}")

        deployment_id = uuid.uuid4().hex[:12]
        remote_dir = f"$HOME/.infrastructure-agent/deployments/{deployment_id}"
        try:
            # Check SSH connection first
            ssh_connected = await self.ssh_executor.connect(device_ip)
            if not ssh_connected:
                return DeploymentResult(
                    success=False, message=f"Could not establish SSH connection to {device_ip}"
                )

            # Check if Docker is available
            check_result = await self.ssh_executor.execute_command(device_ip, "docker --version")
            if not check_result.success:
                return DeploymentResult(
                    success=False, message=f"Docker not found on {device_ip}: {check_result.stderr}"
                )

            # The build context must contain application source, not only config files.
            dockerfile_content = docker_config.get("dockerfile", "")
            compose_content = docker_config.get("docker_compose", "")
            mkdir_result = await self.ssh_executor.execute_command(
                device_ip, f"mkdir -p {remote_dir}"
            )
            if not mkdir_result.success:
                return DeploymentResult(
                    False, f"Could not create deployment directory: {mkdir_result.stderr}"
                )
            source_url = docker_config.get("repository_url")
            if source_url:
                clone = await self.ssh_executor.execute_command(
                    device_ip, f"git clone --depth 1 {source_url} {remote_dir}/source"
                )
                if not clone.success:
                    return DeploymentResult(False, f"Source checkout failed: {clone.stderr}")
                context = f"{remote_dir}/source"
            else:
                context = remote_dir

            # Write Dockerfile
            await self.ssh_executor.execute_command(
                device_ip, f"cat > {context}/Dockerfile << 'EOF'\n{dockerfile_content}\nEOF"
            )

            # Write docker-compose.yml
            await self.ssh_executor.execute_command(
                device_ip, f"cat > {context}/docker-compose.yml << 'EOF'\n{compose_content}\nEOF"
            )

            # Build and start the container
            build_result = await self.ssh_executor.execute_command(
                device_ip, f"cd {context} && docker compose build"
            )

            if not build_result.success:
                await self.ssh_executor.execute_command(
                    device_ip, f"cd {context} && docker compose down --remove-orphans"
                )
                return DeploymentResult(
                    success=False,
                    message=f"Docker build failed on {device_ip}: {build_result.stderr}",
                )

            # Start the container
            start_result = await self.ssh_executor.execute_command(
                device_ip, f"cd {context} && docker compose up -d"
            )

            if not start_result.success:
                await self.ssh_executor.execute_command(
                    device_ip, f"cd {context} && docker compose down --remove-orphans"
                )
                return DeploymentResult(
                    success=False,
                    message=f"Docker compose up failed on {device_ip}: {start_result.stderr}",
                )

            # Health check
            health_result = await self.wait_for_health(
                device_ip,
                timeout=int(self.config.get("deployment", {}).get("health_check_timeout", 60)),
                context=context,
            )

            if not health_result.success:
                await self.ssh_executor.execute_command(
                    device_ip, f"cd {context} && docker compose down --remove-orphans"
                )

            return DeploymentResult(
                success=start_result.success and health_result.success,
                message=(
                    "Deployment successful"
                    if start_result.success and health_result.success
                    else health_result.stderr or start_result.stderr
                ),
                docker_container_id=(start_result.stdout.strip().split()[0][:12] if start_result.stdout.strip() else ""),
                health_check=health_result.success,
            )

        except Exception as e:
            logger.error(f"Deployment error to {device_ip}: {e}")
            return DeploymentResult(success=False, message=str(e))

    async def wait_for_health(
        self, device_ip: str, timeout: int = 60, context: str = ""
    ) -> SSHResult:
        """Wait for deployed container to become healthy"""
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            result = await self.ssh_executor.execute_command(
                device_ip,
                f"cd {context} && docker compose ps --format '{{{{.Service}}}} {{{{.Health}}}}'"
                if context
                else "docker compose ps --format '{{.Service}} {{.Health}}'",
            )
            if result.success and result.stdout.strip():
                return SSHResult(success=True, stdout=result.stdout)
            await asyncio.sleep(2)

        return SSHResult(success=False, stderr="Health check timed out")

    async def cleanup_old_containers(self, device_ip: str) -> SSHResult:
        """Clean up old/dangling containers"""
        result = await self.ssh_executor.execute_command(
            device_ip, "docker system prune -f --volumes"
        )
        return result
