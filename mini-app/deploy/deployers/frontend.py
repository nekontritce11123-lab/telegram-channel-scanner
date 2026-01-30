"""
Frontend Deployer v81.0
Deploy React frontend to production server.
"""
import subprocess
from pathlib import Path
from .base import BaseDeployer, DeployResult
from ..config import ServerConfig
from ..utils.ssh import SSHConnection


class FrontendDeployer(BaseDeployer):
    """Deploy frontend (React) to production."""

    def __init__(self, config: ServerConfig, build_dir: Path = None,
                 dry_run: bool = False):
        super().__init__(config, dry_run)
        self.build_dir = build_dir or Path("frontend/dist")

    def validate(self) -> bool:
        """Check that build directory exists and has files."""
        if not self.build_dir.exists():
            self.log(f"ERROR: Build directory not found: {self.build_dir}")
            return False

        files = list(self.build_dir.glob("*"))
        if not files:
            self.log(f"ERROR: Build directory is empty: {self.build_dir}")
            return False

        self.log(f"Found {len(files)} items in {self.build_dir}")
        return True

    def build(self) -> bool:
        """Run npm build."""
        self.log("Building frontend...")
        try:
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=self.build_dir.parent,
                capture_output=True,
                text=True,
                shell=True
            )
            if result.returncode != 0:
                self.log(f"Build failed: {result.stderr}")
                return False
            self.log("Build successful")
            return True
        except Exception as e:
            self.log(f"Build error: {e}")
            return False

    def deploy(self) -> DeployResult:
        """Deploy built frontend to server."""
        if not self.validate():
            return DeployResult(success=False, message="Validation failed")

        if self.dry_run:
            files = list(self.build_dir.rglob("*"))
            return DeployResult(
                success=True,
                files_uploaded=len([f for f in files if f.is_file()]),
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
                remote_path = self.config.remote_path

                # Clear old files
                self.log("Clearing old files...")
                ssh.exec(f"rm -rf {remote_path}/*")
                ssh.exec(f"mkdir -p {remote_path}/assets")

                # Upload files one by one (use direct SFTP put, mkdir via exec)
                uploaded = 0
                for local_file in self.build_dir.rglob("*"):
                    if local_file.is_file():
                        relative = local_file.relative_to(self.build_dir).as_posix()
                        remote_file = f"{remote_path}/{relative}"
                        remote_dir = str(Path(remote_file).parent)
                        ssh.exec(f"mkdir -p {remote_dir}")
                        # Direct SFTP put (skip _mkdir_p which has permission issues)
                        ssh._sftp.put(str(local_file), remote_file)
                        uploaded += 1
                        self.log(f"  {relative}")

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
