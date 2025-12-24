# -*- coding: utf-8 -*-
"""
WingedFlyer MFI Portal Controller
Bounded support offers, no surveillance scoring
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

    # For each borrower, get signal summary
    borrower_data = []
    for b in borrowers:
        # Count signals with 'WORSE' outcome in last 7 days
        recent_worse = db(
            (db.daily_signal.b2c_id == b.id) &
            (db.daily_signal.outcome == 'WORSE') &
            (db.daily_signal.signal_date >= (datetime.now() - timedelta(days=7)).date())
        ).count()

        # Count pending offers
        pending_offers = db(
            (db.support_offer.b2c_id == b.id) &
            ((db.support_offer.borrower_response == 'PENDING') |
             (db.support_offer.borrower_response == None))
        ).count()

        # Check for late payments
        overdue_payments = db(
            (db.b2c_payment.b2c_id == b.id) &
            (db.b2c_payment.paid_date == None) &
            (db.b2c_payment.due_date < datetime.now().date())
        ).count()

        borrower_data.append({
            'borrower': b,
            'recent_worse_signals': recent_worse,
            'pending_offers': pending_offers,
            'overdue_payments': overdue_payments,
            'needs_attention': recent_worse > 2 or overdue_payments > 0
        })

    return dict(
        mfi=session.mfi_name,
        borrower_data=borrower_data
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

    # Get payments
    payments = db(db.b2c_payment.b2c_id == b2c_id).select(
        orderby=~db.b2c_payment.due_date,
        limitby=(0, 10)
    )

    # Get support offers
    support_offers = db(db.support_offer.b2c_id == b2c_id).select(
        orderby=~db.support_offer.created_on,
        limitby=(0, 10)
    )

    # Get timeline
    timeline = db(db.b2c_timeline_message.b2c_id == b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date,
        limitby=(0, 10)
    )

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

    # Timeline message form
    timeline_form = SQLFORM.factory(
        Field('title', 'string', label="Title", requires=IS_NOT_EMPTY()),
        Field('message', 'text', label="Message"),
        Field('date', 'datetime', label="Date", default=request.now),
        submit_button="Add Timeline Message",
        formname='timeline'
    )

    if timeline_form.process().accepted:
        db.b2c_timeline_message.insert(
            b2c_id=b2c_id,
            title=timeline_form.vars.title,
            the_message=timeline_form.vars.message,
            the_date=timeline_form.vars.date
        )
        session.flash = "Timeline message added"
        redirect(URL('b2c', args=[b2c_id]))

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
        payments=payments,
        support_offers=support_offers,
        timeline=timeline,
        payment_form=payment_form,
        timeline_form=timeline_form,
        repay_form=repay_form,
        balance=balance
    )


# ---------------------------------------------------------------------
# CREATE SUPPORT OFFER (The ONLY way MFIs act on signals)
# ---------------------------------------------------------------------
@mfi_requires_login
def create_offer():
    """Create a support offer for borrower"""
    b2c_id = request.args(0, cast=int)
    if not b2c_id:
        session.flash = "Invalid B2C account"
        redirect(URL('dashboard'))

    borrower = db.b2c(b2c_id)
    if not borrower or borrower.mfi_id != session.mfi_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    # Get recent signals that might trigger offers
    recent_signals = get_recent_signals(b2c_id, days=7)

    form = SQLFORM.factory(
        Field('offer_type', 'string', label="Type of Support Offer",
              requires=IS_IN_SET([
                  ('ADJUST_PAYMENT_TIMING', 'Adjust Payment Timing (Coordination)'),
                  ('SHARE_INFORMATION', 'Share Information/Resources (Info Gap)'),
                  ('OFFER_RESTRUCTURING', 'Offer Payment Restructuring (Shock Response)'),
                  ('FACILITATE_SERVICE_ACCESS', 'Facilitate Service Access (Info/Constraint)'),
                  ('REQUEST_CONVERSATION', 'Request Conversation (Complex)')
              ]),
              comment="Select the type of support you're offering"),
        Field('trigger_signal', 'string', label="What triggered this offer?",
              comment="Which borrower signal prompted this?"),
        Field('offer_text', 'text', label="Offer Details", requires=IS_NOT_EMPTY(),
              comment="Explain clearly what you're offering. Remember: this is an OFFER, not a command."),
        submit_button="Create Support Offer"
    )

    if form.process().accepted:
        create_support_offer(
            b2c_id=b2c_id,
            offer_type=form.vars.offer_type,
            offer_text=form.vars.offer_text,
            trigger_signal=form.vars.trigger_signal
        )
        session.flash = "Support offer sent to borrower. They can accept, decline, or request modification."
        redirect(URL('b2c', args=[b2c_id]))

    return dict(
        borrower=borrower,
        form=form,
        recent_signals=recent_signals
    )


# ---------------------------------------------------------------------
# VIEW OFFER RESPONSES
# ---------------------------------------------------------------------
@mfi_requires_login
def offer_responses():
    """View how borrowers have responded to offers"""
    
    # Get all offers across all borrowers
    offers = db(
        (db.support_offer.b2c_id == db.b2c.id) &
        (db.b2c.mfi_id == session.mfi_id)
    ).select(
        db.support_offer.ALL,
        db.b2c.real_name,
        db.b2c.username,
        orderby=~db.support_offer.created_on
    )

    # Separate by response status
    pending = [o for o in offers if o.support_offer.borrower_response in (None, 'PENDING')]
    accepted = [o for o in offers if o.support_offer.borrower_response == 'ACCEPTED']
    declined = [o for o in offers if o.support_offer.borrower_response == 'DECLINED']
    modified = [o for o in offers if o.support_offer.borrower_response == 'MODIFIED']

    return dict(
        pending=pending,
        accepted=accepted,
        declined=declined,
        modified=modified
    )


# ---------------------------------------------------------------------
# SIGNALS OVERVIEW - See what borrowers are signaling
# ---------------------------------------------------------------------
@mfi_requires_login
def signals_overview():
    """View signals across all borrowers (no scoring, just visibility)"""
    
    # Get signals from last 7 days
    cutoff = (datetime.now() - timedelta(days=7)).date()
    
    signals = db(
        (db.daily_signal.b2c_id == db.b2c.id) &
        (db.b2c.mfi_id == session.mfi_id) &
        (db.daily_signal.signal_date >= cutoff)
    ).select(
        db.daily_signal.ALL,
        db.b2c.real_name,
        db.b2c.username,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.daily_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.daily_signal.signal_date
    )

    # Group by outcome for quick overview
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
# DELETE TIMELINE MESSAGE
# ---------------------------------------------------------------------
@mfi_requires_login
def delete_timeline():
    """Delete a timeline message"""
    msg_id = request.args(0, cast=int)
    if msg_id:
        msg = db.b2c_timeline_message(msg_id)
        if msg:
            borrower = db.b2c(msg.b2c_id)
            if borrower and borrower.mfi_id == session.mfi_id:
                b2c_id = msg.b2c_id
                db(db.b2c_timeline_message.id == msg_id).delete()
                session.flash = "Timeline message deleted"
                redirect(URL('b2c', args=[b2c_id]))
    
    session.flash = "Invalid request"
    redirect(URL('dashboard'))


# ---------------------------------------------------------------------
# HELP / DOCUMENTATION
# ---------------------------------------------------------------------
@mfi_requires_login
def help():
    """Help page explaining the autonomy-respecting approach"""
    return dict()