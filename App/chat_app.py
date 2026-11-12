"""Chat-with-PDF blueprint — a thin web layer over App.rag.RAGService.

All RAG logic (extraction, chunking, hybrid retrieval, reranking, grounded Gemini generation, token/cost tracking)
lives in App/rag so the evaluation in eval/ measures exactly the code users run.
"""
import json
import logging
import statistics
import threading

from flask import Blueprint, jsonify, render_template, request, session

chat_app = Blueprint('chat_app', __name__, template_folder='templates', static_folder='static', url_prefix='/chat')
log = logging.getLogger(__name__)

MAX_HISTORY = 3
_service = None
_service_lock = threading.Lock()


def get_service():
    """Created on first use so the rest of the site starts instantly and works without the ML stack loaded."""
    global _service
    with _service_lock:
        if _service is None:
            from App.rag import RAGService
            _service = RAGService()
    return _service


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'


def _error(message, code=400):
    return jsonify({'status': 'error', 'message': message}), code


@chat_app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return render_template('chat.html', chat_history=session.get('chat_history', []))

    if 'pdf_files' in request.files:
        files = [f for f in request.files.getlist('pdf_files') if f and f.filename]
        if not files or not allowed_file(files[0].filename):
            return _error('Please upload a PDF file.')
        try:
            info = get_service().ingest(files[0].read(), filename=files[0].filename)
        except ValueError as e:
            return _error(str(e), 422)
        except Exception:
            log.exception('PDF ingestion failed')
            return _error('Could not process this PDF.', 500)
        session['doc_id'] = info['doc_id']
        session['chat_history'] = []
        return jsonify({'status': 'success', 'message': 'PDF processed successfully',
                        'document': {k: info[k] for k in ('title', 'pages', 'n_chunks', 'reused_existing_index',
                                                          'seconds')}})

    if 'user_question' in request.form:
        question = request.form['user_question'].strip()
        doc_id = session.get('doc_id')
        if not question:
            return _error('Please type a question.')
        if not doc_id:
            return _error('Please upload a PDF first')
        from App.rag.llm import LLMNotConfigured, QuotaExhausted
        try:
            res = get_service().ask(doc_id, question, session.get('chat_history', []))
        except KeyError as e:
            return _error(str(e).strip("'"), 404)
        except QuotaExhausted:
            return _error('The Gemini free-tier quota is used up for now. Please try again later.', 429)
        except LLMNotConfigured as e:
            return _error(str(e), 503)
        except Exception:
            log.exception('Question answering failed')
            return _error('Something went wrong while answering. Please try again.', 500)

        history = session.get('chat_history', [])
        history.append({'question': question, 'answer': res['answer'][:600]})
        session['chat_history'] = history[-MAX_HISTORY:]
        return jsonify({'status': 'success', 'answer': res['answer'], 'citations': res['citations'],
                        'sources': [{k: r[k] for k in ('rank', 'pages', 'text')} for r in res['retrieved']],
                        'usage': res['usage'], 'latency_ms': res['latency_ms']})

    return _error('Invalid request')


@chat_app.route('/stats')
def stats():
    """Aggregate token / cost / latency numbers from data/metrics/requests.jsonl."""
    f = get_service().cfg.metrics_file
    rows = [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()] if f.exists() else []
    live = [r for r in rows if not r['usage'].get('cached')]

    def med(vals):
        vals = [v for v in vals if v is not None]
        return statistics.median(vals) if vals else None

    return jsonify({'requests': len(rows), 'llm_calls': len(live), 'cache_hits': len(rows) - len(live),
                    'input_tokens_median': med([r['usage']['input_tokens'] for r in live]),
                    'output_tokens_median': med([r['usage']['output_tokens'] for r in live]),
                    'cost_usd_total_if_paid_tier': round(sum(r['usage']['cost_usd'] or 0 for r in live), 6),
                    'latency_ms_median': med([r['latency_ms']['total'] for r in live])})


@chat_app.errorhandler(413)
def too_large(e):
    return jsonify({'status': 'error', 'message': 'File is too large'}), 413
