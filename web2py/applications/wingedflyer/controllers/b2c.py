# -*- coding: utf-8 -*-
"""
b2c-side controller for WingedFlyer.
Provides a minimal, low-bandwidth tool for b2cs to:
  - View their borrowed/paid-back status
  - View messages from the MFI
  - Update their public micro-webpage text
  - Toggle working status
"""

import markdown
from io import BytesIO
import qrcode
import base64


def user():
    """
    b2c login/logout using default web2py auth.
    """
    return dict(form=auth())


def index():
    """
    b2c dashboard.
    Shows:
      - Working status
      - Messages from MFI
      - Micro-page editor
      - b2c account details
    """
    if not auth.is_logged_in():
        redirect(URL('user/login'))

    # Find this b2c account
    b2c = db(db.b2c_account.b2c_user_id == auth.user.id).select().first()
    if not b2c:
        session.flash = "b2c account not found"
        redirect(URL('user/logout'))

    # Fetch messages
    messages = db(db.b2c_message.b2c_id == b2c.id).select(
        orderby=~db.b2c_message.created_on
    )

    # Fetch flyer (microwebpage)
    flyer = db(db.flyer.user_id == auth.user.id).select().first()

    return dict(
        b2c=b2c,
        messages=messages,
        flyer=flyer
    )


@auth.requires_login()
def toggle_working():
    """
    b2c toggles 'working' checkbox.
    Lightweight and extremely fast.
    """
    b2c = db(db.b2c_account.b2c_user_id == auth.user.id).select().first()
    if not b2c:
        session.flash = "b2c not found"
        redirect(URL('index'))

    b2c.update_record(is_working=not b2c.is_working)
    db.commit()

    session.flash = "Status updated"
    redirect(URL('index'))


@auth.requires_login()
def save_micro_page():
    """
    Save the b2c's public micro-webpage text.
    This is intentionally lightweight for low-bandwidth networks.
    """
    b2c = db(db.b2c_account.b2c_user_id == auth.user.id).select().first()
    if not b2c:
        session.flash = "b2c not found"
        redirect(URL('index'))

    flyer = db(db.flyer.user_id == auth.user.id).select().first()

    # Create flyer if missing
    if not flyer:
        flyer_id = db.flyer.insert(
            user_id=auth.user.id,
            title="b2c Micro Page",
            thecontent="",
            is_public=True
        )
        flyer = db.flyer(flyer_id)

    new_text = (request.post_vars.text or "").strip()

    flyer.update_record(thecontent=new_text)
    db.commit()

    session.flash = "Your customer message has been updated"
    redirect(URL('index'))


@auth.requires_login()
def send_message():
    """
    b2c sends a simple message to MFI.
    Appears in MFI timeline.
    """
    b2c = db(db.b2c_account.b2c_user_id == auth.user.id).select().first()
    if not b2c:
        session.flash = "b2c not found"
        redirect(URL('index'))

    text = (request.post_vars.message or "").strip()
    if not text:
        session.flash = "Message is empty"
        redirect(URL('index'))

    db.b2c_message.insert(
        b2c_id=b2c.id,
        sender='b2c',
        message=text
    )
    db.commit()

    session.flash = "Message sent to Microfinance Institution"
    redirect(URL('index'))


@auth.requires_login()
def preview():
    """
    b2c preview of their public micro-webpage.
    """
    flyer = db(db.flyer.user_id == auth.user.id).select().first()

    if not flyer:
        html = "<p>No content yet.</p>"
    else:
        html = markdown.markdown(
            flyer.thecontent,
            extensions=['extra', 'nl2br', 'tables']
        )

    return dict(html_content=html, flyer=flyer)


def public():
    """
    Public customer-facing webpage:
    /b2c/public/<username>
    """
    username = request.args(0)
    b2c = db(db.b2c_account.username == username).select().first()
    if not b2c:
        raise HTTP(404, "b2c not found")

    flyer = db(db.flyer.user_id == b2c.b2c_user_id).select().first()

    if not flyer or not flyer.is_public:
        return dict(
            html_content="<p>This b2c has no public messages today.</p>",
            b2c=b2c
        )

    html = markdown.markdown(
        flyer.thecontent,
        extensions=['extra', 'nl2br', 'tables']
    )

    return dict(html_content=html, b2c=b2c, flyer=flyer)


def qr():
    """
    Return a QR code for the b2c's public customer-facing page.
    /b2c/qr/<username>
    """
    username = request.args(0)
    b2c = db(db.b2c_account.username == username).select().first()
    if not b2c:
        raise HTTP(404, "b2c not found")

    public_url = URL('public', args=[b2c.username], scheme=True, host=True)

    qr_img = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
    )
    qr_img.add_data(public_url)
    qr_img.make(fit=True)

    img = qr_img.make_image()
    buffer = BytesIO()
    img.save(buffer, format='PNG')

    response.headers['Content-Type'] = 'image/png'
    return buffer.getvalue()
