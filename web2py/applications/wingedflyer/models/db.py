"""
WingedFlyer database schema - Autonomy-Respecting Design
Implements borrower-defined signals and bounded MFI responses
Based on principles from "When Transparency Becomes Surveillance"
"""

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

# Auth system (admin only)
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
    Field('created_on', 'datetime', default=request.now),
    format='%(name)s'
)

db.mfi.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'mfi.username')]
db.mfi.name.requires = IS_NOT_EMPTY()
db.mfi.email.requires = IS_EMPTY_OR(IS_EMAIL())
db.mfi.b2c_accounts.requires = IS_INT_IN_RANGE(0, 10000)


def hash_mfi_password_on_insert(fields):
    if 'password_hash' in fields and fields['password_hash']:
        pwd = fields['password_hash']
        fields['password_hash'] = bcrypt.hashpw(pwd.encode('utf-8'), 
                                                bcrypt.gensalt()).decode('utf-8')

def hash_mfi_password_on_update(s, fields):
    if 'password_hash' in fields and fields['password_hash']:
        pwd = fields['password_hash']
        if not pwd.startswith('$2b$') and not pwd.startswith('$2a$'):
            fields['password_hash'] = bcrypt.hashpw(pwd.encode('utf-8'), 
                                                    bcrypt.gensalt()).decode('utf-8')

db.mfi._before_insert.append(hash_mfi_password_on_insert)
db.mfi._before_update.append(hash_mfi_password_on_update)


############################################################
# 2. BORROWER TABLE - Simplified, No Surveillance Scoring
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
    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(real_name)s'
)

db.b2c.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'b2c.username')]
db.b2c.real_name.requires = IS_NOT_EMPTY()
db.b2c.email.requires = IS_EMPTY_OR(IS_EMAIL())


def validate_b2c_limit(fields):
    mfi_id = fields.get('mfi_id')
    if mfi_id:
        mfi = db.mfi(mfi_id)
        if mfi:
            current_count = db(db.b2c.mfi_id == mfi_id).count()
            if current_count >= mfi.b2c_accounts:
                raise Exception('MFI has reached maximum B2C account limit (%d)' % 
                              mfi.b2c_accounts)

db.b2c._before_insert.append(validate_b2c_limit)


def hash_b2c_password_on_insert(fields):
    if 'password_hash' in fields and fields['password_hash']:
        pwd = fields['password_hash']
        if not pwd.startswith('$2b$') and not pwd.startswith('$2a$'):
            fields['password_hash'] = bcrypt.hashpw(pwd.encode('utf-8'), 
                                                    bcrypt.gensalt()).decode('utf-8')

def hash_b2c_password_on_update(s, fields):
    if 'password_hash' in fields and fields['password_hash']:
        pwd = fields['password_hash']
        if not pwd.startswith('$2b$') and not pwd.startswith('$2a$'):
            fields['password_hash'] = bcrypt.hashpw(pwd.encode('utf-8'), 
                                                    bcrypt.gensalt()).decode('utf-8')

db.b2c._before_insert.append(hash_b2c_password_on_insert)
db.b2c._before_update.append(hash_b2c_password_on_update)


############################################################
# 3. BORROWER-DEFINED WORK ACTIVITIES
############################################################

db.define_table(
    'work_activity',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('activity_name', 'string', notnull=True,
          comment='Borrower-defined activity (e.g., "Weekly market sales")'),
    Field('description', 'text',
          comment='Optional description of what this activity involves'),
    Field('is_active', 'boolean', default=True,
          comment='Whether this activity is currently tracked'),
    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(activity_name)s'
)

db.work_activity.activity_name.requires = IS_NOT_EMPTY()
db.work_activity.activity_name.label = 'Activity Name'
db.work_activity.description.label = 'Description (Optional)'
db.work_activity.is_active.label = 'Currently Tracking?'


############################################################
# 4. BORROWER DAILY SIGNALS (Not Scores)
############################################################

db.define_table(
    'daily_signal',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('work_activity_id', 'reference work_activity', notnull=True),
    Field('signal_date', 'date', notnull=True, default=request.now),
    Field('outcome', 'string', notnull=True,
          comment='BETTER, AS_EXPECTED, or WORSE'),
    Field('note', 'text',
          comment='Optional short note from borrower'),
    Field('created_on', 'datetime', default=request.now),
    format='%(signal_date)s - %(outcome)s'
)

db.daily_signal.outcome.requires = IS_IN_SET(['BETTER', 'AS_EXPECTED', 'WORSE'])
db.daily_signal.signal_date.label = 'Date'
db.daily_signal.outcome.label = 'How did it go?'
db.daily_signal.note.label = 'Note (Optional)'


############################################################
# 5. PAYMENT TRACKING (No Scoring)
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
    Field('created_on', 'datetime', default=request.now),
    format='Payment %(amount)s'
)

db.b2c_payment.amount.requires = IS_NOT_EMPTY()
db.b2c_payment.due_date.requires = IS_NOT_EMPTY()


