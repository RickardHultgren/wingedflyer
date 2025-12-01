# -*- coding: utf-8 -*-

"""
Controller for Microfinance Institution (MFI) accounts
MFIs have their own authentication separate from admin Auth
"""

import bcrypt

# ============================================================
# MFI AUTHENTICATION FUNCTIONS
# ============================================================

def login():
    """
    MFI login page - separate from admin auth system
    """
    if session.mfi_id:
        redirect(URL('index'))
    
    form = FORM(
        DIV(
            LABEL('Username:', _for='username'),
            INPUT(_name='username', _id='username', _class='form-control', requires=IS_NOT_EMPTY()),
            _class='form-group'
        ),
        DIV(
            LABEL('Password:', _for='password'),
            INPUT(_name='password', _type='password', _id='password', _class='form-control', requires=IS_NOT_EMPTY()),
            _class='form-group'
        ),
        DIV(
            INPUT(_type='submit', _value='Login', _class='btn btn-primary'),
            _class='form-group'
        )
    )
    
    if form.accepts(request.vars, session):
        username = form.vars.username
        password = form.vars.password
        
        # Look up MFI by username
        mfi = db(db.mfi.username == username).select().first()
        
        if mfi and mfi.password_hash:
            # Verify password using bcrypt
            if bcrypt.checkpw(password.encode('utf-8'), mfi.password_hash.encode('utf-8')):
                # Login successful
                session.mfi_id = mfi.id
                session.mfi_username = mfi.username
                session.mfi_name = mfi.name
                session.flash = 'Welcome, %s' % mfi.name
                redirect(URL('index'))
            else:
                response.flash = 'Invalid username or password'
        else:
            response.flash = 'Invalid username or password'
    
    return dict(form=form)


def logout():
    """
    MFI logout
    """
    session.mfi_id = None
    session.mfi_username = None
    session.mfi_name = None
    session.flash = 'Logged out successfully'
    redirect(URL('login'))


def requires_mfi_login(f):
    """
    Decorator to require MFI login
    """
    def wrapper(*args, **kwargs):
        if not session.mfi_id:
            session.flash = 'Please login first'
            redirect(URL('login'))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
# MFI DASHBOARD
# ============================================================

@requires_mfi_login
def index():
    """
    Landing page for MFI users.
    Displays the list of B2C accounts owned by this MFI.
    """
    mfi_id = session.mfi_id
    mfi = db.mfi(mfi_id)
    
    if not mfi:
        session.flash = 'MFI account not found'
        redirect(URL('logout'))
    
    # Get all B2C accounts for this MFI
    b2c_accounts = db(db.b2c.mfi_id == mfi_id).select(orderby=db.b2c.real_name)
    
    # Count actual B2C accounts
    actual_count = len(b2c_accounts)
    allowed_count = mfi.b2c_accounts
    
    # Can create more accounts?
    can_create = actual_count < allowed_count
    
    return dict(
        mfi=mfi,
        b2c_accounts=b2c_accounts,
        actual_count=actual_count,
        allowed_count=allowed_count,
        can_create=can_create
    )


# ============================================================
# B2C ACCOUNT MANAGEMENT
# ============================================================

@requires_mfi_login
def create_b2c():
    """
    Create a new B2C account
    """
    mfi_id = session.mfi_id
    mfi = db.mfi(mfi_id)
    
    if not mfi:
        session.flash = 'MFI account not found'
        redirect(URL('logout'))
    
    # Check if MFI can create more accounts
    current_count = db(db.b2c.mfi_id == mfi_id).count()
    if current_count >= mfi.b2c_accounts:
        session.flash = 'You have reached your maximum number of B2C accounts (%d)' % mfi.b2c_accounts
        redirect(URL('index'))
    
    # Create form for B2C account
    db.b2c.mfi_id.default = mfi_id
    db.b2c.mfi_id.writable = False
    db.b2c.mfi_id.readable = False
    
    form = SQLFORM(db.b2c)
    
    if form.process().accepted:
        # Auto-generate password if not provided
        b2c_id = form.vars.id
        if not form.vars.password_hash:
            import random
            import string
            # Generate random password
            password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            # Hash it
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db(db.b2c.id == b2c_id).update(password_hash=hashed)
            session.flash = 'B2C account created! Generated password: %s (save this!)' % password
        else:
            session.flash = 'B2C account created successfully'
        
        redirect(URL('view_b2c', args=[b2c_id]))
    
    return dict(form=form, mfi=mfi)


