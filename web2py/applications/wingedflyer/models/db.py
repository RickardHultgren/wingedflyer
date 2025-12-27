from gluon.contrib.appconfig import AppConfig
from gluon.tools import Auth
import bcrypt
from datetime import datetime, timedelta

# Load configuration
configuration = AppConfig(reload=True)

# Database connection
db = DAL(configuration.get('db.uri'),
         pool_size=configuration.get('db.pool_size'),
         migrate_enabled=configuration.get('db.migrate'),
         check_reserved=['all'])

# Auth system
auth = Auth(db)
auth.define_tables(username=True, signature=False)

############################################################
# 1. MFI TABLE
############################################################

db.define_table(
    'mfi',
    Field('username', 'string', unique=True, notnull=True),
    Field('password_hash', 'password', readable=False, writable=True),
    Field('name', 'string', notnull=True),
    Field('telephone', 'string'),
    Field('email', 'string'),
    Field('contact_person', 'string'),
    Field('country', 'string'),
    Field('notes', 'text'),
    Field('b2c_accounts', 'integer', default=0, 
          comment='Maximum number of B2C accounts allowed'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    format='%(name)s'
)

# Validators
db.mfi.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'mfi.username')]
db.mfi.name.requires = IS_NOT_EMPTY()
db.mfi.email.requires = IS_EMPTY_OR(IS_EMAIL())
db.mfi.b2c_accounts.requires = IS_INT_IN_RANGE(0, 10000)

# Password Hashing Logic
def hash_password(pwd):
    if pwd and not pwd.startswith('$2b$'):
        return bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    return pwd

#db.mfi._before_insert.append(lambda f: f.update(password_hash=hash_password(f.get('password_hash'))))

def encrypt_mfi_password(row):
    if 'password_hash' in row:
        row['password_hash'] = hash_password(row['password_hash'])

db.mfi._before_insert.append(encrypt_mfi_password)

db.mfi._before_update.append(lambda s, f: f.update(password_hash=hash_password(f.get('password_hash'))))

############################################################
# 2. BORROWER TABLE
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
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    format='%(real_name)s'
)

db.b2c.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'b2c.username')]
db.b2c.real_name.requires = IS_NOT_EMPTY()
db.b2c.email.requires = IS_EMPTY_OR(IS_EMAIL())

def validate_b2c_limit(fields):
    mfi_id = fields.get('mfi_id')
    if mfi_id:
        mfi = db.mfi(mfi_id)
        current_count = db(db.b2c.mfi_id == mfi_id).count()
        if current_count >= mfi.b2c_accounts:
            # In a real app, use a custom validator instead of a hard exception
            raise ValueError('MFI account limit reached')

db.b2c._before_insert.append(validate_b2c_limit)
db.b2c._before_insert.append(lambda f: f.update(password_hash=hash_password(f.get('password_hash'))))

############################################################
# 4. BORROWER DAILY SIGNALS (Schema Diagram Placeholder)
############################################################



db.define_table(
    'work_activity',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('activity_name', 'string', notnull=True),
    Field('description', 'text'),
    Field('is_active', 'boolean', default=True),
    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(activity_name)s'
)

db.define_table(
    'daily_signal',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('work_activity_id', 'reference work_activity', notnull=True),
    Field('signal_date', 'date', notnull=True, default=request.now),
    Field('outcome', 'string', notnull=True),
    Field('note', 'text'),
    Field('created_on', 'datetime', default=request.now)
)

db.daily_signal.outcome.requires = IS_IN_SET(['BETTER', 'AS_EXPECTED', 'WORSE'])

############################################################
# 5. PAYMENT TRACKING
############################################################

db.define_table(
    'b2c_payment',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('amount', 'double', notnull=True),
    Field('due_date', 'date', notnull=True),
    Field('paid_date', 'date'),
    Field('days_late', 'integer', default=0),
    Field('payment_method', 'string'),
    Field('notes', 'text'),
    Field('created_on', 'datetime', default=request.now)
)

def calculate_days_late(fields):
    # Ensure we are dealing with date objects
    paid = fields.get('paid_date')
    due = fields.get('due_date')
    if paid and due:
        # If web2py hasn't converted them to dates yet (e.g. from raw dicts)
        if isinstance(due, str): due = datetime.strptime(due, '%Y-%m-%d').date()
        if isinstance(paid, str): paid = datetime.strptime(paid, '%Y-%m-%d').date()
        
        delta = (paid - due).days
        fields['days_late'] = delta if delta > 0 else 0

db.b2c_payment._before_insert.append(calculate_days_late)
db.b2c_payment._before_update.append(lambda s, f: calculate_days_late(f))

############################################################
# 7. MESSAGING SYSTEM
############################################################

db.define_table(
    'mfi_info_flyer',
    Field('mfi_id', 'reference mfi', notnull=True),
    Field('subject', 'string', notnull=True),
    Field('info_flyer_text', 'text', notnull=True),
    Field('response_template', 'string', default='NONE'),
    Field('created_on', 'datetime', default=request.now),
    Field('sent_by', 'string'),
    format='%(subject)s'
)


db.define_table(
    'info_flyer_recipient',
    Field('info_flyer_id', 'reference mfi_info_flyer', notnull=True),
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('is_read', 'boolean', default=False),
    Field('read_on', 'datetime'),
    Field('response', 'string'),
    Field('responded_on', 'datetime'),
    Field('created_on', 'datetime', default=request.now)
)
