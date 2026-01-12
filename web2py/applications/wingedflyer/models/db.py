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
# 0. CONTEXT SYSTEM
############################################################
# A context represents the operational domain (microfinance, coaching, internal org)
# in which the mechanics are applied. This allows the same system to serve
# different use cases with different language and rules, without duplicating logic.

db.define_table(
    'context',
    Field('context_key', 'string', unique=True, notnull=True,
          comment='Unique identifier for this context (e.g. "microfinance", "coaching", "internal_org")'),
    Field('display_name', 'string', notnull=True,
          comment='Human-readable name for this context'),
    Field('description', 'text',
          comment='Description of what this context represents'),
    Field('is_active', 'boolean', default=True,
          comment='Whether this context is currently active'),
    Field('config_json', 'json',
          comment='Context-specific configuration (e.g. participant limits, payment cycles)'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    format='%(display_name)s'
)

db.context.context_key.requires = [
    IS_NOT_EMPTY(),
    IS_NOT_IN_DB(db, 'context.context_key'),
    IS_SLUG(error_message='Must be lowercase alphanumeric with underscores only')
]
db.context.display_name.requires = IS_NOT_EMPTY()

############################################################
# 0.1 FEATURE LANGUAGE MAPPING
############################################################
# This table maps mechanic-level feature keys to context-specific language.
# It allows the same feature to be displayed differently across contexts
# without hardcoding strings in views or controllers.
#
# Example usage:
# - feature_key='instruction', context='microfinance', variant='label' → 'Bank Message'
# - feature_key='instruction', context='coaching', variant='label' → 'Coach Check-in'
# - feature_key='participant', context='microfinance', variant='label_plural' → 'Borrowers'

db.define_table(
    'feature_language',
    Field('context_id', 'reference context', notnull=True,
          label=T('Context'),
          requires=IS_IN_DB(db, 'context.id', '%(display_name)s')),
    Field('feature_key', 'string', notnull=True),
    Field('language_variant', 'string', notnull=True),
    Field('language_value', 'string', notnull=True),
    # ... created_on, updated_on ...
)

# Apply these after the table is defined
db.feature_language.language_variant.requires = IS_IN_SET(['label', 'label_plural', 'description', 'call_to_action'])
db.feature_language.feature_key.requires = IS_IN_SET(['participant', 'responsible', 'instruction', 'execution_signal'])

# Index for fast lookups by context and feature
db.executesql('CREATE INDEX IF NOT EXISTS idx_feature_language_lookup ON feature_language(context_id, feature_key, language_variant);')

############################################################
# 1. RESPONSIBLE TABLE (formerly MFI)
############################################################
# Represents the entity responsible for managing participants.
# In microfinance: an MFI
# In coaching: a coaching organization
# In internal org: a department or team lead
#
# MIGRATION NOTE: Rename mfi → responsible, preserve all fields

db.define_table(
    'responsible',
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this responsible entity belongs to'),
    Field('username', 'string', unique=True, notnull=True),
    Field('password_hash', 'password', readable=False, writable=True),
    Field('name', 'string', notnull=True,
          comment='Display name for this responsible entity'),
    Field('telephone', 'string'),
    Field('email', 'string'),
    Field('contact_person', 'string',
          comment='Primary contact within this organization'),
    Field('country', 'string'),
    Field('notes', 'text'),
    Field('participant_limit', 'integer', default=0,
          comment='Maximum number of participants this responsible entity can manage. '
                  'Renamed from b2c_accounts - mechanic is context-neutral'),
    Field('created_on', 'datetime', default=request.now, writable=False),
    format='%(name)s'
)

# Validators
db.responsible.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'responsible.username')]
db.responsible.name.requires = IS_NOT_EMPTY()
db.responsible.email.requires = IS_EMPTY_OR(IS_EMAIL())
db.responsible.participant_limit.requires = IS_INT_IN_RANGE(0, 10000)

