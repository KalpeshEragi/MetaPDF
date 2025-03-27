import streamlit as st
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import PyPDF2
import torch
import re

# App title and description
st.set_page_config(page_title="SmartSummarizer", page_icon="📑")
st.title("📑 Summary Generator")
st.markdown("*High-quality PDF summarization optimized for RTX 2050*")

# Download and cache the model
@st.cache_resource
def load_model():
    # Use a smaller, more efficient model that works well on RTX 2050
    model_name = "facebook/bart-large-cnn"  # Better than T5-base for summarization, optimized size
    
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        
        # Half-precision to reduce VRAM usage
        if torch.cuda.is_available():
            model = model.half().to("cuda")
            st.sidebar.success("✅ Using GPU acceleration (optimized)")
        else:
            st.sidebar.info("ℹ️ Running on CPU")
            
        summarizer = pipeline("summarization", model=model, tokenizer=tokenizer)
        return summarizer
    except Exception as e:
        st.error(f"Error loading model: {e}")
        return None

# Extract text from PDF with better error handling
def extract_pages(file):
    try:
        reader = PyPDF2.PdfReader(file)
        pages = []
        
        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                # Clean the text
                text = re.sub(r'\s+', ' ', text).strip()
                pages.append(text)
            except Exception as e:
                pages.append(f"[Error extracting page {i+1}]")
                
        return pages
    except Exception as e:
        st.error(f"Error processing PDF: {e}")
        return []

# Text preprocessing to improve summary quality WITHOUT NLTK dependency
def preprocess_text(text):
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove headers, footers, and page numbers (common in PDFs)
    text = re.sub(r'\d+\s*of\s*\d+', '', text)
    
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    
    # Simple sentence splitting without NLTK
    # Look for periods, question marks, or exclamation points followed by a space and an uppercase letter
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    
    # Split text into smaller chunks if too long
    if len(text) > 1000:
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < 1000:
                current_chunk += " " + sentence
            else:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
                
        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks
    
    return [text] if text else []

# Improved summarization with quality metrics
def generate_smart_summary(text, max_length=150, min_length=50):
    summarizer = load_model()
    if not summarizer or not text:
        return ""
    
    chunks = preprocess_text(text)
    if not chunks:
        return ""
    
    # For shorter texts, use higher compression ratio
    word_count = len(text.split())
    
    # Dynamic summary length based on content
    if word_count < 100:
        max_length = min(max_length, word_count)
        min_length = min(min_length, max_length - 10)
    elif word_count > 500:
        max_length = min(200, int(word_count * 0.3))
        min_length = max(50, int(max_length * 0.6))
    
    # Quality parameters
    summarization_params = {
        "max_length": max_length,
        "min_length": min_length,
        "do_sample": False,  # More deterministic results
        "num_beams": 4,      # Beam search for better quality
        "length_penalty": 1.5, # Favor longer summaries for better coherence
        "early_stopping": True
    }
    
    # Summarize each chunk
    summaries = []
    
    for chunk in chunks:
        if len(chunk.split()) < 15:  # Skip very short chunks
            continue
            
        try:
            summary = summarizer(chunk, **summarization_params)[0]['summary_text']
            summaries.append(summary)
        except Exception as e:
            continue
    
    # Combine chunk summaries
    final_summary = " ".join(summaries)
    
    # Ensure the summary is coherent if we had multiple chunks
    if len(summaries) > 1 and len(final_summary.split()) > max_length:
        try:
            final_summary = summarizer(final_summary, 
                                       max_length=max_length,
                                       min_length=min_length)[0]['summary_text']
        except:
            pass
    
    return final_summary

# Sidebar controls for customization
with st.sidebar:
    st.subheader("Summary Settings")
    quality_option = st.select_slider(
        "Summary Quality",
        options=["Fast", "Balanced", "High Quality"],
        value="Balanced"
    )
    
    # Map quality options to parameters
    if quality_option == "Fast":
        max_length = 100
        min_length = 30
    elif quality_option == "Balanced":
        max_length = 150
        min_length = 50
    else:  # High Quality
        max_length = 200
        min_length = 75
    
    # Additional controls
    show_metrics = st.checkbox("Show summary metrics", value=False)

# Main app interface
uploaded_file = st.file_uploader("Upload a PDF document", type="pdf")

