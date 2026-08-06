"""
[PENANGGUNG JAWAB: Anggota A]
Endpoint: POST /api/documents/upload — unggah PDF untuk masuk ke knowledge base RAG.
"""
import io
import uuid

from fastapi import APIRouter, UploadFile, File, Depends, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, User
from app.auth.utils import get_current_user
from app.rag.vectorstore import extract_text_from_pdf, index_document

router = APIRouter(prefix="/api/documents", tags=["documents"])

@router.post("/upload")
async def upload_document(
    chat_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    file_bytes = await file.read()
    text = extract_text_from_pdf(io.BytesIO(file_bytes))

    doc_id = str(uuid.uuid4())
    chunk_count = index_document(text=text, doc_id=doc_id, filename=file.filename, chat_id=chat_id)

    doc_record = Document(id=doc_id, uploaded_by=user.id, filename=file.filename)
    db.add(doc_record)
    db.commit()

    return {"filename": file.filename, "chunks_indexed": chunk_count}
