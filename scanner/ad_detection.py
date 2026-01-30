"""
Ad Detection Module v52.0
Backward-compatibility wrapper - imports from ad_detector.py
"""

# Re-export analyze_private_invites from ad_detector for backward compatibility
from .ad_detector import analyze_private_invites

__all__ = ['analyze_private_invites']