# Password Hashing Logic (preserved from original)
def hash_password(pwd):
    """Hash password using bcrypt if not already hashed"""
    if pwd and not pwd.startswith('$2b$'):
        return bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    return pwd

def encrypt_responsible_password(row):
    """Before insert: hash the password"""
    if 'password_hash' in row:
        row['password_hash'] = hash_password(row['password_hash'])

db.responsible._before_insert.append(encrypt_responsible_password)
db.responsible._before_update.append(lambda s, f: f.__setitem__('password_hash', hash_password(f.get('password_hash'))))

############################################################
# 2. PARTICIPANT TABLE (formerly B2C/BORROWER)
############################################################
# Represents individuals being tracked/supported by the responsible entity.
# In microfinance: borrowers
# In coaching: clients/coachees
# In internal org: team members
#
# MIGRATION NOTE: Rename b2c → participant
# Domain-specific fields (amount_borrowed, amount_repaid_b2c_reported) are preserved
# but should be understood as context-specific metrics that can be repurposed:
# - In coaching: could represent "goals achieved" vs "goals set"
# - In internal org: could represent "tasks completed" vs "tasks assigned"
#
# FUTURE CONTEXT-AWARE LOGIC:
# These fields should eventually be moved to a flexible metrics table
# that allows different contexts to define their own tracked values

