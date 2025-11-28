"""
Template Registry with Async Caching

Singleton registry for template definitions with TTL caching.
Manages template definitions and provides fast lookup.
"""
from typing import Dict, Optional
from app.models.template_schema import TemplateDefinition
from app.repositories.template_definition_repo import (
    TemplateDefinitionRepository,
    TemplateDefinitionNotFoundError
)
from app.db.config import get_session
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TemplateRegistry:
    """
    Singleton registry for template definitions with TTL caching.
    """
    _instance: Optional['TemplateRegistry'] = None
    _cache: Dict[str, TemplateDefinition] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    _cache_ttl = timedelta(minutes=15)  # 15-minute TTL
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get(
        self, type_key: str, force_refresh: bool = False
    ) -> TemplateDefinition:
        """
        Get template definition with caching.
        
        Args:
            type_key: Template type identifier
            force_refresh: Bypass cache and fetch from DB
            
        Returns:
            TemplateDefinition
            
        Raises:
            TemplateDefinitionNotFoundError: If not found
        """
        # Check cache if not forcing refresh
        if not force_refresh:
            cached = self._get_from_cache(type_key)
            if cached:
                logger.debug(f"Cache hit for template: {type_key}")
                return cached
        
        # Fetch from database
        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh:
                cached = self._get_from_cache(type_key)
                if cached:
                    return cached
            
            logger.debug(
                f"Cache miss for template: {type_key}, fetching from DB"
            )
            async for session in get_session():
                repo = TemplateDefinitionRepository(session)
                definition = await repo.get_by_type_key(type_key)
                
                # Store in cache
                self._cache[type_key] = definition
                self._cache_timestamps[type_key] = datetime.utcnow()
                
                return definition
        
        # This should never be reached but satisfies type checker
        raise TemplateDefinitionNotFoundError(
            f"Failed to retrieve template: {type_key}"
        )
    
    def _get_from_cache(self, type_key: str) -> Optional[TemplateDefinition]:
        """Get from cache if present and not expired."""
        if type_key not in self._cache:
            return None
        
        # Check TTL
        cached_at = self._cache_timestamps.get(type_key)
        if cached_at and (datetime.utcnow() - cached_at) > self._cache_ttl:
            logger.debug(f"Cache expired for template: {type_key}")
            del self._cache[type_key]
            del self._cache_timestamps[type_key]
            return None
        
        return self._cache[type_key]
    
    async def exists(self, type_key: str) -> bool:
        """Check if template definition exists."""
        try:
            await self.get(type_key)
            return True
        except TemplateDefinitionNotFoundError:
            return False
    
    async def invalidate(self, type_key: Optional[str] = None):
        """
        Invalidate cache entries.
        
        Args:
            type_key: Specific key to invalidate, or None to clear all
        """
        async with self._lock:
            if type_key:
                self._cache.pop(type_key, None)
                self._cache_timestamps.pop(type_key, None)
                logger.info(f"Invalidated cache for template: {type_key}")
            else:
                self._cache.clear()
                self._cache_timestamps.clear()
                logger.info("Cleared entire template cache")
    
    async def preload_cache(self):
        """Load all definitions into cache on startup."""
        async with self._lock:
            async for session in get_session():
                repo = TemplateDefinitionRepository(session)
                definitions = await repo.list_all()
                
                for definition in definitions:
                    self._cache[definition.type_key] = definition
                    self._cache_timestamps[definition.type_key] = (
                        datetime.utcnow()
                    )
                
                logger.info(
                    f"Preloaded {len(definitions)} template definitions "
                    "into cache"
                )
                break  # Exit after first iteration


# Global registry instance
registry = TemplateRegistry()
