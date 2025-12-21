"""
WingedFlyer database schema with Traffic Light Classification System.
Implements dual-sided communication + autonomy-based borrower management
 - MFI dashboard for borrower/b2c management
 - B2C micro-webpages for customers
 - Traffic light protocol for visibility-based autonomy
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
db.mfi.b2c_accounts.requires = IS_INT_IN_RANGE(0, 10000)

# Field labels
db.mfi.username.label = 'Username'
db.mfi.password_hash.label = 'Password'
db.mfi.name.label = 'MFI Name'
db.mfi.email.label = 'Email Address'
db.mfi.contact_person.label = 'Contact Person'
db.mfi.country.label = 'Country'
db.mfi.notes.label = 'Notes'
db.mfi.b2c_accounts.label = 'Max B2C Accounts (Limit)'
db.mfi.created_on.label = 'Created On'

db.mfi.b2c_accounts.readable = True
db.mfi.b2c_accounts.writable = True
db.mfi.b2c_accounts.comment = 'Set the maximum number of B2C accounts this MFI can create'


# Automatically hash MFI passwords
def hash_mfi_password_on_insert(fields):
    """Hash password on insert"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        fields['password_hash'] = hashed

def hash_mfi_password_on_update(s, fields):
    """Hash password on update"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

db.mfi._before_insert.append(hash_mfi_password_on_insert)
db.mfi._before_update.append(hash_mfi_password_on_update)


############################################################
# 2. b2c / BORROWER TABLE (Enhanced with Traffic Light)
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

    # Traffic Light System Fields
    Field('traffic_light_status', 'string', default='YELLOW',
          comment='GREEN, YELLOW, or RED based on visibility'),
    Field('visibility_score', 'integer', default=0,
          comment='0-7 points: Payment(0-3) + Communication(0-2) + Proactivity(0-2)'),
    Field('last_status_update', 'datetime', default=request.now),
    Field('status_notes', 'text',
          comment='Internal notes about status changes'),

    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(real_name)s'
)

db.b2c.username.requires  = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'b2c.username')]
db.b2c.real_name.requires = IS_NOT_EMPTY()
db.b2c.email.requires = IS_EMPTY_OR(IS_EMAIL())
db.b2c.traffic_light_status.requires = IS_IN_SET(['GREEN', 'YELLOW', 'RED'])

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
db.b2c.traffic_light_status.label = 'Traffic Light Status'
db.b2c.visibility_score.label = 'Visibility Score (0-7)'
db.b2c.last_status_update.label = 'Last Status Update'
db.b2c.status_notes.label = 'Status Notes'


# Validate MFI B2C limit
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
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

def hash_b2c_password_on_update(s, fields):
    """Hash B2C password on update if provided"""
    if 'password_hash' in fields and fields['password_hash']:
        pwd_plain = fields['password_hash']
        if not pwd_plain.startswith('$2b$') and not pwd_plain.startswith('$2a$'):
            hashed = bcrypt.hashpw(pwd_plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            fields['password_hash'] = hashed

db.b2c._before_insert.append(hash_b2c_password_on_insert)
db.b2c._before_update.append(hash_b2c_password_on_update)


############################################################
# 3. PAYMENT TRACKING (NEW - for Traffic Light calculations)
############################################################

db.define_table(
    'b2c_payment',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('amount', 'double', notnull=True),
    Field('due_date', 'date', notnull=True),
    Field('paid_date', 'date'),
    Field('days_late', 'integer', default=0,
          comment='Negative if early, 0 if on-time, positive if late'),
    Field('payment_method', 'string'),
    Field('notes', 'text'),
    Field('created_on', 'datetime', default=request.now),
    format='Payment %(amount)s on %(paid_date)s'
)

db.b2c_payment.amount.requires = IS_NOT_EMPTY()
db.b2c_payment.due_date.requires = IS_NOT_EMPTY()
db.b2c_payment.b2c_id.label = 'B2C Account'
db.b2c_payment.amount.label = 'Payment Amount'
db.b2c_payment.due_date.label = 'Due Date'
db.b2c_payment.paid_date.label = 'Paid Date'
db.b2c_payment.days_late.label = 'Days Late'
db.b2c_payment.payment_method.label = 'Payment Method'
db.b2c_payment.notes.label = 'Notes'


# Calculate days late when payment is recorded
def calculate_days_late(fields):
    """Auto-calculate days late based on due_date and paid_date"""
    if 'paid_date' in fields and fields['paid_date'] and 'due_date' in fields:
        due = fields['due_date']
        paid = fields['paid_date']
        if isinstance(due, str):
            due = datetime.strptime(due, '%Y-%m-%d').date()
        if isinstance(paid, str):
            paid = datetime.strptime(paid, '%Y-%m-%d').date()
        fields['days_late'] = (paid - due).days

db.b2c_payment._before_insert.append(calculate_days_late)
db.b2c_payment._before_update.append(lambda s, fields: calculate_days_late(fields))


############################################################
# 4. COMMUNICATION LOG (NEW - for Traffic Light calculations)
############################################################

db.define_table(
    'b2c_communication',
    Field('b2c_id', 'reference b2c', notnull=True),
    Field('initiated_by', 'string', notnull=True,
          comment='MFI or BORROWER'),
    Field('communication_type', 'string',
          comment='CALL, TEXT, VISIT, EMAIL, PROACTIVE_WARNING'),
    Field('response_time_hours', 'integer',
          comment='Hours until borrower responded (if MFI initiated)'),
    Field('is_proactive', 'boolean', default=False,
          comment='Did borrower warn of problem before it escalated?'),
    Field('message_summary', 'text'),
    Field('communication_date', 'datetime', default=request.now),
    format='%(communication_type)s on %(communication_date)s'
)

db.b2c_communication.initiated_by.requires = IS_IN_SET(['MFI', 'BORROWER'])
db.b2c_communication.communication_type.requires = IS_IN_SET([
    'CALL', 'TEXT', 'VISIT', 'EMAIL', 'PROACTIVE_WARNING'
])
db.b2c_communication.b2c_id.label = 'B2C Account'
db.b2c_communication.initiated_by.label = 'Initiated By'
db.b2c_communication.communication_type.label = 'Type'
db.b2c_communication.response_time_hours.label = 'Response Time (hours)'
db.b2c_communication.is_proactive.label = 'Proactive Communication?'
db.b2c_communication.message_summary.label = 'Summary'
db.b2c_communication.communication_date.label = 'Date'


############################################################
# 5. TIMELINE MESSAGES
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
# 6. URGENT MESSAGE (single entry per b2c)
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
# 7. VIEW LOGS
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


############################################################
# TRAFFIC LIGHT CLASSIFICATION FUNCTIONS
############################################################

def calculate_payment_score(b2c_id):
    """
    Step 1: Payment Predictability Score (0-3 points)
    - 3 points: 5-6 of last 6 payments on-time OR consistent pattern
    - 0 points: 4 or fewer on-time AND no pattern
    """
    # Get last 6 payments
    payments = db(db.b2c_payment.b2c_id == b2c_id).select(
        orderby=~db.b2c_payment.due_date,
        limitby=(0, 6)
    )
    
    if len(payments) < 3:
        return 1  # Too few payments, give neutral score
    
    on_time_count = sum(1 for p in payments if p.days_late <= 0)
    
    # Check for consistent delay pattern
    if len(payments) >= 4:
        delays = [p.days_late for p in payments if p.days_late is not None]
        if delays:
            avg_delay = sum(delays) / len(delays)
            # Pattern is consistent if standard deviation is low
            variance = sum((d - avg_delay) ** 2 for d in delays) / len(delays)
            is_consistent_pattern = variance < 4  # Within 2 days variation
        else:
            is_consistent_pattern = False
    else:
        is_consistent_pattern = False
    
    # Scoring logic
    if on_time_count >= 5 or (on_time_count >= 4 and is_consistent_pattern):
        return 3  # Excellent
    elif on_time_count >= 4:
        return 2  # Good
    elif on_time_count >= 2 or is_consistent_pattern:
        return 1  # Fair
    else:
        return 0  # Poor predictability


def calculate_communication_score(b2c_id):
    """
    Step 2: Communication Responsiveness Score (0-2 points)
    - 2 points: Consistently responds within 48 hours
    - 0 points: Often doesn't respond or takes >48 hours
    """
    # Get last 5 MFI-initiated communications
    comms = db(
        (db.b2c_communication.b2c_id == b2c_id) &
        (db.b2c_communication.initiated_by == 'MFI')
    ).select(
        orderby=~db.b2c_communication.communication_date,
        limitby=(0, 5)
    )
    
    if len(comms) == 0:
        return 1  # No data, neutral score
    
    responses_within_48h = sum(
        1 for c in comms 
        if c.response_time_hours is not None and c.response_time_hours <= 48
    )
    
    response_rate = responses_within_48h / len(comms)
    
    if response_rate >= 0.8:  # 80%+ within 48h
        return 2
    elif response_rate >= 0.5:  # 50%+ within 48h
        return 1
    else:
        return 0


def calculate_proactivity_score(b2c_id):
    """
    Step 3: Proactive Context Sharing Score (0-2 points)
    - 2 points: Warns of problems before they escalate
    - 1 point: Explains when asked
    - 0 points: Provides no explanation
    """
    # Look for proactive communications in last 90 days
    ninety_days_ago = datetime.now() - timedelta(days=90)
    
    proactive_comms = db(
        (db.b2c_communication.b2c_id == b2c_id) &
        (db.b2c_communication.is_proactive == True) &
        (db.b2c_communication.communication_date >= ninety_days_ago)
    ).count()
    
    if proactive_comms >= 2:
        return 2  # Regular proactive communication
    elif proactive_comms >= 1:
        return 1  # Some proactive communication
    else:
        # Check if they at least respond with explanations
        recent_comms = db(
            (db.b2c_communication.b2c_id == b2c_id) &
            (db.b2c_communication.initiated_by == 'BORROWER') &
            (db.b2c_communication.communication_date >= ninety_days_ago)
        ).count()
        
        if recent_comms >= 2:
            return 1  # Responsive when asked
        else:
            return 0  # No proactive or responsive communication


def calculate_traffic_light_status(b2c_id):
    """
    Calculate complete traffic light status based on three-question formula
    Returns: (status, score, breakdown)
    """
    payment_score = calculate_payment_score(b2c_id)
    communication_score = calculate_communication_score(b2c_id)
    proactivity_score = calculate_proactivity_score(b2c_id)
    
    total_score = payment_score + communication_score + proactivity_score
    
    # Classification logic
    if total_score >= 6:
        status = 'GREEN'
    elif total_score >= 4:
        status = 'YELLOW'
    else:
        status = 'RED'
    
    breakdown = {
        'payment': payment_score,
        'communication': communication_score,
        'proactivity': proactivity_score,
        'total': total_score
    }
    
    return status, total_score, breakdown


def update_borrower_traffic_light(b2c_id, notes=None):
    """
    Update a borrower's traffic light status
    Call this after recording payments or communications
    """
    status, score, breakdown = calculate_traffic_light_status(b2c_id)
    
    borrower = db.b2c(b2c_id)
    if borrower:
        old_status = borrower.traffic_light_status
        
        # Prepare status notes
        status_note = "Score breakdown: Payment=%d, Communication=%d, Proactivity=%d (Total: %d/7)" % (
            breakdown['payment'], breakdown['communication'], 
            breakdown['proactivity'], breakdown['total']
        )
        if notes:
            status_note += " | " + notes
        if old_status != status:
            status_note = "Changed from %s to %s. %s" % (old_status, status, status_note)
        
        # Update the borrower record
        borrower.update_record(
            traffic_light_status=status,
            visibility_score=score,
            last_status_update=datetime.now(),
            status_notes=status_note
        )
        
        return True, status, score
    
    return False, None, None


# Helper function to get protocol for a borrower
def get_borrower_protocol(b2c_id):
    """
    Returns the operational protocol for a borrower based on their status
    """
    borrower = db.b2c(b2c_id)
    if not borrower:
        return None
    
    protocols = {
        'GREEN': {
            'grace_period_days': 7,
            'first_contact': 'TEXT',
            'tone': 'How can we help?',
            'loan_increase_max': 1.5,
            'meeting_frequency': 'QUARTERLY'
        },
        'YELLOW': {
            'grace_period_days': 3,
            'first_contact': 'CALL',
            'tone': 'Friendly check-in, standard support',
            'loan_increase_max': 1.2,
            'meeting_frequency': 'MONTHLY'
        },
        'RED': {
            'grace_period_days': 1,
            'first_contact': 'VISIT',
            'tone': 'We want to understand and help',
            'loan_increase_max': 0.8,
            'meeting_frequency': 'WEEKLY'
        }
    }
    
    return protocols.get(borrower.traffic_light_status, protocols['YELLOW'])


############################################################
# 8. FLYER TABLES (Replace this section in db.py)
############################################################

db.define_table('flyer',
    Field('b2c_id', 'reference b2c', notnull=True),  # REMOVED writable=False
    Field('title', 'string', length=255, notnull=True, default='Untitled Flyer'),
    Field('thecontent', 'text', notnull=True, default='# Your content here\n\nStart writing...'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    Field('is_public', 'boolean', default=True),
    Field('view_count', 'integer', default=0, writable=False),
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
db.flyer.b2c_id.label = 'Borrower'
db.flyer.view_count.label = 'Views'
db.flyer.created_on.label = 'Created On'
db.flyer.updated_on.label = 'Updated On'


# Flyer view tracking table
db.define_table('flyer_view',
    Field('flyer_id', 'reference flyer', notnull=True),
    Field('viewer_ip', 'string'),
    Field('viewed_on', 'datetime', default=request.now)
)

db.flyer_view.flyer_id.label = 'Flyer'
db.flyer_view.viewer_ip.label = 'Viewer IP'
db.flyer_view.viewed_on.label = 'Viewed On'