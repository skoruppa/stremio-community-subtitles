#!/usr/bin/env python3
"""Application entry point"""
import os
import sys
import asyncio
import click
from app import create_app

app = create_app()

@click.group()
def cli():
    """Management commands"""
    pass

@cli.command()
@click.argument("email")
@click.argument("username")
@click.argument("password")
def create_admin(email, username, password):
    """Create an admin user"""
    from app.extensions import async_session_maker
    from app.models import User, Role
    from sqlalchemy import select
    
    async def _create():
        async with async_session_maker() as session:
            result = await session.execute(
                select(User).filter((User.email == email) | (User.username == username))
            )
            if result.scalar_one_or_none():
                click.echo("User already exists")
                return
            
            user = User(email=email, username=username, active=True)
            user.set_password(password)
            user.generate_manifest_token()
            
            result = await session.execute(select(Role).filter_by(name='Admin'))
            admin_role = result.scalar_one_or_none()
            if not admin_role:
                admin_role = Role(name='Admin', description='Administrator')
                session.add(admin_role)
            
            user.roles.append(admin_role)
            session.add(user)
            await session.commit()
            click.echo(f"Admin user created: {username}")
    
    asyncio.run(_create())

@cli.command('init-db')
def init_db_command():
    """Initialize database tables"""
    from app.extensions import async_engine, Base
    
    async def _init():
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        click.echo("Database tables created")
    
    asyncio.run(_init())

@cli.command('create-roles')
def create_roles_command():
    """Create default roles"""
    from app.extensions import async_session_maker
    from app.models import Role
    from sqlalchemy import select
    
    async def _create():
        async with async_session_maker() as session:
            roles = [
                ('User', 'Standard user'),
                ('Admin', 'Administrator')
            ]
            
            for name, desc in roles:
                result = await session.execute(select(Role).filter_by(name=name))
                if not result.scalar_one_or_none():
                    session.add(Role(name=name, description=desc))
                    click.echo(f"Created role: {name}")
                else:
                    click.echo(f"Role already exists: {name}")
            
            await session.commit()
    
    asyncio.run(_create())


@cli.command('init-anime-db')
def init_anime_db_command():
    """Initialize anime mapping database"""
    from app.lib.anime_mapping import update_database, ANIME_LISTS_JSON
    
    if not ANIME_LISTS_JSON.exists():
        click.echo(f"Error: {ANIME_LISTS_JSON} not found")
        click.echo("Run: git submodule update --init --recursive")
        return
    
    if update_database():
        click.echo("✓ Anime mapping database initialized")
    else:
        click.echo("✓ Anime mapping database already up to date")

if __name__ == '__main__':
    # Check if running CLI commands
    if len(sys.argv) > 1 and sys.argv[1] in ['create-admin', 'init-db', 'create-roles', 'init-anime-db']:
        cli()
        sys.exit(0)
    
    # Run web server
    debug = os.getenv('DEBUG', 'false').lower() in ('true', '1', 'yes')
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 5000))
    
    if debug:
        # Development mode - Quart built-in server with auto-reload
        print(f"Starting development server on {host}:{port}")
        print("Auto-reload enabled")
        app.run(host=host, port=port, debug=True, use_reloader=True)
    else:
        # Production mode - use Hypercorn
        print(f"Starting production server on {host}:{port}")
        
        # Try to use hypercorn if available
        try:
            from hypercorn.config import Config
            from hypercorn.asyncio import serve
            import asyncio
            
            workers = int(os.getenv('HYPERCORN_WORKERS', 1))
            
            if workers > 1:
                # Use hypercorn CLI for multiple workers
                import subprocess
                import sys
                import os
                
                # Get hypercorn path from venv
                venv_bin = os.path.dirname(sys.executable)
                hypercorn_path = os.path.join(venv_bin, 'hypercorn')
                
                cmd = [
                    hypercorn_path, 'run:app',
                    '--bind', f'{host}:{port}',
                    '--workers', str(workers),
                    '--access-logfile', '-',
                    '--error-logfile', '-'
                ]
                print(f"Running with Hypercorn ({workers} workers)")
                subprocess.run(cmd)
            else:
                # Single worker - use serve directly
                config = Config()
                config.bind = [f"{host}:{port}"]
                config.accesslog = '-'
                config.errorlog = '-'
                
                print(f"Running with Hypercorn (1 worker)")
                asyncio.run(serve(app, config))
        except ImportError:
            print("Hypercorn not found, falling back to Quart dev server")
            print("Install: pip install hypercorn")
            app.run(host=host, port=port, debug=False)
