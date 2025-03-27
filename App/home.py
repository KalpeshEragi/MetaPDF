import os
from flask import Blueprint, render_template, send_from_directory

# Create a Blueprint for the home module
home_bp = Blueprint('home', __name__, 
                    template_folder='templates', 
                    static_folder='static')

# Splash Screen Route
@home_bp.route('/')
def splash():
    # Ensure splash.html exists in 'App/templates'
    return render_template('splash.html')

# Main Home Page Route
@home_bp.route('/home')
def main_home():
    # Ensure home.html exists in 'App/templates'
    return render_template('home.html')

@home_bp.route('/convertor')
def convertor():
    return render_template('convertor.html')
# Route for serving static files (optional)
# @home_bp.route('/static/<path:filename>')
# def serve_static(filename):
#     # Serves static files from the 'static' folder within the App directory
#     return send_from_directory(os.path.join(home_bp.root_path, 'static'), filename)
