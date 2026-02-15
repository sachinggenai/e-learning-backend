import asyncio
from app.db.config import get_database_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.repositories.component_type_repo import ComponentTypeRepository

async def check():
    engine = create_async_engine(get_database_url())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    
    async with SessionLocal() as session:
        repo = ComponentTypeRepository(session)
        ct = await repo.get_by_type_id('video-slide')
        
        print(f'video-slide found: {ct is not None}')
        if ct:
            print(f'Display name: {ct.display_name}')
            print(f'Category: {ct.category}')
            print(f'Active: {ct.is_active}')
        else:
            print('video-slide NOT in database!')
            
        # Count total component types
        all_types = await repo.list_all()
        print(f'\nTotal component types in DB: {len(all_types)}')

asyncio.run(check())
