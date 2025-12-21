# -*- coding: utf-8 -*-
"""
WingedFlyer MFI Portal Controller (refined and debugged)
"""

import bcrypt


# ---------------------------------------------------------------------
# MFI LOGIN (uses mfi table, NOT auth)
# ---------------------------------------------------------------------
def login():
    """
    Login screen for MFIs.
    Uses db.mfi (username + bcrypt)
    """
    if session.mfi_id:
        redirect(URL('dashboard'))

    form = FORM(
        DIV(
            LABEL("Username"),
            INPUT(_name='username', _class='form-control', requires=IS_NOT_EMPTY()),
            LABEL("Password", _style="margin-top:10px"),
            INPUT(_name='password', _type='password', _class='form-control', requires=IS_NOT_EMPTY()),
            INPUT(_type='submit', _value='Login', _class='btn btn-primary', _style="margin-top:15px"),
            _class='form-group'
        )
    )

    if form.accepts(request, session):
        username = form.vars.username
        password = form.vars.password
        
        user = db(db.mfi.username == username).select().first()

        if user and user.password_hash:
            try:
                # Ensure both are bytes for comparison
                password_bytes = password.encode('utf-8')
                hash_bytes = user.password_hash.encode('utf-8') if isinstance(user.password_hash, str) else user.password_hash
                
                if bcrypt.checkpw(password_bytes, hash_bytes):
                    session.mfi_id = user.id
                    session.mfi_name = user.name
                    session.mfi_username = user.username
                    redirect(URL('dashboard'))
                else:
                    response.flash = "Invalid username or password"
            except Exception as e:
                response.flash = "Login error. Please contact administrator."
                print("Login error: %s" % str(e))  # Log for debugging
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


