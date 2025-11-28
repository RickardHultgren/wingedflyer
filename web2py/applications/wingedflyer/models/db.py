"""
Database models for WingedFlyer application.
Lightweight, mobile-first flyer management.

MFI


B2C


"""

from gluon.contrib.appconfig import AppConfig
from gluon.tools import Auth

# Load configuration
configuration = AppConfig(reload=True)

# Database connection
db = DAL(configuration.get('db.uri'),
         pool_size=configuration.get('db.pool_size'),
         migrate_enabled=configuration.get('db.migrate'),
         check_reserved=['all'])

# Authentication
auth = Auth(db)
auth.define_tables(username=False, signature=False)

# Custom auth messages
auth.messages.verify_email = 'Click on the link to verify your email'
auth.messages.logged_in = 'Welcome!'
auth.messages.logged_out = 'Logged out successfully'

# Flyer table
db.define_table('flyer',
    Field('user_id', 'reference auth_user', default=auth.user_id, writable=False),
    Field('title', 'string', length=255, notnull=True, default='Untitled Flyer'),
    Field('thecontent', 'text', notnull=True, default='# Your content here\n\nStart writing...'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    Field('is_public', 'boolean', default=True),
    Field('view_count', 'integer', default=0, writable=False),  # Track popularity
    format='%(title)s'
)

# Validation
db.flyer.title.requires = [
    IS_NOT_EMPTY(error_message='Title required'),
    IS_LENGTH(255, error_message='Title too long (max 255 chars)')
]
db.flyer.thecontent.requires = IS_NOT_EMPTY(error_message='Content required')

# Labels
db.flyer.title.label = 'Flyer Title'
db.flyer.thecontent.label = 'Content (Markdown)'
db.flyer.is_public.label = 'Make Public'