@requires_mfi_login
def view_b2c():
    """
    View and manage a specific B2C account
    """
    mfi_id = session.mfi_id
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = 'Invalid B2C account'
        redirect(URL('index'))
    
    b2c = db.b2c(b2c_id)
    
    # Verify ownership
    if not b2c or b2c.mfi_id != mfi_id:
        session.flash = 'B2C account not found or unauthorized'
        redirect(URL('index'))
    
    # Get timeline messages
    timeline_messages = db(db.b2c_timeline_message.b2c_id == b2c_id).select(
        orderby=~db.b2c_timeline_message.the_date
    )
    
    # Get urgent message
    urgent_message = db(db.b2c_urgent_message.b2c_id == b2c_id).select().first()
    
    # Get view logs
    view_logs = db(db.b2c_micro_page_view.b2c_id == b2c_id).select(
        orderby=~db.b2c_micro_page_view.viewed_on,
        limitby=(0, 10)
    )
    total_views = db(db.b2c_micro_page_view.b2c_id == b2c_id).count()
    
    # Generate URLs
    micro_page_url = URL('b2c_public', 'micropage', args=[b2c.username], scheme=True, host=True)
    qr_code_url = URL('generate_qr', vars=dict(data=micro_page_url))
    
    return dict(
        b2c=b2c,
        timeline_messages=timeline_messages,
        urgent_message=urgent_message,
        view_logs=view_logs,
        total_views=total_views,
        micro_page_url=micro_page_url,
        qr_code_url=qr_code_url
    )


@requires_mfi_login
def edit_b2c():
    """
    Edit B2C account details
    """
    mfi_id = session.mfi_id
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = 'Invalid B2C account'
        redirect(URL('index'))
    
    b2c = db.b2c(b2c_id)
    
    # Verify ownership
    if not b2c or b2c.mfi_id != mfi_id:
        session.flash = 'B2C account not found or unauthorized'
        redirect(URL('index'))
    
    # Make mfi_id non-editable
    db.b2c.mfi_id.writable = False
    db.b2c.mfi_id.readable = False
    
    form = SQLFORM(db.b2c, b2c, deletable=True)
    
    if form.process().accepted:
        if form.vars.get('delete_this_record') == 'on':
            session.flash = 'B2C account deleted'
            redirect(URL('index'))
        else:
            session.flash = 'B2C account updated'
            redirect(URL('view_b2c', args=[b2c_id]))
    
    return dict(form=form, b2c=b2c)


@requires_mfi_login
def update_amounts():
    """
    Update borrowed and repaid amounts for a B2C account
    """
    mfi_id = session.mfi_id
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = 'Invalid B2C account'
        redirect(URL('index'))
    
    b2c = db.b2c(b2c_id)
    
    # Verify ownership
    if not b2c or b2c.mfi_id != mfi_id:
        session.flash = 'B2C account not found or unauthorized'
        redirect(URL('index'))
    
    form = SQLFORM.factory(
        Field('amount_borrowed', 'double', default=b2c.amount_borrowed, label='Amount Borrowed'),
        Field('amount_repaid_b2c_reported', 'double', default=b2c.amount_repaid_b2c_reported, label='Amount Repaid'),
        submit_button='Update Amounts'
    )
    
    if form.process().accepted:
        db(db.b2c.id == b2c_id).update(
            amount_borrowed=form.vars.amount_borrowed,
            amount_repaid_b2c_reported=form.vars.amount_repaid_b2c_reported
        )
        session.flash = 'Amounts updated successfully'
        redirect(URL('view_b2c', args=[b2c_id]))
    
    return dict(form=form, b2c=b2c)


# ============================================================
# MESSAGES
# ============================================================

