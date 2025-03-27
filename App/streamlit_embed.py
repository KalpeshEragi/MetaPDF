from flask import Blueprint, render_template

streamlit_bp = Blueprint('streamlit_bp', __name__)

@streamlit_bp.route('/streamlit')
def streamlit_app():
    return render_template('streamlit_embed.html')
