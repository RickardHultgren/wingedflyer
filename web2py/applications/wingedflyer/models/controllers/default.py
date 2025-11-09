'''from gluon.http import redirect
import json
'''
import markdown
import qrcode
from io import BytesIO
import base64


# ---- Action for login/register/etc (required for auth) -----
def user():
    """
    exposes:
    http://..../[app]/default/user/login
    http://..../[app]/default/user/logout
    http://..../[app]/default/user/register
    http://..../[app]/default/user/profile
    http://..../[app]/default/user/retrieve_password
    http://..../[app]/default/user/change_password
    http://..../[app]/default/user/bulk_register
    use @auth.requires_login()
        @auth.requires_membership('team name')
        @auth.requires_permission('read','table name',record_id)
    to decorate functions that need access control
    also notice there is http://..../[app]/appadmin/manage/auth to allow administrator to manage users
    """
    return dict(form=auth())


def index():
    """
    Home page - redirects to login if not authenticated, otherwise to editor.
    """
    if auth.is_logged_in():
        redirect(URL('editor'))
    else:
        redirect(URL('user'))
    return

'''
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
'''

@auth.requires_login()
def editor():
    """
    Markdown editor page (writer-only).
    Allows creating and editing flyers.
    """
    
    # Check authentication
    if not auth.is_logged_in():
        redirect(URL('user'))
    
    # Get flyer ID if editing existing
    flyer_id = request.args(0) if request.args else None
    
    # Fetch all flyers for the list
    if 'flyer' in db.tables():
        flyer = db(db.flyer).select(orderby=~db.flyer.updated_on)
    else:
        flyer = []
    
    # Load existing flyer if ID provided
    current_flyer = None

    if flyer_id: #If editing a flyer
        current_flyer = db.flyer(flyer_id)
    else:
        # Defensive: ensure table exists
        if 'flyer' not in db.tables():
            current_flyer = None
            flyer_id = None  # Nothing we can generate yet
        else:
            # Count existing rows
            count = db(db.flyer).count()

            # Start looking for the next free id
            candidate_id = count + 1

            # Loop until an unused id is found
            # NOTE: db.flyer(<id>) returns None if id doesn't exist
            while db.flyer(candidate_id):
                candidate_id += 1

            flyer_id = candidate_id
            current_flyer = None  # because it's a new flyer
    return dict(flyer=flyer, current_flyer=current_flyer, flyer_id=flyer_id)

@auth.requires_login()
def save():
    """
    Save or update a flyer (defensive).
    """
    # ensure table exists
    if 'flyer' not in db.tables():
        # optionally create table or return an error message
        # For now, fail gracefully:
        session.flash = "Flyer storage not available (table missing)."
        redirect(URL('editor'))
    # normalize incoming flyer_id (request.vars are strings)
    incoming_id = request.vars.get('flyer_id') or None
    try:
        incoming_id = int(incoming_id) if incoming_id not in (None, '', 'None') else None
    except (ValueError, TypeError):
        incoming_id = None

    # gather fields
    title = (request.vars.get('title') or "Untitled Flyer").strip()
    thecontent = request.vars.thecontent  # allow empty string if desired
    # basic validation
    if thecontent is None:
        # no content provided
        session.flash = "No content provided."
        redirect(URL('editor', args=[incoming_id] if incoming_id else None))
    try:
        if incoming_id and db.flyer(incoming_id):
            # update existing
            db(db.flyer.id == incoming_id).update(
                title=title,
                thecontent=thecontent,
                updated_on=request.now  # if you have an updated_on field (optional)
            )
            new_id = incoming_id
        else:
            # insert new
            new_id = db.flyer.insert(
                title=title,
                thecontent=thecontent
            )

        db.commit()
    except Exception as e:
        # rollback and show friendly message
        try:
            db.rollback()
        except Exception:
            pass
        # Log the error to server logs
        current.logger.error("Failed to save flyer: %s" % str(e))
        session.flash = "Failed to save flyer (database error)."
        # redirect back to editor; do not expose raw exception in production
        redirect(URL('editor', args=[incoming_id] if incoming_id else None))

    # success: go to preview using the numeric id
    redirect(URL('preview', args=[new_id]))


def preview():
    """
    Preview page for writer to see rendered markdown.
    """
    # Check authentication
    if not auth.is_logged_in():
        redirect(URL('user'))
    
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


def view_flyer():
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
    
    try:
        flyer = db.flyer(flyer_id)
    #if not flyer:
    except:
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
    if not auth.is_logged_in():
        redirect(URL('login'))
    
    flyer_id = request.args(0)
    if flyer_id:
        db(db.flyer.id == flyer_id).delete()
        db.commit()
    
    redirect(URL('editor'))











