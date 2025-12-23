# -*- coding: utf-8 -*-
#controllers/b2c.py
"""
WingedFlyer B2C Borrower Portal Controller with Traffic Light System
Allows borrowers to manage their own profiles and communicate with MFI
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
# B2C LOGIN
# ---------------------------------------------------------------------
def login():
    """
    Login screen for B2C borrowers.
    Uses db.b2c (username + bcrypt)
    """
    if session.b2c_id:
        redirect(URL('dashboard'))

    form = FORM(
        DIV(
            LABEL("Username"),
            INPUT(_name='username', _class='form-control', requires=IS_NOT_EMPTY()),
            LABEL("Password", _style="margin-top:10px"),
            INPUT(_name='password', _type='password', _class='form-control', requires=IS_NOT_EMPTY()),
            INPUT(_type='submit', _value='Login', _class='btn btn-success', _style="margin-top:15px"),
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
                hash_bytes = borrower.password_hash.encode('utf-8') if isinstance(borrower.password_hash, str) else borrower.password_hash

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


# ------------------------------------------------------------
# REQUIRE LOGIN DECORATOR FOR B2C PORTAL
# ------------------------------------------------------------
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
# B2C DASHBOARD - Main landing page with Traffic Light Status
# ---------------------------------------------------------------------
@b2c_requires_login
def dashboard():
    """Main dashboard for B2C borrowers with traffic light status"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get MFI information
    mfi = db.mfi(borrower.mfi_id)

    # Get traffic light protocol
    #protocol = get_borrower_protocol(session.b2c_id)

    # Calculate financial summary
    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported
    repayment_percentage = 0
    if borrower.amount_borrowed > 0:
        repayment_percentage = (borrower.amount_repaid_b2c_reported / borrower.amount_borrowed) * 100

    # Get recent timeline messages
    recent_timeline = db(db.b2c_timeline_message.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date,
        limitby=(0, 5)
    )

    
    # Get urgent message
    #urgent_msg = db(db.b2c_urgent_message.b2c_id == session.b2c_id).select().first()
    

    # Get recent payments (last 5)
    recent_payments = db(db.b2c_payment.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_payment.due_date,
        limitby=(0, 5)
    )

    '''
    # Get micro-page stats
    #view_count = db(db.b2c_micro_page_view.b2c_id == session.b2c_id).count()
    #recent_views = db(db.b2c_micro_page_view.b2c_id == session.b2c_id).select(
    #    orderby=~db.b2c_micro_page_view.viewed_on,
    #    limitby=(0, 10)
    #)

    # Micro-page URL
    #micro_page_url = URL('mfi', 'micro', args=[borrower.username], scheme=True, host=True)
    #qr_url = URL('mfi', 'qr', vars=dict(data=micro_page_url), scheme=True, host=True)
    '''

    return dict(
        borrower=borrower,
        mfi=mfi,
        #protocol=protocol,
        balance=balance,
        repayment_percentage=repayment_percentage,
        recent_timeline=recent_timeline,
        recent_payments=recent_payments#,
        #urgent_msg=urgent_msg,
        #view_count=view_count,
        #recent_views=recent_views,
        #micro_page_url=micro_page_url,
        #qr_url=qr_url
    )


