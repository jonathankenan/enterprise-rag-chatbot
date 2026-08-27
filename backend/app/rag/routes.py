"""Endpoint: POST /api/documents/upload — unggah PDF untuk masuk ke knowledge base RAG."""
import io
import uuid

from fastapi import APIRouter, UploadFile, File, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, User
from app.auth.utils import get_current_user
from app.rag.vectorstore import extract_pages_from_pdf, index_document
from app.guardrail.filters import is_prompt_blocked, get_blocked_category
from app.guardrail.prompt_injection import is_prompt_injection, get_matched_signals
from app.guardrail.audit_log import log_guardrail_event, EventType

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCUMENT_REJECTED_MESSAGE = (
    "Dokumen ditolak karena teks di dalamnya terindikasi melanggar kebijakan "
    "penggunaan atau mengandung upaya prompt injection."
)


@router.post("/upload")
async def upload_document(
    chat_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    file_bytes = await file.read()
    pages = extract_pages_from_pdf(io.BytesIO(file_bytes))
    text = "\n\n".join(p["text"] for p in pages)  # flat text buat guardrail scan; indexing pakai `pages` supaya bisa ditag nomor halaman

    # Guardrail F2-04 (SRS hal. 15 poin c) pada konten dokumen, bukan cuma prompt chat -- scan seluruh teks sekaligus, bukan per-chunk (trade-off kesederhanaan, risiko false-positive pada dokumen sangat panjang)
    doc_blocked = is_prompt_blocked(text)
    doc_injection = is_prompt_injection(text)


    if doc_blocked or doc_injection:
        metadata = {"filename": file.filename, "chat_id": chat_id}
        if doc_blocked:
            metadata["reason"] = "blocked_keyword"
            metadata["category"] = get_blocked_category(text)
        if doc_injection:
            metadata["reason"] = "prompt_injection" if not doc_blocked else "blocked_keyword+prompt_injection"
            metadata["matched_patterns"] = get_matched_signals(text)

        log_guardrail_event(
            db, user.id, EventType.DOCUMENT_BLOCKED,
            detail=f"document_upload:{file.filename}", metadata=metadata,
        )
        raise HTTPException(status_code=400, detail=DOCUMENT_REJECTED_MESSAGE)

    doc_id = str(uuid.uuid4())
    chunk_count = index_document(pages=pages, doc_id=doc_id, filename=file.filename, chat_id=chat_id)

    doc_record = Document(id=doc_id, uploaded_by=user.id, filename=file.filename)
    db.add(doc_record)
    db.commit()

    log_guardrail_event(  # upload berhasil (beda dari DOCUMENT_BLOCKED), layak dicatat siapa yang menambahkannya
        db, user.id, EventType.DOCUMENT_UPLOADED,
        detail=f"document_upload:{file.filename}",
        metadata={"chat_id": chat_id, "doc_id": doc_id, "chunk_count": chunk_count},
    )

    return {"filename": file.filename, "chunks_indexed": chunk_count}
