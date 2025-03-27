import os
import uuid
import logging
import comtypes.client  # For interacting with PowerPoint via COM
import pythoncom  # For managing COM initialization
from flask import Flask,Blueprint, request, send_from_directory, render_template, jsonify
import psutil  # For managing and terminating PowerPoint processes
from werkzeug.utils import secure_filename

ppt_converter_bp=Blueprint('ppt_converter',__name__,template_folder='templates',static_folder='static')

UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/pdfs'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Allowed extensions for upload
ALLOWED_EXTENSIONS = {'.ppt', '.pptx'}

def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

@ppt_converter_bp.route('/')
def index():
    return render_template('ppt.html')  # Serve 'ppt.html' from the templates folder

@ppt_converter_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No selected file'})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)

        pdf_filename = unique_filename.rsplit('.', 1)[0] + '.pdf'
        pdf_filepath = os.path.join(OUTPUT_FOLDER, pdf_filename)

        try:
            convert_ppt_to_pdf(filepath, pdf_filepath)
            pdf_url = f'/static/pdfs/{pdf_filename}'
            return jsonify({'pdf_url': pdf_url})
        except Exception as e:
            logging.error(f"Error converting file: {str(e)}")
            return jsonify({'error': 'Failed to convert PPT to PDF'}), 500
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    return jsonify({'error': 'Invalid file format. Please upload a PPT or PPTX file.'}), 400

def convert_ppt_to_pdf(ppt_path, pdf_path):
    try:
        pythoncom.CoInitialize()

        ppt_path = os.path.abspath(ppt_path)
        pdf_path = os.path.abspath(pdf_path)

        if not os.path.exists(ppt_path):
            raise FileNotFoundError(f"File not found: {ppt_path}")

        logging.info(f"Converting: {ppt_path} to {pdf_path}")

        kill_ppt_processes()

        ppt = comtypes.client.CreateObject("PowerPoint.Application")
        ppt.Visible = True
        presentation = ppt.Presentations.Open(ppt_path)

        presentation.SaveAs(pdf_path, FileFormat=32)
        presentation.Close()
        ppt.Quit()

        pythoncom.CoUninitialize()
        logging.info("Conversion successful!")

    except Exception as e:
        logging.error(f"Error during conversion: {str(e)}")
        raise

def kill_ppt_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == 'powerpnt.exe':
            proc.terminate()

@ppt_converter_bp.route('/static/pdfs/<filename>')
def download_pdf(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)



