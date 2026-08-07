import io
import jinja2
from xhtml2pdf import pisa
from datetime import datetime

PDF_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        @page { size: A4; margin: 15mm; }
        body { font-family: sans-serif; font-size: 10pt; }
        .header { border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; }
        .message { margin-bottom: 12px; }
        .user { text-align: right; color: #2b6cb0; }
        .assistant { text-align: left; color: #2d3748; background: #f7fafc; padding: 10px; border-radius: 6px; }
        
        /* Avoid splitting chat bubbles across two pages */
        .chat-bubble, .message-row, .message {
          page-break-inside: avoid !important;
        }

        /* Ensure code blocks and tables format cleanly */
        pre, table {
          page-break-inside: avoid !important;
          max-width: 100%;
          overflow-x: hidden;
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>{{ session_title }}</h2>
        <p>Exported on: {{ export_date }} | Model: {{ model_used }}</p>
    </div>
    
    {% for msg in messages %}
        <div class="message {{ msg.role }}">
            <strong>{{ msg.role.capitalize() }}:</strong>
            <div>{{ msg.content }}</div>
        </div>
    {% endfor %}
</body>
</html>
"""

def generate_pdf(session_title: str, messages: list, model_used: str = "Various") -> bytes:
    # Render HTML template
    template = jinja2.Template(PDF_TEMPLATE)
    html_out = template.render(
        session_title=session_title,
        export_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model_used=model_used,
        messages=messages
    )
    
    # Convert HTML to PDF using xhtml2pdf
    pdf_file = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_out, dest=pdf_file)
    
    if pisa_status.err:
        raise Exception("Error rendering PDF")
        
    return pdf_file.getvalue()