# ---------------------------------------------------------------------
# MY STATUS - Detailed view of traffic light status
# ---------------------------------------------------------------------
@b2c_requires_login
def my_status():
    """Detailed view of borrower's traffic light status"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)
    #protocol = get_borrower_protocol(session.b2c_id)

    # Get detailed scoring breakdown
    status, score, breakdown = calculate_traffic_light_status(session.b2c_id)

    # Get recent payments for analysis
    recent_payments = db(db.b2c_payment.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_payment.due_date,
        limitby=(0, 6)
    )

    # Get recent communications
    recent_comms = db(db.b2c_communication.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_communication.communication_date,
        limitby=(0, 10)
    )

    # Calculate payment statistics
    if recent_payments:
        on_time_count = sum(1 for p in recent_payments if p.days_late <= 0)
        avg_days_late = sum(p.days_late for p in recent_payments if p.days_late is not None) / len(recent_payments)
    else:
        on_time_count = 0
        avg_days_late = 0

    # Calculate communication statistics
    mfi_initiated = sum(1 for c in recent_comms if c.initiated_by == 'MFI')
    borrower_initiated = sum(1 for c in recent_comms if c.initiated_by == 'BORROWER')
    proactive_count = sum(1 for c in recent_comms if c.is_proactive)

    return dict(
        borrower=borrower,
        mfi=mfi#,
        #protocol=protocol#,
        #score=score,
        #breakdown=breakdown,
        #recent_payments=recent_payments,
        #recent_comms=recent_comms,
        #on_time_count=on_time_count,
        #avg_days_late=avg_days_late,
        #mfi_initiated=mfi_initiated,
        #borrower_initiated=borrower_initiated,
        #proactive_count=proactive_count
    )

'''
# ---------------------------------------------------------------------
# COMMUNICATE WITH MFI - Proactive communication
# ---------------------------------------------------------------------
@b2c_requires_login
def communicate():
    """Send proactive communication to MFI"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    # Communication form
    form = SQLFORM.factory(
        Field('communication_type', 'string', label="Type of Communication",
              requires=IS_IN_SET(['PROACTIVE_WARNING', 'EMAIL', 'CALL']),
              comment="Choose 'Proactive Warning' if reporting a problem before it happens"),
        Field('subject', 'string', label="Subject", requires=IS_NOT_EMPTY()),
        Field('message', 'text', label="Message", requires=IS_NOT_EMPTY()),
        Field('is_about_payment', 'boolean', label="This is about an upcoming payment",
              comment="Check if you're warning about a payment issue"),
        submit_button="Send to MFI"
    )

    if form.process().accepted:
        # Determine if this is proactive
        is_proactive = (form.vars.communication_type == 'PROACTIVE_WARNING' or
                       form.vars.is_about_payment)

        # Log the communication
        db.b2c_communication.insert(
            b2c_id=session.b2c_id,
            initiated_by='BORROWER',
            communication_type=form.vars.communication_type,
            is_proactive=is_proactive,
            message_summary="%s: %s" % (form.vars.subject, form.vars.message)
        )

        # Also create a timeline message for MFI to see
        db.b2c_timeline_message.insert(
            b2c_id=session.b2c_id,
            title="[From Borrower] " + form.vars.subject,
            the_message=form.vars.message,
            the_date=request.now
        )

        # Update traffic light status
        update_borrower_traffic_light(session.b2c_id,
                                      notes="Borrower proactive communication")

        session.flash = "Message sent to your MFI. Your communication improves your trust status!"
        redirect(URL('dashboard'))

    return dict(borrower=borrower, mfi=mfi, form=form)
