"""
Deploy CLI v81.0
Unified command-line interface for all deployment operations.

Usage:
    python -m deploy deploy frontend    # Deploy frontend only
    python -m deploy deploy backend     # Deploy backend only
    python -m deploy deploy all         # Deploy both
    python -m deploy --dry-run deploy all  # Preview without changes
"""
import argparse
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import DeployConfig
from .deployers import FrontendDeployer, BackendDeployer, DeployResult


def deploy_frontend(config: DeployConfig, dry_run: bool = False) -> DeployResult:
    """Deploy frontend."""
    deployer = FrontendDeployer(
        config=config.frontend,
        build_dir=Path(__file__).parent.parent / "frontend" / "dist",
        dry_run=dry_run
    )
    return deployer.deploy()


def deploy_backend(config: DeployConfig, dry_run: bool = False) -> DeployResult:
    """Deploy backend."""
    deployer = BackendDeployer(
        config=config.backend,
        backend_dir=Path(__file__).parent.parent / "backend",
        dry_run=dry_run
    )
    return deployer.deploy()


def deploy_all(config: DeployConfig, dry_run: bool = False) -> dict:
    """Deploy both frontend and backend in parallel."""
    results = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(deploy_frontend, config, dry_run): "frontend",
            executor.submit(deploy_backend, config, dry_run): "backend",
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = DeployResult(
                    success=False,
                    errors=[str(e)],
                    message=f"Error: {e}"
                )

    return results


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy mini-app to production servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    python -m deploy deploy frontend       Deploy frontend only
    python -m deploy deploy backend        Deploy backend only
    python -m deploy deploy all            Deploy both in parallel
    python -m deploy --dry-run deploy all  Preview without changes
        '''
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without deploying"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).parent / ".env",
        help="Path to .env file (default: deploy/.env)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy to servers")
    deploy_parser.add_argument(
        "target",
        choices=["frontend", "backend", "all"],
        help="What to deploy"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load configuration
    print(f"Loading config from {args.env_file}")
    config = DeployConfig.from_env(args.env_file)

    if args.dry_run:
        print("=== DRY RUN MODE ===")

    if args.command == "deploy":
        if args.target == "frontend":
            result = deploy_frontend(config, args.dry_run)
            print(f"\nFrontend: {'OK' if result.success else 'FAILED'} - {result.message}")
            sys.exit(0 if result.success else 1)

        elif args.target == "backend":
            result = deploy_backend(config, args.dry_run)
            print(f"\nBackend: {'OK' if result.success else 'FAILED'} - {result.message}")
            sys.exit(0 if result.success else 1)

        elif args.target == "all":
            results = deploy_all(config, args.dry_run)

            print("\n=== DEPLOYMENT SUMMARY ===")
            all_success = True
            for name, result in results.items():
                status = "OK" if result.success else "FAILED"
                print(f"{name.upper()}: {status} - {result.message}")
                if not result.success:
                    all_success = False

            sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
