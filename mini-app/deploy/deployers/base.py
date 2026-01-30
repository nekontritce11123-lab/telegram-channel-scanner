"""
Base Deployer v81.0
Abstract base class for deployers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from ..config import ServerConfig


@dataclass
class DeployResult:
    """Result of deployment operation."""
    success: bool
    files_uploaded: int = 0
    errors: list = None
    message: str = ""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class BaseDeployer(ABC):
    """Abstract base class for deployers."""

    def __init__(self, config: ServerConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

    @abstractmethod
    def deploy(self) -> DeployResult:
        """Execute deployment. Must be implemented by subclasses."""
        pass

    @abstractmethod
    def validate(self) -> bool:
        """Validate pre-deployment conditions."""
        pass

    def log(self, message: str) -> None:
        """Log deployment message."""
        prefix = "[DRY] " if self.dry_run else ""
        print(f"{prefix}{message}")