@requires_mfi_login
def add_timeline_message():
    """
    Add a timeline message for a B2C account
    """
    mfi_id = session.mfi_id
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = 'Invalid B2C account'
        redirect(URL('index'))
    
    b2c = db.b2c(b2c_id)
    
    # Verify ownership
    if not b2c or b2c.mfi_id != mfi_id:
        session.flash = 'B2C account not found or unauthorized'
        redirect(URL('index'))
    
    db.b2c_timeline_message.b2c_id.default = b2c_id
    db.b2c_timeline_message.b2c_id.writable = False
    db.b2c_timeline_message.b2c_id.readable = False
    
    form = SQLFORM(db.b2c_timeline_message)
    
    if form.process().accepted:
        session.flash = 'Timeline message added'
        redirect(URL('view_b2c', args=[b2c_id]))
    
    return dict(form=form, b2c=b2c)


@requires_mfi_login
def set_urgent_message():
    """
    Set or update urgent message for a B2C account
    """
    mfi_id = session.mfi_id
    b2c_id = request.args(0, cast=int)
    
    if not b2c_id:
        session.flash = 'Invalid B2C account'
        redirect(URL('index'))
    
    b2c = db.b2c(b2c_id)
    
    # Verify ownership
    if not b2c or b2c.mfi_id != mfi_id:
        session.flash = 'B2C account not found or unauthorized'
        redirect(URL('index'))
    
    # Check if urgent message exists
    urgent = db(db.b2c_urgent_message.b2c_id == b2c_id).select().first()
    
    if urgent:
        form = SQLFORM(db.b2c_urgent_message, urgent)
    else:
        db.b2c_urgent_message.b2c_id.default = b2c_id
        db.b2c_urgent_message.b2c_id.writable = False
        db.b2c_urgent_message.b2c_id.readable = False
        form = SQLFORM(db.b2c_urgent_message)
    
    if form.process().accepted:
        session.flash = 'Urgent message updated'
        redirect(URL('view_b2c', args=[b2c_id]))
    
    return dict(form=form, b2c=b2c)


# ============================================================
# QR CODE GENERATION
# ============================================================

def generate_qr():
    """
    Generate a QR code for any URL
    """
    try:
        import qrcode
        from io import BytesIO
    except ImportError:
        return "QR code library not installed"
    
    data = request.vars.data or "https://wingedflyer.com"
    
    # Create QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to BytesIO
    stream = BytesIO()
    img.save(stream, format='PNG')
    stream.seek(0)
    
    response.headers['Content-Type'] = 'image/png'
    return stream.read()


# ============================================================
# PUBLIC B2C MICROPAGE (accessible without login)
# ============================================================

def b2c_public():
    """
    Public controller for B2C micropages
    This should be in a separate controller, but included here for completeness
    """
    return dict(message="B2C Public Controller")


def micropage():
    """
    Public-facing micropage for a B2C account
    Accessible by anyone with the link
    """
    username = request.args(0)
    
    if not username:
        return dict(error='Invalid URL')
    
    # Find B2C account
    b2c = db(db.b2c.username == username).select().first()
    
    if not b2c:
        return dict(error='B2C account not found')
    
    # Log the view
    viewer_ip = request.env.remote_addr
    db.b2c_micro_page_view.insert(
        b2c_id=b2c.id,
        viewer_ip=viewer_ip
    )
    
    # Get timeline messages
    timeline_messages = db(db.b2c_timeline_message.b2c_id == b2c.id).select(
        orderby=~db.b2c_timeline_message.the_date
    )
    
    # Get urgent message
    urgent_message = db(db.b2c_urgent_message.b2c_id == b2c.id).select().first()
    
    # Calculate repayment progress
    if b2c.amount_borrowed > 0:
        repayment_percentage = (b2c.amount_repaid_b2c_reported / b2c.amount_borrowed) * 100
    else:
        repayment_percentage = 0
    
    return dict(
        b2c=b2c,
        timeline_messages=timeline_messages,
        urgent_message=urgent_message,
        repayment_percentage=repayment_percentage
    )