if uploaded_file:
    with st.status("Processing your PDF...") as status:
        status.update(label="Extracting text from PDF...")
        pages = extract_pages(uploaded_file)
        total_pages = len(pages)
        
        if total_pages == 0:
            st.error("Could not extract any text from the PDF. The file may be corrupted or scanned.")
        else:
            status.update(label=f"Successfully extracted {total_pages} pages", state="complete")
            st.success(f"📄 PDF processed: {total_pages} pages found")
            
            # Page selection
            selection_mode = st.radio("Pages to summarize:", 
                                    options=["All pages", "Select specific pages", "Page range"],
                                    horizontal=True)
            
            selected_pages = []
            
            if selection_mode == "All pages":
                selected_pages = list(range(1, total_pages + 1))
                
            elif selection_mode == "Select specific pages":
                page_input = st.text_input(f"Enter page numbers (1-{total_pages}, separated by commas)", 
                                          value="1")
                try:
                    selected_pages = [int(p.strip()) for p in page_input.split(",") if p.strip().isdigit()]
                    selected_pages = [p for p in selected_pages if 1 <= p <= total_pages]
                    if not selected_pages:
                        st.warning("Please enter valid page numbers")
                except:
                    st.warning("Please enter page numbers in the correct format")
                    
            elif selection_mode == "Page range":
                col1, col2 = st.columns(2)
                with col1:
                    start_page = st.number_input("Start page", min_value=1, max_value=total_pages, value=1)
                with col2:
                    end_page = st.number_input("End page", min_value=start_page, max_value=total_pages, value=min(start_page+4, total_pages))
                selected_pages = list(range(start_page, end_page + 1))
            
            # Summarize button
            if st.button("🔍 Generate Smart Summaries", type="primary"):
                if not selected_pages:
                    st.warning("No pages selected for summarization")
                else:
                    progress_bar = st.progress(0)
                    summaries = []
                    
                    with st.spinner("Generating summaries..."):
                        for i, page_num in enumerate(selected_pages):
                            idx = page_num - 1
                            if 0 <= idx < total_pages:
                                page_text = pages[idx]
                                if page_text and len(page_text.strip()) > 20:
                                    summary = generate_smart_summary(page_text, max_length, min_length)
                                    
                                    # Calculate metrics
                                    if show_metrics and summary:
                                        original_words = len(page_text.split())
                                        summary_words = len(summary.split())
                                        compression = round((1 - summary_words/original_words) * 100, 1) if original_words > 0 else 0
                                        
                                        summaries.append({
                                            "page": page_num,
                                            "summary": summary,
                                            "metrics": {
                                                "original_words": original_words,
                                                "summary_words": summary_words,
                                                "compression_ratio": compression
                                            }
                                        })
                                    else:
                                        summaries.append({
                                            "page": page_num,
                                            "summary": summary
                                        })
                            
                            # Update progress
                            progress_bar.progress((i + 1) / len(selected_pages))
                    
                    # Display results
                    if summaries:
                        st.subheader("📋 Summary Results")
                        
                        # Option to combine all summaries
                        if len(summaries) > 1:
                            show_combined = st.checkbox("Show combined summary")
                            
                            if show_combined:
                                combined_text = " ".join([s["summary"] for s in summaries if s["summary"]])
                                st.subheader("📑 Complete Document Summary")
                                st.markdown(combined_text)
                                st.download_button(
                                    "Download complete summary",
                                    combined_text,
                                    file_name="complete_summary.txt"
                                )
                                st.markdown("---")
                        
                        # Individual page summaries
                        st.subheader("Individual Page Summaries")
                        for item in summaries:
                            st.markdown(f"### Page {item['page']}")
                            st.markdown(item["summary"])
                            
                            if show_metrics and "metrics" in item:
                                metrics = item["metrics"]
                                st.caption(f"Original: {metrics['original_words']} words → Summary: {metrics['summary_words']} words (Compressed by {metrics['compression_ratio']}%)")
                            
                            st.download_button(
                                f"Download page {item['page']} summary",
                                item["summary"],
                                file_name=f"page_{item['page']}_summary.txt",
                                key=f"dl_{item['page']}"
                            )
                            st.markdown("---")
                                
                        st.success("✅ Summarization completed!")
                    else:
                        st.warning("⚠️ Could not generate summaries for the selected pages.")

# Footer with app information
st.sidebar.markdown("---")
st.sidebar.caption("SmartSummarizer Pro v1.0")
st.sidebar.caption("Optimized for RTX 2050")
