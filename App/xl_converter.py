import os
import pythoncom
from flask import Flask,Blueprint, request, send_from_directory, jsonify, render_template
from win32com import client
import psutil

xl_converter_bp=Blueprint('xl_converter',__name__,template_folder='templates',static_folder='static')

UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/pdfs'


# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Home route
@xl_converter_bp.route('/')
def index():
    return render_template('xl.html')

# Route for handling file uploads
@xl_converter_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.xlsx'):
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        print(f"File uploaded to: {filepath}")

        pdf_filename = file.filename.replace('.xlsx', '.pdf')
        pdf_filepath = os.path.join(OUTPUT_FOLDER, pdf_filename)
        
        try:
            convert_excel_to_pdf(filepath, pdf_filepath)
            return jsonify({'pdf_url': f'/static/pdfs/{pdf_filename}'}), 200
        except Exception as e:
            print(f"Error during conversion: {e}")
            return jsonify({'error': 'Failed to convert Excel to PDF'}), 500

    return jsonify({'error': 'Invalid file format. Please upload an Excel file.'}), 400

# Function to convert Excel to PDF
def convert_excel_to_pdf(excel_path, pdf_path):
    try:
        pythoncom.CoInitialize()

        excel_path = os.path.abspath(excel_path)
        pdf_path = os.path.abspath(pdf_path)

        kill_excel_processes()

        if not os.path.exists(excel_path):
            raise Exception(f"File not found: {excel_path}")

        excel = client.Dispatch("Excel.Application")
        excel.Visible = False
        wb = excel.Workbooks.Open(excel_path)
        wb.ExportAsFixedFormat(0, pdf_path)  # 0 is for PDF format
        wb.Close()
        excel.Quit()

        pythoncom.CoUninitialize()

    except Exception as e:
        print(f"Error during conversion: {e}")
        raise

# Function to terminate any running Excel processes
def kill_excel_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == 'EXCEL.EXE':
            proc.terminate()

# Route for serving the converted PDF file
@xl_converter_bp.route('/static/pdfs/<filename>')
def download_pdf(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)
