"""
Deploy Configuration v81.0
Centralized deployment settings with validation.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ServerConfig:
    """Configuration for a single server."""
    host: str
    user: str
    password: str
    remote_path: str
    port: int = 22

    def validate(self) -> None:
        """Validate configuration."""
        if not self.host:
            raise ValueError("host is required")
        if not self.user:
            raise ValueError("user is required")
        if not self.remote_path:
            raise ValueError("remote_path is required")


@dataclass
class DeployConfig:
    """Complete deployment configuration."""
    frontend: ServerConfig
    backend: ServerConfig

    # Build settings
    frontend_build_dir: Path = Path("frontend/dist")
    backend_files: list = None  # Files to deploy

    # Exclusions
    exclude_patterns: list = None

    def __post_init__(self):
        if self.backend_files is None:
            self.backend_files = ["main.py", "requirements.txt"]
        if self.exclude_patterns is None:
            self.exclude_patterns = ["__pycache__", "*.pyc", ".env", "*.log"]

    @classmethod
    def from_env(cls, env_path: Path = None) -> "DeployConfig":
        """Load configuration from environment or .env file."""
        if env_path and env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path)

        # Frontend server config (matches existing .env)
        frontend = ServerConfig(
            host=os.getenv("FRONTEND_HOST", "37.140.192.181"),
            user=os.getenv("FRONTEND_USER", "u3372484"),
            password=os.getenv("FRONTEND_PASS", ""),
            remote_path="/var/www/u3372484/data/www/ads.factchain-traker.online",
            port=22,
        )

        # Backend server config (matches existing .env)
        backend = ServerConfig(
            host=os.getenv("BACKEND_HOST", "217.60.3.122"),
            user=os.getenv("BACKEND_USER", "root"),
            password=os.getenv("BACKEND_PASS", ""),
            remote_path="/root/reklamshik",
            port=22,
        )

        return cls(frontend=frontend, backend=backend)

    def validate(self) -> None:
        """Validate all configurations."""
        self.frontend.validate()
        self.backend.validate()
