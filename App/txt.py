import os
from flask import Flask, Blueprint, request, send_from_directory, jsonify, render_template
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

txt_converter_bp= Blueprint('txt_converter', __name__, template_folder='templates', static_folder='static')

UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/pdfs'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Home route
@txt_converter_bp.route('/')
def index():
    return render_template('txt.html')
# Route for handling file uploads
@txt_converter_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.txt'):
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        print(f"File uploaded to: {filepath}")

        pdf_filename = file.filename.replace('.txt', '.pdf')
        pdf_filepath = os.path.join(OUTPUT_FOLDER, pdf_filename)
        
        try:
            convert_txt_to_pdf(filepath, pdf_filepath)
            return jsonify({'pdf_url': f'/static/pdfs/{pdf_filename}'}), 200
        except Exception as e:
            print(f"Error during conversion: {e}")
            return jsonify({'error': 'Failed to convert TXT to PDF'}), 500

    return jsonify({'error': 'Invalid file format. Please upload a TXT file.'}), 400

# Function to convert TXT to PDF using reportlab with line wrapping
def convert_txt_to_pdf(txt_path, pdf_path):
    try:
        # Read the content of the text file using UTF-8 encoding
        with open(txt_path, 'r', encoding='utf-8') as file:
            text_content = file.readlines()

        # Create a PDF canvas using reportlab
        c = canvas.Canvas(pdf_path, pagesize=letter)
        c.setFont("Helvetica", 12)

        # Set page dimensions and margins
        width, height = letter
        margin = 40
        x_start = margin
        y_start = height - margin
        line_height = 14  # Line spacing

        # Define the position to start writing
        x_pos = x_start
        y_pos = y_start

        # Write content to the PDF, handling line wrapping and new pages
        for line in text_content:
            words = line.split(' ')
            current_line = ''
            for word in words:
                # Check if adding the word exceeds the line width
                if c.stringWidth(current_line + ' ' + word, "Helvetica", 12) <= width - 2 * margin:
                    current_line += ' ' + word
                else:
                    # Write the current line to the canvas
                    c.drawString(x_pos, y_pos, current_line.strip())
                    y_pos -= line_height
                    current_line = word

                    # Check if we need a new page
                    if y_pos < margin:
                        c.showPage()
                        c.setFont("Helvetica", 12)
                        y_pos = y_start

            # Write the last line in the current line buffer
            if current_line:
                c.drawString(x_pos, y_pos, current_line.strip())
                y_pos -= line_height

                # Add a new page if needed
                if y_pos < margin:
                    c.showPage()
                    c.setFont("Helvetica", 12)
                    y_pos = y_start

        # Finalize and save the PDF
        c.save()

        print(f"PDF created successfully at: {pdf_path}")
    except Exception as e:
        print(f"Error during conversion: {e}")
        raise



# Route for serving the converted PDF file
@txt_converter_bp.route('/static/pdfs/<filename>')
def download_pdf(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)



