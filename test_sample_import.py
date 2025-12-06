#!/usr/bin/env python3
"""
Test importing the actual sample SCORM package
"""

import asyncio
import sys
from pathlib import Path
import zipfile

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.import_service import ImportService
from app.db.config import SessionLocal

async def test_sample_import():
    """Test importing sample SCORM package"""
    
    sample_zip = Path(__file__).parent / "sample_course" / "RuntimeMinimumCalls_SCORM12.zip"
    
    if not sample_zip.exists():
        print(f"❌ Sample file not found: {sample_zip}")
        return False
    
    print(f"\n📦 Testing import of: {sample_zip.name}")
    print(f"   Size: {sample_zip.stat().st_size / 1024:.1f} KB")
    
    try:
        # Read the ZIP file
        print("\n📥 Reading ZIP file...")
        zip_data = sample_zip.read_bytes()
        print(f"   Read {len(zip_data) / 1024:.1f} KB of data")
        
        # Get database session
        async with SessionLocal() as db_session:
            # Step 1: Analyze the package
            print("\n🔍 Step 1: Analyzing package...")
            service = ImportService(db_session)
            result = await service.analyze_package(zip_data)
            
            print(f"✅ Analysis complete!")
            print(f"   Job ID: {result['job_id']}")
            print(f"   Status: {result['status']}")
            print(f"   Course ID: {result.get('course_id', 'Not yet assigned')}")
            
            # Step 2: Check what was discovered
            if 'preview' in result:
                preview = result['preview']
                print(f"\n📋 Preview Data:")
                print(f"   Course ID: {preview.get('courseId', 'N/A')}")
                print(f"   Title: {preview.get('title', 'N/A')}")
                print(f"   Templates found: {len(preview.get('templates', []))}")
                
                for i, template in enumerate(preview.get('templates', [])):
                    print(f"\n   Template {i}:")
                    print(f"      ID: {template.get('id', 'N/A')}")
                    print(f"      Type: {template.get('type', 'N/A')}")
                    print(f"      Title: {template.get('title', 'N/A')}")
                    print(f"      Order: {template.get('order', 'N/A')}")
                    
                    schema = template.get('schema', {})
                    if schema:
                        print(f"      Schema fields: {len(schema.get('properties', {}))}")
                        for field_name, field_def in schema.get('properties', {}).items():
                            field_type = field_def.get('type', 'unknown')
                            print(f"         - {field_name}: {field_type}")
            
            # Step 3: Check for warnings
            if 'warnings' in result:
                print(f"\n⚠️  Warnings ({len(result['warnings'])}):")
                for warning in result['warnings']:
                    print(f"   - {warning}")
        
        print("\n✅ Phase 1 import successful!")
        return True
        
    except Exception as e:
        print(f"\n❌ Import failed with error:")
        print(f"   {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def inspect_zip():
    """Inspect the SCORM ZIP structure"""
    sample_zip = Path(__file__).parent / "sample_course" / "RuntimeMinimumCalls_SCORM12.zip"
    
    if not sample_zip.exists():
        return
    
    print("\n📂 ZIP File Structure:")
    try:
        with zipfile.ZipFile(sample_zip, 'r') as z:
            for info in z.filelist[:15]:  # First 15 files
                print(f"   {info.filename} ({info.file_size} bytes)")
            if len(z.filelist) > 15:
                print(f"   ... and {len(z.filelist) - 15} more files")
    except Exception as e:
        print(f"   Error: {e}")


async def main():
    print("=" * 70)
    print("PHASE 1 IMPORT TEST - Sample Course")
    print("=" * 70)
    
    # Inspect ZIP first
    await inspect_zip()
    
    # Run import test
    success = await test_sample_import()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ PHASE 1 IS WORKING! Sample import completed successfully.")
    else:
        print("❌ PHASE 1 HAS ISSUES. See errors above.")
    print("=" * 70)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
