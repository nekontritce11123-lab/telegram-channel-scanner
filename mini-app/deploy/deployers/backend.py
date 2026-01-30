"""
Backend Deployer v81.0
Deploy FastAPI backend + scanner/ to production server.
"""
from pathlib import Path
from .base import BaseDeployer, DeployResult
from ..config import ServerConfig
from ..utils.ssh import SSHConnection


class BackendDeployer(BaseDeployer):
    """Deploy backend (FastAPI + scanner) to production."""

    def __init__(self, config: ServerConfig, backend_dir: Path = None,
                 dry_run: bool = False):
        super().__init__(config, dry_run)
        self.backend_dir = backend_dir or Path("backend")
        # Scanner is in project root, not backend
        self.scanner_dir = self.backend_dir.parent.parent / "scanner"

    def validate(self) -> bool:
        """Check that backend files exist."""
        if not (self.backend_dir / "main.py").exists():
            self.log(f"ERROR: main.py not found in {self.backend_dir}")
            return False
        if not self.scanner_dir.exists():
            self.log(f"ERROR: scanner/ not found at {self.scanner_dir}")
            return False

        self.log(f"All required files found in {self.backend_dir}")
        return True

    def deploy(self) -> DeployResult:
        """Deploy backend files to server."""
        if not self.validate():
            return DeployResult(success=False, message="Validation failed")

        if self.dry_run:
            return DeployResult(
                success=True,
                files_uploaded=0,
                message="Dry run - no files uploaded"
            )

        try:
            with SSHConnection(
                host=self.config.host,
                user=self.config.user,
                password=self.config.password,
                port=self.config.port
            ) as ssh:
                self.log(f"Connected to {self.config.host}")
                uploaded = 0
                remote_path = self.config.remote_path

                # Create directories
                ssh.exec(f"mkdir -p {remote_path}/scanner")

                # Upload scanner/ from project root
                self.log("Uploading scanner/...")
                for local_file in self.scanner_dir.rglob("*"):
                    if local_file.is_file() and "__pycache__" not in str(local_file):
                        relative = local_file.relative_to(self.scanner_dir)
                        remote_file = f"{remote_path}/scanner/{relative}".replace("\\", "/")
                        remote_dir = str(Path(remote_file).parent)
                        ssh.exec(f"mkdir -p {remote_dir}")
                        ssh.upload_file(local_file, remote_file)
                        uploaded += 1

                # Upload backend files (excluding scanner symlink/copy)
                self.log("Uploading backend/...")
                for local_file in self.backend_dir.rglob("*"):
                    if local_file.is_file() and "__pycache__" not in str(local_file) and "scanner" not in str(local_file):
                        relative = local_file.relative_to(self.backend_dir)
                        remote_file = f"{remote_path}/{relative}".replace("\\", "/")
                        remote_dir = str(Path(remote_file).parent)
                        ssh.exec(f"mkdir -p {remote_dir}")
                        ssh.upload_file(local_file, remote_file)
                        uploaded += 1
                        self.log(f"  {relative}")

                # Restart service
                self.log("Restarting backend service...")
                ssh.exec(f"cd {remote_path} && {remote_path}/venv/bin/pip install -r requirements.txt --quiet")
                ssh.exec("systemctl restart reklamshik-api")

                return DeployResult(
                    success=True,
                    files_uploaded=uploaded,
                    message=f"Deployed {uploaded} files to {self.config.host}"
                )
        except Exception as e:
            return DeployResult(
                success=False,
                errors=[str(e)],
                message=f"Deploy failed: {e}"
            )
