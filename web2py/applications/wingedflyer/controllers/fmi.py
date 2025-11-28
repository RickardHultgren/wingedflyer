# -*- coding: utf-8 -*-

"""
Controller for Microfinance Institution (MFI) accounts
"""

@auth.requires_login()
def index():
    """
    Landing page for MFI users.
    Displays the list of vendor accounts owned by this MFI.
    """
    if auth.user.role != 'mfi':
        redirect(URL('default', 'index'))

    vendors = db(db.vendor_account.mfi_user_id == auth.user.id).select()

    return dict(vendors=vendors)


@auth.requires_login()
def vendor():
    """
    Display a specific vendor account and allow the MFI to:
        - View vendor details
        - View generated login credentials
        - See working status
        - View/update borrowed/paid amounts
        - Send messages
        - View the micro-webpage and QR code
    """
    if auth.user.role != 'mfi':
        redirect(URL('default', 'index'))

    vendor_id = request.args(0, cast=int)

    vendor = db.vendor_account(vendor_id)
    if not vendor or vendor.mfi_user_id != auth.user.id:
        session.flash = "Vendor not found or unauthorized"
        redirect(URL('index'))

    # Messages between MFI and vendor
    messages = db(db.vendor_message.vendor_id == vendor_id).select(orderby=~db.vendor_message.created_on)

    # Send new urgent message
    urgent_form = SQLFORM.factory(
        Field('urgent_text', 'text', label="Send urgent message to vendor")
    )

    if urgent_form.process(formname='urgent').accepted:
        db.vendor_message.insert(
            vendor_id=vendor.id,
            sender='mfi',
            message=urgent_form.vars.urgent_text
        )
        session.flash = "Urgent message sent"
        redirect(URL('vendor', args=[vendor_id]))

    # Update repayment values
    repayment_form = SQLFORM.factory(
        Field('amount_borrowed', 'double', default=vendor.amount_borrowed),
        Field('amount_paid_back', 'double', default=vendor.amount_paid_back),
        submit_button="Update repayment"
    )

    if repayment_form.process(formname='repay').accepted:
        vendor.update_record(
            amount_borrowed=repayment_form.vars.amount_borrowed,
            amount_paid_back=repayment_form.vars.amount_paid_back
        )
        session.flash = "Repayment information updated"
        redirect(URL('vendor', args=[vendor_id]))

    # Generate QR code URL
    vendor_page_url = URL('vendor_side', 'index', args=[vendor.username], scheme=True, host=True)
    qr_code_url = URL('fmi', 'qr', vars=dict(data=vendor_page_url))

    return dict(
        vendor=vendor,
        messages=messages,
        urgent_form=urgent_form,
        repayment_form=repayment_form,
        vendor_page_url=vendor_page_url,
        qr_code_url=qr_code_url,
    )


def qr():
    """
    Generate a QR code for external use.
    """
    import qrcode
    import cStringIO

    data = request.vars.data or "empty"
    stream = cStringIO.StringIO()

    img = qrcode.make(data)
    img.save(stream, "PNG")

    response.headers['Content-Type'] = 'image/png'
    return stream.getvalue()


# --------------------------------------------------------------------
# Vendor-side controller endpoint (minimal)
# --------------------------------------------------------------------
def vendor_side():
    """
    Redirect for vendor micro-webpage.
    This assumes the vendor micro page is simply the vendor's flyer.
    """
    username = request.args(0)
    vendor = db(db.vendor_account.username == username).select().first()

    if not vendor:
        session.flash = "Vendor not found"
        redirect(URL('default', 'index'))

    flyer = db(db.flyer.user_id == vendor.vendor_user_id).select().first()

    if not flyer:
        return dict(vendor=vendor, flyer=None)

    return dict(vendor=vendor, flyer=flyer)
