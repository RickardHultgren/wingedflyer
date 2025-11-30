"""
WingedFlyer database schema.
Implements dual-sided communication:
 - MFI dashboard for borrower/b2c management
 - B2C micro-webpages for customers
"""

from gluon.contrib.appconfig import AppConfig
from gluon.tools import Auth
import bcrypt

# Load configuration
configuration = AppConfig(reload=True)

# Database connection
db = DAL(configuration.get('db.uri'),
         pool_size=configuration.get('db.pool_size'),
         migrate_enabled=configuration.get('db.migrate'),
         check_reserved=['all'])

# Auth system (admin only — MFIs do NOT use this)
auth = Auth(db)
auth.define_tables(username=True, signature=False)


############################################################
# 1. MFI TABLE (managed ONLY via appadmin)
############################################################

db.define_table(
    'mfi',
    Field('username', 'string', unique=True, notnull=True),
    Field('password_hash', 'password', readable=False, writable=True),

    Field('name', 'string', notnull=True),
    Field('email', 'string'),
    Field('contact_person', 'string'),
    Field('country', 'string'),
    Field('notes', 'text'),

    Field('b2c_accounts', 'integer', default=0),

    Field('created_on', 'datetime', default=request.now),
    format='%(name)s'
)

# Validation
db.mfi.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'mfi.username')]
db.mfi.name.requires     = IS_NOT_EMPTY()
db.mfi.email.requires    = IS_EMPTY_OR(IS_EMAIL())

# b2c count should not be editable by admin
db.mfi.b2c_accounts.readable = True
db.mfi.b2c_accounts.writable = False

# Field labels for better admin UI
db.mfi.username.label = 'Username'
db.mfi.password_hash.label = 'Password'
db.mfi.name.label = 'MFI Name'
db.mfi.email.label = 'Email Address'
db.mfi.contact_person.label = 'Contact Person'
db.mfi.country.label = 'Country'
db.mfi.notes.label = 'Notes'
db.mfi.b2c_accounts.label = 'B2C Accounts'
db.mfi.created_on.label = 'Created On'


# Automatically hash MFI passwords on insert
def hash_mfi_password_on_insert(fields):
    """Hash password on insert"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        fields['password_hash'] = hashed

# Automatically hash MFI passwords on update
def hash_mfi_password_on_update(s, fields):
    """Hash password on update - s is the Set object, fields is the dict of updates"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        # Only hash if it's not already a bcrypt hash
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

db.mfi._before_insert.append(hash_mfi_password_on_insert)
db.mfi._before_update.append(hash_mfi_password_on_update)


############################################################
# 2. b2c / BORROWER TABLE
############################################################

db.define_table(
    'b2c',
    Field('mfi_id', 'reference mfi', notnull=True),

    Field('username', 'string', unique=True),
    Field('password_hash', 'string'),

    Field('real_name', 'string'),
    Field('address', 'string'),
    Field('telephone', 'string'),
    Field('email', 'string'),
    Field('social_media', 'string'),

    Field('amount_borrowed', 'double', default=0),
    Field('amount_repaid_b2c_reported', 'double', default=0),

    Field('location_lat', 'double'),
    Field('location_lng', 'double'),
    Field('started_working_today', 'boolean', default=False),

    Field('qr_code_url', 'string'),
    Field('micro_page_text', 'text', default=""),

    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(real_name)s'
)

db.b2c.username.requires  = IS_NOT_EMPTY()
db.b2c.real_name.requires = IS_NOT_EMPTY()


# Update MFI b2c_accounts count after insert
def update_mfi_count_on_insert(fields, id):
    """Update MFI b2c count after inserting a borrower"""
    mfi_id = fields.get('mfi_id')
    if mfi_id:
        count = db(db.b2c.mfi_id == mfi_id).count()
        db(db.mfi.id == mfi_id).update(b2c_accounts=count)

# Update MFI b2c_accounts count after delete
def update_mfi_count_on_delete(s):
    """Update MFI b2c count after deleting a borrower"""
    # Get the records that will be deleted
    records = db(s).select(db.b2c.mfi_id)
    mfi_ids = set([r.mfi_id for r in records])
    
    # Delete happens here (handled by web2py)
    # After delete, update counts
    for mfi_id in mfi_ids:
        count = db(db.b2c.mfi_id == mfi_id).count()
        db(db.mfi.id == mfi_id).update(b2c_accounts=count)

db.b2c._after_insert.append(update_mfi_count_on_insert)
db.b2c._before_delete.append(update_mfi_count_on_delete)


############################################################
# 3. TIMELINE MESSAGES
############################################################

db.define_table(
    'b2c_timeline_message',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('title', 'string', notnull=True),
    Field('the_message', 'text'),
    Field('the_date', 'datetime', default=request.now),
    Field('created_on', 'datetime', default=request.now),
    format='%(title)s'
)

db.b2c_timeline_message.title.requires = IS_NOT_EMPTY()


############################################################
# 4. URGENT MESSAGE (single entry per b2c)
############################################################

db.define_table(
    'b2c_urgent_message',
    Field('b2c_id', 'reference b2c', unique=True),
    Field('the_message', 'text'),
    Field('created_on', 'datetime', default=request.now)
)


############################################################
# 5. VIEW LOGS
############################################################

db.define_table(
    'b2c_micro_page_view',
    Field('b2c_id', 'reference b2c'),
    Field('viewer_ip', 'string'),
    Field('viewed_on', 'datetime', default=request.now)
)