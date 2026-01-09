# -*- coding: utf-8 -*-
"""
WingedFlyer MFI Portal Controller
With messaging system for borrower communication
"""

import bcrypt
from datetime import datetime, timedelta


# ---------------------------------------------------------------------
# MFI LOGIN
# ---------------------------------------------------------------------
def login():
    """Login screen for MFIs"""
    if session.mfi_id:
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
        user = db(db.mfi.username == username).select().first()

        if user and user.password_hash:
            try:
                password_bytes = password.encode('utf-8')
                hash_bytes = (user.password_hash.encode('utf-8')
                            if isinstance(user.password_hash, str)
                            else user.password_hash)

                if bcrypt.checkpw(password_bytes, hash_bytes):
                    session.mfi_id = user.id
                    session.mfi_name = user.name
                    session.mfi_username = user.username
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
def mfi_requires_login(func):
    """Decorator to protect MFI-only pages"""
    def wrapper(*args, **kwargs):
        if not session.mfi_id:
            session.flash = "Please log in first"
            redirect(URL('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ---------------------------------------------------------------------
# MFI DASHBOARD
# ---------------------------------------------------------------------
@mfi_requires_login
def dashboard():
    """Dashboard showing all borrowers with their recent signals"""
    mfi_record = db.mfi(session.mfi_id)
    if not mfi_record:
        session.clear()
        redirect(URL('login'))

    # Get all borrowers with their recent signal counts
    borrowers = db(db.b2c.mfi_id == session.mfi_id).select(
        orderby=db.b2c.real_name
    )

    # For each borrower, get signal summary and info_flyer status
    borrower_data = []
    for b in borrowers:
        # Count signals with 'WORSE' outcome in last 7 days
        recent_worse = db(
            (db.daily_signal.b2c_id == b.id) &
            (db.daily_signal.outcome == 'WORSE') &
            (db.daily_signal.signal_date >= (datetime.now() - timedelta(days=7)).date())
        ).count()

        # Count unread info_flyers
        unread_info_flyers = db(
            (db.info_flyer_recipient.b2c_id == b.id) &
            (db.info_flyer_recipient.is_read == False)
        ).count()

        # Count pending responses (info_flyers with response templates that haven't been responded to)
        pending_responses = db(
            (db.info_flyer_recipient.b2c_id == b.id) &
            (db.info_flyer_recipient.response == None) &
            (db.mfi_info_flyer.id == db.info_flyer_recipient.info_flyer_id) &
            (db.mfi_info_flyer.response_template != 'NONE')
        ).count()
        '''
        # Check for late payments
        overdue_payments = db(
            (db.b2c_payment.b2c_id == b.id) &
            (db.b2c_payment.paid_date == None) &
            (db.b2c_payment.due_date < datetime.now().date())
        ).count()
        '''
        borrower_data.append({
            'borrower': b,
            'recent_worse_signals': recent_worse,
            'unread_info_flyers': unread_info_flyers,
            'pending_responses': pending_responses,
            #'overdue_payments': overdue_payments,
            'needs_attention': recent_worse > 2 #or overdue_payments > 0
        })
    can_create = db(db.b2c.mfi_id == session.mfi_id).count() < mfi_record.b2c_accounts

    return dict(
        mfi=session.mfi_name,
        borrower_data=borrower_data,
        can_create=can_create
    )


# ---------------------------------------------------------------------
# CREATE NEW B2C ACCOUNT
# ---------------------------------------------------------------------
@mfi_requires_login
def create_b2c():
    """Create a new B2C borrower account"""
    mfi_record = db.mfi(session.mfi_id)
    current_count = db(db.b2c.mfi_id == session.mfi_id).count()

    if current_count >= mfi_record.b2c_accounts:
        session.flash = "Maximum B2C account limit reached (%d)" % mfi_record.b2c_accounts
        redirect(URL('dashboard'))

    db.b2c.mfi_id.writable = False
    db.b2c.mfi_id.readable = False

    form = SQLFORM(db.b2c)
    form.vars.mfi_id = session.mfi_id

    if form.process().accepted:
        session.flash = "B2C account created successfully"
        redirect(URL('b2c', args=[form.vars.id]))

    return dict(form=form, current_count=current_count,
                max_accounts=mfi_record.b2c_accounts)


# ---------------------------------------------------------------------
# info_flyer COMPOSER - Send info_flyer to one or more borrowers
# ---------------------------------------------------------------------
@mfi_requires_login
def compose_info_flyer():
    """Compose and send a info_flyer to one or more borrowers"""

    borrowers = db(db.b2c.mfi_id == session.mfi_id).select(orderby=db.b2c.real_name)

    recipient_arg = request.args(0) if request.args else None
    preselected_recipients = []
    if recipient_arg:
        preselected_recipients = [int(recipient_arg)]

    form = SQLFORM.factory(
Field('recipients', 'list:integer',
              label="Recipients",
              requires=IS_IN_SET([(b.id, "%s (%s)" % (b.real_name, b.username)) for b in borrowers],
                                 multiple=True,
                                 error_message="Please select at least one recipient"),
              widget=SQLFORM.widgets.checkboxes.widget,
              comment="Select one or more borrowers to send this message to"),
        Field('subject', 'string', label="Subject",
              # CHANGED error_info_flyer to error_message below
              requires=IS_NOT_EMPTY(error_message="Subject is required")),
        Field('info_flyer_text', 'text', label="Message Content",
              # CHANGED error_info_flyer to error_message below
              requires=IS_NOT_EMPTY(error_message="Message text is required")),
        Field('response_template', 'string', label="Response Type",
              requires=IS_IN_SET([
                  ('NONE', 'No Response Needed'),
                  ('CHECKBOX_READ', 'Mark as Read Checkbox'),
                  ('ACCEPT_DECLINE', 'Accept/Decline Buttons'),
                  ('TEXT_RESPONSE', 'Text Response Field')
              ]),
              default='NONE'),
        submit_button="Send Message"
    )

    if form.process().accepted:
        # This function must be defined in your models/db.py
        info_flyer_id = send_info_flyer_to_borrowers(
            mfi_id=session.mfi_id,
            b2c_ids=form.vars.recipients,
            subject=form.vars.subject,
            info_flyer_text=form.vars.info_flyer_text,
            response_template=form.vars.response_template,
            sent_by=session.mfi_username
        )

        session.flash = "Message sent successfully"
        redirect(URL('sent_info_flyers'))

    return dict(form=form, borrowers=borrowers)

# ---------------------------------------------------------------------
# VIEW SENT info_flyerS
# ---------------------------------------------------------------------
@mfi_requires_login
def sent_info_flyers():
    """View all info_flyers sent by this MFI"""

    info_flyers = db(db.mfi_info_flyer.mfi_id == session.mfi_id).select(
        orderby=~db.mfi_info_flyer.created_on
    )

    # For each info_flyer, get recipient statistics
    info_flyer_data = []
    for msg in info_flyers:
        recipients = db(db.info_flyer_recipient.info_flyer_id == msg.id).select()

        total_recipients = len(recipients)
        read_count = sum(1 for r in recipients if r.is_read)
        responded_count = sum(1 for r in recipients if r.response)

        info_flyer_data.append({
            'info_flyer': msg,
            'total_recipients': total_recipients,
            'read_count': read_count,
            'responded_count': responded_count,
            'recipients': recipients
        })

    return dict(info_flyer_data=info_flyer_data)


# ---------------------------------------------------------------------
# VIEW info_flyer DETAILS AND RESPONSES
# ---------------------------------------------------------------------
@mfi_requires_login
def info_flyer_details():
    """View details of a specific info_flyer and all responses"""
    info_flyer_id = request.args(0, cast=int)
    if not info_flyer_id:
        session.flash = "Invalid info_flyer"
        redirect(URL('sent_info_flyers'))

    info_flyer = db.mfi_info_flyer(info_flyer_id)
    if not info_flyer or info_flyer.mfi_id != session.mfi_id:
        session.flash = "info_flyer not found"
        redirect(URL('sent_info_flyers'))

    # Get all recipients and their responses
    recipients = db(db.info_flyer_recipient.info_flyer_id == info_flyer_id).select(
        db.info_flyer_recipient.ALL,
        db.b2c.ALL,
        left=db.b2c.on(db.info_flyer_recipient.b2c_id == db.b2c.id),
        orderby=db.b2c.real_name
    )

    return dict(info_flyer=info_flyer, recipients=recipients)


# ---------------------------------------------------------------------
# VIEW SINGLE BORROWER
# ---------------------------------------------------------------------
@mfi_requires_login
def b2c():
    """View and manage a single borrower"""
    b2c_id = request.args(0, cast=int)
    if not b2c_id:
        session.flash = "Invalid B2C account"
        redirect(URL('dashboard'))

    borrower = db.b2c(b2c_id)
    if not borrower or borrower.mfi_id != session.mfi_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    # Get borrower's work activities
    work_activities = db(db.work_activity.b2c_id == b2c_id).select(
        orderby=~db.work_activity.is_active|db.work_activity.activity_name
    )

    # Get recent signals (last 30 days)
    recent_signals = db(
        (db.daily_signal.b2c_id == b2c_id) &
        (db.daily_signal.signal_date >= (datetime.now() - timedelta(days=30)).date())
    ).select(
        db.daily_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.daily_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.daily_signal.signal_date,
        limitby=(0, 30)
    )
    '''
    # Get payments
    payments = db(db.b2c_payment.b2c_id == b2c_id).select(
        orderby=~db.b2c_payment.due_date,
        limitby=(0, 10)
    )
    '''
    # Get info_flyers sent to this borrower
    borrower_info_flyers = db(
        (db.info_flyer_recipient.b2c_id == b2c_id)
    ).select(
        db.info_flyer_recipient.ALL,
        db.mfi_info_flyer.ALL,
        left=db.mfi_info_flyer.on(db.info_flyer_recipient.info_flyer_id == db.mfi_info_flyer.id),
        orderby=~db.mfi_info_flyer.created_on,
        limitby=(0, 10)
    )

    # Get timeline
    '''
    timeline = db(db.b2c_timeline_info_flyer.b2c_id == b2c_id).select(
        orderby=~db.b2c_timeline_info_flyer.the_date,
        limitby=(0, 10)
    )
    '''

    '''
    # Payment form
    payment_form = SQLFORM.factory(
        Field('amount', 'double', label="Payment Amount", requires=IS_NOT_EMPTY()),
        Field('due_date', 'date', label="Due Date", requires=IS_NOT_EMPTY()),
        Field('paid_date', 'date', label="Paid Date"),
        Field('payment_method', 'string', label="Payment Method"),
        Field('notes', 'text', label="Notes"),
        submit_button="Record Payment",
        formname='payment'
    )

    if payment_form.process().accepted:
        db.b2c_payment.insert(
            b2c_id=b2c_id,
            amount=payment_form.vars.amount,
            due_date=payment_form.vars.due_date,
            paid_date=payment_form.vars.paid_date,
            payment_method=payment_form.vars.payment_method,
            notes=payment_form.vars.notes
        )
        session.flash = "Payment recorded"
        redirect(URL('b2c', args=[b2c_id]))

    # Timeline info_flyer form
    timeline_form = SQLFORM.factory(
        Field('title', 'string', label="Title", requires=IS_NOT_EMPTY()),
        Field('info_flyer', 'text', label="info_flyer"),
        Field('date', 'datetime', label="Date", default=request.now),
        submit_button="Add Timeline info_flyer",
        formname='timeline'
    )

    if timeline_form.process().accepted:
        db.b2c_timeline_info_flyer.insert(
            b2c_id=b2c_id,
            title=timeline_form.vars.title,
            the_info_flyer=timeline_form.vars.info_flyer,
            the_date=timeline_form.vars.date
        )
        session.flash = "Timeline info_flyer added"
        redirect(URL('b2c', args=[b2c_id]))
    '''
    # Repayment tracking form
    repay_form = SQLFORM.factory(
        Field('amount_borrowed', 'double', label="Amount Borrowed",
              default=borrower.amount_borrowed, requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        Field('amount_repaid', 'double', label="Amount Repaid",
              default=borrower.amount_repaid_b2c_reported,
              requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        submit_button="Update Amounts",
        formname='repay'
    )

    if repay_form.process().accepted:
        borrower.update_record(
            amount_borrowed=repay_form.vars.amount_borrowed,
            amount_repaid_b2c_reported=repay_form.vars.amount_repaid
        )
        session.flash = "Repayment amounts updated"
        redirect(URL('b2c', args=[b2c_id]))

    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported

    return dict(
        borrower=borrower,
        work_activities=work_activities,
        recent_signals=recent_signals,
        #payments=payments,
        borrower_info_flyers=borrower_info_flyers,
        #timeline=timeline,
        #payment_form=payment_form,
        #timeline_form=timeline_form,
        repay_form=repay_form,
        balance=balance
    )


# ---------------------------------------------------------------------
# SIGNALS OVERVIEW - See what borrowers are signaling
# ---------------------------------------------------------------------
# controllers/mfi.py

def signals_overview():
    cutoff = (datetime.now() - timedelta(days=7)).date()

    signals = db(
        (db.daily_signal.b2c_id == db.b2c.id) &
        (db.b2c.mfi_id == session.mfi_id) &
        (db.daily_signal.signal_date >= cutoff)
    ).select(
        db.daily_signal.ALL,
        db.b2c.id,        # Explicitly include this
        db.b2c.real_name,
        db.b2c.username,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.daily_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.daily_signal.signal_date
    )

    worse_signals = [s for s in signals if s.daily_signal.outcome == 'WORSE']
    better_signals = [s for s in signals if s.daily_signal.outcome == 'BETTER']

    return dict(
        all_signals=signals,
        worse_signals=worse_signals,
        better_signals=better_signals
    )

# ---------------------------------------------------------------------
# EDIT B2C PROFILE
# ---------------------------------------------------------------------
@mfi_requires_login
def edit_b2c():
    """Edit B2C borrower profile"""
    b2c_id = request.args(0, cast=int)
    if not b2c_id:
        session.flash = "Invalid B2C account"
        redirect(URL('dashboard'))

    borrower = db.b2c(b2c_id)
    if not borrower or borrower.mfi_id != session.mfi_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    form = SQLFORM(db.b2c, borrower,
                   fields=['real_name', 'username', 'password_hash', 'address',
                          'telephone', 'email', 'social_media'])

    if form.process().accepted:
        session.flash = "B2C profile updated"
        redirect(URL('b2c', args=[b2c_id]))

    return dict(form=form, borrower=borrower)


# ---------------------------------------------------------------------
# DELETE PAYMENT
# ---------------------------------------------------------------------
'''
@mfi_requires_login
def delete_payment():
    """Delete a payment record"""
    payment_id = request.args(0, cast=int)
    if payment_id:
        payment = db.b2c_payment(payment_id)
        if payment:
            borrower = db.b2c(payment.b2c_id)
            if borrower and borrower.mfi_id == session.mfi_id:
                b2c_id = payment.b2c_id
                db(db.b2c_payment.id == payment_id).delete()
                session.flash = "Payment deleted"
                redirect(URL('b2c', args=[b2c_id]))

    session.flash = "Invalid request"
    redirect(URL('dashboard'))


# ---------------------------------------------------------------------
# DELETE TIMELINE info_flyer
# ---------------------------------------------------------------------
@mfi_requires_login
def delete_timeline():
    """Delete a timeline info_flyer"""
    msg_id = request.args(0, cast=int)
    if msg_id:
        msg = db.b2c_timeline_info_flyer(msg_id)
        if msg:
            borrower = db.b2c(msg.b2c_id)
            if borrower and borrower.mfi_id == session.mfi_id:
                b2c_id = msg.b2c_id
                db(db.b2c_timeline_info_flyer.id == msg_id).delete()
                session.flash = "Timeline info_flyer deleted"
                redirect(URL('b2c', args=[b2c_id]))

    session.flash = "Invalid request"
    redirect(URL('dashboard'))
'''

# ---------------------------------------------------------------------
# HELP / DOCUMENTATION
# ---------------------------------------------------------------------
@mfi_requires_login
def help():
    """Help page explaining the autonomy-respecting approach"""
    return dict()



@mfi_requires_login
def delete_b2c():
    """Delete a B2C borrower and all associated data"""
    b2c_id = request.args(0, cast=int)
    if not b2c_id:
        session.flash = "Invalid B2C account"
        redirect(URL('dashboard'))

    # Security check: Ensure this B2C belongs to the logged-in MFI
    borrower = db((db.b2c.id == b2c_id) & (db.b2c.mfi_id == session.mfi_id)).select().first()
    
    if not borrower:
        session.flash = "Unauthorized or account not found"
        redirect(URL('dashboard'))

    # Delete associated records in other tables
    # Note: Use the exact table names from your models/db.py
    db(db.work_activity.b2c_id == b2c_id).delete()
    db(db.daily_signal.b2c_id == b2c_id).delete()
    db(db.info_flyer_recipient.b2c_id == b2c_id).delete()
    db(db.flyer.b2c_id == b2c_id).delete()
    
    # If you uncommented these in db.py, include them here:
    # db(db.b2c_payment.b2c_id == b2c_id).delete()
    # db(db.b2c_timeline_info_flyer.b2c_id == b2c_id).delete()

    # Finally, delete the borrower
    db(db.b2c.id == b2c_id).delete()

    session.flash = "B2C account and all associated data deleted successfully"
    redirect(URL('dashboard'))
