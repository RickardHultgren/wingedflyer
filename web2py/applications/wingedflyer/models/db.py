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

    # This field sets the LIMIT of how many B2C accounts the MFI can create
    Field('b2c_accounts', 'integer', default=0, comment='Maximum number of B2C accounts allowed'),

    Field('created_on', 'datetime', default=request.now),
    format='%(name)s'
)

# Validation
db.mfi.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'mfi.username')]
db.mfi.name.requires     = IS_NOT_EMPTY()
db.mfi.email.requires    = IS_EMPTY_OR(IS_EMAIL())
db.mfi.b2c_accounts.requires = IS_INT_IN_RANGE(0, 10000)  # Max 10,000 accounts

# Field labels for better admin UI
db.mfi.username.label = 'Username'
db.mfi.password_hash.label = 'Password'
db.mfi.name.label = 'MFI Name'
db.mfi.email.label = 'Email Address'
db.mfi.contact_person.label = 'Contact Person'
db.mfi.country.label = 'Country'
db.mfi.notes.label = 'Notes'
db.mfi.b2c_accounts.label = 'Max B2C Accounts (Limit)'
db.mfi.created_on.label = 'Created On'

# The b2c_accounts field is the LIMIT, so it should be writable by admin
db.mfi.b2c_accounts.readable = True
db.mfi.b2c_accounts.writable = True
db.mfi.b2c_accounts.comment = 'Set the maximum number of B2C accounts this MFI can create'


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

db.b2c.username.requires  = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'b2c.username')]
db.b2c.real_name.requires = IS_NOT_EMPTY()
db.b2c.email.requires = IS_EMPTY_OR(IS_EMAIL())

# Field labels
db.b2c.mfi_id.label = 'MFI'
db.b2c.username.label = 'Username'
db.b2c.password_hash.label = 'Password'
db.b2c.real_name.label = 'Real Name'
db.b2c.address.label = 'Address'
db.b2c.telephone.label = 'Telephone'
db.b2c.email.label = 'Email'
db.b2c.social_media.label = 'Social Media'
db.b2c.amount_borrowed.label = 'Amount Borrowed'
db.b2c.amount_repaid_b2c_reported.label = 'Amount Repaid (B2C Reported)'
db.b2c.location_lat.label = 'Latitude'
db.b2c.location_lng.label = 'Longitude'
db.b2c.started_working_today.label = 'Started Working Today'
db.b2c.qr_code_url.label = 'QR Code URL'
db.b2c.micro_page_text.label = 'Micro Page Text'


# Validate that MFI has not exceeded their B2C account limit
def validate_b2c_limit(fields):
    """Check if MFI can create another B2C account"""
    mfi_id = fields.get('mfi_id')
    if mfi_id:
        mfi = db.mfi(mfi_id)
        if mfi:
            current_count = db(db.b2c.mfi_id == mfi_id).count()
            if current_count >= mfi.b2c_accounts:
                raise Exception('MFI has reached maximum B2C account limit (%d)' % mfi.b2c_accounts)

db.b2c._before_insert.append(validate_b2c_limit)


# Hash B2C passwords
def hash_b2c_password_on_insert(fields):
    """Hash B2C password on insert if provided"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        # Only hash if not already hashed
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

def hash_b2c_password_on_update(s, fields):
    """Hash B2C password on update if provided"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        # Only hash if not already hashed
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

db.b2c._before_insert.append(hash_b2c_password_on_insert)
db.b2c._before_update.append(hash_b2c_password_on_update)


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
db.b2c_timeline_message.b2c_id.label = 'B2C Account'
db.b2c_timeline_message.title.label = 'Title'
db.b2c_timeline_message.the_message.label = 'Message'
db.b2c_timeline_message.the_date.label = 'Date'


############################################################
# 4. URGENT MESSAGE (single entry per b2c)
############################################################

db.define_table(
    'b2c_urgent_message',
    Field('b2c_id', 'reference b2c', unique=True),
    Field('the_message', 'text'),
    Field('created_on', 'datetime', default=request.now)
)

db.b2c_urgent_message.b2c_id.label = 'B2C Account'
db.b2c_urgent_message.the_message.label = 'Urgent Message'


############################################################
# 5. VIEW LOGS
############################################################

db.define_table(
    'b2c_micro_page_view',
    Field('b2c_id', 'reference b2c'),
    Field('viewer_ip', 'string'),
    Field('viewed_on', 'datetime', default=request.now)
)

db.b2c_micro_page_view.b2c_id.label = 'B2C Account'
db.b2c_micro_page_view.viewer_ip.label = 'Viewer IP'
db.b2c_micro_page_view.viewed_on.label = 'Viewed On'