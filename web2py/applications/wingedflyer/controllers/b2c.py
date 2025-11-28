# -*- coding: utf-8 -*-
"""
Vendor-side controller for WingedFlyer.
Provides a minimal, low-bandwidth tool for vendors to:
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
    Vendor login/logout using default web2py auth.
    """
    return dict(form=auth())


def index():
    """
    Vendor dashboard.
    Shows:
      - Working status
      - Messages from MFI
      - Micro-page editor
      - Vendor account details
    """
    if not auth.is_logged_in():
        redirect(URL('user/login'))

    # Find this vendor account
    vendor = db(db.vendor_account.vendor_user_id == auth.user.id).select().first()
    if not vendor:
        session.flash = "Vendor account not found"
        redirect(URL('user/logout'))

    # Fetch messages
    messages = db(db.vendor_message.vendor_id == vendor.id).select(
        orderby=~db.vendor_message.created_on
    )

    # Fetch flyer (microwebpage)
    flyer = db(db.flyer.user_id == auth.user.id).select().first()

    return dict(
        vendor=vendor,
        messages=messages,
        flyer=flyer
    )


@auth.requires_login()
def toggle_working():
    """
    Vendor toggles 'working' checkbox.
    Lightweight and extremely fast.
    """
    vendor = db(db.vendor_account.vendor_user_id == auth.user.id).select().first()
    if not vendor:
        session.flash = "Vendor not found"
        redirect(URL('index'))

    vendor.update_record(is_working=not vendor.is_working)
    db.commit()

    session.flash = "Status updated"
    redirect(URL('index'))


@auth.requires_login()
def save_micro_page():
    """
    Save the vendor's public micro-webpage text.
    This is intentionally lightweight for low-bandwidth networks.
    """
    vendor = db(db.vendor_account.vendor_user_id == auth.user.id).select().first()
    if not vendor:
        session.flash = "Vendor not found"
        redirect(URL('index'))

    flyer = db(db.flyer.user_id == auth.user.id).select().first()

    # Create flyer if missing
    if not flyer:
        flyer_id = db.flyer.insert(
            user_id=auth.user.id,
            title="Vendor Micro Page",
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
    Vendor sends a simple message to MFI.
    Appears in MFI timeline.
    """
    vendor = db(db.vendor_account.vendor_user_id == auth.user.id).select().first()
    if not vendor:
        session.flash = "Vendor not found"
        redirect(URL('index'))

    text = (request.post_vars.message or "").strip()
    if not text:
        session.flash = "Message is empty"
        redirect(URL('index'))

    db.vendor_message.insert(
        vendor_id=vendor.id,
        sender='vendor',
        message=text
    )
    db.commit()

    session.flash = "Message sent to Microfinance Institution"
    redirect(URL('index'))


@auth.requires_login()
def preview():
    """
    Vendor preview of their public micro-webpage.
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
    /vendor/public/<username>
    """
    username = request.args(0)
    vendor = db(db.vendor_account.username == username).select().first()
    if not vendor:
        raise HTTP(404, "Vendor not found")

    flyer = db(db.flyer.user_id == vendor.vendor_user_id).select().first()

    if not flyer or not flyer.is_public:
        return dict(
            html_content="<p>This vendor has no public messages today.</p>",
            vendor=vendor
        )

    html = markdown.markdown(
        flyer.thecontent,
        extensions=['extra', 'nl2br', 'tables']
    )

    return dict(html_content=html, vendor=vendor, flyer=flyer)


def qr():
    """
    Return a QR code for the vendor's public customer-facing page.
    /vendor/qr/<username>
    """
    username = request.args(0)
    vendor = db(db.vendor_account.username == username).select().first()
    if not vendor:
        raise HTTP(404, "Vendor not found")

    public_url = URL('public', args=[vendor.username], scheme=True, host=True)

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
