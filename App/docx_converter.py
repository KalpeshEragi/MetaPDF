import os
import pythoncom
from flask import Blueprint, request, send_from_directory, jsonify, render_template
from win32com import client
import psutil

# Create a Blueprint instance
docx_converter_bp = Blueprint('docx_converter', __name__, template_folder='templates', static_folder='static')

# Configure directories
UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Home route
@docx_converter_bp.route('/')
def index():
    return render_template('docx.html')  # Serve 'docx.html' from 'templates' folder

# Route for handling file uploads
@docx_converter_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.docx'):
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        pdf_filename = file.filename.replace('.docx', '.pdf')
        pdf_filepath = os.path.join(OUTPUT_FOLDER, pdf_filename)
        
        try:
            convert_docx_to_pdf(filepath, pdf_filepath)
            return jsonify({'pdf_url': f'/static/pdfs/{pdf_filename}'}), 200
        except Exception as e:
            print(f"Error during conversion: {e}")
            return jsonify({'error': 'Failed to convert DOCX to PDF'}), 500
    return jsonify({'error': 'Invalid file format. Please upload a DOCX file.'}), 400

# Function to convert DOCX to PDF
def convert_docx_to_pdf(docx_path, pdf_path):
    try:
        pythoncom.CoInitialize()
        docx_path = os.path.abspath(docx_path)
        pdf_path = os.path.abspath(pdf_path)
        kill_word_processes()
        if not os.path.exists(docx_path):
            raise Exception(f"File not found: {docx_path}")
        word = client.Dispatch("Word.Application")
        word.visible = False
        doc = word.Documents.Open(docx_path)
        doc.SaveAs(pdf_path, FileFormat=17)
        doc.Close()
        word.Quit()
        pythoncom.CoUninitialize()
    except Exception as e:
        print(f"Error during conversion: {e}")
        raise

# Function to kill Word processes
def kill_word_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == 'WINWORD.EXE':
            proc.terminate()

# Route to serve converted PDF files
@docx_converter_bp.route('/static/pdfs/<filename>')
def download_pdf(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)