'''

# ---------------------------------------------------------------------
# REPORT PAYMENT - Let borrower log their own payments
# ---------------------------------------------------------------------
@b2c_requires_login
def report_payment():
    """Allow borrower to report a payment they made"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    # Get upcoming/recent due dates from existing payments
    upcoming_payments = db(
        (db.b2c_payment.b2c_id == session.b2c_id) &
        (db.b2c_payment.paid_date == None)
    ).select(orderby=db.b2c_payment.due_date)

    form = SQLFORM.factory(
        Field('amount', 'double', label="Payment Amount",
              requires=IS_NOT_EMPTY(),
              comment="Amount you paid"),
        Field('paid_date', 'date', label="Date You Paid",
              default=request.now.date(),
              requires=IS_NOT_EMPTY()),
        Field('payment_method', 'string', label="Payment Method",
              requires=IS_IN_SET(['Cash', 'Mobile Money', 'Bank Transfer', 'Other'])),
        Field('notes', 'text', label="Notes",
              comment="Any additional information about this payment"),
        submit_button="Report Payment"
    )

    if form.process().accepted:
        # Find if there's a matching due payment
        matching_payment = db(
            (db.b2c_payment.b2c_id == session.b2c_id) &
            (db.b2c_payment.paid_date == None)
        ).select(orderby=db.b2c_payment.due_date, limitby=(0,1)).first()

        if matching_payment:
            # Update existing payment record
            matching_payment.update_record(
                paid_date=form.vars.paid_date,
                payment_method=form.vars.payment_method,
                notes=form.vars.notes
            )
        else:
            # Create new payment record (borrower-initiated)
            db.b2c_payment.insert(
                b2c_id=session.b2c_id,
                amount=form.vars.amount,
                due_date=form.vars.paid_date,  # Use paid date as due date
                paid_date=form.vars.paid_date,
                payment_method=form.vars.payment_method,
                notes="Self-reported by borrower: " + (form.vars.notes or "")
            )

        # Log as communication
        db.b2c_communication.insert(
            b2c_id=session.b2c_id,
            initiated_by='BORROWER',
            communication_type='PROACTIVE_WARNING',
            is_proactive=True,
            message_summary="Payment reported: %.2f on %s" % (
                form.vars.amount,
                form.vars.paid_date
            )
        )

        # Update traffic light status
        update_borrower_traffic_light(session.b2c_id,
                                      notes="Borrower reported payment")

        session.flash = "Payment reported successfully. Your MFI will verify it."
        redirect(URL('finances'))

    return dict(
        borrower=borrower,
        mfi=mfi,
        form=form,
        upcoming_payments=upcoming_payments
    )


# ---------------------------------------------------------------------
# PROFILE MANAGEMENT
# ---------------------------------------------------------------------
@b2c_requires_login
def profile():
    """View and edit B2C profile"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Profile edit form
    form = SQLFORM(
        db.b2c,
        borrower,
        fields=['real_name', 'address', 'telephone', 'email',
                'social_media', 'micro_page_text', 'location_lat',
                'location_lng', 'started_working_today'],
        submit_button="Update Profile"
    )

    if form.process().accepted:
        session.flash = "Profile updated successfully"
        redirect(URL('profile'))
    elif form.errors:
        response.flash = "Please correct the errors"

    return dict(borrower=borrower, form=form)


# ---------------------------------------------------------------------
# CHANGE PASSWORD
# ---------------------------------------------------------------------
@b2c_requires_login
def change_password():
    """Change B2C password"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    form = SQLFORM.factory(
        Field('current_password', 'password', label="Current Password",
              requires=IS_NOT_EMPTY()),
        Field('new_password', 'password', label="New Password",
              requires=IS_NOT_EMPTY()),
        Field('confirm_password', 'password', label="Confirm New Password",
              requires=IS_NOT_EMPTY()),
        submit_button="Change Password"
    )

    if form.process().accepted:
        try:
            password_bytes = form.vars.current_password.encode('utf-8')
            hash_bytes = borrower.password_hash.encode('utf-8') if isinstance(borrower.password_hash, str) else borrower.password_hash

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
            print("Password change error: %s" % str(e))

    return dict(form=form)


# ---------------------------------------------------------------------
# FINANCIAL OVERVIEW WITH PAYMENT HISTORY
# ---------------------------------------------------------------------
@b2c_requires_login
def finances():
    """View detailed financial information with payment history"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    # Calculate statistics
    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported
    repayment_percentage = 0
    if borrower.amount_borrowed > 0:
        repayment_percentage = (borrower.amount_repaid_b2c_reported / borrower.amount_borrowed) * 100

    # Get all payments
    all_payments = db(db.b2c_payment.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_payment.due_date
    )

    # Calculate payment statistics
    total_payments = len(all_payments)
    on_time_payments = sum(1 for p in all_payments if p.days_late is not None and p.days_late <= 0)
    late_payments = sum(1 for p in all_payments if p.days_late is not None and p.days_late > 0)

    on_time_percentage = 0
    if total_payments > 0:
        on_time_percentage = (on_time_payments / total_payments) * 100

    # Get timeline of financial changes
    timeline = db(db.b2c_timeline_message.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date
    )

    return dict(
        borrower=borrower,
        mfi=mfi,
        balance=balance,
        repayment_percentage=repayment_percentage,
        all_payments=all_payments,
        total_payments=total_payments,
        on_time_payments=on_time_payments,
        late_payments=late_payments,
        on_time_percentage=on_time_percentage,
        timeline=timeline
    )


# ---------------------------------------------------------------------
# TIMELINE / JOURNEY
# ---------------------------------------------------------------------
@b2c_requires_login
def timeline():
    """View complete timeline/journey"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Get all timeline messages
    timeline_messages = db(db.b2c_timeline_message.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date
    )

    return dict(borrower=borrower, timeline_messages=timeline_messages)

'''
# ---------------------------------------------------------------------
# MICRO-PAGE MANAGEMENT
# ---------------------------------------------------------------------
@b2c_requires_login
def micropage():
    """Manage micro-page settings and view statistics"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    # Micro-page text update form
    form = SQLFORM.factory(
        Field('micro_page_text', 'text', label="About Me / Story",
              default=borrower.micro_page_text,
              comment="Tell your story to potential supporters"),
        Field('started_working_today', 'boolean', label="I am working today",
              default=borrower.started_working_today,
              comment="Update your work status"),
        submit_button="Update Micro-Page"
    )

    if form.process(formname='micropage').accepted:
        borrower.update_record(
            micro_page_text=form.vars.micro_page_text,
            started_working_today=form.vars.started_working_today
        )
        session.flash = "Micro-page updated successfully"
        redirect(URL('micropage'))

    # Get page views
    total_views = db(db.b2c_micro_page_view.b2c_id == session.b2c_id).count()
    recent_views = db(db.b2c_micro_page_view.b2c_id == session.b2c_id).select(
        orderby=~db.b2c_micro_page_view.viewed_on,
        limitby=(0, 20)
    )

    # Views by date
    today = datetime.now().date()
    views_today = db(
        (db.b2c_micro_page_view.b2c_id == session.b2c_id) &
        (db.b2c_micro_page_view.viewed_on >= today)
    ).count()

    week_ago = today - timedelta(days=7)
    views_this_week = db(
        (db.b2c_micro_page_view.b2c_id == session.b2c_id) &
        (db.b2c_micro_page_view.viewed_on >= week_ago)
    ).count()

    # Micro-page URLs
    micro_page_url = URL('mfi', 'micro', args=[borrower.username], scheme=True, host=True)
    qr_url = URL('mfi', 'qr', vars=dict(data=micro_page_url), scheme=True, host=True)

    return dict(
        borrower=borrower,
        form=form,
        total_views=total_views,
        views_today=views_today,
        views_this_week=views_this_week,
        recent_views=recent_views,
        micro_page_url=micro_page_url,
        qr_url=qr_url
    )


# ---------------------------------------------------------------------
# QR CODE DOWNLOAD
# ---------------------------------------------------------------------
@b2c_requires_login
def download_qr():
    """Download QR code as image file"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        redirect(URL('login'))

    micro_page_url = URL('mfi', 'micro', args=[borrower.username], scheme=True, host=True)

    # Generate QR code with higher quality
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(micro_page_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)

    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Disposition'] = 'attachment; filename="qr_%s.png"' % borrower.username

    return buf.read()


