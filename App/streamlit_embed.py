from flask import Blueprint, render_template,redirect

streamlit_bp = Blueprint('streamlit_bp', __name__)

@streamlit_bp.route('/streamlit')
def streamlit_app():
    return redirect("http://localhost:8501")
