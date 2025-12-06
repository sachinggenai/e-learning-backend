import asyncio
import sys
import traceback
sys.path.insert(0, '.')

async def test():
    from app.db.config import SessionLocal
    from app.services.import_service import ImportService
    import tempfile
    import zipfile
    import json
    
    # Create test SCORM package
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        tmp_path = tmp.name
    
    with zipfile.ZipFile(tmp_path, 'w') as zf:
        # imsmanifest.xml
        manifest = """<?xml version="1.0"?>
<manifest identifier="golf-101" version="1">
  <organizations default="org1">
    <organization identifier="org1">
      <title>Golf Training</title>
      <item identifier="item1" identifierref="res1">
        <title>Lesson 1</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res1" type="webcontent" href="index.html">
      <file href="course_data.js"/>
    </resource>
  </resources>
</manifest>"""
        zf.writestr('imsmanifest.xml', manifest)
        
        # course_data.js
        course_data = {
            'courseId': 'golf-training-001',
            'title': 'Golf Training Course',
            'templates': [
                {'id': 'tpl_0', 'type': 'welcome', 'title': 'Welcome', 'data': {}},
                {'id': 'tpl_1', 'type': 'content-text', 'title': 'Text Content', 'data': {'text': 'Sample text'}},
            ]
        }
        js_code = f'var courseData = {json.dumps(course_data, indent=2)};'
        zf.writestr('course_data.js', js_code)
        
        zf.writestr('index.html', '<html></html>')
    
    try:
        from app.db.config import SessionLocal
        
        async with SessionLocal() as session:
            service = ImportService(session)
            
            with open(tmp_path, 'rb') as f:
                zip_data = f.read()
            
            print(f'Starting analyze_package...')
            job_id = await service.analyze_package(zip_data)
            print(f'Job created: {job_id}')
            
            # Check if session is dirty
            print(f'Session is active: {session.is_active}')
            print(f'Session in transaction: {session.in_transaction()}')
            
            # Try to retrieve immediately with explicit query
            from app.models.persisted_course import ImportJob
            result = await session.execute(
                __import__('sqlalchemy').select(ImportJob).where(
                    ImportJob.job_id == job_id
                )
            )
            job = result.scalar_one_or_none()
            print(f'Direct query job retrieved: {job is not None}')
            
            # Try through repo
            job = await service.job_repo.get_by_id(job_id)
            print(f'Job through repo retrieved: {job is not None}')
            if job:
                print(f'Job status: {job.status}')
    except Exception as e:
        print(f'ERROR: {e}')
        traceback.print_exc()
    finally:
        import os
        os.unlink(tmp_path)

asyncio.run(test())
