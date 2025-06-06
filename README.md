📑 MetaPDF — An AI Assistant to summarize, chat with PDFs, and convert documents (DOCX, PPT, Excel, TXT) to PDF.

## 📸 Interface Previews
### 🏠 Home Page
![Home Page](static/Images/Screenshot%20(31).png)

### 📄 PDF Upload & Summary
![PDF Upload](static/Images/Screenshot%20(38).png)

### 🤖 AI Chat with PDF
![AI Chat](static/Images/Screenshot%20(29).png)

###  Convertor
![AI Chat](static/Images/Screenshot%20(33).png)
![AI Chat](static/Images/Screenshot%20(34).png)

A comprehensive web application that combines **document conversion**, **AI-powered PDF summarization**, and **intelligent document chat** capabilities. Transform your document workflow with cutting-edge AI technology!

## ✨ Features

### 🤖 AI-Powered PDF Processing
- **Smart Summarization** - Generate intelligent summaries using BART-large-CNN model
- **Interactive Chat** - Ask questions about your PDF content using Google Gemini AI
- **Real-time Processing** - Live typewriter effect for engaging user experience
- **Multi-page Support** - Process entire documents or specific page ranges

### 🚀 Advanced Capabilities
- **Vector Search** - FAISS-powered semantic search through documents
- **Responsive Design** - Beautiful, modern web interface

### 🔄 Document Conversion
- **Word to PDF** - Convert DOCX files to professional PDFs
- **PowerPoint to PDF** - Transform presentations into PDF format
- **Excel to PDF** - Convert spreadsheets to PDF documents
- **Text to PDF** - Simple text file to PDF conversion

## 🛠️ Technology Stack

- **Backend**: Flask, Python 3.8+
- **AI Models**: Google Gemini, Hugging Face Transformers (BART)
- **Vector Database**: FAISS
- **Document Processing**: PyPDF2, LangChain
- **Frontend**: HTML5, CSS3, JavaScript
- **ML Framework**: PyTorch, Transformers

## 📋 Prerequisites

- Python 3.8 or higher
- Optional NVIDIA GPU (RTX 2050 or better) for optimal performance
- Google API Key for Gemini AI
- 4GB+ RAM recommended

## ⚡ Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/KalpeshEragi/MetaPDF.git
cd MetaPDF
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Setup
Create a `.env` file in the `env/` directory:
```env
GOOGLE_API_KEY=your_google_api_key_here
FLASK_SECRET_KEY=your_secret_key_here
```

### 4. Run the Application
```bash
python app.py
```
In another bash, run :
```bash
streamlit run App/streamlit_app/stream_app.py
```


Visit `http://localhost:5000` to access the application!

## 🎯 Usage Guide

### Document Conversion
1. Navigate to the homepage
2. Select PDF Converter
3. Select your conversion type (Word, PPT, Excel, or Text)
4. Upload your file
5. Download the converted PDF

### AI PDF Summarization
1. Access the Streamlit interface at `/streamlit`
2. Upload your PDF document
3. Choose summary quality (Fast, Balanced, High Quality)
4. Select pages to summarize
5. Get intelligent summaries with typewriter effect

### Interactive PDF Chat
1. Go to `/chat`
2. Upload your PDF document
3. Ask questions about the content
4. Get detailed, context-aware responses

## 📁 Project Structure

```
pdf-converter-ai/
├── App/
│   ├── chat_app.py          # AI chat functionality
│   ├── streamlit_app.py     # PDF summarization
│   ├── docx_converter.py    # Word to PDF
│   ├── ppt_converter.py     # PowerPoint to PDF
│   ├── xl_converter.py      # Excel to PDF
│   └── txt.py               # Text to PDF
├── static/
│   ├── css/                 # Stylesheets
│   ├── js/                  # JavaScript files
│   └── Images/              # UI icons and images
├── templates/               # HTML templates
├── data/
│   ├── faiss_index/        # Vector database
│   └── Uploads/            # File uploads
├── env/
│   └── .env                # Environment variables
├── app.py                  # Main Flask application
└── requirements.txt        # Python dependencies
```

## 🔧 Configuration


### Model Settings
- **Summarization**: facebook/bart-large-cnn
- **Embeddings**: Google's embedding-001
- **Chat AI**: Gemini-1.5-flash-8b-001

## 📊 Performance Features

- **Chunked Processing** - Handle large documents efficiently
- **Dynamic Summary Length** - Adaptive based on content size
- **Beam Search** - High-quality text generation
- **Vector Caching** - Fast document retrieval
- **Session Persistence** - Maintain context across interactions

## 🎨 User Interface

- **Modern Design** - Clean, professional appearance
- **Interactive Elements** - Hover effects and animations
- **Real-time Feedback** - Progress bars and status updates
- **Typewriter Effect** - Engaging text animation

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Google Gemini AI for advanced language understanding
- Hugging Face for transformer models
- FAISS for efficient vector search
- The open-source community for amazing tools and libraries

## 🐛 Issues & Support

Encountered a bug or have a feature request? Please [open an issue](https://github.com/KalpeshEragi/MetaPDF/issues) on GitHub.

## 🌟 Show Your Support

If this project helped you, please consider giving it a ⭐ star on GitHub!

---

<div align="center">
  <strong>Transform your documents with AI-powered intelligence!</strong>
</div>
