"""
WingedFlyer Controllers
Lightweight flyer management for mobile users
"""

import markdown
import qrcode
from io import BytesIO
import base64


def user():
    """
    Authentication endpoints:
    /app/default/user/login
    /app/default/user/logout
    /app/default/user/register
    /app/default/user/profile
    /app/default/user/change_password
    /app/default/user/retrieve_password
    """
    return dict(form=auth())


def index():
    """Home page - redirect based on auth status."""
    if auth.is_logged_in():
        redirect(URL('editor'))
    else:
        redirect(URL('user/login'))


@auth.requires_login()
def editor():
    """Markdown editor - create/edit flyers."""
    flyer_id = request.args(0) if request.args else None
    
    # Fetch user's flyers
    flyers = db(db.flyer.user_id == auth.user_id).select(
        orderby=~db.flyer.updated_on
    )
    
    # Load existing flyer
    current_flyer = None
    if flyer_id:
        try:
            flyer = db.flyer(int(flyer_id))
            if flyer and flyer.user_id == auth.user_id:
                current_flyer = flyer
            else:
                session.flash = 'Flyer not found or access denied'
                redirect(URL('editor'))
        except (ValueError, TypeError):
            session.flash = 'Invalid flyer ID'
            redirect(URL('editor'))
    
    return dict(flyers=flyers, current_flyer=current_flyer, flyer_id=flyer_id)


@auth.requires_login()
def save():
    """Save or create flyer."""
    flyer_id = request.post_vars.flyer_id
    title = (request.post_vars.title or '').strip() or 'Untitled Flyer'
    thecontent = (request.post_vars.thecontent or '').strip()

    if not thecontent:
        session.flash = 'Content cannot be empty'
        redirect(URL('editor', args=[flyer_id] if flyer_id else []))

    try:
        if flyer_id and flyer_id.isdigit():
            # Update existing
            flyer = db.flyer(int(flyer_id))
            if flyer and flyer.user_id == auth.user_id:
                flyer.update_record(title=title, thecontent=thecontent)
                session.flash = 'Flyer updated!'
            else:
                session.flash = 'Cannot edit this flyer'
                redirect(URL('editor'))
        else:
            # Create new
            flyer_id = db.flyer.insert(
                user_id=auth.user_id,
                title=title,
                thecontent=thecontent
            )
            flyer = db.flyer(flyer_id)
            session.flash = 'Flyer created!'
        
        db.commit()
        redirect(URL('preview', args=[flyer.id]))
        
    except Exception as e:
        db.rollback()
        session.flash = f'Error: {str(e)}'
        redirect(URL('editor', args=[flyer_id] if flyer_id else []))


@auth.requires_login()
def preview():
    """Preview rendered markdown."""
    flyer_id = request.args(0)
    if not flyer_id:
        redirect(URL('editor'))
    
    flyer = db.flyer(int(flyer_id))
    if not flyer or flyer.user_id != auth.user_id:
        session.flash = 'Flyer not found'
        redirect(URL('editor'))
    
    html_content = markdown.markdown(flyer.thecontent, extensions=['extra', 'nl2br', 'tables'])
    return dict(flyer=flyer, html_content=html_content)


def view_flyer():
    """Public flyer display."""
    flyer_id = request.args(0)
    if not flyer_id:
        raise HTTP(404, "Flyer not found")
    
    flyer = db.flyer(int(flyer_id))
    if not flyer or not flyer.is_public:
        raise HTTP(404, "Flyer not found")
    
    # Increment view count
    flyer.update_record(view_count=flyer.view_count + 1)
    db.commit()
    
    html_content = markdown.markdown(flyer.thecontent, extensions=['extra', 'nl2br', 'tables'])
    return dict(flyer=flyer, html_content=html_content)


def qr():
    """Generate QR code for flyer."""
    flyer_id = request.args(0)
    if not flyer_id:
        raise HTTP(404, "Flyer not found")
    
    try:
        flyer = db.flyer(int(flyer_id))
        if not flyer or not flyer.is_public:
            raise HTTP(404, "Flyer not found")
    except ValueError:
        raise HTTP(404, "Invalid flyer ID")
    
    # Generate QR code
    flyer_url = URL('view_flyer', args=[flyer_id], scheme=True, host=True)
    
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
    
    return dict(flyer=flyer, qr_image=img_str, flyer_url=flyer_url)


@auth.requires_login()
def delete():
    """Delete flyer (owner only)."""
    flyer_id = request.args(0)
    
    if not flyer_id:
        session.flash = 'No flyer specified'
        redirect(URL('editor'))
    
    try:
        flyer = db.flyer(int(flyer_id))
        
        if not flyer:
            session.flash = 'Flyer not found'
        elif flyer.user_id != auth.user_id:
            session.flash = 'Cannot delete this flyer'
        else:
            db(db.flyer.id == flyer_id).delete()
            db.commit()
            session.flash = 'Flyer deleted'
    
    except Exception as e:
        session.flash = f'Error: {str(e)}'
    
    redirect(URL('editor'))