# ---------------------------------------------------------------------
# MESSAGES / COMMUNICATION WITH MFI
# ---------------------------------------------------------------------
@b2c_requires_login
def messages():
    """View urgent message from MFI"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    mfi = db.mfi(borrower.mfi_id)

    # Get urgent message
    urgent_msg = db(db.b2c_urgent_message.b2c_id == session.b2c_id).select().first()

    return dict(borrower=borrower, mfi=mfi, urgent_msg=urgent_msg)


# ---------------------------------------------------------------------
# CONTACT MFI (Legacy - redirects to new communicate function)
# ---------------------------------------------------------------------
@b2c_requires_login
def contact_mfi():
    """Redirect to new communicate function"""
    redirect(URL('communicate'))


# ---------------------------------------------------------------------
# HELP / INSTRUCTIONS
# ---------------------------------------------------------------------
@b2c_requires_login
def help():
    """Help page with instructions about traffic light system"""
    borrower = db.b2c(session.b2c_id)

    if not borrower:
        session.clear()
        redirect(URL('login'))

    protocol = get_borrower_protocol(session.b2c_id)

    return dict(borrower=borrower, protocol=protocol)
'''

# ---------------------------------------------------------------------
# INDEX
# ---------------------------------------------------------------------
def index():
    """Home page - redirect based on b2c status."""
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
        current_flyer = db((db.flyer.id == flyer_id) & (db.flyer.b2c_id == user_id)).select().first()
        if not current_flyer:
            session.flash = "Flyer not found or access denied"
            redirect(URL('editor'))

    return dict(
        flyers=flyers,
        current_flyer=current_flyer,
        b2c_id=session.b2c_id
    )



@b2c_requires_login
def save():
    """Save flyer with detailed debugging"""
    # Debug: Print what we received
    print("=== SAVE FUNCTION CALLED ===")
    print("request.vars:", request.vars)
    print("request.post_vars:", request.post_vars)

    borrower = db.b2c(session.b2c_id)
    if not borrower:
        print("ERROR: No borrower found")
        session.clear()
        redirect(URL('login'))

    # Get form data
    flyer_id = request.vars.id
    title = (request.vars.title or '').strip()
    content_from_form = (request.vars.thecontent or '').strip()

    print("flyer_id:", flyer_id)
    print("title:", title)
    print("content length:", len(content_from_form))

    # Check if we have required data
    if not title:
        print("ERROR: No title provided")
        session.flash = "Title is required"
        redirect(URL('editor', args=[flyer_id] if flyer_id else []))

    if not content_from_form:
        print("ERROR: No content provided")
        session.flash = "Content is required"
        redirect(URL('editor', args=[flyer_id] if flyer_id else []))

    if flyer_id:
        # UPDATE EXISTING FLYER
        print("Attempting to UPDATE flyer ID:", flyer_id)
        flyer = db.flyer(flyer_id)
        if flyer and flyer.b2c_id == session.b2c_id:
            print("Flyer found, updating...")
            flyer.update_record(title=title, thecontent=content_from_form)
            db.commit()  # Force commit
            print("Update successful!")
            session.flash = "Flyer updated successfully"
            redirect(URL('editor', args=[flyer_id]))
        else:
            print("ERROR: Flyer not found or access denied")
            session.flash = "Flyer not found or access denied"
            redirect(URL('editor'))
    else:
        # CREATE NEW FLYER
        print("Attempting to CREATE new flyer")
        print("b2c_id:", session.b2c_id)
        try:
            new_id = db.flyer.insert(
                b2c_id=session.b2c_id,
                title=title,
                thecontent=content_from_form
            )
            db.commit()  # Force commit
            print("Insert successful! New ID:", new_id)
            session.flash = "Flyer created successfully (ID: %s)" % new_id
            redirect(URL('editor', args=[new_id]))
        except Exception as e:
            print("ERROR during insert:", str(e))
            import traceback
            print(traceback.format_exc())
            session.flash = "Database error: %s" % str(e)
            redirect(URL('editor'))


@b2c_requires_login
def preview():
    """Preview with all required variables (private view)"""
    flyer_id = request.args(0) if request.args else None
    if not flyer_id:
        session.flash = "No flyer specified"
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer:
        session.flash = "Flyer not found"
        redirect(URL('editor'))

    if flyer.b2c_id != session.b2c_id:
        session.flash = "Access denied"
        redirect(URL('editor'))

    html_content = markdown.markdown(
        #flyer.flyer_content or "",
        flyer.thecontent or "",

        extensions=['extra', 'nl2br', 'tables']
    )
    return dict(
        flyer=flyer,
        html_content=html_content,
        b2c_id=session.b2c_id
    )


def view_flyer():
    """Public view of flyer, accessible without login"""
    flyer_id = request.args(0) if request.args else None
    if not flyer_id:
        raise HTTP(404, "Flyer not found")

    flyer = db.flyer(flyer_id)
    if not flyer:
        raise HTTP(404, "Flyer not found")

    db(db.flyer.id == flyer.id).update(view_count=db.flyer.view_count + 1)

    db.flyer_view.insert(
        flyer_id=flyer.id,
        viewer_ip=request.client,
        viewed_on=request.now
    )

    html_content = markdown.markdown(
        #flyer.flyer_content or "",
        flyer.thecontent or "",
        extensions=['extra', 'nl2br', 'tables']
    )
    borrower = db.b2c(flyer.b2c_id)
    return dict(
        flyer=flyer,
        borrower=borrower,
        html_content=html_content,
        b2c_id=session.b2c_id
    )


@b2c_requires_login
def view_b2c():
    """Redirect for public view button from the editor"""
    flyer_id = request.args(0) if request.args else None
    if not flyer_id:
        session.flash = "No flyer specified"
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer or flyer.b2c_id != session.b2c_id:
        session.flash = "Flyer not found or access denied"
        redirect(URL('editor'))

    redirect(URL('view_flyer', args=[flyer.id]))


@b2c_requires_login
def qr():
    """Generate QR code with all required variables (for the view)"""
    flyer_id = request.args(0) if request.args else None
    if not flyer_id:
        session.flash = "No flyer specified"
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer or flyer.b2c_id != session.b2c_id:
        session.flash = "Flyer not found or access denied"
        redirect(URL('editor'))

    flyer_url = URL('view_flyer', args=[flyer.id], scheme=True, host=True)

    qr_img = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr_img.add_data(flyer_url)
    qr_img.make(fit=True)
    img = qr_img.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return dict(
        flyer=flyer,
        qr_image=img_str,
        flyer_url=flyer_url
    )


@b2c_requires_login
def delete():
    """Delete flyer"""
    flyer_id = request.args(0) if request.args else None
    if not flyer_id:
        session.flash = "No flyer specified"
        redirect(URL('editor'))

    flyer = db.flyer(flyer_id)
    if not flyer:
        session.flash = "Flyer not found"
    elif flyer.b2c_id != session.b2c_id:
        session.flash = "Cannot delete this flyer"
    else:
        db(db.flyer.id == flyer_id).delete()
        db.commit()
        session.flash = "Flyer deleted successfully"

    redirect(URL('editor'))
