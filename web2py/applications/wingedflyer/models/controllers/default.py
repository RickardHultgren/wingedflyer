import markdown
import qrcode
from io import BytesIO
import base64

# Hardcoded credentials (for demo purposes)
WRITER_USERNAME = "writer"
WRITER_PASSWORD = "demo"


def index():
    """
    Home page - redirects to login if not authenticated, otherwise to editor.
    """
    if session.authenticated:
        redirect(URL('editor'))
    else:
        redirect(URL('login'))


def login():
    """
    Writer login page with hardcoded authentication.
    """
    form_error = None
    
    if request.vars.username and request.vars.password:
        # Check credentials
        if (request.vars.username == WRITER_USERNAME and 
            request.vars.password == WRITER_PASSWORD):
            session.authenticated = True
            redirect(URL('editor'))
        else:
            form_error = "Invalid username or password"
    
    return dict(error=form_error)


def logout():
    """
    Logout and clear session.
    """
    session.authenticated = None
    redirect(URL('login'))


def editor():
    """
    Markdown editor page (writer-only).
    Allows creating and editing flyers.
    """
    # Check authentication
    if not session.authenticated:
        redirect(URL('login'))
    
    # Get flyer ID if editing existing
    flyer_id = request.args(0) if request.args else None
    
    # Fetch all flyers for the list
    flyer = db(db.flyer).select(orderby=~db.flyer.updated_on)
    
    
    # Load existing flyer if ID provided
    current_flyer = None
    if flyer_id:
        current_flyer = db.flyer(flyer_id)
    
    return dict(flyer=flyer, current_flyer=current_flyer, flyer_id=flyer_id)


def save():
    """
    Save or update a flyer.
    """
    # Check authentication
    title = request.vars.title or "Untitled Flyer"
    thecontent = request.vars.thecontent
    flyer_id = request.vars.flyer_id
    
    
    if not session.authenticated:
        return dict(success=False, message="Not authenticated")
    
    if request.vars.thecontent is None:
        return dict(success=False, message="No content provided")
    
    
    
    if flyer_id and db.flyer(flyer_id):
        db(db.flyer.id == flyer_id).update(
            title=title,
            thecontent=thecontent
        )
    else:
        flyer_id = db.flyer.insert(
            title=title,
            thecontent=thecontent
        )
    
    
    
    
    db.commit()
    redirect(URL('preview', args=[flyer_id]))


def preview():
    """
    Preview page for writer to see rendered markdown.
    """
    # Check authentication
    if not session.authenticated:
        redirect(URL('login'))
    
    flyer_id = request.args(0)
    if not flyer_id:
        redirect(URL('editor'))
    
    flyer = db.flyer(flyer_id)
    if not flyer:
        redirect(URL('editor'))
    
    # Render markdown to HTML
    #html_content = markdown.markdown(flyer.thecontentcontent, extensions=['extra', 'nl2br'])
    html_content = markdown.markdown(flyer.thecontent, extensions=['extra', 'nl2br'])
    
    return dict(flyer=flyer, html_content=html_content)


def flyer():
    """
    Public display page for viewing flyers.
    Route: /qrier/default/flyer/<id>
    """
    flyer_id = request.args(0)
    if not flyer_id:
        raise HTTP(404, "Flyer not found")
    
    flyer = db.flyer(flyer_id)
    if not flyer:
        raise HTTP(404, "Flyer not found")
    
    # Render markdown to HTML
    #html_content = markdown.markdown(flyer.thecontentcontent, extensions=['extra', 'nl2br'])
    html_content = markdown.markdown(flyer.thecontent, extensions=['extra', 'nl2br'])
    
    return dict(flyer=flyer, html_content=html_content)


def qr():
    """
    Public QR code page.
    Route: /qrier/default/qr/<id>
    Generates a QR code linking to the flyer display page.
    """
    flyer_id = request.args(0)
    if not flyer_id:
        raise HTTP(404, "Flyer not found")
    
    flyer = db.flyer(flyer_id)
    if not flyer:
        raise HTTP(404, "Flyer not found")
    
    # Generate the full URL to the flyer
    flyer_url = URL('flyer', args=[flyer_id], scheme=True, host=True)
    
    # Generate QR code
    qr_img = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr_img.add_data(flyer_url)
    qr_img.make(fit=True)
    
    # Create image
    img = qr_img.make_image(fill_color="black", back_color="white")
    
    # Convert to base64 for embedding in HTML
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    
    return dict(flyer=flyer, qr_image=img_str, flyer_url=flyer_url)


def delete():
    """
    Delete a flyer (writer-only).
    """
    if not session.authenticated:
        redirect(URL('login'))
    
    flyer_id = request.args(0)
    if flyer_id:
        db(db.flyer.id == flyer_id).delete()
        db.commit()
    
    redirect(URL('editor'))
