# -*- coding: utf-8 -*-
"""
Participant Portal Controller (formerly B2C)
Context-aware controller for participant self-service across multiple domains
(microfinance borrowers, coaching clients, internal team members)
"""

import bcrypt
from datetime import datetime, timedelta


# ---------------------------------------------------------------------
# CONTEXT HELPER FUNCTIONS
# ---------------------------------------------------------------------

def get_language(context_id, feature_key, variant='label'):
    """
    Retrieve context-specific language for a feature.
    
    This allows the same mechanic to display different text across contexts.
    
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
        'instruction': 'Instruction',
        'instruction_plural': 'Instructions',
        'execution_signal': 'Execution Signal',
        'execution_signal_plural': 'Execution Signals',
        'work_activity': 'Work Activity',
        'work_activity_plural': 'Work Activities',
        'responsible': 'Responsible Entity',
        'flyer': 'Flyer',
        'flyer_plural': 'Flyers'
    }
    return fallback_map.get(feature_key, feature_key.replace('_', ' ').title())


# ---------------------------------------------------------------------
# PARTICIPANT LOGIN
# ---------------------------------------------------------------------

def login():
    """
    Login screen for participants.
    
    CONTEXT-AWARE ANNOTATION:
    Login mechanic is universal across contexts.
    Only welcome messages and labels should be context-specific.
    """
    if session.participant_id:
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
        user = db(db.participant.username == username).select().first()

        if user and user.password_hash:
            try:
                password_bytes = password.encode('utf-8')
                hash_bytes = (user.password_hash.encode('utf-8')
                            if isinstance(user.password_hash, str)
                            else user.password_hash)

                if bcrypt.checkpw(password_bytes, hash_bytes):
                    session.participant_id = user.id
                    session.participant_name = user.real_name
                    session.participant_username = user.username
                    session.context_id = user.context_id
                    session.responsible_id = user.responsible_id
                    
                    # Load context and responsible entity names for UI
                    context = db.context(user.context_id)
                    responsible = db.responsible(user.responsible_id)
                    session.context_name = context.display_name if context else "Unknown"
                    session.responsible_name = responsible.name if responsible else "Unknown"
                    
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

def participant_requires_login(func):
    """Decorator to protect participant-only pages"""
    def wrapper(*args, **kwargs):
        if not session.participant_id:
            session.flash = "Please log in first"
            redirect(URL('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ---------------------------------------------------------------------
# PARTICIPANT DASHBOARD
# ---------------------------------------------------------------------

@participant_requires_login
def dashboard():
    """
    Participant dashboard showing:
    - Recent execution signals
    - Unread instructions
    - Work activities
    - Context-specific metrics
    
    CONTEXT-AWARE ANNOTATION:
    Dashboard mechanics are universal - only language and metric
    interpretation differ per context.
    """
    participant_record = db.participant(session.participant_id)
    if not participant_record:
        session.clear()
        redirect(URL('login'))

    # Get context-specific language
    work_activity_label_plural = get_language(session.context_id, 'work_activity', 'label_plural')
    execution_signal_label_plural = get_language(session.context_id, 'execution_signal', 'label_plural')
    instruction_label_plural = get_language(session.context_id, 'instruction', 'label_plural')
    responsible_label = get_language(session.context_id, 'responsible', 'label')

    # Get work activities
    work_activities = db(
        (db.work_activity.participant_id == session.participant_id) &
        (db.work_activity.context_id == session.context_id)
    ).select(orderby=~db.work_activity.is_active|db.work_activity.activity_name)

    # Get recent execution signals (last 7 days)
    recent_signals = db(
        (db.execution_signal.participant_id == session.participant_id) &
        (db.execution_signal.context_id == session.context_id) &
        (db.execution_signal.signal_date >= (datetime.now() - timedelta(days=7)).date())
    ).select(
        db.execution_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.execution_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.execution_signal.signal_date,
        limitby=(0, 10)
    )

    # Get unread instructions
    unread_instructions = db(
        (db.instruction_recipient.participant_id == session.participant_id) &
        (db.instruction_recipient.context_id == session.context_id) &
        (db.instruction_recipient.is_read == False)
    ).select(
        db.instruction_recipient.ALL,
        db.instruction.ALL,
        left=db.instruction.on(db.instruction_recipient.instruction_id == db.instruction.id),
        orderby=~db.instruction.created_on,
        limitby=(0, 5)
    )

    # Get pending response instructions
    pending_responses = db(
        (db.instruction_recipient.participant_id == session.participant_id) &
        (db.instruction_recipient.context_id == session.context_id) &
        (db.instruction_recipient.response == None) &
        (db.instruction.id == db.instruction_recipient.instruction_id) &
        (db.instruction.response_template != 'NONE')
    ).select(
        db.instruction_recipient.ALL,
        db.instruction.ALL,
        left=db.instruction.on(db.instruction_recipient.instruction_id == db.instruction.id),
        orderby=~db.instruction.created_on
    )

    # Context-specific metrics
    metric1_label = get_language(session.context_id, 'metric_allocated', 'label') or "Allocated"
    metric2_label = get_language(session.context_id, 'metric_completed', 'label') or "Completed"
    balance = participant_record.amount_borrowed - participant_record.amount_repaid_b2c_reported

    return dict(
        participant=participant_record,
        work_activities=work_activities,
        recent_signals=recent_signals,
        unread_instructions=unread_instructions,
        pending_responses=pending_responses,
        balance=balance,
        context_name=session.context_name,
        responsible_name=session.responsible_name,
        work_activity_label_plural=work_activity_label_plural,
        execution_signal_label_plural=execution_signal_label_plural,
        instruction_label_plural=instruction_label_plural,
        responsible_label=responsible_label,
        metric1_label=metric1_label,
        metric2_label=metric2_label
    )


# ---------------------------------------------------------------------
# WORK ACTIVITIES
# ---------------------------------------------------------------------

@participant_requires_login
def work_activities():
    """
    View and manage work activities.
    
    CONTEXT-AWARE ANNOTATION:
    Work activity management is universal:
    - Microfinance: business activities
    - Coaching: goal areas
    - Internal org: projects/responsibilities
    """
    activities = db(
        (db.work_activity.participant_id == session.participant_id) &
        (db.work_activity.context_id == session.context_id)
    ).select(orderby=~db.work_activity.is_active|db.work_activity.activity_name)

    work_activity_label = get_language(session.context_id, 'work_activity', 'label')
    work_activity_label_plural = get_language(session.context_id, 'work_activity', 'label_plural')

    return dict(
        activities=activities,
        work_activity_label=work_activity_label,
        work_activity_label_plural=work_activity_label_plural
    )


@participant_requires_login
def create_work_activity():
    """Create a new work activity"""
    db.work_activity.participant_id.writable = False
    db.work_activity.participant_id.readable = False
    db.work_activity.context_id.writable = False
    db.work_activity.context_id.readable = False

    form = SQLFORM(db.work_activity)
    form.vars.participant_id = session.participant_id
    form.vars.context_id = session.context_id

    if form.process().accepted:
        work_activity_label = get_language(session.context_id, 'work_activity', 'label')
        session.flash = "%s created successfully" % work_activity_label
        redirect(URL('work_activities'))

    work_activity_label = get_language(session.context_id, 'work_activity', 'label')

    return dict(form=form, work_activity_label=work_activity_label)


@participant_requires_login
def edit_work_activity():
    """Edit a work activity"""
    activity_id = request.args(0, cast=int)
    if not activity_id:
        session.flash = "Invalid activity"
        redirect(URL('work_activities'))

    activity = db.work_activity(activity_id)
    if not activity or activity.participant_id != session.participant_id:
        session.flash = "Unauthorized access"
        redirect(URL('work_activities'))

    form = SQLFORM(db.work_activity, activity)

    if form.process().accepted:
        work_activity_label = get_language(session.context_id, 'work_activity', 'label')
        session.flash = "%s updated successfully" % work_activity_label
        redirect(URL('work_activities'))

    work_activity_label = get_language(session.context_id, 'work_activity', 'label')

    return dict(form=form, activity=activity, work_activity_label=work_activity_label)


@participant_requires_login
def delete_work_activity():
    """Delete a work activity"""
    activity_id = request.args(0, cast=int)
    if activity_id:
        activity = db.work_activity(activity_id)
        if activity and activity.participant_id == session.participant_id:
            db(db.work_activity.id == activity_id).delete()
            work_activity_label = get_language(session.context_id, 'work_activity', 'label')
            session.flash = "%s deleted" % work_activity_label
            redirect(URL('work_activities'))

    session.flash = "Invalid request"
    redirect(URL('work_activities'))


# ---------------------------------------------------------------------
# EXECUTION SIGNALS
# ---------------------------------------------------------------------

@participant_requires_login
def signals():
    """
    View execution signal history.
    
    CONTEXT-AWARE ANNOTATION:
    Signal tracking is universal - participants report execution status
    regardless of context (business performance, goal progress, task status).
    """
    signals = db(
        (db.execution_signal.participant_id == session.participant_id) &
        (db.execution_signal.context_id == session.context_id)
    ).select(
        db.execution_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.execution_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.execution_signal.signal_date,
        limitby=(0, 50)
    )

    execution_signal_label = get_language(session.context_id, 'execution_signal', 'label')
    execution_signal_label_plural = get_language(session.context_id, 'execution_signal', 'label_plural')

    return dict(
        signals=signals,
        execution_signal_label=execution_signal_label,
        execution_signal_label_plural=execution_signal_label_plural
    )


@participant_requires_login
def create_signal():
    """Create a new execution signal"""
    # Get work activities for this participant
    activities = db(
        (db.work_activity.participant_id == session.participant_id) &
        (db.work_activity.context_id == session.context_id) &
        (db.work_activity.is_active == True)
    ).select()

    if not activities:
        work_activity_label = get_language(session.context_id, 'work_activity', 'label')
        session.flash = "Please create a %s first" % work_activity_label.lower()
        redirect(URL('create_work_activity'))

    db.execution_signal.participant_id.writable = False
    db.execution_signal.participant_id.readable = False
    db.execution_signal.context_id.writable = False
    db.execution_signal.context_id.readable = False

    form = SQLFORM(db.execution_signal)
    form.vars.participant_id = session.participant_id
    form.vars.context_id = session.context_id

    if form.process().accepted:
        execution_signal_label = get_language(session.context_id, 'execution_signal', 'label')
        session.flash = "%s recorded successfully" % execution_signal_label
        redirect(URL('signals'))

    execution_signal_label = get_language(session.context_id, 'execution_signal', 'label')
    work_activity_label = get_language(session.context_id, 'work_activity', 'label')

    return dict(
        form=form,
        execution_signal_label=execution_signal_label,
        work_activity_label=work_activity_label
    )


# ---------------------------------------------------------------------
# INSTRUCTIONS (INBOX)
# ---------------------------------------------------------------------

@participant_requires_login
def instructions():
    """
    View all instructions received.
    
    CONTEXT-AWARE ANNOTATION:
    Instruction inbox is universal - participants receive messages
    from their responsible entity regardless of context.
    """
    instructions = db(
        (db.instruction_recipient.participant_id == session.participant_id) &
        (db.instruction_recipient.context_id == session.context_id)
    ).select(
        db.instruction_recipient.ALL,
        db.instruction.ALL,
        left=db.instruction.on(db.instruction_recipient.instruction_id == db.instruction.id),
        orderby=~db.instruction.created_on
    )

    instruction_label_plural = get_language(session.context_id, 'instruction', 'label_plural')

    return dict(
        instructions=instructions,
        instruction_label_plural=instruction_label_plural
    )


@participant_requires_login
def read_instruction():
    """
    Read a specific instruction and mark as read.
    
    CONTEXT-AWARE ANNOTATION:
    Reading and responding to instructions is universal.
    Only the language and response template interpretation vary.
    """
    instruction_id = request.args(0, cast=int)
    if not instruction_id:
        session.flash = "Invalid instruction"
        redirect(URL('instructions'))

    # Get the instruction recipient record
    recipient = db(
        (db.instruction_recipient.instruction_id == instruction_id) &
        (db.instruction_recipient.participant_id == session.participant_id) &
        (db.instruction_recipient.context_id == session.context_id)
    ).select().first()

    if not recipient:
        session.flash = "Instruction not found"
        redirect(URL('instructions'))

    instruction = db.instruction(instruction_id)

    # Mark as read if not already read
    if not recipient.is_read:
        recipient.update_record(is_read=True, read_on=datetime.now())

    # Handle response submission
    response_form = None
    if instruction.response_template != 'NONE' and not recipient.response:
        if instruction.response_template == 'CHECKBOX_READ':
            response_form = SQLFORM.factory(
                Field('confirm', 'boolean', label="I have read and understood this message"),
                submit_button="Confirm"
            )
        elif instruction.response_template == 'ACCEPT_DECLINE':
            response_form = SQLFORM.factory(
                Field('response', 'string', label="Your Response",
                      requires=IS_IN_SET(['ACCEPT', 'DECLINE'])),
                submit_button="Submit Response"
            )
        elif instruction.response_template == 'TEXT_RESPONSE':
            response_form = SQLFORM.factory(
                Field('response', 'text', label="Your Response",
                      requires=IS_NOT_EMPTY()),
                submit_button="Submit Response"
            )

        if response_form and response_form.process(formname='response').accepted:
            response_value = str(response_form.vars.get('confirm') or response_form.vars.get('response'))
            recipient.update_record(
                response=response_value,
                responded_on=datetime.now()
            )
            session.flash = "Response submitted"
            redirect(URL('read_instruction', args=[instruction_id]))

    instruction_label = get_language(session.context_id, 'instruction', 'label')

    return dict(
        instruction=instruction,
        recipient=recipient,
        response_form=response_form,
        instruction_label=instruction_label
    )


# ---------------------------------------------------------------------
# FLYERS (PUBLIC CONTENT PUBLISHING)
# ---------------------------------------------------------------------

@participant_requires_login
def flyers():
    """
    View and manage participant's published flyers.
    
    CONTEXT-AWARE ANNOTATION:
    Flyer publishing is universal:
    - Microfinance: business advertisements
    - Coaching: success stories/testimonials
    - Internal org: project showcases
    """
    flyers = db(
        (db.flyer.participant_id == session.participant_id) &
        (db.flyer.context_id == session.context_id)
    ).select(orderby=~db.flyer.created_on)

    flyer_label_plural = get_language(session.context_id, 'flyer', 'label_plural')

    return dict(flyers=flyers, flyer_label_plural=flyer_label_plural)


@participant_requires_login
def create_flyer():
    """Create a new flyer"""
    db.flyer.participant_id.writable = False
    db.flyer.participant_id.readable = False
    db.flyer.context_id.writable = False
    db.flyer.context_id.readable = False

    form = SQLFORM(db.flyer)
    form.vars.participant_id = session.participant_id
    form.vars.context_id = session.context_id

    if form.process().accepted:
        flyer_label = get_language(session.context_id, 'flyer', 'label')
        session.flash = "%s created successfully" % flyer_label
        redirect(URL('flyers'))

    flyer_label = get_language(session.context_id, 'flyer', 'label')

    return dict(form=form, flyer_label=flyer_label)


@participant_requires_login
def edit_flyer():
    """Edit a flyer"""
    flyer_id = request.args(0, cast=int)
    if not flyer_id:
        session.flash = "Invalid flyer"
        redirect(URL('flyers'))

    flyer = db.flyer(flyer_id)
    if not flyer or flyer.participant_id != session.participant_id:
        session.flash = "Unauthorized access"
        redirect(URL('flyers'))

    form = SQLFORM(db.flyer, flyer)

    if form.process().accepted:
        flyer_label = get_language(session.context_id, 'flyer', 'label')
        session.flash = "%s updated successfully" % flyer_label
        redirect(URL('flyers'))

    flyer_label = get_language(session.context_id, 'flyer', 'label')

    return dict(form=form, flyer=flyer, flyer_label=flyer_label)


@participant_requires_login
def delete_flyer():
    """Delete a flyer"""
    flyer_id = request.args(0, cast=int)
    if flyer_id:
        flyer = db.flyer(flyer_id)
        if flyer and flyer.participant_id == session.participant_id:
            db(db.flyer.id == flyer_id).delete()
            flyer_label = get_language(session.context_id, 'flyer', 'label')
            session.flash = "%s deleted" % flyer_label
            redirect(URL('flyers'))

    session.flash = "Invalid request"
    redirect(URL('flyers'))


# ---------------------------------------------------------------------
# PUBLIC FLYER VIEW (No login required)
# ---------------------------------------------------------------------

def view_flyer():
    """
    Public view of a flyer (no authentication required).
    
    CONTEXT-AWARE ANNOTATION:
    Public flyer viewing is universal - anyone can view published content.
    Track views for analytics.
    """
    flyer_id = request.args(0, cast=int)
    if not flyer_id:
        return dict(error="Flyer not found")

    flyer = db.flyer(flyer_id)
    if not flyer or not flyer.is_public:
        return dict(error="Flyer not found or not public")

    # Get context for language
    context_id = flyer.context_id
    flyer_label = get_language(context_id, 'flyer', 'label')

    # Increment view count
    flyer.update_record(view_count=flyer.view_count + 1)

    # Track view
    db.flyer_view.insert(
        flyer_id=flyer_id,
        viewer_ip=request.client
    )

    # Get participant info
    participant = db.participant(flyer.participant_id)

    return dict(
        flyer=flyer,
        participant=participant,
        flyer_label=flyer_label
    )


# ---------------------------------------------------------------------
# PROFILE MANAGEMENT
# ---------------------------------------------------------------------

@participant_requires_login
def profile():
    """View and edit participant profile"""
    participant_record = db.participant(session.participant_id)

    form = SQLFORM(db.participant, participant_record,
                   fields=['real_name', 'username', 'password_hash', 'address',
                          'telephone', 'email', 'social_media'])

    if form.process().accepted:
        session.participant_name = form.vars.real_name
        session.flash = "Profile updated successfully"
        redirect(URL('profile'))

    participant_label = get_language(session.context_id, 'participant', 'label')

    return dict(
        form=form,
        participant=participant_record,
        participant_label=participant_label
    )


# ---------------------------------------------------------------------
# HELP / DOCUMENTATION
# ---------------------------------------------------------------------

@participant_requires_login
def help():
    """
    Help page for participants.
    
    CONTEXT-AWARE ANNOTATION:
    Help content should be context-specific, explaining features
    in terms appropriate to the domain.
    """
    context = db.context(session.context_id)
    
    return dict(
        context=context,
        context_name=session.context_name
    )