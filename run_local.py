import os

os.environ.setdefault('APP_ENV', 'local')
os.environ.setdefault('DEBUG', 'true')
os.environ.setdefault('FLASK_APP', 'app:create_app')
os.environ.setdefault('HOST', '0.0.0.0')
os.environ.setdefault('PORT', '5000')
os.environ.setdefault('AI_SYSTEMS_ENABLED', 'false')
os.environ.setdefault('ENABLE_AUTOMATED_BACKUPS', 'false')

from app import create_app
from extensions import db

application = create_app()


def prepare_local_database():
    with application.app_context():
        try:
            from flask_migrate import upgrade
            upgrade()
        except Exception as exc:
            print(f'WARNING: flask db upgrade failed: {exc}')
            print('Trying db.create_all() for local testing...')
            db.create_all()


if __name__ == '__main__':
    prepare_local_database()
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '5000'))
    application.run(host=host, port=port, debug=True)
