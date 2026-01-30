"""
SSH Utilities v81.0
Paramiko-based SSH/SFTP operations for deployment.
"""
import os
from pathlib import Path
from typing import Tuple, Optional
import paramiko


class SSHConnection:
    """
    SSH connection with SFTP support.

    Usage:
        with SSHConnection(config) as ssh:
            stdout, stderr, code = ssh.exec("ls -la")
            ssh.upload_file(local, remote)
            ssh.upload_directory(local_dir, remote_dir)
    """

    def __init__(self, host: str, user: str, password: str = None,
                 key_path: str = None, port: int = 22):
        self.host = host
        self.user = user
        self.password = password
        self.key_path = key_path
        self.port = port
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def __enter__(self) -> "SSHConnection":
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user,
        }

        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        elif self.password:
            connect_kwargs["password"] = self.password

        self._client.connect(**connect_kwargs)
        self._sftp = self._client.open_sftp()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._sftp:
            self._sftp.close()
        if self._client:
            self._client.close()

    def exec(self, command: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute command and return (stdout, stderr, exit_code)."""
        if not self._client:
            raise RuntimeError("Not connected")

        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return (
            stdout.read().decode('utf-8'),
            stderr.read().decode('utf-8'),
            exit_code
        )

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        """Upload single file, creating parent directories if needed."""
        if not self._sftp:
            raise RuntimeError("Not connected")

        # Ensure remote directory exists
        remote_dir = str(Path(remote_path).parent)
        self._mkdir_p(remote_dir)

        self._sftp.put(str(local_path), remote_path)

    def upload_directory(self, local_dir: Path, remote_dir: str,
                        exclude: list = None) -> int:
        """
        Upload directory recursively.

        Returns:
            Number of files uploaded
        """
        if not self._sftp:
            raise RuntimeError("Not connected")

        exclude = exclude or []
        uploaded = 0

        for root, dirs, files in os.walk(local_dir):
            # Filter directories
            dirs[:] = [d for d in dirs if not self._should_exclude(d, exclude)]

            for file in files:
                if self._should_exclude(file, exclude):
                    continue

                local_path = Path(root) / file
                rel_path = local_path.relative_to(local_dir)
                remote_path = f"{remote_dir}/{rel_path}".replace("\\", "/")

                self.upload_file(local_path, remote_path)
                uploaded += 1

        return uploaded

    def _mkdir_p(self, remote_path: str) -> None:
        """Create remote directory recursively."""
        dirs = remote_path.split('/')
        path = ''
        for d in dirs:
            if not d:
                path = '/'
                continue
            path = f"{path}/{d}" if path != '/' else f"/{d}"
            try:
                self._sftp.stat(path)
            except FileNotFoundError:
                self._sftp.mkdir(path)

    def _should_exclude(self, name: str, patterns: list) -> bool:
        """Check if file/dir should be excluded."""
        import fnmatch
        return any(fnmatch.fnmatch(name, p) for p in patterns)
