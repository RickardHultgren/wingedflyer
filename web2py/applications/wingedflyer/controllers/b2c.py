# -*- coding: utf-8 -*-
"""
WingedFlyer B2C Borrower Portal Controller
Autonomy-respecting design: borrowers signal, MFIs offer support
"""

from gluon.tools import Auth
auth = Auth(db)
b2c = auth

import markdown
import qrcode
from io import BytesIO
import base64
import bcrypt
from datetime import datetime, timedelta


# ---------------------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------------------
def login():
    """Login screen for B2C borrowers"""
    if session.b2c_id:
        redirect(URL('dashboard'))

    form = FORM(
        DIV(
            LABEL("Username"),
            INPUT(_name='username', _class='form-control', requires=IS_NOT_EMPTY()),
            LABEL("Password", _style="margin-top:10px"),
            INPUT(_name='password', _type='password', _class='form-control', 
                  requires=IS_NOT_EMPTY()),
            INPUT(_type='submit', _value='Login', _class='btn btn-success', 
                  _style="margin-top:15px"),
            _class='form-group'
        )
    )

    if form.accepts(request, session):
        username = form.vars.username
        password = form.vars.password
        borrower = db(db.b2c.username == username).select().first()

        if borrower and borrower.password_hash:
            try:
                password_bytes = password.encode('utf-8')
                hash_bytes = (borrower.password_hash.encode('utf-8') 
                            if isinstance(borrower.password_hash, str) 
                            else borrower.password_hash)

                if bcrypt.checkpw(password_bytes, hash_bytes):
                    session.b2c_id = borrower.id
                    session.b2c_username = borrower.username
                    session.b2c_name = borrower.real_name
                    session.mfi_id = borrower.mfi_id
                    redirect(URL('dashboard'))
                else:
                    response.flash = "Invalid username or password"
            except Exception as e:
                response.flash = "Login error. Please contact your MFI."
                print("B2C Login error: %s" % str(e))
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
def b2c_requires_login(func):
    """Decorator to protect B2C-only pages"""
    def wrapper(*args, **kwargs):
        if not session.b2c_id:
            session.flash = "Please log in first"
            redirect(URL('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ---------------------------------------------------------------------
# DASHBOARD - Main landing page
# ---------------------------------------------------------------------
@b2c_requires_login
def dashboard():
    """Main dashboard showing signals, offers, and financial summary"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    # Financial summary
    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported
    repayment_percentage = 0
    if borrower.amount_borrowed > 0:
        repayment_percentage = (borrower.amount_repaid_b2c_reported / 
                              borrower.amount_borrowed) * 100

    # Get active work activities
    work_activities = db(
        (db.work_activity.b2c_id == session.b2c_id) &
        (db.work_activity.is_active == True)
    ).select(orderby=db.work_activity.activity_name)

    # Get recent signals
    recent_signals = get_recent_signals(session.b2c_id, days=7)

    # Get pending support offers from MFI
    pending_offers = get_pending_offers(session.b2c_id)

    # Get recent timeline messages
    recent_timeline = db(
        db.b2c_timeline_message.b2c_id == session.b2c_id
    ).select(orderby=~db.b2c_timeline_message.the_date, limitby=(0, 5))

    # Get upcoming payments
    upcoming_payments = db(
        (db.b2c_payment.b2c_id == session.b2c_id) &
        (db.b2c_payment.paid_date == None)
    ).select(orderby=db.b2c_payment.due_date, limitby=(0, 3))

    return dict(
        borrower=borrower,
        mfi=mfi,
        balance=balance,
        repayment_percentage=repayment_percentage,
        work_activities=work_activities,
        recent_signals=recent_signals,
        pending_offers=pending_offers,
        recent_timeline=recent_timeline,
        upcoming_payments=upcoming_payments
    )


# ---------------------------------------------------------------------
# MY ACTIVITIES - Manage work activities
# ---------------------------------------------------------------------
@b2c_requires_login
def my_activities():
    """Manage work activities (borrower-defined)"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get all activities (active and inactive)
    activities = db(db.work_activity.b2c_id == session.b2c_id).select(
        orderby=~db.work_activity.is_active|db.work_activity.activity_name
    )

    # Count active activities
    active_count = db(
        (db.work_activity.b2c_id == session.b2c_id) &
        (db.work_activity.is_active == True)
    ).count()

    # Form to add new activity (max 5)
    if active_count < 5:
        form = SQLFORM.factory(
            Field('activity_name', 'string', label="Activity Name",
                  requires=IS_NOT_EMPTY(),
                  comment="e.g., 'Weekly market sales', 'Tailoring orders'"),
            Field('description', 'text', label="Description (Optional)",
                  comment="What does this activity involve?"),
            submit_button="Add Activity"
        )

        if form.process(formname='add_activity').accepted:
            db.work_activity.insert(
                b2c_id=session.b2c_id,
                activity_name=form.vars.activity_name,
                description=form.vars.description,
                is_active=True
            )
            session.flash = "Activity added successfully"
            redirect(URL('my_activities'))
    else:
        form = None

    return dict(
        borrower=borrower,
        activities=activities,
        active_count=active_count,
        form=form
    )


@b2c_requires_login
def toggle_activity():
    """Toggle activity active/inactive"""
    activity_id = request.args(0, cast=int)
    if activity_id:
        activity = db.work_activity(activity_id)
        if activity and activity.b2c_id == session.b2c_id:
            activity.update_record(is_active=not activity.is_active)
            session.flash = "Activity updated"
    redirect(URL('my_activities'))


@b2c_requires_login
def delete_activity():
    """Delete a work activity"""
    activity_id = request.args(0, cast=int)
    if activity_id:
        activity = db.work_activity(activity_id)
        if activity and activity.b2c_id == session.b2c_id:
            # Delete associated signals first
            db(db.daily_signal.work_activity_id == activity_id).delete()
            db(db.work_activity.id == activity_id).delete()
            session.flash = "Activity deleted"
    redirect(URL('my_activities'))


# ---------------------------------------------------------------------
# DAILY SIGNAL - Report how things went
# ---------------------------------------------------------------------
@b2c_requires_login
def daily_signal():
    """Record daily signals for work activities"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get active activities
    activities = db(
        (db.work_activity.b2c_id == session.b2c_id) &
        (db.work_activity.is_active == True)
    ).select(orderby=db.work_activity.activity_name)

    if not activities:
        session.flash = "Please add some work activities first"
        redirect(URL('my_activities'))

    # Check if already signaled today
    today = datetime.now().date()
    today_signals = db(
        (db.daily_signal.b2c_id == session.b2c_id) &
        (db.daily_signal.signal_date == today)
    ).select()

    signaled_activity_ids = [s.work_activity_id for s in today_signals]

    # Form for each activity not yet signaled today
    forms = []
    for activity in activities:
        if activity.id not in signaled_activity_ids:
            form = SQLFORM.factory(
                Field('outcome', 'string', 
                      requires=IS_IN_SET(['BETTER', 'AS_EXPECTED', 'WORSE']),
                      widget=lambda field, value: SELECT(
                          OPTION('Better than expected', _value='BETTER'),
                          OPTION('As expected', _value='AS_EXPECTED'),
                          OPTION('Worse than expected', _value='WORSE'),
                          _name=field.name, _class='form-control'
                      )),
                Field('note', 'text', label="Note (Optional)",
                      comment="Brief context if needed"),
                hidden=dict(activity_id=activity.id),
                formname='signal_%s' % activity.id,
                submit_button="Record for: %s" % activity.activity_name
            )

            if form.process().accepted:
                db.daily_signal.insert(
                    b2c_id=session.b2c_id,
                    work_activity_id=activity.id,
                    signal_date=today,
                    outcome=form.vars.outcome,
                    note=form.vars.note
                )
                session.flash = "Signal recorded for: %s" % activity.activity_name
                redirect(URL('daily_signal'))

            forms.append((activity, form))

    return dict(
        borrower=borrower,
        forms=forms,
        today_signals=today_signals
    )


# ---------------------------------------------------------------------
# SIGNAL HISTORY
# ---------------------------------------------------------------------
@b2c_requires_login
def signal_history():
    """View history of signals"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get all signals with activity names
    signals = db(db.daily_signal.b2c_id == session.b2c_id).select(
        db.daily_signal.ALL,
        db.work_activity.activity_name,
        left=db.work_activity.on(
            db.daily_signal.work_activity_id == db.work_activity.id
        ),
        orderby=~db.daily_signal.signal_date,
        limitby=(0, 50)
    )

    return dict(borrower=borrower, signals=signals)


# ---------------------------------------------------------------------
# SUPPORT OFFERS - View and respond to MFI offers
# ---------------------------------------------------------------------
@b2c_requires_login
def support_offers():
    """View and respond to support offers from MFI"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get all offers (pending and responded)
    pending = db(
        (db.support_offer.b2c_id == session.b2c_id) &
        ((db.support_offer.borrower_response == 'PENDING') |
         (db.support_offer.borrower_response == None))
    ).select(orderby=~db.support_offer.created_on)

    responded = db(
        (db.support_offer.b2c_id == session.b2c_id) &
        (db.support_offer.borrower_response != None) &
        (db.support_offer.borrower_response != 'PENDING')
    ).select(orderby=~db.support_offer.responded_on, limitby=(0, 10))

    return dict(borrower=borrower, pending=pending, responded=responded)


@b2c_requires_login
def respond_offer():
    """Respond to a support offer"""
    offer_id = request.args(0, cast=int)
    if not offer_id:
        session.flash = "Invalid offer"
        redirect(URL('support_offers'))

    offer = db.support_offer(offer_id)
    if not offer or offer.b2c_id != session.b2c_id:
        session.flash = "Offer not found"
        redirect(URL('support_offers'))

    form = SQLFORM.factory(
        Field('response', 'string',
              requires=IS_IN_SET(['ACCEPTED', 'DECLINED', 'MODIFIED']),
              widget=lambda field, value: SELECT(
                  OPTION('Accept this offer', _value='ACCEPTED'),
                  OPTION('Decline this offer', _value='DECLINED'),
                  OPTION('Request modification', _value='MODIFIED'),
                  _name=field.name, _class='form-control'
              )),
        Field('note', 'text', label="Your response/comments"),
        submit_button="Send Response"
    )

    if form.process().accepted:
        respond_to_offer(offer_id, form.vars.response, form.vars.note)
        session.flash = "Response sent to MFI"
        redirect(URL('support_offers'))

    return dict(offer=offer, form=form)


# ---------------------------------------------------------------------
# FINANCES
# ---------------------------------------------------------------------
@b2c_requires_login
def finances():
    """View financial information and payment history"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported
    repayment_percentage = 0
    if borrower.amount_borrowed > 0:
        repayment_percentage = (borrower.amount_repaid_b2c_reported / 
                              borrower.amount_borrowed) * 100

    # Get all payments
    all_payments = db(db.b2c_payment.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_payment.due_date
    )

    # Calculate statistics
    total_payments = len(all_payments)
    on_time_payments = sum(1 for p in all_payments 
                          if p.days_late is not None and p.days_late <= 0)

    on_time_percentage = 0
    if total_payments > 0:
        on_time_percentage = (on_time_payments / total_payments) * 100

    return dict(
        borrower=borrower,
        mfi=mfi,
        balance=balance,
        repayment_percentage=repayment_percentage,
        all_payments=all_payments,
        total_payments=total_payments,
        on_time_payments=on_time_payments,
        on_time_percentage=on_time_percentage
    )


# ---------------------------------------------------------------------
# TIMELINE
# ---------------------------------------------------------------------
@b2c_requires_login
def timeline():
    """View complete timeline/journey"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    timeline_messages = db(
        db.b2c_timeline_message.b2c_id == session.b2c_id
    ).select(orderby=~db.b2c_timeline_message.the_date)

    return dict(borrower=borrower, timeline_messages=timeline_messages)


# ---------------------------------------------------------------------
# PROFILE MANAGEMENT
# ---------------------------------------------------------------------
@b2c_requires_login
def profile():
    """View and edit profile"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    form = SQLFORM(
        db.b2c,
        borrower,
        fields=['real_name', 'address', 'telephone', 'email', 'social_media'],
        submit_button="Update Profile"
    )

    if form.process().accepted:
        session.flash = "Profile updated successfully"
        redirect(URL('profile'))

    return dict(borrower=borrower, form=form)


@b2c_requires_login
def change_password():
    """Change password"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    form = SQLFORM.factory(
        Field('current_password', 'password', requires=IS_NOT_EMPTY()),
        Field('new_password', 'password', requires=IS_NOT_EMPTY()),
        Field('confirm_password', 'password', requires=IS_NOT_EMPTY()),
        submit_button="Change Password"
    )

    if form.process().accepted:
        try:
            password_bytes = form.vars.current_password.encode('utf-8')
            hash_bytes = (borrower.password_hash.encode('utf-8') 
                         if isinstance(borrower.password_hash, str) 
                         else borrower.password_hash)

            if not bcrypt.checkpw(password_bytes, hash_bytes):
                response.flash = "Current password is incorrect"
                return dict(form=form)

            if form.vars.new_password != form.vars.confirm_password:
                response.flash = "New passwords do not match"
                return dict(form=form)

            borrower.update_record(password_hash=form.vars.new_password)
            session.flash = "Password changed successfully"
            redirect(URL('dashboard'))
        except Exception as e:
            response.flash = "Error changing password"

    return dict(form=form)


# ---------------------------------------------------------------------
# INDEX
# ---------------------------------------------------------------------
def index():
    """Home page"""
    if session.b2c_id:
        redirect(URL('dashboard'))
    else:
        redirect(URL('login'))


# ---------------------------------------------------------------------
# FLYER MANAGEMENT (Existing functionality preserved)
# ---------------------------------------------------------------------

@b2c_requires_login
def editor():
    """Create or edit a flyer"""
    user_id = session.b2c_id
    flyer_id = request.args(0)
    flyers = db(db.flyer.b2c_id == user_id).select(orderby=~db.flyer.updated_on)
    current_flyer = None
    if flyer_id:
        current_flyer = db(
            (db.flyer.id == flyer_id) & (db.flyer.b2c_id == user_id)
        ).select().first()
        if not current_flyer:
            session.flash = "Flyer not found or access denied"
            redirect(URL('editor'))
    return dict(flyers=flyers, current_flyer=current_flyer, b2c_id=session.b2c_id)


@b2c_requires_login
def save():
    """Save flyer"""
    borrower = db.b2c(session.b2c_id)
    if not borrower:
        session.clear()
        redirect(URL('login'))

    flyer_id = request.vars.id
    title = (request.vars.title or '').strip()
    content = (request.vars.thecontent or '').strip()

    if not title or not content:
        session.flash = "Title and content required"
        redirect(URL('editor', args=[flyer_id] if flyer_id else []))

    if flyer_id:
        flyer = db.flyer(flyer_id)
        if flyer and flyer.b2c_id == session.b2c_id:
            flyer.update_record(title=title, thecontent=content)
            db.commit()
            session.flash = "Flyer updated"
            redirect(URL('editor', args=[flyer_id]))
    else:
        new_id = db.flyer.insert(
            b2c_id=session.b2c_id,
            title=title,
            thecontent=content
        )
        db.commit()
        session.flash = "Flyer created"
        redirect(URL('editor', args=[new_id]))


@b2c_requires_login
def preview():
    """Preview flyer"""
    flyer_id = request.args(0)
    if not flyer_id:
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer or flyer.b2c_id != session.b2c_id:
        session.flash = "Access denied"
        redirect(URL('editor'))

    html_content = markdown.markdown(
        flyer.thecontent or "",
        extensions=['extra', 'nl2br', 'tables']
    )
    return dict(flyer=flyer, html_content=html_content, b2c_id=session.b2c_id)


def view_flyer():
    """Public view of flyer"""
    flyer_id = request.args(0)
    if not flyer_id:
        raise HTTP(404)

    flyer = db.flyer(flyer_id)
    if not flyer:
        raise HTTP(404)

    db(db.flyer.id == flyer.id).update(view_count=db.flyer.view_count + 1)
    db.flyer_view.insert(flyer_id=flyer.id, viewer_ip=request.client)

    html_content = markdown.markdown(
        flyer.thecontent or "",
        extensions=['extra', 'nl2br', 'tables']
    )
    borrower = db.b2c(flyer.b2c_id)
    return dict(flyer=flyer, borrower=borrower, html_content=html_content,
                b2c_id=session.b2c_id)


@b2c_requires_login
def qr():
    """Generate QR code"""
    flyer_id = request.args(0)
    if not flyer_id:
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer or flyer.b2c_id != session.b2c_id:
        session.flash = "Access denied"
        redirect(URL('editor'))

    flyer_url = URL('view_flyer', args=[flyer.id], scheme=True, host=True)
    qr_img = qrcode.QRCode(version=1, box_size=10, border=4)
    qr_img.add_data(flyer_url)
    qr_img.make(fit=True)
    img = qr_img.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return dict(flyer=flyer, qr_image=img_str, flyer_url=flyer_url)


@b2c_requires_login
def delete():
    """Delete flyer"""
    flyer_id = request.args(0)
    if flyer_id:
        flyer = db.flyer(flyer_id)
        if flyer and flyer.b2c_id == session.b2c_id:
            db(db.flyer.id == flyer_id).delete()
            db.commit()
            session.flash = "Flyer deleted"
    redirect(URL('editor'))