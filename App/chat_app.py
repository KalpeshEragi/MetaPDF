import os
from flask import Blueprint, render_template, request, jsonify, session, send_from_directory, current_app, url_for
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import google.generativeai as genai
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import uuid

# Create Blueprint
chat_app = Blueprint('chat_app', __name__,
                    template_folder='templates',
                    static_folder='static',
                    url_prefix='/chat')

# Load environment variables
dotenv_path = os.path.join(os.getcwd(), "env", ".env")
load_dotenv(dotenv_path)

# Configure Google Generative AI
google_api_key = os.getenv("GOOGLE_API_KEY")
if not google_api_key:
    raise ValueError("GOOGLE_API_KEY must be set in environment variables")
genai.configure(api_key=google_api_key)

# Configure upload settings
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# PDF Processing Functions
def get_pdf_text(pdf_docs):
    text = ''
    for pdf in pdf_docs:
        try:
            pdf_reader = PdfReader(pdf)
            for page in pdf_reader.pages:
                text += page.extract_text() or ''
        except Exception as e:
            print(f"Error processing PDF: {e}")
    return text

def get_text_chunks(text):
    if not text:
        return []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=10000,
        chunk_overlap=1000
    )
    return text_splitter.split_text(text)

def get_vector_store(text_chunks):
    if not text_chunks:
        return None
    try:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        vector_store = FAISS.from_texts(text_chunks, embeddings)
        
        # Save in the data folder
        index_path = os.path.join(current_app.root_path, 'data', 'faiss_index')
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        vector_store.save_local(index_path)
        return vector_store
    except Exception as e:
        print(f"Error creating vector store: {e}")
        return None

def load_vector_store():
    try:
        index_path = os.path.join(current_app.root_path, 'data', 'faiss_index')
        if os.path.exists(index_path):
            embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
            return FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
    except Exception as e:
        print(f"Error loading vector store: {e}")
    return None

def get_conversational_chain():
    prompt_template = """
    Answer the question with maximum detail and thoroughness using information from the provided context.

   If the specific information requested is not present in the context, clearly indicate this by stating: "This specific information is not available in the provided context." Then proceed to offer a DETAILED ANSWER based on relevant knowledge about the subject.

   Maintain a formal, authoritative tone throughout the response. Prioritize accuracy, completeness, and comprehensive explanations while organizing information logically and coherently.

   Include all relevant details, examples, and technical specifics from the context when available. Leave no aspect of the question unexplored.

   Context:
   {context}

   Question: 
   {question}

   Answer:
    """
    model = ChatGoogleGenerativeAI(
        model="models/gemini-1.5-flash-8b-001",
        temperature=0.3
    )
    prompt = PromptTemplate(
        template=prompt_template,
        input_variables=["context", "question"]
    )
    return load_qa_chain(model, chain_type="stuff", prompt=prompt)

# Route handlers
@chat_app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        # Initialize empty chat history if it doesn't exist
        if 'chat_history' not in session:
            session['chat_history'] = []
        return render_template('chat.html', chat_history=session['chat_history'])
    
    elif request.method == 'POST':
        try:
            # Handle PDF upload
            if 'pdf_files' in request.files:
                files = request.files.getlist('pdf_files')
                if not files:
                    return jsonify({'status': 'error', 'message': 'No files uploaded'})

                for file in files:
                    if file and allowed_file(file.filename):
                        # Process PDF
                        raw_text = get_pdf_text([file])
                        text_chunks = get_text_chunks(raw_text)
                        vector_store = get_vector_store(text_chunks)
                        
                        if vector_store:
                            session['vector_store_created'] = True
                            return jsonify({'status': 'success', 'message': 'PDF processed successfully'})
                
                return jsonify({'status': 'error', 'message': 'Invalid file format'})

            # Handle chat messages
            elif 'user_question' in request.form:
                user_question = request.form['user_question']
                
                if not session.get('vector_store_created'):
                    return jsonify({
                        'status': 'error',
                        'message': 'Please upload a PDF first'
                    })

                vector_store = load_vector_store()
                if not vector_store:
                    return jsonify({
                        'status': 'error',
                        'message': 'Error loading document data'
                    })

                # Get relevant documents for the question
                docs = vector_store.similarity_search(user_question)
                
                # Get AI response
                chain = get_conversational_chain()
                response = chain(
                    {'input_documents': docs, 'question': user_question},
                    return_only_outputs=True
                )

                # Update chat history
                chat_history = session.get('chat_history', [])
                chat_history.append({
                    'question': user_question,
                    'answer': response.get('output_text', 'Sorry, I could not generate a response.')
                })
                session['chat_history'] = chat_history

                return jsonify({
                    'status': 'success',
                    'answer': response.get('output_text', 'Sorry, I could not generate a response.')
                })

        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'An error occurred: {str(e)}'
            })

    return jsonify({'status': 'error', 'message': 'Invalid request'})

@chat_app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# Error handlers
@chat_app.errorhandler(413)
def too_large(e):
    return jsonify({'status': 'error', 'message': 'File is too large'}), 413

@chat_app.errorhandler(500)
def server_error(e):
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500