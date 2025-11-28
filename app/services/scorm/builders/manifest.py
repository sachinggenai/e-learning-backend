"""IMS Manifest builder for SCORM 1.2 packages."""
from typing import Dict, Any
from jinja2 import Template
from .base import BaseBuilder


class ManifestBuilder(BaseBuilder):
    """Builds imsmanifest.xml for SCORM 1.2 packages."""

    MANIFEST_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{{ course_id }}" version="1.0" 
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                              http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                              http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  
  <organizations default="{{ course_id }}_org">
    <organization identifier="{{ course_id }}_org">
      <title>{{ title }}</title>
      {% for template in templates %}
      <item identifier="item_{{ loop.index0 }}" identifierref="resource_{{ loop.index0 }}">
        <title>{{ template.title }}</title>
        <adlcp:masteryscore>80</adlcp:masteryscore>
      </item>
      {% endfor %}
    </organization>
  </organizations>
  
  <resources>
    <resource identifier="resource_main" type="webcontent" 
              adlcp:scormtype="sco" href="index.html">
      <file href="index.html" />
      <file href="scorm_wrapper.js" />
      <file href="course_data.js" />
      <file href="styles.css" />
      {% for asset in assets %}
      <file href="{{ asset }}" />
      {% endfor %}
    </resource>
    {% for template in templates %}
    <resource identifier="resource_{{ loop.index0 }}" 
              type="webcontent" adlcp:scormtype="sco" 
              href="index.html#slide{{ loop.index0 }}">
      <file href="index.html" />
    </resource>
    {% endfor %}
  </resources>
</manifest>'''

    async def build(self, context: Dict[str, Any]) -> str:
        """Build the IMS manifest XML."""
        template = Template(self.MANIFEST_TEMPLATE)
        return template.render(**context)