db.define_table(
    'participant',
    Field('responsible_id', 'reference responsible', notnull=True,
          comment='Which responsible entity manages this participant'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this participant belongs to'),
    Field('username', 'string', unique=True),
    Field('password_hash', 'string'),
    Field('real_name', 'string'),
    Field('address', 'string'),
    Field('telephone', 'string'),
    Field('email', 'string'),
    Field('social_media', 'string'),
    
    # CONTEXT-SPECIFIC METRICS (annotated for future refactoring)
    # TODO: Move these to a generic participant_metrics table with flexible schema
    # Current microfinance semantics preserved for migration compatibility
    Field('amount_borrowed', 'double', default=0,
          comment='CONTEXT-DEPENDENT: MFI=borrowed amount, Coaching=goal target, Internal=task allocation'),
    Field('amount_repaid_b2c_reported', 'double', default=0,
          comment='CONTEXT-DEPENDENT: MFI=repaid amount, Coaching=goal completion, Internal=task completion'),
    
    Field('created_on', 'datetime', default=request.now, writable=False),
    Field('updated_on', 'datetime', update=request.now, writable=False),
    format='%(real_name)s'
)

db.participant.username.requires = [IS_NOT_EMPTY(), IS_NOT_IN_DB(db, 'participant.username')]
db.participant.real_name.requires = IS_NOT_EMPTY()
db.participant.email.requires = IS_EMPTY_OR(IS_EMAIL())

def validate_participant_limit(fields):
    """
    Enforce participant limit for responsible entity.
    
    CONTEXT-AWARE ANNOTATION:
    This limit validation is mechanically sound across contexts:
    - MFI: borrower account limits
    - Coaching: client capacity limits
    - Internal org: team size limits
    
    The mechanic stays the same; only the language changes.
    Future: limit rules could be stored in context.config_json for per-context customization
    """
    responsible_id = fields.get('responsible_id')
    if responsible_id:
        responsible = db.responsible(responsible_id)
        current_count = db(db.participant.responsible_id == responsible_id).count()
        if current_count >= responsible.participant_limit:
            # TODO: Make error message context-aware using feature_language table
            raise ValueError('Participant limit reached for this responsible entity')

db.participant._before_insert.append(validate_participant_limit)

def encrypt_participant_password(fields):
    """Before insert: hash the password"""
    if fields.get('password_hash'):
        fields['password_hash'] = hash_password(fields['password_hash'])

db.participant._before_insert.append(encrypt_participant_password)

############################################################
# 3. WORK ACTIVITY
############################################################
# Represents the activity/work being tracked for a participant.
# In microfinance: business activity (e.g. "street vending")
# In coaching: goal area (e.g. "fitness routine")
# In internal org: project or responsibility (e.g. "Q1 deliverable")
#
# MIGRATION NOTE: Table name preserved as it's already mechanic-neutral
# Added context_id for multi-context support

db.define_table(
    'work_activity',
    Field('participant_id', 'reference participant', ondelete='CASCADE', notnull=True,
          comment='Which participant this activity belongs to (renamed from b2c_id)'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this activity exists in'),
    Field('activity_name', 'string', notnull=True,
          comment='Name of the activity/goal/project'),
    Field('description', 'text'),
    Field('is_active', 'boolean', default=True),
    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(activity_name)s'
)

############################################################
# 4. EXECUTION SIGNAL (formerly DAILY_SIGNAL)
############################################################
# Represents a participant's self-reported signal about work execution.
# In microfinance: daily business performance signal
# In coaching: daily progress check-in
# In internal org: daily standup update
#
# MIGRATION NOTE: Rename daily_signal → execution_signal
# The "outcome" field is mechanically sound across contexts:
# BETTER/AS_EXPECTED/WORSE works for business, goals, and task progress

db.define_table(
    'execution_signal',
    Field('participant_id', 'reference participant', notnull=True,
          comment='Which participant sent this signal (renamed from b2c_id)'),
    Field('work_activity_id', 'reference work_activity', notnull=True,
          comment='Which activity this signal relates to'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this signal exists in'),
    Field('signal_date', 'date', notnull=True, default=request.now,
          comment='When this signal was recorded'),
    Field('outcome', 'string', notnull=True,
          comment='How execution compared to expectations: BETTER/AS_EXPECTED/WORSE'),
    Field('note', 'text',
          comment='Optional participant note about this signal'),
    Field('created_on', 'datetime', default=request.now)
)

db.execution_signal.outcome.requires = IS_IN_SET(['BETTER', 'AS_EXPECTED', 'WORSE'])

############################################################
# 5. PAYMENT TRACKING (Commented - Context-Specific)
############################################################
# DESIGN NOTE: Payment tracking is currently microfinance-specific.
# For multi-context support, this should become a generic "commitment_tracking" table
# where commitments can represent:
# - MFI: repayment schedules
# - Coaching: milestone deadlines
# - Internal org: deliverable due dates
#
# The mechanic is the same: track expected vs actual completion of commitments,
# measure lateness, record completion method.
#
# FUTURE REFACTORING:
# - Rename to 'commitment_tracking'
# - Add context_id
# - Rename 'amount' → 'commitment_value' (can be monetary, numerical, or boolean)
# - Rename 'payment_method' → 'completion_method'
# - Keep days_late calculation (universally applicable)

'''
db.define_table(
    'b2c_payment',
    Field('participant_id', 'reference participant', notnull=True),  # Renamed from b2c_id
    Field('context_id', 'reference context', notnull=True),  # Added for multi-context
    Field('amount', 'double', notnull=True),
    Field('due_date', 'date', notnull=True),
    Field('paid_date', 'date'),
    Field('days_late', 'integer', default=0),
    Field('payment_method', 'string'),
    Field('notes', 'text'),
    Field('created_on', 'datetime', default=request.now)
)

def calculate_days_late(fields):
    """
    Calculate days late for commitment completion.
    
    CONTEXT-AWARE ANNOTATION:
    This mechanic is universal - any context cares about:
    - What was expected (due_date)
    - What actually happened (paid_date / completion_date)
    - How late it was (days_late)
    
    Language changes per context but logic stays identical.
    """
    paid = fields.get('paid_date')
    due = fields.get('due_date')
    if paid and due:
        if isinstance(due, str): due = datetime.strptime(due, '%Y-%m-%d').date()
        if isinstance(paid, str): paid = datetime.strptime(paid, '%Y-%m-%d').date()
        
        delta = (paid - due).days
        fields['days_late'] = delta if delta > 0 else 0

db.b2c_payment._before_insert.append(calculate_days_late)
db.b2c_payment._before_update.append(lambda s, f: calculate_days_late(f))
'''

############################################################
# 6. INSTRUCTION SYSTEM (formerly MESSAGING)
############################################################
# Represents instructions/messages sent from responsible entities to participants.
# In microfinance: bank messages or payment reminders
# In coaching: coach check-ins or motivational messages
# In internal org: leadership signals or team announcements
#
# MIGRATION NOTE: Rename mfi_info_flyer → instruction

db.define_table(
    'instruction',
    Field('responsible_id', 'reference responsible', notnull=True,
          comment='Which responsible entity sent this instruction (renamed from mfi_id)'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this instruction exists in'),
    Field('subject', 'string', notnull=True,
          comment='Subject line for this instruction'),
    Field('instruction_text', 'text', notnull=True,
          comment='Main content of the instruction (renamed from info_flyer_text)'),
    Field('response_template', 'string', default='NONE',
          comment='Expected response format (NONE, YES_NO, TEXT, etc.)'),
    Field('created_on', 'datetime', default=request.now),
    Field('sent_by', 'string',
          comment='Username or identifier of who sent this instruction'),
    format='%(subject)s'
)

db.define_table(
    'instruction_recipient',
    Field('instruction_id', 'reference instruction', notnull=True,
          comment='Which instruction this record tracks (renamed from info_flyer_id)'),
    Field('participant_id', 'reference participant', notnull=True,
          comment='Which participant received this instruction (renamed from b2c_id)'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this recipient relationship exists in'),
    Field('is_read', 'boolean', default=False),
    Field('read_on', 'datetime'),
    Field('response', 'string'),
    Field('responded_on', 'datetime'),
    Field('created_on', 'datetime', default=request.now)
)

############################################################
# 7. FLYER TABLES (Public Content Publishing)
############################################################
# Represents public content published by participants (e.g. business flyers, portfolios).
# In microfinance: business advertisements or product catalogs
# In coaching: client success stories or testimonials
# In internal org: project showcases or team updates
#
# MIGRATION NOTE: Table names preserved as "flyer" is reasonably context-neutral
# Added context_id for multi-context support

db.define_table('flyer',
    Field('participant_id', 'reference participant', notnull=True,
          comment='Which participant created this flyer (renamed from b2c_id)'),
    Field('context_id', 'reference context', notnull=True,
          comment='Which operational context this flyer exists in'),
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
# 8. HELPER FUNCTIONS
############################################################

def send_instruction_to_participants(responsible_id, participant_ids, subject, instruction_text, response_template, sent_by, context_id):
    """
    Send an instruction from a responsible entity to multiple participants.
    
    CONTEXT-AWARE ANNOTATION:
    This mechanic is universal across contexts:
    - Create one instruction record
    - Link it to N participants
    - Track read/response status per participant
    
    The only context-specific aspect is how this appears in UI language,
    which should be resolved via the feature_language table.
    
    Args:
        responsible_id: ID of the responsible entity sending the instruction (renamed from mfi_id)
        participant_ids: List of participant IDs to receive this instruction (renamed from b2c_ids)
        subject: Subject line
        instruction_text: Main content (renamed from info_flyer_text)
        response_template: Expected response format
        sent_by: Username of sender
        context_id: Which context this instruction belongs to
    
    Returns:
        instruction_id: ID of the created instruction record
    """
    # 1. Insert the main instruction record
    instruction_id = db.instruction.insert(
        responsible_id=responsible_id,
        context_id=context_id,
        subject=subject,
        instruction_text=instruction_text,
        response_template=response_template,
        sent_by=sent_by
    )
    
    # 2. Insert a recipient record for every selected participant
    for p_id in participant_ids:
        db.instruction_recipient.insert(
            instruction_id=instruction_id,
            participant_id=p_id,
            context_id=context_id,
            is_read=False
        )
    
    return instruction_id
