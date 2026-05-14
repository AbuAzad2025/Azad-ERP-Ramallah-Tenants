import os

os.environ.setdefault('APP_ENV', 'local')
os.environ.setdefault('DEBUG', 'true')
os.environ.setdefault('FLASK_APP', 'app:create_app')
os.environ.setdefault('HOST', '0.0.0.0')
os.environ.setdefault('PORT', '5000')
os.environ.setdefault('AI_SYSTEMS_ENABLED', 'false')
os.environ.setdefault('ENABLE_AUTOMATED_BACKUPS', 'false')
os.environ.setdefault('RESET_LOCAL_SQLITE', 'true')


def reset_local_sqlite_database():
    app_env = os.environ.get('APP_ENV', '').lower()
    has_external_db = bool(os.environ.get('DATABASE_URL'))
    reset_enabled = os.environ.get('RESET_LOCAL_SQLITE', 'true').lower() in {'1', 'true', 'yes', 'on'}

    if app_env != 'local' or has_external_db or not reset_enabled:
        return

    base_dir = os.path.abspath(os.path.dirname(__file__))
    instance_dir = os.path.join(base_dir, 'instance')
    for filename in ('garage.db', 'garage.db-shm', 'garage.db-wal'):
        path = os.path.join(instance_dir, filename)
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f'Removed local test database file: {path}')
        except Exception as exc:
            print(f'WARNING: could not remove {path}: {exc}')


reset_local_sqlite_database()

from app import create_app
from extensions import db

application = create_app()


def prepare_local_database():
    with application.app_context():
        print('Preparing local SQLite database with db.create_all()...')
        db.create_all()
        print('Local database is ready.')


if __name__ == '__main__':
    prepare_local_database()
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '5000'))
    application.run(host=host, port=port, debug=True)