def calculate_days_late(fields):
    if 'paid_date' in fields and fields['paid_date'] and 'due_date' in fields:
        due = fields['due_date']
        paid = fields['paid_date']
        if isinstance(due, str):
            due = datetime.strptime(due, '%Y-%m-%d').date()
        if isinstance(paid, str):
            paid = datetime.strptime(paid, '%Y-%m-%d').date()
        fields['days_late'] = (paid - due).days

db.b2c_payment._before_insert.append(calculate_days_late)
db.b2c_payment._before_update.append(lambda s, f: calculate_days_late(f))


############################################################
# 6. MFI SUPPORT OFFERS (Not Commands)
############################################################

db.define_table(
    'support_offer',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('offer_type', 'string', notnull=True,
          comment='Type of support being offered'),
    Field('trigger_signal', 'string',
          comment='What signal prompted this offer'),
    Field('offer_text', 'text', notnull=True,
          comment='The actual offer being made'),
    Field('borrower_response', 'string',
          comment='ACCEPTED, DECLINED, PENDING, or MODIFIED'),
    Field('borrower_note', 'text',
          comment='Borrowers note about their response'),
    Field('created_on', 'datetime', default=request.now),
    Field('responded_on', 'datetime'),
    format='%(offer_type)s offer'
)

# Bounded set of 5 offer types
OFFER_TYPES = [
    'ADJUST_PAYMENT_TIMING',      # Coordination
    'SHARE_INFORMATION',           # Information gap
    'OFFER_RESTRUCTURING',         # Shock response
    'FACILITATE_SERVICE_ACCESS',   # Information/constraint
    'REQUEST_CONVERSATION'         # Complex situations
]

db.support_offer.offer_type.requires = IS_IN_SET(OFFER_TYPES)
db.support_offer.borrower_response.requires = IS_EMPTY_OR(
    IS_IN_SET(['ACCEPTED', 'DECLINED', 'PENDING', 'MODIFIED'])
)
db.support_offer.offer_type.label = 'Offer Type'
db.support_offer.offer_text.label = 'Offer Details'
db.support_offer.borrower_response.label = 'Borrower Response'


############################################################
# 7. TIMELINE MESSAGES (Transparent Communication)
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
# 8. FLYER TABLES (Existing Functionality)
############################################################

db.define_table('flyer',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('title', 'string', length=255, notnull=True, default='Untitled Flyer'),
    Field('thecontent', 'text', notnull=True, 
          default='# Your content here\n\nStart writing...'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    Field('is_public', 'boolean', default=True),
    Field('view_count', 'integer', default=0, writable=False),
    format='%(title)s'
)

db.flyer.title.requires = [
    IS_NOT_EMPTY(error_message='Title required'),
    IS_LENGTH(255, error_message='Title too long (max 255 chars)')
]
db.flyer.thecontent.requires = IS_NOT_EMPTY(error_message='Content required')


db.define_table('flyer_view',
    Field('flyer_id', 'reference flyer', notnull=True),
    Field('viewer_ip', 'string'),
    Field('viewed_on', 'datetime', default=request.now)
)


############################################################
# HELPER FUNCTIONS FOR AUTONOMY-RESPECTING OPERATIONS
############################################################

def get_recent_signals(b2c_id, days=7):
    """Get recent signals without scoring them"""
    cutoff = datetime.now() - timedelta(days=days)
    signals = db(
        (db.daily_signal.b2c_id == b2c_id) &
        (db.daily_signal.signal_date >= cutoff.date())
    ).select(
        db.daily_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.daily_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.daily_signal.signal_date
    )
    return signals


def get_pending_offers(b2c_id):
    """Get offers awaiting borrower response"""
    offers = db(
        (db.support_offer.b2c_id == b2c_id) &
        ((db.support_offer.borrower_response == 'PENDING') |
         (db.support_offer.borrower_response == None))
    ).select(orderby=~db.support_offer.created_on)
    return offers


def create_support_offer(b2c_id, offer_type, offer_text, trigger_signal=None):
    """
    Create a support offer for borrower to accept/decline
    This is the ONLY way MFIs should act on borrower signals
    """
    if offer_type not in OFFER_TYPES:
        raise ValueError('Invalid offer type. Must be one of: %s' % 
                        ', '.join(OFFER_TYPES))
    
    offer_id = db.support_offer.insert(
        b2c_id=b2c_id,
        offer_type=offer_type,
        offer_text=offer_text,
        trigger_signal=trigger_signal,
        borrower_response='PENDING'
    )
    
    # Also create timeline message so borrower sees it
    db.b2c_timeline_message.insert(
        b2c_id=b2c_id,
        title="Support Offer: %s" % offer_type.replace('_', ' ').title(),
        the_message=offer_text
    )
    
    return offer_id


def respond_to_offer(offer_id, response, borrower_note=None):
    """Borrower responds to an MFI offer"""
    if response not in ['ACCEPTED', 'DECLINED', 'MODIFIED']:
        raise ValueError('Invalid response')
    
    offer = db.support_offer(offer_id)
    if offer:
        offer.update_record(
            borrower_response=response,
            borrower_note=borrower_note,
            responded_on=datetime.now()
        )
        return True
    return False