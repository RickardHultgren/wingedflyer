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


# Automatically hash MFI passwords set in appadmin
def hash_mfi_password(row):
    # row is a dict-like object, not a form
    pwd_plain = row.get('password_hash')

    if not pwd_plain:
        return row  # nothing to hash

    # Hash it
    hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    row['password_hash'] = hashed
    return row

db.mfi._before_insert.append(hash_mfi_password)
db.mfi._before_update.append(hash_mfi_password)



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



############################################################
# Helper: auto-update B2C count for each MFI
############################################################

def update_b2c_count(mfi_id):
    count = db(db.b2c.mfi_id == mfi_id).count()
    db(db.mfi.id == mfi_id).update(b2c_accounts=count)
