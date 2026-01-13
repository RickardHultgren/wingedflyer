# -*- coding: utf-8 -*-
"""
Responsible Entity Portal Controller (formerly MFI)
Context-aware controller for managing participants across multiple domains
(microfinance, coaching, internal organizations)
"""

import bcrypt
from datetime import datetime, timedelta


# ---------------------------------------------------------------------
# CONTEXT HELPER FUNCTIONS
# ---------------------------------------------------------------------

def get_language(context_id, feature_key, variant='label'):
    """
    Retrieve context-specific language for a feature.
    
    This allows the same mechanic to display different text across contexts:
    - feature_key='instruction', context='microfinance', variant='label' → 'Bank Message'
    - feature_key='instruction', context='coaching', variant='label' → 'Coach Check-in'
    
    Args:
        context_id: The context ID to look up
        feature_key: The mechanic identifier (e.g. 'participant', 'instruction')
        variant: The type of text to retrieve (e.g. 'label', 'label_plural', 'description')
    
    Returns:
        The language string, or a fallback based on feature_key if not found
    """
    lang = db(
        (db.feature_language.context_id == context_id) &
        (db.feature_language.feature_key == feature_key) &
        (db.feature_language.language_variant == variant)
    ).select(db.feature_language.language_value).first()
    
    if lang:
        return lang.language_value
    
    # Fallback to mechanic name if no language mapping exists
    fallback_map = {
        'participant': 'Participant',
        'participant_plural': 'Participants',
        'instruction': 'Instruction',
        'execution_signal': 'Execution Signal',
        'work_activity': 'Work Activity',
        'responsible': 'Responsible Entity'
    }
    return fallback_map.get(feature_key, feature_key.replace('_', ' ').title())


# ---------------------------------------------------------------------
# RESPONSIBLE LOGIN (formerly MFI LOGIN)
# ---------------------------------------------------------------------

def login():
    """Login screen for responsible entities"""
    if session.responsible_id:
        redirect(URL('dashboard'))

    form = FORM(
        DIV(
            LABEL("Username"),
            INPUT(_name='username', _class='form-control', requires=IS_NOT_EMPTY()),
            LABEL("Password", _style="margin-top:10px"),
            INPUT(_name='password', _type='password', _class='form-control',
                  requires=IS_NOT_EMPTY()),
            INPUT(_type='submit', _value='Login', _class='btn btn-primary',
                  _style="margin-top:15px"),
            _class='form-group'
        )
    )

    if form.accepts(request, session):
        username = form.vars.username
        password = form.vars.password
        user = db(db.responsible.username == username).select().first()

        if user and user.password_hash:
            try:
                password_bytes = password.encode('utf-8')
                hash_bytes = (user.password_hash.encode('utf-8')
                            if isinstance(user.password_hash, str)
                            else user.password_hash)

                if bcrypt.checkpw(password_bytes, hash_bytes):
                    session.responsible_id = user.id
                    session.responsible_name = user.name
                    session.responsible_username = user.username
                    session.context_id = user.context_id  # Store context in session
                    
                    # Load context display name for UI
                    context = db.context(user.context_id)
                    session.context_name = context.display_name if context else "Unknown"
                    
                    redirect(URL('dashboard'))
                else:
                    response.flash = "Invalid username or password"
            except Exception as e:
                response.flash = "Login error. Please contact administrator."
                print("Login error: %s" % str(e))
            redirect(URL(args=request.args, vars=request.vars))
        else:
            response.flash = "Invalid username or password"
    elif form.errors:
        response.flash = "Please fill in all fields"

    return dict(form=form)


def logout():
    """Clear session and redirect to login"""
    session.clear()
    redirect(URL('login'))


# ---------------------------------------------------------------------
# REQUIRE LOGIN DECORATOR
# ---------------------------------------------------------------------