# ------------------------------------------------------------
# REQUIRE LOGIN DECORATOR FOR MFI PORTAL
# ------------------------------------------------------------
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
# MFI DASHBOARD – LIST ALL B2C ACCOUNTS
# ---------------------------------------------------------------------
@mfi_requires_login
def dashboard():
    """Landing page for MFI users - shows all their B2C accounts"""
    mfi_record = db.mfi(session.mfi_id)
    
    if not mfi_record:
        session.clear()
        redirect(URL('login'))
    
    b2c_accounts = db(db.b2c.mfi_id == session.mfi_id).select(
        orderby=db.b2c.real_name
    )
    
    # Calculate statistics
    current_count = len(b2c_accounts)
    max_accounts = mfi_record.b2c_accounts
    
    return dict(
        b2c_accounts=b2c_accounts,
        mfi=session.mfi_name,
        current_count=current_count,
        max_accounts=max_accounts
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
        session.flash = "You have reached your maximum B2C account limit (%d)" % mfi_record.b2c_accounts
        redirect(URL('dashboard'))

    # Set field attributes before creating the form
    db.b2c.mfi_id.writable = False
    db.b2c.mfi_id.readable = False

    form = SQLFORM(db.b2c)
    form.vars.mfi_id = session.mfi_id
    
    if form.process().accepted:
        session.flash = "B2C account created successfully"
        redirect(URL('b2c', args=[form.vars.id]))
    elif form.errors:
        response.flash = "Please correct the errors in the form"
    
    return dict(form=form, current_count=current_count, max_accounts=mfi_record.b2c_accounts)


# ---------------------------------------------------------------------
# VIEW / MANAGE A SINGLE B2C ACCOUNT
# ---------------------------------------------------------------------
@mfi_requires_login
def b2c():
    """
    View & manage a single b2c borrower:
        - Basic info
        - Repayments tracking
        - Timeline messages
        - Urgent message
        - Micro-page link and QR code
    """
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = "Invalid B2C account"
        redirect(URL('dashboard'))
    
    borrower = db.b2c(b2c_id)

    if not borrower or borrower.mfi_id != session.mfi_id:
        session.flash = "Unauthorized access"
        redirect(URL('dashboard'))

    # Get timeline messages
    timeline = db(db.b2c_timeline_message.b2c_id == b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date
    )
    
    # Get current urgent message
    current_urgent = db(db.b2c_urgent_message.b2c_id == b2c_id).select().first()

    # Timeline message form
    timeline_form = SQLFORM.factory(
        Field('title', 'string', label="Title", requires=IS_NOT_EMPTY()),
        Field('message', 'text', label="Message"),
        Field('date', 'datetime', label="Date", default=request.now),
        submit_button="Add Timeline Message"
    )
    
    if timeline_form.process(formname='timeline').accepted:
        db.b2c_timeline_message.insert(
            b2c_id=b2c_id,
            title=timeline_form.vars.title,
            the_message=timeline_form.vars.message,
            the_date=timeline_form.vars.date
        )
        session.flash = "Timeline message added"
        redirect(URL('b2c', args=[b2c_id]))

    # Urgent message form
    urgent_form = SQLFORM.factory(
        Field('urgent_text', 'text', label="Urgent Message", 
              default=current_urgent.the_message if current_urgent else ""),
        submit_button="Update Urgent Message"
    )
    
    if urgent_form.process(formname='urgent').accepted:
        db.b2c_urgent_message.update_or_insert(
            (db.b2c_urgent_message.b2c_id == b2c_id),
            b2c_id=b2c_id,
            the_message=urgent_form.vars.urgent_text
        )
        session.flash = "Urgent message updated"
        redirect(URL('b2c', args=[b2c_id]))

    # Repayment tracking form
    repay_form = SQLFORM.factory(
        Field('amount_borrowed', 'double', label="Amount Borrowed",
              default=borrower.amount_borrowed, requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        Field('amount_repaid', 'double', label="Amount Repaid (B2C Reported)",
              default=borrower.amount_repaid_b2c_reported, requires=IS_FLOAT_IN_RANGE(0, 1e10)),
        submit_button="Update Amounts"
    )
    
    if repay_form.process(formname='repay').accepted:
        borrower.update_record(
            amount_borrowed=repay_form.vars.amount_borrowed,
            amount_repaid_b2c_reported=repay_form.vars.amount_repaid
        )
        session.flash = "Repayment amounts updated"
        redirect(URL('b2c', args=[b2c_id]))

    # Micro-page URL and QR code
    micro_page_url = URL('micro', args=[borrower.username], scheme=True, host=True)
    qr_url = URL('qr', vars=dict(data=micro_page_url), scheme=True, host=True)
    
    # Calculate remaining balance
    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported

    return dict(
        borrower=borrower,
        timeline=timeline,
        timeline_form=timeline_form,
        urgent_form=urgent_form,
        repay_form=repay_form,
        micro_page_url=micro_page_url,
        qr_url=qr_url,
        balance=balance
    )


# ---------------------------------------------------------------------
# EDIT B2C PROFILE
# ---------------------------------------------------------------------
@mfi_requires_login
def edit_b2c():
    """Edit B2C borrower profile information"""
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
                          'telephone', 'email', 'social_media', 'micro_page_text',
                          'location_lat', 'location_lng', 'started_working_today'])
    
    if form.process().accepted:
        session.flash = "B2C profile updated"
        redirect(URL('b2c', args=[b2c_id]))
    elif form.errors:
        response.flash = "Please correct the errors"
    
    return dict(form=form, borrower=borrower)


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
# PUBLIC MICRO PAGE (no login required)
# ---------------------------------------------------------------------
def micro():
    """Public-facing micro-page for a B2C borrower"""
    username = request.args(0)
    
    if not username:
        return "Borrower not found"
    
    borrower = db(db.b2c.username == username).select().first()

    if not borrower:
        return "Borrower not found"
    
    # Log the view
    db.b2c_micro_page_view.insert(
        b2c_id=borrower.id,
        viewer_ip=request.client
    )
    
    # Get timeline and urgent message
    timeline = db(db.b2c_timeline_message.b2c_id == borrower.id).select(
        orderby=~db.b2c_timeline_message.the_date
    )
    urgent_msg = db(db.b2c_urgent_message.b2c_id == borrower.id).select().first()
    
    # Calculate balance
    balance = borrower.amount_borrowed - borrower.amount_repaid_b2c_reported
    
    return dict(
        borrower=borrower,
        timeline=timeline,
        urgent_msg=urgent_msg,
        balance=balance
    )


# ---------------------------------------------------------------------
# QR CODE GENERATOR (no login required)
# ---------------------------------------------------------------------
def qr():
    """Generate QR code for a given URL"""
    import qrcode
    try:
        from io import BytesIO
    except ImportError:
        import cStringIO as BytesIO

    data = request.vars.data or "https://wingedflyer.com"
    
    buf = BytesIO()
    img = qrcode.make(data)
    img.save(buf, 'PNG')
    buf.seek(0)

    response.headers['Content-Type'] = 'image/png'
    response.headers['Cache-Control'] = 'max-age=3600'
    
    return buf.read()
