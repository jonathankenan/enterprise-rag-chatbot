"""
Tests for SRS FCR-003 poin 12.a — source citation.

Run from the repo root:      python backend/tests/test_source_citation.py
(or with pytest:             pytest backend/tests/test_source_citation.py)

No Postgres, no Ollama, no API keys, no Chroma required. The two units under
test are pure functions, so we load them straight out of the source files by
AST and exec them in a clean namespace — what runs here is verbatim the code
that ships, not a copy that can drift.

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
exec(_segment(SCHEMAS_SRC, "SourceCitation"), _ns)
exec(_segment(ROUTES_SRC, "_build_source_citations"), _ns)
build_citations = _ns["_build_source_citations"]

_fn = _segment(VECTOR_SRC, "retrieve_context")
_tail = _fn[_fn.index("    docs = docs[:top_k]"):]
_tail = "\n".join(l[4:] if l.startswith("    ") else l for l in _tail.split("\n"))
_helper = _segment(VECTOR_SRC, "_distance_to_similarity_percent")
# The tail gained a lexical gate on 2026-08-26 (_has_query_id/_is_toc), so it
# now also closes over `re`, the tokenizer, the identifier regex and the two
# identifier helpers. Loaded the same way as everything else here — from the
# shipping source, not a copy.
_lexical = "\n".join([
    _segment(VECTOR_SRC, "custom_bm25_tokenizer"),
    _assignment(VECTOR_SRC, "_IDENTIFIER_RE"),
    _segment(VECTOR_SRC, "extract_query_identifiers"),
    _segment(VECTOR_SRC, "text_mentions_identifier"),
    # 2026-08-26: chunk juga ditandai id_in_example, jadi tail-nya sekarang
    # ikut menutup identifier_only_in_example beserta pola wilayah contohnya.
    _assignment(VECTOR_SRC, "_FENCED_RE"),
    _assignment(VECTOR_SRC, "_INLINE_CODE_RE"),
    _assignment(VECTOR_SRC, "_JSON_PAIR_RE"),
    _segment(VECTOR_SRC, "_example_spans"),
    _segment(VECTOR_SRC, "identifier_only_in_example"),
])


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
    ns = {"docs": list(docs), "top_k": top_k, "settings": _Settings,
          "search_query": search_query, "re": __import__("re")}
    exec(_lexical, ns)
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
    """Stand-in for a langchain Document."""
    def __init__(self, text="...", **meta):
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
exec(_lexical, _lex_ns)
extract_ids = _lex_ns["extract_query_identifiers"]


def test_identifier_recognises_requirement_style_ids():
    assert extract_ids("Requirement FR-14 specifics") == {"fr-14"}
    assert extract_ids("Priority of NFR-PERF-03") == {"nfr-perf-03"}
    assert extract_ids("mitigation for RSK-02") == {"rsk-02"}
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
