"""
Feature Flags System for Backend
Environment-based feature control for the eLearning application backend
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class Environment(Enum):
    DEVELOPMENT = "development"
    QA = "qa"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class FeatureFlag:
    name: str
    enabled: bool
    description: str
    environments: List[Environment]


class FeatureFlagService:
    """Service for managing feature flags in the backend"""
    
    def __init__(self):
        self.current_environment = self._get_current_environment()
        self.flags = self._initialize_flags()
    
    def _get_current_environment(self) -> Environment:
        """Get current environment from environment variable"""
        env_name = os.getenv('ENVIRONMENT', 'development').lower()
        try:
            return Environment(env_name)
        except ValueError:
            return Environment.DEVELOPMENT
    
    def _initialize_flags(self) -> Dict[str, FeatureFlag]:
        """Initialize feature flags with their configurations"""
        flags = {
            'asset_upload': FeatureFlag(
                name='asset_upload',
                enabled=True,
                description='Enable file upload functionality',
                environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
            ),
            'collaboration': FeatureFlag(
                name='collaboration',
                enabled=False,
                description='Enable multi-user collaboration features',
                environments=[Environment.QA, Environment.STAGING, Environment.PRODUCTION]
            ),
            'analytics': FeatureFlag(
                name='analytics',
                enabled=False,
                description='Enable analytics and tracking',
                environments=[Environment.STAGING, Environment.PRODUCTION]
            ),
            'ai_suggestions': FeatureFlag(
                name='ai_suggestions',
                enabled=False,
                description='Enable AI-powered content suggestions',
                environments=[Environment.STAGING, Environment.PRODUCTION]
            ),
            'advanced_scorm': FeatureFlag(
                name='advanced_scorm',
                enabled=False,
                description='Enable advanced SCORM features',
                environments=[Environment.DEVELOPMENT, Environment.QA]
            ),
            'performance_monitoring': FeatureFlag(
                name='performance_monitoring',
                enabled=False,
                description='Enable detailed performance monitoring',
                environments=[Environment.STAGING, Environment.PRODUCTION]
            ),
            'rate_limiting': FeatureFlag(
                name='rate_limiting',
                enabled=False,
                description='Enable API rate limiting',
                environments=[Environment.STAGING, Environment.PRODUCTION]
            ),
            'cache_enabled': FeatureFlag(
                name='cache_enabled',
                enabled=False,
                description='Enable response caching',
                environments=[Environment.STAGING, Environment.PRODUCTION]
            )
        }
        
        # Apply environment-specific overrides
        self._apply_environment_overrides(flags)
        
        return flags
    
    def _apply_environment_overrides(self, flags: Dict[str, FeatureFlag]) -> None:
        """Apply environment-specific feature flag overrides"""
        for flag in flags.values():
            # Check if flag is enabled for current environment
            if self.current_environment in flag.environments:
                flag.enabled = True
            else:
                flag.enabled = False
            
            # Apply environment variable overrides
            env_var_name = f"FEATURE_{flag.name.upper()}"
            env_override = os.getenv(env_var_name)
            if env_override is not None:
                flag.enabled = env_override.lower() in ('true', '1', 'yes', 'on')
    
    def is_enabled(self, flag_name: str) -> bool:
        """Check if a feature flag is enabled"""
        flag = self.flags.get(flag_name)
        if flag is None:
            return False
        return flag.enabled
    
    def get_flag(self, flag_name: str) -> Optional[FeatureFlag]:
        """Get a specific feature flag"""
        return self.flags.get(flag_name)
    
    def get_all_flags(self) -> Dict[str, FeatureFlag]:
        """Get all feature flags"""
        return self.flags.copy()
    
    def get_enabled_flags(self) -> List[str]:
        """Get list of all enabled flag names"""
        return [name for name, flag in self.flags.items() if flag.enabled]
    
    def enable_flag(self, flag_name: str) -> bool:
        """Enable a feature flag (development only)"""
        if self.current_environment != Environment.DEVELOPMENT:
            return False
        
        flag = self.flags.get(flag_name)
        if flag:
            flag.enabled = True
            return True
        return False
    
    def disable_flag(self, flag_name: str) -> bool:
        """Disable a feature flag (development only)"""
        if self.current_environment != Environment.DEVELOPMENT:
            return False
        
        flag = self.flags.get(flag_name)
        if flag:
            flag.enabled = False
            return True
        return False
    
    def get_environment_info(self) -> Dict:
        """Get current environment information"""
        return {
            'current_environment': self.current_environment.value,
            'total_flags': len(self.flags),
            'enabled_flags': len(self.get_enabled_flags()),
            'flag_summary': {name: flag.enabled for name, flag in self.flags.items()}
        }


# Global feature flag service instance
feature_flags = FeatureFlagService()


# Convenience functions for common usage
def is_feature_enabled(flag_name: str) -> bool:
    """Check if a feature is enabled"""
    return feature_flags.is_enabled(flag_name)


def require_feature(flag_name: str):
    """Decorator to require a feature flag for an endpoint"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not is_feature_enabled(flag_name):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=404,
                    detail=f"Feature '{flag_name}' is not available"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Async version for FastAPI dependencies
async def require_feature_async(flag_name: str):
    """FastAPI dependency to require a feature flag"""
    if not is_feature_enabled(flag_name):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"Feature '{flag_name}' is not available"
        )
    return True