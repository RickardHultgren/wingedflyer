"""
Database models for qrier application.
Defines the flyers table for storing markdown content.
"""

# Database connection
db = DAL('sqlite://storage.sqlite', pool_size=1, check_reserved=['all'])

# Session configuration
#session.connect(request, response, db=db)

# Define the flyers table
db.define_table('flyer',
    Field('title', 'string', length=255, notnull=True),
    Field('thecontent', 'text', notnull=True),
    Field('created_on', 'datetime', default=request.now),
    Field('updated_on', 'datetime', update=request.now),
    format='%(title)s'
)

# Create tables if they don't exist
db.commit()
