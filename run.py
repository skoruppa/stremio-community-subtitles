import os
import click
from app import create_app, db
from waitress import serve

# Create the Flask app instance using the factory
app = create_app()

@app.cli.command("init-db")
def init_db_command():
    """Clear existing data and create database tables."""
    click.echo("Dropping all tables...")
    db.drop_all()
    click.echo("Creating all tables...")
    db.create_all()
    click.echo("Initialized the database!")

@app.cli.command("create-roles")
def create_roles_command():
    """Create the default roles."""
    from app.models import Role
    click.echo("Creating default roles...")
    try:
        # Check if roles already exist
        admin_role = Role.query.filter_by(name='Admin').first()
        user_role = Role.query.filter_by(name='User').first()
        
        if not admin_role:
            admin_role = Role(name='Admin', description='Administrator')
            db.session.add(admin_role)
            click.echo("Created 'Admin' role")
        
        if not user_role:
            user_role = Role(name='User', description='Standard user')
            db.session.add(user_role)
            click.echo("Created 'User' role")
        
        db.session.commit()
        click.echo("Roles created successfully")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error creating roles: {e}")

@app.cli.command("create-admin")
@click.argument("email")
@click.argument("username")
@click.argument("password")
def create_admin_command(email, username, password):
    """Create an admin user."""
    from app.models import User, Role
    click.echo(f"Creating admin user: {username} ({email})...")
    try:
        # Check if user already exists
        user = User.query.filter((User.email == email) | (User.username == username)).first()
        if user:
            click.echo(f"User with email {email} or username {username} already exists")
            return
        
        # Create new user
        user = User(email=email, username=username, active=True)
        user.set_password(password)
        user.generate_manifest_token()
        
        # Add admin role
        admin_role = Role.query.filter_by(name='Admin').first()
        if not admin_role:
            click.echo("Admin role not found. Creating it...")
            admin_role = Role(name='Admin', description='Administrator')
            db.session.add(admin_role)
        
        user.roles.append(admin_role)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin user created successfully: {username}")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error creating admin user: {e}")

if __name__ == '__main__':
    # Get host and port from environment variables or use defaults
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    try:
        port = int(os.environ.get('FLASK_RUN_PORT', '5000'))
    except ValueError:
        port = 5000  # Default port if env var is not an integer

    if app.config['DEBUG']:
        # Use Flask's built-in server for development
        app.run(host=host, port=port, debug=True)
    else:
        # Use waitress for production
        print(f"Starting production server on {host}:{port}")
        serve(app, host=host, port=port)
