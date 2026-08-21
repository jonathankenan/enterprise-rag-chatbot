"""
[PENANGGUNG JAWAB: Anggota B]
Multi-Tenant Knowledge Base — SRS poin 11 & hal. 68/70: "Knowledge Base
dapat dibuatkan terpisah untuk setiap divisi... Terdapat Knowledge Base
Company Wide dengan klasifikasi informasi umum internal seperti POJK,
Peraturan BEI, SK yang dapat di akses oleh semua divisi."

Otorisasi (SRS hal. 64: "Admin IT" vs "Admin User [divisi]" — 2 level admin
berbeda, TANPA field/flag tambahan, cukup baca User.divisi milik admin itu
sendiri lewat get_divisi_scope()):
  - IT_ADMIN dengan divisi=None -> admin GLOBAL, kelola KB divisi mana pun + Company Wide.
  - IT_ADMIN dengan divisi="PTI" -> admin TERBATAS, cuma boleh kelola KB PTI
    sendiri. TIDAK bisa upload/hapus dokumen Company Wide atau divisi lain.
"""
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, Divisi, KbDocument
from app.schemas import KbDocumentResponse
from app.auth.utils import require_role, get_divisi_scope
from app.guardrail.audit_log import log_guardrail_event, EventType
from app.guardrail.filters import is_prompt_blocked, get_blocked_category
from app.guardrail.prompt_injection import is_prompt_injection, get_matched_signals
from app.rag.vectorstore import extract_text_from_pdf, index_kb_document, delete_kb_document_from_index

router = APIRouter(prefix="/api/kb", tags=["kb"])

KB_PDF_REJECTED_MESSAGE = (
    "PDF ditolak karena teks di dalamnya terindikasi melanggar kebijakan "
    "penggunaan atau mengandung upaya prompt injection."
)


def _assert_can_manage(admin: User, target_divisi: str | None):
    """
    target_divisi=None berarti upload/hapus dokumen COMPANY WIDE. Cuma
    admin GLOBAL (scope None) yang boleh menyentuh Company Wide — admin
    divisi TIDAK boleh, supaya informasi "umum internal" (POJK/Peraturan
    BEI/SK) tetap satu sumber kebenaran yang dikurasi terpusat.
    """
    scope = get_divisi_scope(admin)
    if scope is None:
        return  # admin global — bebas
    if target_divisi != scope:
        raise HTTPException(
            status_code=403,
            detail=f"Anda cuma admin divisi {scope} — tidak bisa mengelola dokumen divisi lain atau Company Wide",
        )


@router.get("/documents", response_model=list[KbDocumentResponse])
def list_documents(db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    scope = get_divisi_scope(admin)
    query = db.query(KbDocument)
    if scope is not None:
        # Admin divisi lihat dokumen divisinya + Company Wide (buat konteks
        # "ini yang berlaku ke user saya juga"), meski cuma boleh HAPUS yang divisinya sendiri.
        query = query.filter((KbDocument.divisi == scope) | (KbDocument.divisi.is_(None)))
    return query.order_by(KbDocument.created_at.desc()).all()


@router.post("/upload", response_model=KbDocumentResponse)
async def upload_kb_document(
    file: UploadFile = File(...),
    divisi: str | None = Form(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    if divisi == "":
        divisi = None
    if divisi is not None and divisi not in Divisi.ALL:
        raise HTTPException(status_code=400, detail=f"Divisi tidak dikenal: {divisi}")
    _assert_can_manage(admin, divisi)

    file_bytes = await file.read()
    text = extract_text_from_pdf(io.BytesIO(file_bytes))

    # Sama seperti upload dokumen chat & FAQ — konten yang masuk ke RAG
    # (apalagi ini bisa ditarik SELURUH divisi atau company-wide) wajib
    # lolos guardrail F2-04 sebelum diindeks.
    if is_prompt_blocked(text) or is_prompt_injection(text):
        log_guardrail_event(
            db, admin.id, EventType.DOCUMENT_BLOCKED,
            detail=f"kb_document_upload:{file.filename}",
            metadata={"divisi": divisi, "category": get_blocked_category(text), "matched_patterns": get_matched_signals(text)},
        )
        raise HTTPException(status_code=400, detail=KB_PDF_REJECTED_MESSAGE)

    doc_id = str(uuid.uuid4())
    chunk_count = index_kb_document(text=text, doc_id=doc_id, filename=file.filename, divisi=divisi)

    doc_record = KbDocument(id=doc_id, divisi=divisi, filename=file.filename, chunk_count=chunk_count, uploaded_by=admin.id)
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    log_guardrail_event(
        db, admin.id, EventType.KB_DOCUMENT_UPLOADED,
        detail=f"kb_document_upload:{file.filename}",
        metadata={"divisi": divisi or "company_wide", "doc_id": doc_id, "chunk_count": chunk_count},
    )
    return doc_record


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    doc = db.query(KbDocument).filter(KbDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
    _assert_can_manage(admin, doc.divisi)

    delete_kb_document_from_index(doc_id)
    db.delete(doc)
    db.commit()

    log_guardrail_event(
        db, admin.id, EventType.KB_DOCUMENT_DELETED,
        detail=f"kb_document_delete:{doc.filename}",
        metadata={"divisi": doc.divisi or "company_wide", "doc_id": doc_id},
    )
    return {"message": "Dokumen dihapus"}
