"""
Tests for SRS FCR-003 poin 12.a — source citation.

Run from the repo root:      python backend/tests/test_source_citation.py
(or with pytest:             pytest backend/tests/test_source_citation.py)

No Postgres, no Ollama, no API keys, and no Chroma data. The two units under
test are pure functions: the tail of retrieve_context() is sliced out by AST
and exec'd over a namespace seeded from the real module, so what runs here is
verbatim the code that ships, not a copy that can drift.

  * _build_source_citations()  — backend/app/chat/routes.py
  * the top-match / confidence tail of retrieve_context()
                               — backend/app/rag/vectorstore.py
"""
import ast
import sys
from pathlib import Path

# repo root = two levels up from backend/tests/
APP = Path(__file__).resolve().parents[1] / "app"
if not APP.is_dir():  # fallback when run from an unexpected cwd
    raise SystemExit(f"cannot find backend/app at {APP}")

ROUTES_SRC = (APP / "chat" / "routes.py").read_text(encoding="utf-8")
SCHEMAS_SRC = (APP / "schemas.py").read_text(encoding="utf-8")
VECTOR_SRC = (APP / "rag" / "vectorstore.py").read_text(encoding="utf-8")


def _segment(source: str, name: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise LookupError(f"{name} not found")


def _assignment(source: str, name: str) -> str:
    """Same idea as _segment but for a module-level constant (e.g. a compiled
    regex), so the tests use the shipping pattern rather than a copy."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return ast.get_source_segment(source, node)
    raise LookupError(f"{name} not found")


# ---------------------------------------------------------------- load units
_ns: dict = {}
exec("from pydantic import BaseModel", _ns)
exec(_segment(SCHEMAS_SRC, "CitationChunk"), _ns)
exec(_segment(SCHEMAS_SRC, "SourceCitation"), _ns)
exec(_segment(ROUTES_SRC, "_build_source_citations"), _ns)
build_citations = _ns["_build_source_citations"]

_fn = _segment(VECTOR_SRC, "retrieve_context")
_tail = _fn[_fn.index("    docs = docs[:top_k]"):]
_tail = "\n".join(l[4:] if l.startswith("    ") else l for l in _tail.split("\n"))
_helper = _segment(VECTOR_SRC, "_distance_to_similarity_percent")
# The tail closes over several module-level helpers (the lexical identifier
# gate, the example detector, the table-row counter, the synthesis expansion).
# Listing them by hand broke these tests four separate times: every new helper
# `retrieve_context` touched had to be registered here or ~19 tests failed with
# a bare NameError, which reads like broken logic rather than a stale list.
#
# So the namespace is seeded from the REAL module instead. Same property the
# hand-written list was after -- what runs is the shipping code, not a copy --
# but the dependency list now maintains itself.
#
# Importing app.rag.vectorstore is safe here: it touches no database and no
# network at import time. It does load chromadb/langchain, which is why this
# file no longer claims to need nothing installed.
import app.rag.vectorstore as _vs


# Chroma is never reached: _expand_table_rows() is the tail's only caller of
# get_collection(), and an empty store makes it a no-op. These tests are about
# citation selection; expansion has its own tests in test_table_chunking.py.
class _EmptyCollection:
    def get(self, *a, **k):
        return {"documents": [], "metadatas": []}


def _config_default(name: str):
    """Read a Settings default straight out of config.py, so these tests use
    the real configured value instead of a hardcoded copy that can drift."""
    src = (APP / "config.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)
    raise LookupError(f"{name} not found in config.py")


class _Settings:
    citation_similarity_gap = _config_default("citation_similarity_gap")


def select(docs, top_k=10, search_query=""):
    """Run the real is_top_match/confidence block over stub documents.

    search_query defaults to "" — no identifier token, so the 2026-08-26
    lexical gate stays inert and these tests exercise the similarity floor on
    its own, exactly as they did before the gate existed. Pass a real query to
    test the gate itself.
    """
    ns = dict(vars(_vs))
    # chat_id/collection_name adalah PARAMETER retrieve_context, bukan helper
    # modul -- tail memakainya sejak ekspansi baris tabel ditambahkan.
    ns.update({"docs": list(docs), "top_k": top_k, "settings": _Settings,
               "chat_id": "test-chat", "collection_name": "kb_general",
               "search_query": search_query,
               "get_collection": lambda *a, **k: _EmptyCollection()})
    exec(_helper, ns)
    exec(_tail.replace("return chunks, confidence", "__r__ = (chunks, confidence)"), ns)
    return ns["__r__"]


GAP = _Settings.citation_similarity_gap


def dist_for(sim_pct: float) -> float:
    """Inverse of _distance_to_similarity_percent: the distance a chunk needs
    to land on a given similarity. Lets a test say "rank 2 sits one point
    inside the gap" instead of hardcoding a distance that silently encodes
    whatever citation_similarity_gap happened to be when it was written --
    which is exactly how three tests broke when the gap moved 15 -> 5 on
    2026-08-26."""
    return 2 * (1 - sim_pct / 100)


class Doc:
    """
    Stand-in for a langchain Document.

    text defaults to a per-instance UNIQUE placeholder, not a fixed "...".
    2026-09-01: citation selection started deduping candidates by page_content
    shape (see _dedup_shape in retrieve_context) so two near-identical chunks
    can't both win a citation slot. Every existing fixture that left text at
    its old fixed default would collide under that check and look like
    duplicates of each other -- not what those tests are about. A test that
    genuinely wants duplicate/near-duplicate text still can, by passing
    text= explicitly with the same string on two Docs.
    """
    _counter = 0

    def __init__(self, text=None, **meta):
        if text is None:
            Doc._counter += 1
            text = f"chunk placeholder #{Doc._counter}"
        self.page_content = text
        self.metadata = meta


def chunk(text="...", filename=None, page=None, source_type="chat_document",
          is_top_match=True, chunk_index=0):
    """Mirror the dict shape retrieve_context() emits."""
    return {"text": text, "filename": filename, "chunk_index": chunk_index,
            "page": page, "source_type": source_type, "is_top_match": is_top_match}


def labels(citations):
    return [c.label for c in citations]


# ======================================================= _build_source_citations

def test_one_doc_many_chunks_dedups_and_merges_pages():
    got = build_citations([
        chunk(filename="NEXUS_BRD.pdf", page=7),
        chunk(filename="NEXUS_BRD.pdf", page=3),
        chunk(filename="NEXUS_BRD.pdf", page=7),
    ])
    assert labels(got) == ["NEXUS_BRD.pdf (hal. 3, 7)"]
    assert got[0].pages == [3, 7]


def test_citation_order_follows_relevance_not_alphabet():
    got = build_citations([chunk(filename="B.pdf", page=2),
                           chunk(filename="A.pdf", page=1)])
    assert labels(got) == ["B.pdf (hal. 2)", "A.pdf (hal. 1)"]


def test_non_top_match_chunks_excluded():
    """Regression: the FR-01 report — citations naming topically-nearby pages."""
    got = build_citations([
        chunk(filename="NEXUS_BRD.pdf", page=1, is_top_match=True),
        chunk(filename="NEXUS_BRD.pdf", page=2, is_top_match=False),
        chunk(filename="Unrelated.pdf", page=9, is_top_match=False),
    ])
    assert labels(got) == ["NEXUS_BRD.pdf (hal. 1)"]


def test_missing_is_top_match_defaults_true():
    """get_all_session_chunks() ('ringkas semua') emits no is_top_match key."""
    got = build_citations([{"text": "x", "filename": "Ringkasan.pdf",
                            "chunk_index": 0, "page": 4,
                            "source_type": "chat_document"}])
    assert labels(got) == ["Ringkasan.pdf (hal. 4)"]


def test_faq_entries_collapse_to_one_citation():
    got = build_citations([chunk(source_type="faq"), chunk(source_type="faq")])
    assert labels(got) == ["FAQ Helpdesk"]
    assert got[0].pages == [] and got[0].filename is None


def test_same_filename_different_source_type_stays_separate():
    got = build_citations([
        chunk(filename="Kebijakan.pdf", page=1, source_type="chat_document"),
        chunk(filename="Kebijakan.pdf", page=5, source_type="kb_divisi"),
    ])
    assert labels(got) == ["Kebijakan.pdf (hal. 1)", "Kebijakan.pdf (hal. 5)"]


def test_missing_filename_gets_placeholder():
    got = build_citations([chunk(filename=None, page=2)])
    assert labels(got) == ["Dokumen tanpa nama (hal. 2)"]


def test_unmapped_pages_omit_the_page_suffix():
    """extract_pages_from_pdf() bailed -> empty rather than guessed."""
    got = build_citations([chunk(filename="Tabel.pdf", page=None),
                           chunk(filename="Tabel.pdf", page=None)])
    assert labels(got) == ["Tabel.pdf"]
    assert got[0].pages == []


def test_partial_page_mapping_lists_only_known_pages():
    got = build_citations([chunk(filename="Campuran.pdf", page=None),
                           chunk(filename="Campuran.pdf", page=6)])
    assert labels(got) == ["Campuran.pdf (hal. 6)"]


def test_empty_context_yields_no_citations():
    assert build_citations([]) == []


def test_page_zero_is_recorded_not_skipped():
    """Guards `if page is not None` against regressing to `if page`."""
    got = build_citations([chunk(filename="Z.pdf", page=0)])
    assert got[0].pages == [0]


# ============================================================ selection logic

def test_top_matches_gates_citations_but_not_context():
    """Vector-only path: Chroma returns distance-ascending, so the first three
    positions are the three closest."""
    # ranks 2 and 3 sit inside the gap whatever it is set to, so this test
    # stays about the top-3 window and not about the floor's exact value.
    sims = [95, 95 - GAP / 3, 95 - 2 * GAP / 3]
    docs = [
        Doc(filename="BRD.pdf", page=1, _distance=dist_for(sims[0])),
        Doc(filename="BRD.pdf", page=2, _distance=dist_for(sims[1])),
        Doc(filename="BRD.pdf", page=3, _distance=dist_for(sims[2])),
        Doc(filename="BRD.pdf", page=4, _distance=dist_for(95 - GAP - 20)),
        Doc(filename="BRD.pdf", page=5, _distance=dist_for(95 - GAP - 25)),
    ]
    chunks, confidence = select(docs)
    assert len(chunks) == 5, "full context must still reach the LLM"
    assert [c["is_top_match"] for c in chunks] == [True, True, True, False, False]
    assert build_citations(chunks)[0].pages == [1, 2, 3]
    assert confidence == round(sum(sims) / len(sims))


def test_selection_follows_ensemble_rank_not_raw_distance():
    """Hybrid path: EnsembleRetriever returns RRF-fused order, so distances
    are NOT ascending. The first three positions still win — that fused rank
    is what actually decided what the LLM saw."""
    docs = [
        Doc(filename="BRD.pdf", page=1, _distance=0.10),   # sim 95
        Doc(filename="BRD.pdf", page=2, _distance=0.20),   # sim 90, RRF 2nd
        Doc(filename="BRD.pdf", page=3, _distance=0.16),   # sim 92
        Doc(filename="BRD.pdf", page=4, _distance=0.60),
        Doc(filename="BRD.pdf", page=5, _distance=0.14),   # sim 93, ranked last
    ]
    chunks, _ = select(docs)
    assert [c["is_top_match"] for c in chunks] == [True, True, True, False, False]
    assert build_citations(chunks)[0].pages == [1, 2, 3], \
        "page 5 is closer by cosine but the ensemble ranked it out of the top 3"


def test_confidence_ignores_chunks_beyond_the_top_three():
    """The 2026-08-24 fix: chunks 4..top_k no longer affect the score."""
    strong = [Doc(_distance=0.1, filename="a.pdf", page=p) for p in range(1, 4)]
    junk = [Doc(_distance=1.9, filename="a.pdf", page=p) for p in range(4, 11)]
    assert select(strong)[1] == select(strong + junk)[1] == 95


def test_lone_precise_match_is_not_diluted_by_filler():
    """
    Regression for the 2026-08-25 relevance floor. TOP_MATCHES used to be a
    fixed count, so one precise hit was always averaged with the next two
    however bad: a 95%-similarity chunk surrounded by junk reported 38%, shown
    in red by chat/page.jsx on an answer backed by a near-exact match. Ranks
    2-3 now have to earn their slot.
    """
    docs = [Doc(_distance=0.1, filename="a.pdf", page=1)] + [
        Doc(_distance=1.8, filename="a.pdf", page=p) for p in range(2, 9)
    ]
    chunks, confidence = select(docs)
    assert build_citations(chunks)[0].pages == [1], "filler must not be cited"
    assert confidence == 95, "and must not drag the score down either"
    assert len(chunks) == 8, "full context still reaches the LLM"


def test_close_scores_all_survive_the_floor():
    """FR-12 multi-document synthesis: three genuinely comparable sources must
    all stay cited. The floor is relative, so nothing is dropped here."""
    docs = [Doc(filename="A.pdf", page=2, _distance=0.30),
            Doc(filename="B.pdf", page=5, _distance=0.34),
            Doc(filename="C.pdf", page=1, _distance=0.36)]
    chunks, _ = select(docs)
    assert all(c["is_top_match"] for c in chunks)
    assert [c.filename for c in build_citations(chunks)] == ["A.pdf", "B.pdf", "C.pdf"]


def test_dedup_shape_ignores_a_heading_shared_by_every_row():
    """Regression: found live on 'daftar regulasi yang berlaku di perusahaan'.
    Four DIFFERENT regulation rows (REG-01..04) each carry the same >120-char
    intro heading ("### Ketentuan turunan mengenai sanksi administratif
    dimuat pada REG-08...") because chunk_text() attaches it to every row of
    the table it introduces. The old fingerprint was just the first 120 raw
    characters, so all four rows collided on the heading alone and three of
    four were discarded as "duplicates" of the first -- even though they are
    four distinct regulations. Restricting the fingerprint to the table row
    itself (same technique as _is_render_duplicate) tells them apart."""
    heading = ("### Ketentuan turunan mengenai sanksi administratif dimuat pada "
               "REG-08, yang masih dalam proses penyusunan lebih dari seratus dua "
               "puluh karakter panjangnya supaya benar-benar menguji batas prefix.\n\n"
               "|Kode|Peraturan|Penerbit|Berlaku<br>Sejak|\n|---|---|---|---|\n")
    docs = [
        Doc(heading + "|REG-01|POJK Nomor 4/POJK.04/2025 tentang Keterbukaan Informasi|Otoritas Jasa<br>Keuangan|1 Maret 2025|",
            filename="CompanyWide.pdf", page=1, _distance=dist_for(80)),
        Doc(heading + "|REG-02|Peraturan Bursa Nomor I-A tentang Pencatatan Saham|Bursa Efek<br>Indonesia|1 Januari 2024|",
            filename="CompanyWide.pdf", page=1, _distance=dist_for(78)),
    ]
    chunks, _ = select(docs, search_query="daftar regulasi yang berlaku di perusahaan")
    assert all(c["is_top_match"] for c in chunks), "two distinct regulations sharing an intro heading must both be citable"


def test_rank_two_just_inside_and_just_outside_the_gap():
    """The boundary itself, expressed relative to the configured gap."""
    inside = [Doc(filename="a.pdf", page=1, _distance=dist_for(95)),
              Doc(filename="a.pdf", page=2, _distance=dist_for(95 - GAP + 1))]   # keep
    outside = [Doc(filename="a.pdf", page=1, _distance=dist_for(95)),
               Doc(filename="a.pdf", page=2, _distance=dist_for(95 - GAP - 1))]  # drop
    assert build_citations(select(inside)[0])[0].pages == [1, 2]
    assert build_citations(select(outside)[0])[0].pages == [1]


def test_unscored_rank_one_sets_a_strict_bar():
    """A BM25 exact match at rank 1 has no similarity, so it is treated as the
    highest possible reference — ranks 2-3 must be genuinely strong to join it.
    This is the live 'hal. 7, 9, 11' case: only page 7 should survive."""
    docs = [Doc("FR-01 spec", filename="B.pdf", page=7),               # BM25
            Doc("nearby", filename="B.pdf", page=9, _distance=0.78),   # sim 61
            Doc("nearby", filename="B.pdf", page=11, _distance=0.80)]  # sim 60
    chunks, confidence = select(docs)
    assert build_citations(chunks)[0].pages == [7]
    assert confidence is None, "nothing cited carries a comparable score"


def test_fewer_than_three_vector_chunks_still_scores():
    docs = [Doc(filename="Memo.pdf", page=1, _distance=dist_for(92.5)),
            Doc(filename="Memo.pdf", page=2, _distance=dist_for(92.5 - GAP / 2))]
    chunks, confidence = select(docs)
    assert all(c["is_top_match"] for c in chunks)
    assert confidence is not None


def test_source_type_inferred_from_metadata_keys():
    chunks, _ = select([
        Doc(faq_id="f1", _distance=0.2),
        Doc(filename="k.pdf", divisi="IT", page=1, _distance=0.3),
        Doc(filename="c.pdf", page=1, _distance=0.4),
    ])
    assert [c["source_type"] for c in chunks] == ["faq", "kb_divisi", "chat_document"]


# ------------------------------------------------------ BM25 citability (fix)

def test_bm25_only_chunk_can_be_cited():
    """
    Regression for the 2026-08-25 fix. A chunk retrieved only by the BM25 leg
    carries no "_distance". Selecting on raw cosine distance made it
    permanently uncitable, so "jelaskan req ID FR-01" was answered correctly
    from the page-7 chunk while the citation named pages 6 and 9 -- the
    vector leg's topical neighbours. Selecting on ensemble rank lets it
    compete.
    """
    docs = [
        Doc("FR-01 spec — the actual answer", filename="BRD.pdf", page=7),  # BM25 only
        Doc("scope prose", filename="BRD.pdf", page=6, _distance=0.62),
        Doc("api prose", filename="BRD.pdf", page=9, _distance=0.66),
        Doc("nfr prose", filename="BRD.pdf", page=8, _distance=0.70),
    ]
    chunks, _ = select(docs)
    cited = build_citations(chunks)[0].pages
    assert 7 in cited, "the chunk that actually answered must be citable"
    assert 8 not in cited, "still capped at TOP_MATCHES"


# ------------------------------- BM25-only relevance gate (added 2026-09-01)
# "sim is None -> cited unconditionally" above is safe for identifier queries
# (_has_query_id already forces an exact code match). For a synthesis query
# with no identifier, _has_query_id is inert, so that same rule used to let
# ANY BM25 hit through -- BM25Retriever has no score floor of its own, it
# just returns its top-k regardless of how weak the match is. Live case:
# "daftar regulasi yang berlaku di perusahaan" cited a completely unrelated
# "PTI-03 Daftar Risiko PTI" row that shared exactly one word ("daftar")
# with the query, found only via the KB-divisi BM25 leg added the same day.

def test_bm25_only_needs_relevance_when_query_has_no_identifier():
    docs = [
        Doc("REG-01 POJK tentang Keterbukaan Informasi Otoritas Jasa Keuangan",
            filename="CompanyWide.pdf", page=1, _distance=dist_for(75)),
        Doc("PTI-03 Daftar Risiko PTI Manajemen Risiko Triwulanan",  # BM25 only, shares just "daftar"
            filename="PTI.pdf", page=1),
    ]
    chunks, _ = select(docs, search_query="daftar regulasi yang berlaku di perusahaan")
    assert not any(c["filename"] == "PTI.pdf" and c["is_top_match"] for c in chunks), \
        "one incidental shared word must not be enough to earn a citation slot"


def test_bm25_only_relevance_gate_ignores_stopwords():
    """Regression: the first version of this gate counted 'yang' (a
    connector, no topical meaning) as 1 of 4 'content' query words purely
    because it happened to be 4+ letters -- 25% of the overlap budget for
    free. A chunk whose only real overlap is a stopword must still fail."""
    docs = [
        Doc("REG-01 POJK tentang Keterbukaan Informasi Otoritas Jasa Keuangan",
            filename="CompanyWide.pdf", page=1, _distance=dist_for(75)),
        Doc("Dokumen ini mengatur tata kerja divisi yang sama sekali berbeda dari topik lain",
            filename="PTI.pdf", page=1),  # BM25 only, overlaps only on "yang"
    ]
    chunks, _ = select(docs, search_query="daftar regulasi yang berlaku di perusahaan")
    assert not any(c["filename"] == "PTI.pdf" and c["is_top_match"] for c in chunks)


def test_bm25_only_relevance_gate_admits_real_overlap():
    """Positive control -- a BM25-only chunk that genuinely shares most of
    the query's content words must still be citable. The gate targets weak
    incidental matches, not BM25-only citability itself."""
    docs = [
        Doc("Daftar regulasi perusahaan yang berlaku mencakup empat POJK dan Peraturan Bursa",
            filename="CompanyWide.pdf", page=1),  # BM25 only, but genuinely on-topic
    ]
    chunks, _ = select(docs, search_query="daftar regulasi yang berlaku di perusahaan")
    assert chunks[0]["is_top_match"]


def test_bm25_only_relevance_gate_is_inert_for_identifier_queries():
    """An identifier query is already guarded by _has_query_id, which is a
    stricter, more precise check than generic word overlap -- the new gate
    must not double-filter and must not reject a legitimate exact-string
    BM25 match just because the surrounding prose shares few other words."""
    docs = [
        Doc("FR-01 spec — the actual answer, nothing else in common with the question",
            filename="BRD.pdf", page=7),  # BM25 only
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert chunks[0]["is_top_match"]


def test_all_bm25_result_is_cited_but_scores_no_confidence():
    """All-BM25 result: citable (they are what the LLM saw), but there is no
    cosine-comparable number, so confidence stays None rather than inventing
    one. chat/routes.py guards None before the escalation comparison."""
    chunks, confidence = select([Doc(filename="BRD.pdf", page=4),
                                 Doc(filename="BRD.pdf", page=5)])
    assert build_citations(chunks)[0].pages == [4, 5]
    assert confidence is None


def test_confidence_skips_unscored_chunks_but_still_cites_them():
    """A BM25 chunk in the top 3 is cited without dragging the average — it
    has no comparable number, so it is excluded from the mean only."""
    docs = [
        Doc("exact match", filename="BRD.pdf", page=7),                  # no distance
        Doc("close", filename="BRD.pdf", page=1, _distance=0.10),
        Doc("close", filename="BRD.pdf", page=2, _distance=0.10),
    ]
    chunks, confidence = select(docs)
    assert build_citations(chunks)[0].pages == [1, 2, 7]
    assert confidence == 95, "mean of the two scored chunks only"


# ------------------------------------------- lexical gate (added 2026-08-26)
# Regression cover for the reported bug: "jelaskan req ID FR-01" cited
# hal. 1, 3, 7 -- page 1 is the cover sheet (no "FR-01" anywhere on it) and
# page 3 is the Table of Contents (has the string, but only as a nav line).
# Measured on the real corpus, the whole top-10 spanned 8 similarity points,
# so the floor alone could never separate them.

def test_identifier_query_drops_chunks_that_lack_the_identifier():
    docs = [
        Doc("|**FR-01**|Retrieval Accuracy|... 92% (MRR@5)|Must Have|",
            filename="BRD.pdf", page=7, _distance=dist_for(95)),
        Doc("BUSINESS REQUIREMENTS DOCUMENT — PROJECT NEXUS — Document ID: BRD-2026",
            filename="BRD.pdf", page=1, _distance=dist_for(94)),   # cover sheet
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert build_citations(chunks)[0].pages == [7], "cover sheet has no FR-01"
    assert len(chunks) == 2, "full context still reaches the LLM"


def test_table_of_contents_is_never_cited_even_holding_the_identifier():
    docs = [
        Doc("|**FR-01**|Retrieval Accuracy|...|", filename="BRD.pdf", page=7,
            _distance=dist_for(95)),
        Doc("Scope & Boundaries ........... Page 5\n"
            "Detailed Functional Requirements (FR-01 to FR-15) ........... Page 6\n"
            "Non-Functional Requirements ........... Page 7",
            filename="BRD.pdf", page=3, _distance=dist_for(94)),
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert build_citations(chunks)[0].pages == [7]


def test_gate_also_applies_to_bm25_chunks():
    """The `sim is None` branch used to admit BM25 hits unconditionally — that
    is how the ToC page got cited in the first place."""
    docs = [
        Doc("|**FR-01**|Retrieval Accuracy|...|", filename="BRD.pdf", page=7,
            _distance=dist_for(95)),
        Doc("Table of Contents\nExecutive Summary ....... Page 2\n"
            "Functional Requirements (FR-01 to FR-15) ....... Page 6\n"
            "Appendix ....... Page 11",
            filename="BRD.pdf", page=3),                            # BM25-only
        Doc("Average cost per voice call sits at $6.20",
            filename="BRD.pdf", page=4),                            # BM25-only, no id
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert build_citations(chunks)[0].pages == [7]


def test_bm25_chunk_holding_the_identifier_is_still_citable():
    """The gate must not undo commit 2013249 — an exact-match BM25 chunk is
    precisely what these identifier queries are retrieved by."""
    docs = [
        Doc("## 5. Detailed Functional Requirements", filename="BRD.pdf", page=7,
            _distance=dist_for(95)),
        Doc("|Req ID|Category|...|\n|**FR-01**|Retrieval Accuracy|92% (MRR@5)|",
            filename="BRD.pdf", page=7),                            # BM25-only
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert [c["is_top_match"] for c in chunks] == [True, True]


def test_query_without_identifier_leaves_the_gate_inert():
    """Multi-document synthesis (the FR-12 case) must keep working."""
    docs = [
        Doc("Overdraft fee is $35.00 per occurrence", filename="Fees.pdf", page=2,
            _distance=dist_for(95)),
        Doc("Capped at 3 occurrences per calendar day", filename="Terms.pdf", page=9,
            _distance=dist_for(95 - GAP + 1)),
    ]
    chunks, _ = select(docs, search_query="overdraft fee policy summary")
    assert [c["is_top_match"] for c in chunks] == [True, True]
    assert {c.filename for c in build_citations(chunks)} == {"Fees.pdf", "Terms.pdf"}


# ------------------------------------ identifier extraction (added 2026-08-26)
_lex_ns: dict = {"re": __import__("re")}
_lex_ns.update(vars(_vs))
extract_ids = _lex_ns["extract_query_identifiers"]


def test_identifier_recognises_requirement_style_ids():
    # 2026-08-31: identifiers come out CANONICAL (leading zeros stripped from
    # each hyphenated digit group) -- "NFR-PERF-03" extracts as "nfr-perf-3",
    # not "nfr-perf-03". See _canonical_identifier: a document writing
    # "SOP-02" was unreachable by a query typed as "SOP-2", a more natural
    # spelling than the padded form, so the two must compare equal. "2026" in
    # DOC-FEE-2026 is untouched -- only touched when the leading digit is '0'.
    assert extract_ids("Requirement FR-14 specifics") == {"fr-14"}
    assert extract_ids("Priority of NFR-PERF-03") == {"nfr-perf-3"}
    assert extract_ids("mitigation for RSK-02") == {"rsk-2"}
    assert extract_ids("update frequency of DOC-FEE-2026") == {"doc-fee-2026"}


def test_bare_numbers_are_not_identifiers():
    """The first cut of this rule counted any token containing a digit, which
    would have treated "92" in a figure question as an item identifier and
    filtered context on it."""
    assert extract_ids("retrieval accuracy 92 percent target") == set()
    assert extract_ids("what is the 600 ms TTFT threshold") == set()
    assert extract_ids("compare Platinum and Gold card benefits") == set()


def test_id_match_tags_every_chunk():
    docs = [
        Doc("|**FR-01**|Retrieval Accuracy|...|", filename="BRD.pdf", page=7,
            _distance=dist_for(95)),
        Doc("BUSINESS REQUIREMENTS DOCUMENT — PROJECT NEXUS", filename="BRD.pdf",
            page=1, _distance=dist_for(94)),
    ]
    chunks, _ = select(docs, search_query="Requirement FR-01 specifics")
    assert [c["id_match"] for c in chunks] == [True, False]


def test_id_match_is_true_for_all_when_query_has_no_identifier():
    docs = [Doc("overdraft fee $35.00", filename="Fees.pdf", page=2, _distance=dist_for(95)),
            Doc("unrelated text", filename="Fees.pdf", page=3, _distance=dist_for(80))]
    chunks, _ = select(docs, search_query="overdraft fee policy summary")
    assert all(c["id_match"] for c in chunks)


# ------------------------------------------- render duplicates (added 2026-09-01)
# Found live via the citation-content panel on KB_PTI_Pedoman_Operasional.pdf,
# page 1: pymupdf4llm renders the SOP table TWICE on the same page -- once as
# a proper `|SOP-01|...|` pipe table (correct), once as flowing prose where
# the wrapped second line of "Judul Prosedur" ("Produksi") lands AFTER the
# whole "Ketentuan" cell instead of right after "Penanganan Insiden". Reading
# order got scrambled, not the words themselves. Confirmed with a real
# extraction run against the fixture -- `table_strategy` tuning made it worse
# (`text` strategy shreds the whole page into a bogus per-character table),
# so the fix lives here: never let the scrambled shape win a citation slot
# when the well-formed table shape of the same (filename, page) is also a
# candidate. The existing _dedup_shape() (exact 120-char prefix) does not
# catch this -- the scrambled version's prefix differs because its word
# ORDER differs, not just its formatting.

def test_scrambled_table_prose_never_wins_over_the_real_table():
    scrambled = ("SOP-01 Penanganan Insiden Insiden severity-1 wajib dieskalasi ke Kepala "
                 "Divisi dalam 15 menit dan root\nProduksi cause analysis diserahkan "
                 "maksimal 3 hari kerja.\n\nSOP-02 Permintaan Akses Permintaan akses ke "
                 "Core Trading Engine memerlukan persetujuan dua\nSistem tingkat dan "
                 "otomatis dicabut setelah 90 hari tanpa aktivitas.")
    real_table = ("|Kode<br>SOP|Judul Prosedur|Ketentuan|\n|---|---|---|\n"
                  "|SOP-01|Penanganan Insiden<br>Produksi|Insiden severity-1 wajib "
                  "dieskalasi ke Kepala Divisi dalam 15 menit dan root<br>cause analysis "
                  "diserahkan maksimal 3 hari kerja.|")
    docs = [
        Doc(scrambled, filename="KB_PTI_Pedoman_Operasional.pdf", page=1, _distance=dist_for(90)),
        Doc(real_table, filename="KB_PTI_Pedoman_Operasional.pdf", page=1, _distance=dist_for(88)),
    ]
    chunks, _ = select(docs, search_query="jelaskan SOP-01")
    cited_texts = [c["text"] for c in chunks if c["is_top_match"]]
    assert real_table in cited_texts
    assert scrambled not in cited_texts, "the scrambled render must never be the one shown to the user"


def test_render_duplicate_suppression_needs_same_page():
    """Same scrambled/table pair, but on DIFFERENT pages of the same file --
    that is two legitimately separate citation locations, not a render
    duplicate, and must not be filtered."""
    scrambled = ("SOP-01 Penanganan Insiden Insiden severity-1 wajib dieskalasi ke Kepala "
                 "Divisi dalam 15 menit dan root\nProduksi cause analysis diserahkan "
                 "maksimal 3 hari kerja.")
    real_table = ("|Kode<br>SOP|Judul Prosedur|Ketentuan|\n|---|---|---|\n"
                  "|SOP-01|Penanganan Insiden<br>Produksi|Insiden severity-1 wajib "
                  "dieskalasi ke Kepala Divisi dalam 15 menit dan root<br>cause analysis "
                  "diserahkan maksimal 3 hari kerja.|")
    docs = [
        Doc(scrambled, filename="KB_PTI_Pedoman_Operasional.pdf", page=1, _distance=dist_for(90)),
        Doc(real_table, filename="KB_PTI_Pedoman_Operasional.pdf", page=9, _distance=dist_for(88)),
    ]
    chunks, _ = select(docs, search_query="jelaskan SOP-01")
    assert all(c["is_top_match"] for c in chunks), "different pages are never render duplicates"


def test_render_duplicate_suppression_needs_real_word_overlap():
    """Two unrelated table rows on the same page must not be treated as
    render duplicates just because one has pipes and the other does not."""
    unrelated_prose = "Batas persetujuan anggaran Kepala Divisi Rp250.000.000 wajib persetujuan Direksi."
    unrelated_table = ("|Kode<br>SOP|Judul Prosedur|Ketentuan|\n|---|---|---|\n"
                       "|SOP-03|Rilis ke Produksi|Rilis hanya boleh dijalankan Selasa dan Kamis.|")
    docs = [
        Doc(unrelated_prose, filename="KB_PTI_Pedoman_Operasional.pdf", page=1, _distance=dist_for(90)),
        Doc(unrelated_table, filename="KB_PTI_Pedoman_Operasional.pdf", page=1, _distance=dist_for(88)),
    ]
    chunks, _ = select(docs, search_query="anggaran dan rilis produksi")
    assert all(c["is_top_match"] for c in chunks), "genuinely different content must not be suppressed"


def test_render_duplicate_detection_ignores_a_heading_that_only_the_table_side_has():
    """Regression: caught by re-running this exact pair straight off the real
    fixture (KB_PTI_Pedoman_Operasional.pdf, page 1). The clean render is
    preceded by a section heading ("### Ketentuan pengadaan...") that the
    scrambled render never has -- that heading alone dropped the word-overlap
    ratio to 65%, under the 0.75 threshold, so the scrambled duplicate still
    won a citation slot alongside the clean one. Comparing only the TABLE
    ROW lines (not the heading) brings it to 81%."""
    real_table_with_heading = (
        "### Ketentuan pengadaan lintas divisi mengacu pada PTI-09, yang belum "
        "diterbitkan pada saat dokumen ini disusun.\n\n"
        "|Kode<br>SOP|Judul Prosedur|Ketentuan|\n|---|---|---|\n"
        "|SOP-01|Penanganan Insiden<br>Produksi|Insiden severity-1 wajib "
        "dieskalasi ke Kepala Divisi dalam 15 menit dan root<br>cause analysis "
        "diserahkan maksimal 3 hari kerja.|")
    real_scrambled_full_page = (
        "SOP-01 Penanganan Insiden Insiden severity-1 wajib dieskalasi ke Kepala "
        "Divisi dalam 15 menit dan root\nProduksi cause analysis diserahkan "
        "maksimal 3 hari kerja.\n\nSOP-02 Permintaan Akses Permintaan akses ke "
        "Core Trading Engine memerlukan persetujuan dua\nSistem tingkat dan "
        "otomatis dicabut setelah 90 hari tanpa aktivitas.\n\nSOP-03 Rilis ke "
        "Produksi Rilis hanya boleh dijalankan Selasa dan Kamis pukul "
        "19.00-22.00 WIB, di\nluar itu wajib emergency change request.\n\n"
        "## 3. Inventaris Dokumen Internal\n\n**ID** **Nama Dokumen** "
        "**Pemilik** **Frekuensi**\n**Dokumen** **Pembaruan**")
    assert _vs._is_render_duplicate(real_table_with_heading, real_scrambled_full_page)


# --------------------------------------- reanchor_citable_chunks (added 2026-09-01)
# chat/routes.py narrows context_chunks to id_chunks for identifier queries
# (only chunks that actually mention the identifier survive, row-preferred).
# is_top_match on each dict was computed by retrieve_context() BEFORE that
# narrowing, so it can point at a chunk that just got dropped, or -- the live
# case this covers -- at a same-shaped chunk for a DIFFERENT code that won on
# raw similarity ("jelaskan SOP-01" citing the SOP-02 row).

def test_reanchors_when_the_original_top_match_was_dropped():
    """The chunk retrieve_context() marked as the anchor didn't mention this
    identifier at all (a same-shaped row for a different code) and was
    filtered out of id_chunks before reanchor runs. The real match, further
    down the id-narrowed list, must become citable instead of nothing at
    all being cited."""
    wrong_code_row = {"text": "|SOP-02|Permintaan Akses|...|", "filename": "f.pdf",
                       "page": 1, "source_type": "kb_divisi", "is_top_match": True}
    right_code_row = {"text": "|SOP-01|Penanganan Insiden|...|", "filename": "f.pdf",
                      "page": 1, "source_type": "kb_divisi", "is_top_match": False}
    id_chunks = [right_code_row]  # wrong_code_row already dropped by the id_match filter upstream
    _vs.reanchor_citable_chunks(id_chunks)
    assert right_code_row["is_top_match"] is True


def test_reanchor_keeps_a_survivor_that_was_already_top_match():
    """If the original selection happens to still be valid after narrowing,
    reanchor should not second-guess it."""
    a = {"text": "a", "is_top_match": True}
    b = {"text": "b", "is_top_match": False}
    chunks = [a, b]
    _vs.reanchor_citable_chunks(chunks)
    assert a["is_top_match"] is True
    assert b["is_top_match"] is False


def test_reanchor_also_suppresses_render_duplicates_among_survivors():
    """Both the scrambled prose and the clean table row mention SOP-01 (both
    pass the id_match filter upstream), so both can land in id_chunks
    together -- reanchor must still never let the scrambled one be citable
    alongside the clean one, same rule as retrieve_context()'s own dedup."""
    scrambled = {"text": "SOP-01 Penanganan Insiden Insiden severity-1 wajib dieskalasi ke Kepala "
                          "Divisi dalam 15 menit dan root\nProduksi cause analysis diserahkan "
                          "maksimal 3 hari kerja.",
                 "filename": "f.pdf", "page": 1, "is_top_match": False}
    clean = {"text": "|Kode<br>SOP|Judul Prosedur|Ketentuan|\n|---|---|---|\n"
                     "|SOP-01|Penanganan Insiden<br>Produksi|Insiden severity-1 wajib "
                     "dieskalasi ke Kepala Divisi dalam 15 menit dan root<br>cause analysis "
                     "diserahkan maksimal 3 hari kerja.|",
             "filename": "f.pdf", "page": 1, "is_top_match": False}
    id_chunks = [clean, scrambled]  # row-preference already put the clean one first
    _vs.reanchor_citable_chunks(id_chunks)
    assert clean["is_top_match"] is True
    assert scrambled["is_top_match"] is False


def test_reanchor_respects_the_limit():
    chunks = [{"text": str(i), "is_top_match": False} for i in range(5)]
    _vs.reanchor_citable_chunks(chunks, limit=2)
    assert sum(c["is_top_match"] for c in chunks) == 2
    assert [c["is_top_match"] for c in chunks[:2]] == [True, True], "falls back to list order, table-row-preference already applied by the caller"


# ---------------------------------------------------------------- standalone
if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
