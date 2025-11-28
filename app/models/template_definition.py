"""
Template Definition Models for Dynamic Template System

SQLAlchemy ORM model for storing template metadata in PostgreSQL.
Stores schema and rendering configuration for runtime rendering.
"""
from sqlalchemy import Column, String, Text, Integer, DateTime, Index
from sqlalchemy.sql import func
from app.models.persisted_course import Base
import json


class TemplateDefinitionRecord(Base):
    """
    SQLAlchemy model for template definitions.
    Stores schema and rendering configuration for dynamic templates.
    """
    __tablename__ = "template_definitions"
    
    # Primary identifier (same as type_key for simplicity)
    id = Column(String(50), primary_key=True)
    
    # Template type identifier (e.g., "mcq", "content-text")
    type_key = Column(String(50), unique=True, nullable=False, index=True)
    
    # SHA-256 hash of field schema for versioning
    schema_signature = Column(String(64), nullable=False, index=True)
    
    # JSON-serialized field schemas
    field_schema_json = Column(Text, nullable=False)
    
    # JSON-serialized rendering configuration
    render_config_json = Column(Text, nullable=False)
    
    # JSON-serialized sanitization rules
    sanitize_rules_json = Column(Text, nullable=False)
    
    # JSON-serialized SCORM behavior configuration
    scorm_behavior_json = Column(Text, nullable=False)
    
    # Python class path for custom renderer
    renderer_class = Column(String(200), nullable=False)
    
    # Layout version for backward compatibility
    layout_version = Column(Integer, default=1, nullable=False)
    
    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    __table_args__ = (
        Index('idx_schema_sig', 'schema_signature'),
        Index('idx_type_version', 'type_key', 'layout_version'),
    )
    
    def to_dict(self):
        """Convert record to dictionary with parsed JSON fields."""
        return {
            'id': self.id,
            'type_key': self.type_key,
            'schema_signature': self.schema_signature,
            'field_schema': json.loads(self.field_schema_json),
            'render_config': json.loads(self.render_config_json),
            'sanitize_rules': json.loads(self.sanitize_rules_json),
            'scorm_behavior': json.loads(self.scorm_behavior_json),
            'renderer_class': self.renderer_class,
            'layout_version': self.layout_version,
            'created_at': (
                self.created_at.isoformat() if self.created_at else None
            ),
            'updated_at': (
                self.updated_at.isoformat() if self.updated_at else None
            )
        }
