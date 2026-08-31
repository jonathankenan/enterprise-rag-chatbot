"""CRUD FAQ Helpdesk (SRS poin 10.b) — Postgres jadi source-of-truth, tiap create/delete juga sync ke index ChromaDB kb_faq_helpdesk. Dibatasi Role.IT_ADMIN."""
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User, FaqEntry
from app.schemas import CreateFaqRequest, FaqEntryResponse, FaqBulkImportResponse
from app.auth.utils import require_role
from app.guardrail.audit_log import log_guardrail_event, EventType
from app.guardrail.filters import is_prompt_blocked, get_blocked_category
from app.guardrail.prompt_injection import is_document_injection, get_document_matched_signals
from app.rag.vectorstore import index_faq_entry, delete_faq_entry_from_index, extract_text_from_pdf
from app.faq.parser import parse_faq_pairs

router = APIRouter(prefix="/api/faq", tags=["faq"])

FAQ_PDF_REJECTED_MESSAGE = (
    "PDF ditolak karena teks di dalamnya terindikasi melanggar kebijakan "
    "penggunaan atau mengandung upaya prompt injection."
)


@router.get("", response_model=list[FaqEntryResponse])
def list_faqs(db: Session = Depends(get_db), user: User = Depends(require_role(Role.IT_ADMIN))):
    return db.query(FaqEntry).order_by(FaqEntry.created_at.desc()).all()


@router.post("", response_model=FaqEntryResponse)
def create_faq(
    payload: CreateFaqRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    entry = FaqEntry(question=payload.question, answer=payload.answer, created_by=admin.id)
    db.add(entry)
    db.commit()
    db.refresh(entry)

    index_faq_entry(entry.id, entry.question, entry.answer)  # diindeks setelah commit supaya baris Postgres tidak hilang kalau ini gagal

    log_guardrail_event(
        db, admin.id, EventType.FAQ_CREATED,
        detail=f"FAQ dibuat: {entry.question[:100]}",
        metadata={"faq_id": entry.id},
    )
    return entry


@router.post("/upload-pdf", response_model=FaqBulkImportResponse)
async def upload_faq_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(Role.IT_ADMIN)),
):
    """Bulk-import FAQ dari 1 PDF (format Q:/A:, Pertanyaan:/Jawaban:, atau baris "?") — tiap pasangan jadi 1 FaqEntry terpisah."""
    file_bytes = await file.read()
    text = extract_text_from_pdf(io.BytesIO(file_bytes))

    # Sama seperti upload dokumen chat (rag/routes.py) — konten yang masuk
    # ke RAG (apalagi FAQ ini company-wide, ditarik ke SEMUA chat) tetap
    # wajib lolos guardrail F2-04 sebelum diindeks.
    if is_prompt_blocked(text) or is_document_injection(text):
        log_guardrail_event(
            db, admin.id, EventType.DOCUMENT_BLOCKED,
            detail=f"faq_pdf_upload:{file.filename}",
            metadata={"category": get_blocked_category(text), "matched_patterns": get_document_matched_signals(text)},
        )
        raise HTTPException(status_code=400, detail=FAQ_PDF_REJECTED_MESSAGE)

    pairs = parse_faq_pairs(text)
    if not pairs:
        raise HTTPException(
            status_code=400,
            detail="Tidak ditemukan pola tanya-jawab di PDF ini. Format yang didukung: 'Q: .../A: ...', "
                   "'Pertanyaan: .../Jawaban: ...', atau baris pertanyaan (diakhiri '?') diikuti jawabannya.",
        )

    created = [FaqEntry(question=q, answer=a, created_by=admin.id) for q, a in pairs]  # commit Postgres dulu, baru index satu-satu
    db.add_all(created)
    db.commit()
    for entry in created:
        db.refresh(entry)
        index_faq_entry(entry.id, entry.question, entry.answer)

    log_guardrail_event(
        db, admin.id, EventType.FAQ_CREATED,
        detail=f"Bulk import {len(created)} FAQ dari {file.filename}",
        metadata={"filename": file.filename, "count": len(created)},
    )
    return FaqBulkImportResponse(filename=file.filename, created=created, count=len(created))


@router.delete("/{faq_id}")
def delete_faq(faq_id: str, db: Session = Depends(get_db), admin: User = Depends(require_role(Role.IT_ADMIN))):
    entry = db.query(FaqEntry).filter(FaqEntry.id == faq_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="FAQ tidak ditemukan")

    delete_faq_entry_from_index(faq_id)
    db.delete(entry)
    db.commit()

    log_guardrail_event(
        db, admin.id, EventType.FAQ_DELETED,
        detail=f"FAQ dihapus: {entry.question[:100]}",
        metadata={"faq_id": faq_id},
    )
    return {"message": "FAQ dihapus"}
