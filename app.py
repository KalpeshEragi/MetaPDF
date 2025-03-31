from dotenv import load_dotenv
from flask import Flask
import os
from flask_cors import CORS



from App.home import home_bp
from App.chat_app import chat_app
from App.docx_converter import docx_converter_bp
from App.ppt_converter import ppt_converter_bp
from App.xl_converter import xl_converter_bp
from App.txt import txt_converter_bp
from App.streamlit_embed import streamlit_bp  

# Load environment variables
load_dotenv()



# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set secret key from environment variables
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    
    raise ValueError("FLASK_SECRET_KEY is not set in .env file")

# Upload folder config
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "data", "Uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Register blueprints
app.register_blueprint(home_bp)
app.register_blueprint(chat_app)
app.register_blueprint(docx_converter_bp, url_prefix='/docx')
app.register_blueprint(ppt_converter_bp, url_prefix='/ppt')
app.register_blueprint(xl_converter_bp, url_prefix='/xl')
app.register_blueprint(txt_converter_bp, url_prefix='/txt')
app.register_blueprint(streamlit_bp)  # NEW

# Run
if __name__ == '__main__':
    app.run(debug=True)
