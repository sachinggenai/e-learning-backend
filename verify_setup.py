#!/usr/bin/env python3
"""
Verification script for Phase 1C & 2 setup.
Run: python verify_setup.py
"""

import sys
from pathlib import Path
import json


def check_file_exists(path: str, description: str) -> bool:
    """Check if a file exists."""
    p = Path(path)
    if p.exists():
        print(f"✅ {description}: {path}")
        return True
    else:
        print(f"❌ {description}: {path}")
        return False


def check_imports_in_file(file_path: str, imports: list, description: str) -> bool:
    """Check if file contains specific imports/strings."""
    p = Path(file_path)
    if not p.exists():
        print(f"❌ File not found: {file_path}")
        return False
    
    content = p.read_text()
    missing = []
    for imp in imports:
        if imp not in content:
            missing.append(imp)
    
    if missing:
        print(f"❌ {description} - Missing: {missing}")
        return False
    else:
        print(f"✅ {description}")
        return True


def check_router_registration() -> bool:
    """Check if imports router is registered."""
    main_py = Path("app/main.py")
    if not main_py.exists():
        print("❌ app/main.py not found")
        return False
    
    content = main_py.read_text()
    
    checks = [
        ("from app.routers import" in content and "imports" in content, "Import statement"),
        ("app.include_router(imports.router" in content, "Router registration"),
    ]
    
    all_good = True
    for check, desc in checks:
        if check:
            print(f"✅ {desc}")
        else:
            print(f"❌ {desc}")
            all_good = False
    
    return all_good


def check_database() -> bool:
    """Check if database is initialized."""
    db_path = Path("data/elearning.db")
    if not db_path.exists():
        print("⚠️  Database not yet created (will be created on first run)")
        return True  # Not a failure
    
    print(f"✅ Database exists: {db_path}")
    
    # Try to query import_jobs table
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='import_jobs'"
        )
        if cursor.fetchone():
            print("✅ import_jobs table exists")
            
            # Check columns
            cursor.execute("PRAGMA table_info(import_jobs)")
            cols = [row[1] for row in cursor.fetchall()]
            required = ['job_id', 'status', 'progress', 'result_data']
            missing = [col for col in required if col not in cols]
            
            if missing:
                print(f"❌ Missing columns: {missing}")
                return False
            else:
                print(f"✅ All required columns present: {required}")
        else:
            print("⚠️  import_jobs table not yet created")
        
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️  Could not check database: {e}")
        return True


def main():
    print("=" * 70)
    print("PHASE 1C & 2 SETUP VERIFICATION")
    print("=" * 70)
    print()
    
    results = []
    
    # Check 1: Code files
    print("📁 Code Files:")
    print("-" * 70)
    results.append(check_file_exists("app/services/heuristic_parser.py", "HeuristicParser"))
    results.append(check_file_exists("app/services/schema_inference.py", "SchemaInferenceEngine"))
    results.append(check_file_exists("app/services/asset_rewriter.py", "AssetRewriter"))
    results.append(check_file_exists("app/services/template_data_converter.py", "TemplateDataConverter"))
    results.append(check_file_exists("app/services/import_service.py", "ImportService"))
    results.append(check_file_exists("app/repositories/import_job_repository.py", "ImportJobRepository"))
    results.append(check_file_exists("app/routers/imports.py", "ImportRouter"))
    print()
    
    # Check 2: Test files
    print("🧪 Test Files:")
    print("-" * 70)
    results.append(check_file_exists("test_import_quick.py", "Quick test script"))
    results.append(check_file_exists("TESTING_QUICK_START.md", "Quick start guide"))
    results.append(check_file_exists("HOW_TO_TEST_PHASE_1C_AND_2.md", "Testing guide"))
    print()
    
    # Check 3: Router registration
    print("🔗 Router Registration:")
    print("-" * 70)
    results.append(check_router_registration())
    print()
    
    # Check 4: Database
    print("💾 Database:")
    print("-" * 70)
    results.append(check_database())
    print()
    
    # Check 5: Dependencies
    print("📦 Dependencies:")
    print("-" * 70)
    try:
        import fastapi
        print("✅ FastAPI installed")
        results.append(True)
    except ImportError:
        print("❌ FastAPI not installed")
        results.append(False)
    
    try:
        import sqlalchemy
        print("✅ SQLAlchemy installed")
        results.append(True)
    except ImportError:
        print("❌ SQLAlchemy not installed")
        results.append(False)
    
    try:
        import pydantic
        print("✅ Pydantic installed")
        results.append(True)
    except ImportError:
        print("❌ Pydantic not installed")
        results.append(False)
    
    print()
    print("=" * 70)
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL CHECKS PASSED ({passed}/{total})")
        print()
        print("You're ready to test!")
        print()
        print("Quick start:")
        print("  1. Terminal 1: ./run_dev.ps1")
        print("  2. Terminal 2: python test_import_quick.py")
        print()
        return 0
    else:
        print(f"⚠️  Some checks failed ({passed}/{total})")
        print()
        print("Please fix the issues above, then try again.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