def responsible_requires_login(func):
    """Decorator to protect responsible-only pages"""
    def wrapper(*args, **kwargs):
        if not session.responsible_id:
            session.flash = "Please log in first"
            redirect(URL('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------

@responsible_requires_login
def dashboard():
    responsible_record = db.responsible(session.responsible_id)
    if not responsible_record:
        session.clear()
        redirect(URL('login'))

    # Get context-specific language
    # Ensure get_language is defined in your models or here!
    participant_label = get_language(session.context_id, 'participant', 'label')
    participant_label_plural = get_language(session.context_id, 'participant', 'label_plural')

    participants = db(
        (db.participant.responsible_id == session.responsible_id) &
        (db.participant.context_id == session.context_id)
    ).select(orderby=db.participant.real_name)

    participant_data = []
    now = datetime.now()
    seven_days_ago = (now - timedelta(days=7)).date()

    for p in participants:
        # 1. Recent Worse Signals
        recent_worse = db(
            (db.execution_signal.participant_id == p.id) &
            (db.execution_signal.outcome == 'WORSE') &
            (db.execution_signal.signal_date >= seven_days_ago)
        ).count()

        # 2. Unread Instructions
        unread_instructions = db(
            (db.instruction_recipient.participant_id == p.id) &
            (db.instruction_recipient.is_read == False)
        ).count()

        # 3. Pending Responses (Fixed Join Query)
        pending_responses = db(
            (db.instruction_recipient.participant_id == p.id) &
            (db.instruction_recipient.response == None) &
            (db.instruction.id == db.instruction_recipient.instruction_id) &
            (db.instruction.response_template != 'NONE')
        ).count()

        participant_data.append({
            'participant': p,
            'recent_worse_signals': recent_worse,
            'unread_instructions': unread_instructions,
            'pending_responses': pending_responses,
            'needs_attention': recent_worse > 2 or pending_responses > 0
        })
    
    # Calculate if they can create more participants
    current_count = len(participants)
    can_create = current_count < (responsible_record.participant_limit or 0)

    return dict(
        responsible=session.responsible_name,
        context_name=session.context_name,
        participant_data=participant_data,
        can_create=can_create,
        participant_label=participant_label,
        participant_label_plural=participant_label_plural
    )

    
# ---------------------------------------------------------------------
# CREATE NEW PARTICIPANT (formerly CREATE B2C)
# ---------------------------------------------------------------------

@responsible_requires_login
def create_participant():
    responsible_record = db.responsible(session.responsible_id)
    current_count = db(
        (db.participant.responsible_id == session.responsible_id) &
        (db.participant.context_id == session.context_id)
    ).count()

    # Define BOTH labels at the start so they are ALWAYS available
    participant_label = get_language(session.context_id, 'participant', 'label')
    participant_label_plural = get_language(session.context_id, 'participant', 'label_plural')

    if current_count >= responsible_record.participant_limit:
        session.flash = "Maximum %s limit reached (%d)" % (participant_label_plural, responsible_record.participant_limit)
        redirect(URL('dashboard'))

    db.participant.responsible_id.writable = False
    db.participant.responsible_id.readable = False
    db.participant.context_id.writable = False
    db.participant.context_id.readable = False

    form = SQLFORM(db.participant)
    form.vars.responsible_id = session.responsible_id
    form.vars.context_id = session.context_id

    if form.process().accepted:
        session.flash = "%s account created successfully" % participant_label
        redirect(URL('participant', args=[form.vars.id]))

    return dict(
        form=form,
        current_count=current_count,
        max_accounts=responsible_record.participant_limit,
        participant_label=participant_label,
        participant_label_plural=participant_label_plural  # <--- MUST BE INCLUDED HERE
    )

# ---------------------------------------------------------------------
# INSTRUCTION COMPOSER (formerly COMPOSE INFO_FLYER)
# ---------------------------------------------------------------------

@responsible_requires_login
def compose_instruction():
    """
    Compose and send an instruction to one or more participants.
    
    CONTEXT-AWARE ANNOTATION:
    The instruction mechanic is universal:
    - Select recipients
    - Write subject and content
    - Define response template
    - Track delivery and responses
    
    Only the UI language changes per context.
    """
    participants = db(
        (db.participant.responsible_id == session.responsible_id) &
        (db.participant.context_id == session.context_id)
    ).select(orderby=db.participant.real_name)

    recipient_arg = request.args(0) if request.args else None
    preselected_recipients = []
    if recipient_arg:
        preselected_recipients = [int(recipient_arg)]

    # Get context-specific language
    participant_label_plural = get_language(session.context_id, 'participant', 'label_plural')
    instruction_label = get_language(session.context_id, 'instruction', 'label')

    form = SQLFORM.factory(
        Field('recipients', 'list:integer',
              label="Recipients",
              requires=IS_IN_SET(
                  [(p.id, "%s (%s)" % (p.real_name, p.username)) for p in participants],
                  multiple=True,
                  error_message="Please select at least one recipient"
              ),
              widget=SQLFORM.widgets.checkboxes.widget,
              comment="Select one or more %s to send this %s to" % (
                  participant_label_plural.lower(),
                  instruction_label.lower()
              )),
        Field('subject', 'string', label="Subject",
              requires=IS_NOT_EMPTY(error_message="Subject is required")),
        Field('instruction_text', 'text', label="%s Content" % instruction_label,
              requires=IS_NOT_EMPTY(error_message="Content is required")),
        Field('response_template', 'string', label="Response Type",
              requires=IS_IN_SET([
                  ('NONE', 'No Response Needed'),
                  ('CHECKBOX_READ', 'Mark as Read Checkbox'),
                  ('ACCEPT_DECLINE', 'Accept/Decline Buttons'),
                  ('TEXT_RESPONSE', 'Text Response Field')
              ]),
              default='NONE'),
        submit_button="Send %s" % instruction_label
    )

    if form.process().accepted:
        # Use the helper function from db.py
        instruction_id = send_instruction_to_participants(
            responsible_id=session.responsible_id,
            participant_ids=form.vars.recipients,
            subject=form.vars.subject,
            instruction_text=form.vars.instruction_text,
            response_template=form.vars.response_template,
            sent_by=session.responsible_username,
            context_id=session.context_id
        )

        session.flash = "%s sent successfully" % instruction_label
        redirect(URL('sent_instructions'))

    return dict(
        form=form,
        participants=participants,
        instruction_label=instruction_label,
        participant_label_plural=participant_label_plural
    )


# ---------------------------------------------------------------------
# VIEW SENT INSTRUCTIONS (formerly SENT INFO_FLYERS)
# ---------------------------------------------------------------------

@responsible_requires_login
def sent_instructions():
    """View all instructions sent by this responsible entity"""
    
    instructions = db(
        (db.instruction.responsible_id == session.responsible_id) &
        (db.instruction.context_id == session.context_id)
    ).select(orderby=~db.instruction.created_on)

    # For each instruction, get recipient statistics
    instruction_data = []
    for msg in instructions:
        recipients = db(db.instruction_recipient.instruction_id == msg.id).select()

        total_recipients = len(recipients)
        read_count = sum(1 for r in recipients if r.is_read)
        responded_count = sum(1 for r in recipients if r.response)

        instruction_data.append({
            'instruction': msg,
            'total_recipients': total_recipients,
            'read_count': read_count,
            'responded_count': responded_count,
            'recipients': recipients
        })

    instruction_label = get_language(session.context_id, 'instruction', 'label')
    instruction_label_plural = get_language(session.context_id, 'instruction', 'label_plural')

    return dict(
        instruction_data=instruction_data,
        instruction_label=instruction_label,
        instruction_label_plural=instruction_label_plural
    )


# ---------------------------------------------------------------------
# VIEW INSTRUCTION DETAILS AND RESPONSES
# ---------------------------------------------------------------------

@responsible_requires_login
def instruction_details():
    """View details of a specific instruction and all responses"""
    instruction_id = request.args(0, cast=int)
    if not instruction_id:
        session.flash = "Invalid instruction"
        redirect(URL('sent_instructions'))

    instruction = db.instruction(instruction_id)
    if not instruction or instruction.responsible_id != session.responsible_id:
        session.flash = "Instruction not found"
        redirect(URL('sent_instructions'))

    # Get all recipients and their responses
    recipients = db(db.instruction_recipient.instruction_id == instruction_id).select(
        db.instruction_recipient.ALL,
        db.participant.ALL,
        left=db.participant.on(db.instruction_recipient.participant_id == db.participant.id),
        orderby=db.participant.real_name
    )

    instruction_label = get_language(session.context_id, 'instruction', 'label')

    return dict(
        instruction=instruction,
        recipients=recipients,
        instruction_label=instruction_label
    )


# ---------------------------------------------------------------------
# VIEW SINGLE PARTICIPANT (formerly B2C)
# ---------------------------------------------------------------------

@responsible_requires_login
def participant():
    """
    View and manage a single participant.
    
    CONTEXT-AWARE ANNOTATION:
    This view shows:
    - Participant profile
    - Work activities
    - Recent execution signals
    - Instructions sent to this participant
    - Context-specific metrics (amount_borrowed/repaid)
    
    The mechanics are universal; only language and metric interpretation vary.
    """
    participant_id = request.args(0, cast=int)
    if not participant_id:
        session.flash = "Invalid participant account"
        redirect(URL('dashboard'))

    participant_record = db.participant(participant_id)
    if not participant_record or participant_record.responsible_id != session.responsible_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    # Get context-specific language
    participant_label = get_language(session.context_id, 'participant', 'label')
    work_activity_label = get_language(session.context_id, 'work_activity', 'label')
    execution_signal_label = get_language(session.context_id, 'execution_signal', 'label')
    instruction_label_plural = get_language(session.context_id, 'instruction', 'label_plural')

    # Get participant's work activities
    work_activities = db(
        (db.work_activity.participant_id == participant_id) &
        (db.work_activity.context_id == session.context_id)
    ).select(orderby=~db.work_activity.is_active|db.work_activity.activity_name)

    # Get recent signals (last 30 days)
    recent_signals = db(
        (db.execution_signal.participant_id == participant_id) &
        (db.execution_signal.context_id == session.context_id) &
        (db.execution_signal.signal_date >= (datetime.now() - timedelta(days=30)).date())
    ).select(
        db.execution_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.execution_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.execution_signal.signal_date,
        limitby=(0, 30)
    )

    # Get instructions sent to this participant
    participant_instructions = db(
        (db.instruction_recipient.participant_id == participant_id) &
        (db.instruction_recipient.context_id == session.context_id)
    ).select(
        db.instruction_recipient.ALL,
        db.instruction.ALL,
        left=db.instruction.on(db.instruction_recipient.instruction_id == db.instruction.id),
        orderby=~db.instruction.created_on,
        limitby=(0, 10)
    )

    # CONTEXT-SPECIFIC METRICS FORM
    # TODO: Replace with flexible metrics system
    # For now, these fields represent different things per context:
    # - Microfinance: borrowed/repaid amounts
    # - Coaching: goals set/achieved
    # - Internal org: tasks assigned/completed
    
    metric1_label = get_language(session.context_id, 'metric_allocated', 'label') or "Amount Allocated"
    metric2_label = get_language(session.context_id, 'metric_completed', 'label') or "Amount Completed"

    metrics_form = SQLFORM.factory(
        Field('amount_borrowed', 'double', label=metric1_label,
              default=participant_record.amount_borrowed,
              requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        Field('amount_repaid', 'double', label=metric2_label,
              default=participant_record.amount_repaid_b2c_reported,
              requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        submit_button="Update Metrics",
        formname='metrics'
    )

    if metrics_form.process().accepted:
        participant_record.update_record(
            amount_borrowed=metrics_form.vars.amount_borrowed,
            amount_repaid_b2c_reported=metrics_form.vars.amount_repaid
        )
        session.flash = "Metrics updated"
        redirect(URL('participant', args=[participant_id]))

    balance = participant_record.amount_borrowed - participant_record.amount_repaid_b2c_reported

    return dict(
        participant=participant_record,
        work_activities=work_activities,
        recent_signals=recent_signals,
        participant_instructions=participant_instructions,
        metrics_form=metrics_form,
        balance=balance,
        participant_label=participant_label,
        work_activity_label=work_activity_label,
        execution_signal_label=execution_signal_label,
        instruction_label_plural=instruction_label_plural,
        metric1_label=metric1_label,
        metric2_label=metric2_label
    )


# ---------------------------------------------------------------------
# SIGNALS OVERVIEW
# ---------------------------------------------------------------------

@responsible_requires_login
def signals_overview():
    """
    View recent execution signals from all participants.
    
    CONTEXT-AWARE ANNOTATION:
    Shows what participants are reporting about their execution.
    Identical mechanic across contexts; only labels differ.
    """
    cutoff = (datetime.now() - timedelta(days=7)).date()

    signals = db(
        (db.execution_signal.participant_id == db.participant.id) &
        (db.participant.responsible_id == session.responsible_id) &
        (db.participant.context_id == session.context_id) &
        (db.execution_signal.signal_date >= cutoff)
    ).select(
        db.execution_signal.ALL,
        db.participant.id,
        db.participant.real_name,
        db.participant.username,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.execution_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.execution_signal.signal_date
    )

    worse_signals = [s for s in signals if s.execution_signal.outcome == 'WORSE']
    better_signals = [s for s in signals if s.execution_signal.outcome == 'BETTER']

    execution_signal_label_plural = get_language(session.context_id, 'execution_signal', 'label_plural')

    return dict(
        all_signals=signals,
        worse_signals=worse_signals,
        better_signals=better_signals,
        execution_signal_label_plural=execution_signal_label_plural
    )


# ---------------------------------------------------------------------
# EDIT PARTICIPANT PROFILE
# ---------------------------------------------------------------------

@responsible_requires_login
def edit_participant():
    """Edit participant profile"""
    participant_id = request.args(0, cast=int)
    if not participant_id:
        session.flash = "Invalid participant account"
        redirect(URL('dashboard'))

    participant_record = db.participant(participant_id)
    if not participant_record or participant_record.responsible_id != session.responsible_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    form = SQLFORM(db.participant, participant_record,
                   fields=['real_name', 'username', 'password_hash', 'address',
                          'telephone', 'email', 'social_media'])

    if form.process().accepted:
        participant_label = get_language(session.context_id, 'participant', 'label')
        session.flash = "%s profile updated" % participant_label
        redirect(URL('participant', args=[participant_id]))

    participant_label = get_language(session.context_id, 'participant', 'label')

    return dict(
        form=form,
        participant=participant_record,
        participant_label=participant_label
    )


# ---------------------------------------------------------------------
# DELETE PARTICIPANT
# ---------------------------------------------------------------------

@responsible_requires_login
def delete_participant():
    """
    Delete a participant and all associated data.
    
    CONTEXT-AWARE ANNOTATION:
    Deletion mechanic is universal - remove participant and cascade to:
    - Work activities
    - Execution signals
    - Instruction recipients
    - Flyers
    """
    participant_id = request.args(0, cast=int)
    if not participant_id:
        session.flash = "Invalid participant account"
        redirect(URL('dashboard'))

    # Security check: Ensure this participant belongs to the logged-in responsible entity
    participant_record = db(
        (db.participant.id == participant_id) &
        (db.participant.responsible_id == session.responsible_id) &
        (db.participant.context_id == session.context_id)
    ).select().first()
    
    if not participant_record:
        session.flash = "Unauthorized or account not found"
        redirect(URL('dashboard'))

    # Delete associated records in other tables
    db(db.work_activity.participant_id == participant_id).delete()
    db(db.execution_signal.participant_id == participant_id).delete()
    db(db.instruction_recipient.participant_id == participant_id).delete()
    db(db.flyer.participant_id == participant_id).delete()

    # Finally, delete the participant
    db(db.participant.id == participant_id).delete()

    participant_label = get_language(session.context_id, 'participant', 'label')
    session.flash = "%s account and all associated data deleted successfully" % participant_label
    redirect(URL('dashboard'))


# ---------------------------------------------------------------------
# HELP / DOCUMENTATION
# ---------------------------------------------------------------------

@responsible_requires_login
def help():
    """
    Help page explaining the system.
    
    CONTEXT-AWARE ANNOTATION:
    Help content should be context-specific, explaining the system
    in terms appropriate to the domain (microfinance, coaching, etc.)
    """
    context = db.context(session.context_id)
    
    return dict(
        context=context,
        context_name=session.context_name
    )